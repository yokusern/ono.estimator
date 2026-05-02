import asyncio
import os
import json
import time
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.notifier import Notifier
from ono_estimator.core.database import SupabaseClient
from ono_estimator.core import ONOPredictionEngine, SignalStatus

load_dotenv()

app = FastAPI(title="ONO Estimator Ultra v4.5", version="4.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

target_symbols = ["USDJPY=X", "GC=F", "BTC-USD", "^N225", "XAGUSD=X", "AUDJPY=X", "EURUSD=X", "EURJPY=X"]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

# グローバルステート
system_state = {sym: {tf: {"status": "Syncing", "score": 0, "ai_text": "Awaiting Core...", "predicted_price": 0, "probability": 0} for tf in TIMEFRAMES} for sym in target_symbols}
chart_data = {sym: {tf: [] for tf in TIMEFRAMES} for sym in target_symbols}
price_cache = {sym: 0.0 for sym in target_symbols}
market_overview = {"fear_greed": "50", "global_theme": "Initializing Global Synergy...", "last_update_ts": 0}

fetcher = HybridDataFetcher()
engine = ONOPredictionEngine()
ai_analyzer = GeminiAnalyzer()
notifier = Notifier()
db = SupabaseClient()

async def analyze_symbol(symbol: str):
    """単一銘柄の並列分析処理"""
    try:
        df_base = fetcher.fetch_ohlcv(symbol, interval="1min")
        if df_base is None or df_base.empty: return None
        
        mtf_summaries = {}
        symbol_charts = {}
        
        for tf in TIMEFRAMES:
            df_tf = fetcher.resample_ohlcv(df_base, tf)
            df_tf = fetcher.calculate_indicators(df_tf)
            if df_tf.empty: continue
            
            result = engine.analyze(None, symbol=symbol, df_precomputed=df_tf)
            latest = df_tf.iloc[-1]
            
            mtf_summaries[tf] = {
                "status": result.status.value if result.status else "Wait",
                "score": result.win_rate_score,
                "rsi": round(float(latest.get('rsi', 0)), 1),
                "price": float(latest['close']),
                "theme": "MTF Active"
            }
            
            records = []
            for idx, row in df_tf.tail(100).iterrows():
                records.append({
                    "time": int(idx.timestamp()),
                    "open": float(row['open']), "high": float(row['high']), "low": float(row['low']), "close": float(row['close']),
                    "rsi": float(row.get('rsi', 0)), "macd": float(row.get('macd', 0))
                })
            symbol_charts[tf] = records
            
        price_cache[symbol] = float(df_base.iloc[-1]['close'])
        
        return {
            "symbol": symbol,
            "mtf": mtf_summaries,
            "charts": symbol_charts,
            "result_obj": result
        }
    except Exception as e:
        print(f"[AsyncPool] Error on {symbol}: {e}")
        return None

async def estimation_loop():
    print("[Server] High-Speed MTF Loop Started.")
    
    while True:
        start_time = time.time()
        try:
            # 1. 並列データ取得と計算 (最大速度)
            tasks = [analyze_symbol(sym) for sym in target_symbols]
            results = await asyncio.gather(*tasks)
            
            batch_metrics = {}
            for res in results:
                if res:
                    sym = res["symbol"]
                    chart_data[sym] = res["charts"]
                    batch_metrics[sym] = {
                        "mtf": res["mtf"],
                        "timeframe": "1m",
                        "score": res["mtf"].get("1m", {}).get("score", 0),
                        "result_obj": res["result_obj"]
                    }
                    # 状態の仮更新
                    for tf in TIMEFRAMES:
                        system_state[sym][tf].update({
                            "status": res["mtf"].get(tf, {}).get("status", "Wait"),
                            "score": res["mtf"].get(tf, {}).get("score", 0)
                        })

            # 2. MTF AI分析
            if batch_metrics:
                ai_results = ai_analyzer.batch_analyze(batch_metrics)
                if isinstance(ai_results, dict):
                    market_overview["global_theme"] = ai_results.get("market_intelligence", market_overview["global_theme"])
                    market_overview["last_update_ts"] = int(time.time())
                    
                    for sym in target_symbols:
                        if sym in ai_results:
                            ai_data = ai_results[sym]
                            for tf in TIMEFRAMES:
                                system_state[sym][tf].update({
                                    "ai_text": ai_data.get("ai_text", "---"),
                                    "predicted_price": ai_data.get("predicted_price", 0),
                                    "probability": ai_data.get("probability", 0),
                                    "last_updated": datetime.now().isoformat()
                                })
                            
                            # 通知と保存 (スコアしきい値)
                            if system_state[sym]["1m"]["score"] >= 80:
                                notifier.notify_if_needed(sym, batch_metrics[sym]["result_obj"], ai_data, price_cache[sym])
                                db.save_prediction({
                                    "symbol": sym,
                                    "status": system_state[sym]["1m"]["status"],
                                    "score": system_state[sym]["1m"]["score"],
                                    "ai_text": ai_data.get("ai_text", ""),
                                    "predicted_price": ai_data.get("predicted_price", 0),
                                    "probability": ai_data.get("probability", 0)
                                })

            elapsed = time.time() - start_time
            # 60秒周期だが、実行時間を引いて正確な間隔を維持
            sleep_time = max(1, 60 - elapsed)
            print(f"[Loop] Cycle Complete in {elapsed:.1f}s. Next scan in {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            print(f"Critical Loop Error: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    # 起動時にバックグラウンドタスクとして開始
    asyncio.create_task(estimation_loop())

@app.get("/api/predict")
def get_prediction(tf: str = Query("1m", regex="^(1m|5m|15m|1h|4h)$")):
    tf_state = {}
    for sym, states in system_state.items():
        tf_state[sym] = states.get(tf)
    return {
        "data": tf_state, 
        "overview": market_overview, 
        "current_tf": tf,
        "server_time": int(time.time())
    }

@app.get("/api/chart/{symbol}")
def get_chart(symbol: str, tf: str = Query("1m", regex="^(1m|5m|15m|1h|4h)$")):
    symbol = symbol.replace("/", "")
    matched_sym = next((s for s in target_symbols if symbol in s), symbol)
    return {"data": chart_data.get(matched_sym, {}).get(tf, [])}

@app.get("/api/history")
def get_history():
    return {"data": db.get_history(limit=50)}

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy", 
        "mode": "Parallel_MTF_Active",
        "last_sync": market_overview["last_update_ts"]
    }
