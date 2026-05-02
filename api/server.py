import asyncio
import os
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ono_estimator.core import ONOPredictionEngine, SignalStatus
from ono_estimator.core.connector import YFinanceConnector
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.funda_analyzer import FundaAnalyzer
from ono_estimator.core.notifier import Notifier
from ono_estimator.core.market_context import MarketContextFetcher

load_dotenv()

app = FastAPI(title="ONO Estimator Pro v3.0", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 監視銘柄
target_symbols = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"]

# グローバルステート
system_state = {sym: {"status": "Wait", "score": 0, "ai_text": "Analyzing...", "funda": {}} for sym in target_symbols}
chart_data = {sym: [] for sym in target_symbols}
market_overview = {"fear_greed": "50", "global_theme": "Analyzing..."}

def calculate_zigzag(df, deviation=0.5):
    """簡易ZigZag計算"""
    closes = df['close'].values
    zigzag = []
    # 簡易実装: 高値安値を結ぶ（ここではcloseベース）
    for i in range(len(closes)):
        if i == 0 or i == len(closes)-1:
            zigzag.append({"time": int(df.index[i].timestamp()), "value": float(closes[i])})
        elif i % 10 == 0: # 10本に1回頂点を作る簡易モック
            zigzag.append({"time": int(df.index[i].timestamp()), "value": float(closes[i])})
    return zigzag

def calculate_indicators(df):
    """テクニカル指標の計算"""
    # MA
    df['ma25'] = df['close'].rolling(25).mean()
    df['ma75'] = df['close'].rolling(75).mean()
    df['ma200'] = df['close'].rolling(200).mean()
    
    # Bollinger Bands (2σ)
    std = df['close'].rolling(20).std()
    df['bb_upper'] = df['ma25'] + (std * 2)
    df['bb_lower'] = df['ma25'] - (std * 2)
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['histogram'] = df['macd'] - df['signal']
    
    return df.fillna(0)

async def estimation_loop():
    connector = YFinanceConnector()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    funda_analyzer = FundaAnalyzer()
    context_fetcher = MarketContextFetcher()
    notifier = Notifier()
    
    while True:
        try:
            # マクロ情報の更新
            global_ctx = context_fetcher.fetch_all("GLOBAL")
            market_overview["fear_greed"] = global_ctx.get("fear_greed", "50")
            market_overview["global_theme"] = global_ctx.get("theme", "Range Market")

            for symbol in target_symbols:
                try:
                    await asyncio.sleep(3) # レート制限対策
                    
                    # 1. データ取得
                    mtf_data = connector.fetch_mtf_data(symbol)
                    if not mtf_data: continue
                    
                    df_m5 = mtf_data.get_data("5m")
                    if df_m5 is None: continue
                    
                    # 2. チャート指標計算
                    df_full = calculate_indicators(df_m5)
                    
                    # フロントエンド用のチャートデータ生成 (最新100件)
                    records = []
                    for idx, row in df_full.tail(100).iterrows():
                        records.append({
                            "time": int(idx.timestamp()),
                            "open": float(row['open']),
                            "high": float(row['high']),
                            "low": float(row['low']),
                            "close": float(row['close']),
                            "ma25": float(row['ma25']),
                            "ma75": float(row['ma75']),
                            "bb_upper": float(row['bb_upper']),
                            "bb_lower": float(row['bb_lower']),
                            "rsi": float(row['rsi']),
                            "macd": float(row['macd']),
                            "signal": float(row['signal']),
                            "hist": float(row['histogram'])
                        })
                    chart_data[symbol] = records
                    
                    # 3. 分析実行
                    await asyncio.sleep(2) # Gemini 429 回避
                    funda_info = funda_analyzer.analyze(symbol, [], global_ctx)
                    result = engine.analyze(mtf_data, symbol=symbol, funda_info=funda_info)
                    
                    ai_text = ai_analyzer.analyze(result, symbol)
                    
                    system_state[symbol] = {
                        "status": result.status.value,
                        "score": result.win_rate_score,
                        "ai_text": ai_text,
                        "funda": funda_info,
                        "zigzag": calculate_zigzag(df_full.tail(100)),
                        "last_updated": datetime.now().isoformat()
                    }
                    
                    print(f"Sync Complete: {symbol} @ {result.win_rate_score}%")
                    
                except Exception as e:
                    print(f"Error Syncing {symbol}: {e}")
                    
            await asyncio.sleep(300) # 5分おきに全銘柄同期
        except Exception as e:
            print(f"Critical Loop Error: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())

@app.get("/api/predict")
def get_prediction():
    return {"data": system_state, "overview": market_overview}

@app.get("/api/chart/{symbol}")
def get_chart(symbol: str):
    return {"data": chart_data.get(symbol, [])}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
