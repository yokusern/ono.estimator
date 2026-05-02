import asyncio
import os
import json
import time
import pandas as pd
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.funda_analyzer import FundaAnalyzer
from ono_estimator.core import ONOPredictionEngine, SignalStatus

load_dotenv()

app = FastAPI(title="ONO Estimator Ultra v4.0", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

target_symbols = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"]

# グローバルステート
system_state = {sym: {"status": "Wait", "score": 0, "ai_text": "Syncing...", "funda": {}} for sym in target_symbols}
chart_data = {sym: [] for sym in target_symbols}
market_overview = {"fear_greed": "50", "global_theme": "Analyzing Global Synergy..."}

async def estimation_loop():
    fetcher = HybridDataFetcher()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    funda_analyzer = FundaAnalyzer()
    
    while True:
        try:
            batch_metrics = {}
            
            for symbol in target_symbols:
                try:
                    # 1. 冗長化されたデータ取得
                    df = fetcher.fetch_ohlcv(symbol)
                    if df is None: continue
                    
                    # 2. 指標計算
                    df = fetcher.calculate_indicators(df)
                    
                    # 3. テクニカル判定
                    result = engine.analyze(None, symbol=symbol, df_precomputed=df)
                    
                    # AI分析用の指標サマリーを作成
                    latest = df.iloc[-1]
                    batch_metrics[symbol] = {
                        "status": result.status.value,
                        "score": result.win_rate_score,
                        "rsi": round(latest['rsi'], 1),
                        "macd": round(latest['macd'], 4),
                        "theme": "Stable" # Funda分析を統合可能
                    }
                    
                    # チャートデータの更新
                    records = []
                    for idx, row in df.tail(100).iterrows():
                        records.append({
                            "time": int(idx.timestamp()),
                            "open": row['open'], "high": row['high'], "low": row['low'], "close": row['close'],
                            "ma25": row['ma25'], "bb_upper": row['bb_upper'], "bb_lower": row['bb_lower'],
                            "rsi": row['rsi'], "macd": row['macd'], "hist": row['hist']
                        })
                    chart_data[symbol] = records
                    
                except Exception as e:
                    print(f"[Loop] Error on {symbol}: {e}")
                
                await asyncio.sleep(2) # API制限に配慮（強化）

            # 4. 一括 AI 分析 (1リクエストで8銘柄)
            if batch_metrics:
                ai_results = ai_analyzer.batch_analyze(batch_metrics)
                market_overview["global_theme"] = ai_results.get("market_intelligence", "Stable Correlation")
                
                for sym in target_symbols:
                    if sym in ai_results:
                        system_state[sym].update({
                            "status": batch_metrics[sym]["status"],
                            "score": batch_metrics[sym]["score"],
                            "ai_text": ai_results[sym]["ai_text"],
                            "last_updated": datetime.now().isoformat()
                        })

            print(f"--- Batch Sync Complete: {datetime.now().isoformat()} ---")
            await asyncio.sleep(300) # 5分おき
            
        except Exception as e:
            print(f"Critical Loop Error: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())

@app.get("/")
def read_root():
    return {"message": "ONO Estimator Ultra API is running", "status": "active", "version": "4.1.0"}

@app.get("/api/predict")
def get_prediction():
    return {"data": system_state, "overview": market_overview}

@app.get("/api/chart/{symbol}")
def get_chart(symbol: str):
    return {"data": chart_data.get(symbol, [])}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
