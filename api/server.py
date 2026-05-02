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

# グローバルステート (TF別)
system_state = {sym: {tf: {"status": "Wait", "score": 0, "ai_text": "Syncing...", "predicted_price": 0, "probability": 0} for tf in TIMEFRAMES} for sym in target_symbols}
chart_data = {sym: {tf: [] for tf in TIMEFRAMES} for sym in target_symbols}
price_cache = {sym: 0.0 for sym in target_symbols}
market_overview = {"fear_greed": "50", "global_theme": "Analyzing Global Synergy..."}

async def estimation_loop():
    fetcher = HybridDataFetcher()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    notifier = Notifier()
    db = SupabaseClient()
    
    print("[Server] MTF Autonomous Loop Started.")
    
    while True:
        start_time = time.time()
        try:
            batch_metrics = {}
            
            for symbol in target_symbols:
                try:
                    # 1. 1分足データを多めに取得 (リサンプリング用)
                    df_base = fetcher.fetch_ohlcv(symbol, interval="1min")
                    if df_base is None or df_base.empty: continue
                    
                    mtf_summaries = {}
                    
                    for tf in TIMEFRAMES:
                        # 2. 動的リサンプリング
                        df_tf = fetcher.resample_ohlcv(df_base, tf)
                        df_tf = fetcher.calculate_indicators(df_tf)
                        if df_tf.empty: continue
                        
                        # 3. テクニカル判定
                        result = engine.analyze(None, symbol=symbol, df_precomputed=df_tf)
                        latest = df_tf.iloc[-1]
                        
                        # TF別メトリクス
                        mtf_summaries[tf] = {
                            "status": result.status.value if result.status else "Wait",
                            "score": result.win_rate_score,
                            "rsi": round(float(latest.get('rsi', 0)), 1),
                            "price": float(latest['close']),
                            "theme": "MTF Analysis"
                        }
                        
                        # チャートデータの保存
                        records = []
                        for idx, row in df_tf.tail(100).iterrows():
                            records.append({
                                "time": int(idx.timestamp()),
                                "open": float(row['open']), "high": float(row['high']), "low": float(row['low']), "close": float(row['close']),
                                "rsi": float(row.get('rsi', 0)), "macd": float(row.get('macd', 0))
                            })
                        chart_data[symbol][tf] = records
                        
                        # 4. ステート更新 (暫定)
                        system_state[symbol][tf].update({
                            "status": mtf_summaries[tf]["status"],
                            "score": mtf_summaries[tf]["score"]
                        })

                    # AI分析用にパッキング
                    batch_metrics[symbol] = {
                        "mtf": mtf_summaries,
                        "timeframe": "1m", # デフォルト
                        "score": mtf_summaries.get("1m", {}).get("score", 0),
                        "result_obj": result # 通知用
                    }
                    
                    price_cache[symbol] = float(df_base.iloc[-1]['close'])
                    
                except Exception as e:
                    print(f"[Loop] Error on {symbol}: {e}")
                
                await asyncio.sleep(0.5)

            # 5. MTF AI分析
            if batch_metrics:
                ai_results = ai_analyzer.batch_analyze(batch_metrics)
                if isinstance(ai_results, dict):
                    market_overview["global_theme"] = ai_results.get("market_intelligence", market_overview["global_theme"])
                    for sym in target_symbols:
                        if sym in ai_results:
                            ai_data = ai_results[sym]
                            # 全時間軸に同じAIテキストを適用（コンフルエンス分析の結果）
                            for tf in TIMEFRAMES:
                                system_state[sym][tf].update({
                                    "ai_text": ai_data.get("ai_text", "---"),
                                    "predicted_price": ai_data.get("predicted_price", 0),
                                    "probability": ai_data.get("probability", 0),
                                    "last_updated": datetime.now().isoformat()
                                })
                            
                            # 通知と保存 (1mを代表として)
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
            sleep_time = max(1, 60 - elapsed)
            print(f"[Loop] MTF Cycle Complete ({elapsed:.1f}s). Sleeping {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            print(f"Critical Loop Error: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())

@app.get("/api/predict")
def get_prediction(tf: str = Query("1m", regex="^(1m|5m|15m|1h|4h)$")):
    # 指定されたTFのデータを抽出して返す
    tf_state = {}
    for sym, states in system_state.items():
        tf_state[sym] = states.get(tf)
    return {"data": tf_state, "overview": market_overview, "current_tf": tf}

@app.get("/api/chart/{symbol}")
def get_chart(symbol: str, tf: str = Query("1m", regex="^(1m|5m|15m|1h|4h)$")):
    symbol = symbol.replace("/", "")
    # 正確なシンボルマッチング (USDJPY -> USDJPY=X)
    matched_sym = next((s for s in target_symbols if symbol in s), symbol)
    return {"data": chart_data.get(matched_sym, {}).get(tf, [])}

@app.get("/api/history")
def get_history():
    db = SupabaseClient()
    return {"data": db.get_history(limit=50)}

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "mode": "MTF_Active"}
