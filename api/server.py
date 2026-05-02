import asyncio
import os
import json
import time
from datetime import datetime
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

app = FastAPI(title="ONO Estimator Ultimate v2.2", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 監視銘柄 (8銘柄)
target_symbols = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"]

# グローバルステートの初期化 (空の状態でもUIが壊れないようにする)
system_state = {
    sym: {
        "status": "Wait",
        "score": 0,
        "ai_text": "分析待機中...",
        "last_updated": datetime.now().isoformat(),
        "tags": [],
        "funda": {"theme": "Initializing...", "direction": "NEUTRAL"}
    } for sym in target_symbols
}

# 市場全体の状況（Cross-Asset用）
market_overview = {
    "fear_greed": "Loading...",
    "global_theme": "Analyzing Global Market...",
    "correlations": []
}

async def estimation_loop():
    print("--- ONO Estimator v2.2: Stability & Performance Mode ---")
    connector = YFinanceConnector()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    funda_analyzer = FundaAnalyzer()
    notifier = Notifier()
    context_fetcher = MarketContextFetcher()
    
    previous_status = {sym: SignalStatus.NONE for sym in target_symbols}
    
    while True:
        try:
            # 1. 市場全体の共通コンテキスト取得（ループの最初に一度だけ）
            global_context = context_fetcher.fetch_all("GLOBAL")
            market_overview["fear_greed"] = global_context.get("fear_greed", "N/A")
            
            for symbol in target_symbols:
                try:
                    # レート制限回避: 銘柄間にインターバルを置く
                    await asyncio.sleep(2) 
                    
                    # 2. データ取得 (Yahoo Finance)
                    mtf_data = connector.fetch_mtf_data(symbol)
                    yf_news = connector.fetch_news(symbol)
                    
                    if mtf_data is None:
                        print(f"Skipping {symbol}: No data from yfinance.")
                        continue
                        
                    df_m5 = mtf_data.get_data("5m")
                    current_price = df_m5['close'].iloc[-1] if df_m5 is not None else 0.0
                    
                    # 3. ファンダメンタルズ分析 (Gemini)
                    # ここでもレート制限を考慮し、ウェイトを置く
                    await asyncio.sleep(1)
                    funda_info = funda_analyzer.analyze(symbol, yf_news, global_context)
                    
                    # 4. テクニカル判定
                    result = engine.analyze(mtf_data, symbol=symbol, funda_info=funda_info)
                    
                    prev = previous_status[symbol]
                    curr = result.status
                    
                    # AI詳細分析の実行要件
                    should_ai_analyze = (curr != prev) or (curr != SignalStatus.NONE and "分析待機中" in system_state[symbol]["ai_text"])
                    
                    if should_ai_analyze:
                        await asyncio.sleep(2) # Geminiの連続リクエストを避ける
                        ai_text = ai_analyzer.analyze(result, symbol)
                        
                        system_state[symbol] = {
                            "status": curr.value,
                            "score": result.win_rate_score,
                            "ai_text": ai_text,
                            "last_updated": datetime.now().isoformat(),
                            "tags": result.tags,
                            "funda": funda_info
                        }
                        
                        notifier.notify_if_needed(symbol, result, ai_text, current_price)
                        print(f">>> [{symbol}] {curr.value} (Score: {result.win_rate_score}) <<<")
                    else:
                        # ステータス不変でも価格や一部のデータのみ更新
                        system_state[symbol]["last_updated"] = datetime.now().isoformat()

                    previous_status[symbol] = curr
                    
                except Exception as sym_e:
                    print(f"Error processing {symbol}: {sym_e}")
                    await asyncio.sleep(5)

            # 全銘柄一巡後の待機
            await asyncio.sleep(300)
            
        except Exception as e:
            print(f"Main Loop Critical Error: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())

@app.get("/api/predict")
def get_prediction():
    return {"data": system_state, "overview": market_overview}

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/history")
def get_history(limit: int = 50):
    history = []
    if os.path.exists("annotations.jsonl"):
        try:
            with open("annotations.jsonl", "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    history.append(json.loads(line))
                    if len(history) >= limit: break
        except Exception: pass
    return {"data": history}
