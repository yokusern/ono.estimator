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

# 監視銘柄の最適化 (yfinance/安定性重視)
target_symbols = ["USDJPY=X", "GC=F", "BTC-USD", "^N225", "XAGUSD=X", "AUDJPY=X", "EURUSD=X", "EURJPY=X"]

# グローバルステート
system_state = {sym: {"status": "Wait", "score": 0, "ai_text": "Syncing...", "funda": {}} for sym in target_symbols}
chart_data = {sym: [] for sym in target_symbols}
market_overview = {"fear_greed": "50", "global_theme": "Analyzing Global Synergy..."}

async def estimation_loop():
    fetcher = HybridDataFetcher()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    
    while True:
        try:
            batch_metrics = {}
            
            for symbol in target_symbols:
                try:
                    # 1. 冗長化されたデータ取得
                    df = fetcher.fetch_ohlcv(symbol)
                    
                    # 厳格なバリデーション: None, 空, または DataFrame 以外はスキップ
                    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                        print(f"[Loop] Skip {symbol}: No valid data.")
                        continue
                    
                    # 2. 指標計算
                    df = fetcher.calculate_indicators(df)
                    if len(df) < 2: continue
                    
                    # 3. テクニカル判定
                    result = engine.analyze(None, symbol=symbol, df_precomputed=df)
                    
                    # AI分析用の指標サマリーを作成 (floatキャストで安全に)
                    latest = df.iloc[-1]
                    batch_metrics[symbol] = {
                        "status": result.status.value if result.status else "Standby",
                        "score": result.win_rate_score,
                        "rsi": round(float(latest.get('rsi', 0)), 1),
                        "macd": round(float(latest.get('macd', 0)), 4),
                        "theme": "Stable"
                    }
                    
                    # チャートデータの更新
                    records = []
                    for idx, row in df.tail(100).iterrows():
                        records.append({
                            "time": int(idx.timestamp()),
                            "open": float(row['open']), "high": float(row['high']), "low": float(row['low']), "close": float(row['close']),
                            "ma25": float(row.get('ma25', 0)), "bb_upper": float(row.get('bb_upper', 0)), "bb_lower": float(row.get('bb_lower', 0)),
                            "rsi": float(row.get('rsi', 0)), "macd": float(row.get('macd', 0)), "hist": float(row.get('hist', 0))
                        })
                    chart_data[symbol] = records
                    
                except Exception as e:
                    print(f"[Loop] Error on {symbol}: {e}")
                
                await asyncio.sleep(3) # レート制限対策をさらに強化

            # 4. 一括 AI 分析 (データがある場合のみ)
            if batch_metrics:
                ai_results = ai_analyzer.batch_analyze(batch_metrics)
                
                # 型チェック: 辞書でない場合はスキップ
                if isinstance(ai_results, dict):
                    market_overview["global_theme"] = ai_results.get("market_intelligence", "Analyzing Market Correlation...")
                    
                    for sym in target_symbols:
                        if sym in ai_results and isinstance(ai_results[sym], dict):
                            system_state[sym].update({
                                "status": batch_metrics.get(sym, {}).get("status", "Standby"),
                                "score": batch_metrics.get(sym, {}).get("score", 0),
                                "ai_text": ai_results[sym].get("ai_text", "Analysis Pending..."),
                                "last_updated": datetime.now().isoformat()
                            })
                else:
                    print("[Gemini] Unexpected response format, skipping state update.")

            print(f"--- Batch Sync Complete: {datetime.now().isoformat()} ---")
            await asyncio.sleep(300) # 5分おき
            
        except Exception as e:
            print(f"Critical Loop Error: {e}")
            await asyncio.sleep(60)
            
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
