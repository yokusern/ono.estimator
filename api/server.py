import asyncio
import os
import json
import time
import traceback
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import requests

from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.notifier import Notifier
from ono_estimator.core.database import SupabaseClient
from ono_estimator.core import ONOPredictionEngine, SignalStatus

load_dotenv()

app = FastAPI(title="ONO Estimator Ultra v4.5", version="4.5.0")

# CORS: Vercel URLを明示指定（ブラウザからの接続を確実に許可）
VERCEL_URL = os.environ.get("VERCEL_URL", "")
ALLOWED_ORIGINS = [
    "https://ono-estimator.vercel.app",
    "https://ono-estimator-ultra.vercel.app",
    "http://localhost:3000",
]
if VERCEL_URL:
    ALLOWED_ORIGINS.append(f"https://{VERCEL_URL}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",  # 全Vercelプレビューも許可
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,  # credentialsなしで"*"相当の柔軟性を維持
)

target_symbols = ["USDJPY=X", "GC=F", "BTC-USD", "^N225", "XAGUSD=X", "AUDJPY=X", "EURUSD=X", "EURJPY=X"]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

# グローバルステート
system_state = {sym: {tf: {"status": "Syncing", "score": 0, "ai_text": "Awaiting Raw Intelligence...", "predicted_price": 0, "probability": 0} for tf in TIMEFRAMES} for sym in target_symbols}
chart_data = {sym: {tf: [] for tf in TIMEFRAMES} for sym in target_symbols}
price_cache = {sym: 0.0 for sym in target_symbols}
market_overview = {"fear_greed": "50", "global_theme": "Analyzing Real-time Market Pulse...", "last_update_ts": 0}

fetcher = HybridDataFetcher()
engine = ONOPredictionEngine()
ai_analyzer = GeminiAnalyzer()
notifier = Notifier()
db = SupabaseClient()

def _sync_analyze_symbol(symbol: str):
    """同期処理をスレッドプールで実行するためのラッパー"""
    df_base = fetcher.fetch_ohlcv(symbol, interval="1min")
    if df_base is None or df_base.empty: return None
    
    mtf_summaries = {}
    symbol_charts = {}
    result = None
    
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
    return {"symbol": symbol, "mtf": mtf_summaries, "charts": symbol_charts, "result_obj": result}

async def analyze_symbol(symbol: str):
    """ブロッキング処理をスレッドにオフロードしてevent loopを解放する"""
    try:
        # asyncio.to_thread で同期関数をスレッドプールで実行
        # これにより重い処理中でもAPIが即座に応答できる
        return await asyncio.to_thread(_sync_analyze_symbol, symbol)
    except Exception as e:
        print(f"[AsyncPool] Error on {symbol}: {e}")
        return None

async def backtest_loop():
    """過去の予測が当たったか自動採点するプロセス (30分おき)"""
    print("[Self-Learning] Scoring cycle started.")
    while True:
        try:
            pending = db.get_unscored_predictions()
            for p in pending:
                sym = p["symbol"]
                current = price_cache.get(sym)
                if current and current > 0:
                    is_buy = "BUY" in p["status"].upper()
                    is_sell = "SELL" in p["status"].upper()
                    is_correct = False
                    if is_buy and current > p["current_price"]: is_correct = True
                    if is_sell and current < p["current_price"]: is_correct = True
                    db.update_prediction_result(p["id"], current, is_correct)
                    print(f"[Self-Learning] Scored {sym}: {'WIN' if is_correct else 'LOSS'}")
        except Exception as e:
            print(f"[Self-Learning] Error: {e}")
        await asyncio.sleep(1800)

async def estimation_loop():
    print("[Server] ONO High-Precision Autonomous Engine Started.")
    while True:
        cycle_start = time.time()
        try:
            performance_data = db.get_performance_summary()
            print(f"[Loop] Cycle started with Intel: {performance_data}")
            
            tasks = [analyze_symbol(sym) for sym in target_symbols]
            results = await asyncio.gather(*tasks)
            
            for res in results:
                if not res: continue
                sym = res["symbol"]
                chart_data[sym] = res["charts"]
                is_open = fetcher.is_market_open(sym)
                
                for tf in TIMEFRAMES:
                    status_text = res["mtf"].get(tf, {}).get("status", "Wait") if is_open else "Closed"
                    system_state[sym][tf].update({
                        "status": status_text,
                        "score": res["mtf"].get(tf, {}).get("score", 0) if is_open else 0
                    })

                if is_open:
                    print(f"[Gemini] Analyzing {sym} with Self-Learning...")
                    # Gemini API呼び出しもスレッドに移してevent loopをブロックしない
                    ai_data = await asyncio.to_thread(
                        ai_analyzer.analyze_single, sym, res, performance_data
                    )
                    
                    if ai_data and "ai_text" in ai_data:
                        if market_overview["last_update_ts"] < int(time.time()) - 300:
                            market_overview["global_theme"] = ai_data["ai_text"][:100] + "..."
                            market_overview["last_update_ts"] = int(time.time())

                        for tf in TIMEFRAMES:
                            system_state[sym][tf].update({
                                "ai_text": ai_data["ai_text"],
                                "predicted_price": ai_data.get("predicted_price", 0),
                                "probability": ai_data.get("probability", 0),
                                "last_updated": datetime.now().isoformat()
                            })
                        
                        try:
                            db.save_prediction({
                                "symbol": sym,
                                "status": system_state[sym]["1m"]["status"],
                                "score": system_state[sym]["1m"]["score"],
                                "ai_text": ai_data["ai_text"],
                                "predicted_price": ai_data.get("predicted_price", 0),
                                "probability": ai_data.get("probability", 0),
                                "current_price": price_cache[sym]
                            })
                        except Exception as db_e:
                            print(f"[Loop] DB Save Error for {sym}: {db_e}")
                        
                        if system_state[sym]["1m"]["score"] >= 80:
                            notifier.notify_if_needed(sym, res["result_obj"], ai_data, price_cache[sym])
                
                if is_open: await asyncio.sleep(2.5)

            if os.environ.get("RENDER_EXTERNAL_URL"):
                try: requests.get(f"{os.environ['RENDER_EXTERNAL_URL']}/api/health", timeout=5)
                except: pass

            elapsed = time.time() - cycle_start
            sleep_time = max(5, 60 - elapsed)
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            print(f"!!! CRITICAL LOOP ERROR: {e}")
            traceback.print_exc()
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    # 起動直後にSupabaseから最新キャッシュをロード (初期表示を即座に返すため)
    try:
        history = db.get_history(limit=len(target_symbols))
        for row in history:
            sym = row.get("symbol")
            if sym and sym in system_state:
                for tf in TIMEFRAMES:
                    system_state[sym][tf].update({
                        "ai_text": row.get("ai_text", "Syncing..."),
                        "score": row.get("score", 0),
                        "status": row.get("status", "Wait"),
                        "predicted_price": row.get("predicted_price", 0),
                        "probability": row.get("probability", 0),
                    })
        print(f"[Startup] Preloaded {len(history)} records from Supabase.")
    except Exception as e:
        print(f"[Startup] Preload failed (non-critical): {e}")

    asyncio.create_task(estimation_loop())
    asyncio.create_task(backtest_loop())
    asyncio.create_task(anti_sleep_loop())

async def anti_sleep_loop():
    """Renderのスリープを防ぐ専用ループ (4分おきにセルフping)"""
    await asyncio.sleep(10)  # 起動直後は少し待つ
    while True:
        render_url = os.environ.get("RENDER_EXTERNAL_URL")
        if render_url:
            try:
                requests.get(f"{render_url}/api/health", timeout=10)
                print(f"[Anti-Sleep] Ping sent to keep Render alive.")
            except Exception as e:
                print(f"[Anti-Sleep] Ping failed: {e}")
        await asyncio.sleep(240)  # 4分おき

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
    mapping = {"USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD", "JP225": "^N225", "XAGUSD": "XAGUSD=X", "AUDJPY": "AUDJPY=X", "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X"}
    ticker = mapping.get(symbol, symbol)
    return {"data": chart_data.get(ticker, {}).get(tf, [])}

@app.get("/api/history")
def get_history():
    return {"data": db.get_history(limit=50)}

@app.get("/")
def read_root():
    return {"status": "ONO Estimator Backend Active", "time": datetime.now().isoformat()}

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "mode": "Self_Learning_Serial_AI_Active", "last_sync": int(time.time())}
