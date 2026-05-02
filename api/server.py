import asyncio
import os
import json
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

app = FastAPI(title="ONO Estimator Ultimate v2.1", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 監視銘柄 (8銘柄)
target_symbols = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"]
system_state = {sym: {"status": "Wait", "score": 0, "ai_text": "", "last_updated": ""} for sym in target_symbols}

async def estimation_loop():
    print("--- ONO Estimator v2.1: 7-Source Integration Mode Started ---")
    connector = YFinanceConnector()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    funda_analyzer = FundaAnalyzer()
    notifier = Notifier()
    context_fetcher = MarketContextFetcher()
    
    previous_status = {sym: SignalStatus.NONE for sym in target_symbols}
    
    while True:
        try:
            for symbol in target_symbols:
                # 1. マルチデータソースからのコンテキスト取得
                market_context = context_fetcher.fetch_all(symbol)
                
                # 2. 基本データ（yfinance）とニュース取得
                mtf_data = connector.fetch_mtf_data(symbol)
                yf_news = connector.fetch_news(symbol)
                
                if mtf_data is None: continue
                
                df_m5 = mtf_data.get_data("5m")
                current_price = df_m5['close'].iloc[-1] if df_m5 is not None else 0.0
                
                # 3. 7つのデータソースを統合したAIファンダメンタルズ分析
                funda_info = funda_analyzer.analyze(symbol, yf_news, market_context)
                
                # 4. メインエンジンによるテクニカル＋ファンダ統合判定
                result = engine.analyze(mtf_data, symbol=symbol, funda_info=funda_info)
                
                prev = previous_status[symbol]
                curr = result.status
                
                # 重要変化時、または重要サイン時に詳細AI分析を実行
                if curr != prev or (curr != SignalStatus.NONE and not system_state[symbol]["ai_text"]):
                    ai_text = ai_analyzer.analyze(result, symbol)
                    
                    # グローバル状態の更新 (Frontend同期用)
                    system_state[symbol] = {
                        "status": curr.value,
                        "score": result.win_rate_score,
                        "ai_text": ai_text,
                        "last_updated": datetime.now().isoformat(),
                        "tags": result.tags,
                        "funda": funda_info
                    }
                    
                    # 5. マルチチャネル・ルーティング通知
                    notifier.notify_if_needed(symbol, result, ai_text, current_price)
                    
                    print(f">>> [{symbol}] {prev.value} -> {curr.value} (Price: {current_price}) <<<")
                    
                previous_status[symbol] = curr

            # 5分間の待機（APIレート制限と市場変動のバランス）
            await asyncio.sleep(300)
            
        except Exception as e:
            print(f"Server Loop Critical Error: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())

@app.get("/api/predict")
def get_prediction():
    """フロントエンドの全銘柄同期用エンドポイント"""
    return {"data": system_state}

@app.get("/api/history")
def get_history(limit: int = 50):
    """履歴ログ取得"""
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
