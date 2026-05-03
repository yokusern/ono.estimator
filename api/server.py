import asyncio
import os
import time
import traceback
import pandas as pd
from collections import deque
from datetime import datetime, timedelta
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import requests

from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.notifier import Notifier
from ono_estimator.core.database import SupabaseClient
from ono_estimator.core import ONOPredictionEngine

load_dotenv()

app = FastAPI(title="ONO Estimator Ultra v5.0", version="5.0.0")

# CORS: Vercel URLを完全カバー
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ─── 設定 ────────────────────────────────────────────────
SYMBOLS = ["USDJPY=X", "GC=F", "BTC-USD", "^N225", "SI=F", "AUDJPY=X", "EURUSD=X", "EURJPY=X"]
CRYPTO_SYMBOLS = {"BTC-USD", "ETH-USD"}  # 24時間稼働
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ono-estimator.onrender.com")
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

# Geminiレート制限: 無料枠対応 (最大3回/分)
MAX_GEMINI_PER_MINUTE = 3
GEMINI_CALL_INTERVAL = 15  # 秒 (銘柄間ウェイト)

# ─── グローバルステート（APIが即返す） ─────────────────────
system_state = {
    sym: {tf: {
        "status": "Loading",
        "score": 0,
        "ai_text": "システム起動中...",
        "predicted_price": 0,
        "probability": 0,
        "last_updated": None
    } for tf in TIMEFRAMES}
    for sym in SYMBOLS
}
chart_data = {sym: {tf: [] for tf in TIMEFRAMES} for sym in SYMBOLS}
price_cache = {sym: 0.0 for sym in SYMBOLS}
# 各銘柄の最終AI分析時刻
last_ai_analysis = {sym: 0.0 for sym in SYMBOLS}
market_overview = {
    "global_theme": "市場データを同期中...",
    "last_update_ts": 0,
    "mode": "Starting"
}

# Geminiコール履歴（レート制限トラッキング）
_gemini_call_times: deque = deque(maxlen=60)

# ─── サービス初期化 ────────────────────────────────────────
fetcher = HybridDataFetcher()
engine = ONOPredictionEngine()
ai_analyzer = GeminiAnalyzer()
notifier = Notifier()
db = SupabaseClient()


# ─── ユーティリティ ────────────────────────────────────────
def is_market_open(symbol: str) -> bool:
    """市場が開いているか判定"""
    if symbol in CRYPTO_SYMBOLS:
        return True
    now = datetime.utcnow()
    wd = now.weekday()  # 0=月, 5=土, 6=日
    if wd == 5:
        return False  # 土曜終日
    if wd == 6 and now.hour < 21:
        return False  # 日曜の夜(21UTC=月朝6時JST)まで
    return True

def needs_ai_analysis(symbol: str) -> bool:
    """AI分析が必要かどうか（週末省エネモード）"""
    now = time.time()
    last = last_ai_analysis.get(symbol, 0)
    if symbol in CRYPTO_SYMBOLS:
        return True  # 仮想通貨は常に
    if is_market_open(symbol):
        return (now - last) > 58  # 1分ごと
    else:
        return (now - last) > 3600  # 週末は1時間ごと（展望のみ）

def can_call_gemini() -> bool:
    """レート制限チェック: 直近1分以内の呼び出し数を確認"""
    now = time.time()
    # 1分以上前のエントリを除去
    while _gemini_call_times and now - _gemini_call_times[0] > 60:
        _gemini_call_times.popleft()
    return len(_gemini_call_times) < MAX_GEMINI_PER_MINUTE

def record_gemini_call():
    """Gemini呼び出しを記録"""
    _gemini_call_times.append(time.time())


# ─── データ取得（スレッドで実行） ─────────────────────────
def _sync_fetch_and_analyze(symbol: str) -> dict:
    """ブロッキング処理: データ取得 + テクニカル分析"""
    df_base = fetcher.fetch_ohlcv(symbol, interval="1min")
    if df_base is None or df_base.empty:
        return None

    mtf_summaries = {}
    symbol_charts = {}
    result = None

    for tf in TIMEFRAMES:
        df_tf = fetcher.resample_ohlcv(df_base, tf)
        df_tf = fetcher.calculate_indicators(df_tf)
        if df_tf.empty:
            continue

        result = engine.analyze(None, symbol=symbol, df_precomputed=df_tf)
        latest = df_tf.iloc[-1]

        mtf_summaries[tf] = {
            "status": result.status.value if result.status else "Wait",
            "score": result.win_rate_score,
            "rsi": round(float(latest.get("rsi", 0)), 1),
            "price": float(latest["close"]),
        }

        records = []
        for idx, row in df_tf.tail(100).iterrows():
            records.append({
                "time": int(idx.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "rsi": float(row.get("rsi", 0)),
                "macd": float(row.get("macd", 0)),
            })
        symbol_charts[tf] = records

    price_cache[symbol] = float(df_base.iloc[-1]["close"])
    return {
        "symbol": symbol,
        "mtf": mtf_summaries,
        "charts": symbol_charts,
        "result_obj": result
    }


# ─── メインの監視ループ ────────────────────────────────────
async def estimation_loop():
    """メイン監視ループ: データ取得とAI分析を分離・スロットリング"""
    print("[Server] ONO Estimator Ultra v5.0 - Engine Started")

    # 起動直後にSupabaseから最新キャッシュをロード
    try:
        history = db.get_history(limit=len(SYMBOLS))
        for row in history:
            sym = row.get("symbol")
            if sym and sym in system_state:
                for tf in TIMEFRAMES:
                    system_state[sym][tf].update({
                        "ai_text": row.get("ai_text", "分析データを読み込み中..."),
                        "score": row.get("score", 0),
                        "status": row.get("status", "Wait"),
                        "predicted_price": row.get("predicted_price", 0),
                        "probability": row.get("probability", 0),
                        "last_updated": row.get("created_at"),
                    })
        print(f"[Startup] Preloaded {len(history)} records from Supabase cache")
        market_overview["mode"] = "Live"
    except Exception as e:
        print(f"[Startup] Cache preload failed (OK): {e}")

    while True:
        cycle_start = time.time()
        try:
            wday = datetime.utcnow().weekday()
            is_weekend = wday >= 5
            mode = "Weekend" if is_weekend else "Weekday"
            market_overview["mode"] = mode

            # ─── Step 1: 全銘柄のデータ取得（並列） ───────────
            tasks = [asyncio.to_thread(_sync_fetch_and_analyze, sym) for sym in SYMBOLS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # UIステートを即更新（AI待機ゼロ）
            valid_results = []
            for res in results:
                if isinstance(res, Exception) or res is None:
                    continue
                sym = res["symbol"]
                chart_data[sym] = res["charts"]
                open_status = is_market_open(sym)
                for tf in TIMEFRAMES:
                    if not open_status:
                        system_state[sym][tf]["status"] = "Closed"
                    elif tf in res["mtf"]:
                        system_state[sym][tf].update({
                            "status": res["mtf"][tf].get("status", "Wait"),
                            "score": res["mtf"][tf].get("score", 0),
                        })
                valid_results.append(res)

            # ─── Step 2: 順次AI分析（スロットリング付き） ────────
            performance_data = db.get_performance_summary()

            for res in valid_results:
                sym = res["symbol"]

                # 分析不要ならスキップ
                if not needs_ai_analysis(sym):
                    continue

                # レート制限チェック（1分に最大MAX_GEMINI_PER_MINUTE回）
                if not can_call_gemini():
                    wait_sec = 60 - (time.time() - _gemini_call_times[0])
                    if wait_sec > 0:
                        print(f"[RateLimiter] Quota reached. Waiting {wait_sec:.1f}s...")
                        await asyncio.sleep(wait_sec + 1)

                mode_label = "週末展望" if not is_market_open(sym) else "生分析"
                print(f"[Gemini] {mode_label} → {sym}")

                # AI分析をスレッドで実行
                record_gemini_call()
                ai_data = await asyncio.to_thread(
                    ai_analyzer.analyze_single, sym, res, performance_data
                )

                if ai_data and ai_data.get("ai_text"):
                    last_ai_analysis[sym] = time.time()
                    for tf in TIMEFRAMES:
                        system_state[sym][tf].update({
                            "ai_text": ai_data["ai_text"],
                            "predicted_price": ai_data.get("predicted_price", 0),
                            "probability": ai_data.get("probability", 0),
                            "last_updated": datetime.now().isoformat(),
                        })

                    # Supabaseに保存
                    try:
                        db.save_prediction({
                            "symbol": sym,
                            "status": system_state[sym]["1m"]["status"],
                            "score": system_state[sym]["1m"]["score"],
                            "ai_text": ai_data["ai_text"],
                            "predicted_price": ai_data.get("predicted_price", 0),
                            "probability": ai_data.get("probability", 0),
                            "current_price": price_cache.get(sym, 0),
                        })
                    except Exception as db_e:
                        print(f"[DB] Save error for {sym}: {db_e}")

                    # 通知
                    if system_state[sym]["1m"]["score"] >= 80:
                        notifier.notify_if_needed(sym, res.get("result_obj"), ai_data, price_cache.get(sym, 0))

                    # グローバルテーマ更新
                    if market_overview["last_update_ts"] < time.time() - 120:
                        market_overview["global_theme"] = ai_data["ai_text"][:80] + "..."
                        market_overview["last_update_ts"] = int(time.time())
                else:
                    print(f"[Gemini] No valid response for {sym}")

                # 銘柄間のウェイト（レート制限の核心）
                await asyncio.sleep(GEMINI_CALL_INTERVAL)

        except Exception as e:
            print(f"[Loop] Critical error: {e}")
            traceback.print_exc()

        elapsed = time.time() - cycle_start
        sleep_time = max(5, 60 - elapsed)
        print(f"[Loop] Cycle done in {elapsed:.1f}s. Next in {sleep_time:.1f}s")
        await asyncio.sleep(sleep_time)


async def backtest_loop():
    """30分おきに予測の自己採点"""
    await asyncio.sleep(60)
    while True:
        try:
            pending = db.get_unscored_predictions()
            for p in pending:
                sym = p["symbol"]
                current = price_cache.get(sym, 0)
                if current > 0 and p.get("current_price", 0) > 0:
                    is_buy = "BUY" in p.get("status", "").upper()
                    is_sell = "SELL" in p.get("status", "").upper()
                    is_correct = (is_buy and current > p["current_price"]) or \
                                 (is_sell and current < p["current_price"])
                    db.update_prediction_result(p["id"], current, is_correct)
                    print(f"[Backtest] {sym}: {'WIN' if is_correct else 'LOSS'}")
        except Exception as e:
            print(f"[Backtest] Error: {e}")
        await asyncio.sleep(1800)


async def anti_sleep_loop():
    """4分おきにセルフPingでRenderを起こし続ける"""
    await asyncio.sleep(30)
    while True:
        try:
            r = requests.get(f"{RENDER_URL}/api/health", timeout=10)
            print(f"[AntiSleep] Ping OK ({r.status_code})")
        except Exception as e:
            print(f"[AntiSleep] Ping failed: {e}")
        await asyncio.sleep(240)


# ─── API エンドポイント ────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())
    asyncio.create_task(backtest_loop())
    asyncio.create_task(anti_sleep_loop())


@app.get("/")
def root():
    return {"status": "ONO Estimator Ultra v5.0", "time": datetime.now().isoformat()}


@app.get("/api/health")
def health():
    gemini_calls = len(_gemini_call_times)
    return {
        "status": "healthy",
        "mode": market_overview.get("mode", "unknown"),
        "gemini_calls_last_min": gemini_calls,
        "last_sync": market_overview["last_update_ts"],
        "uptime": int(time.time()),
    }


@app.get("/api/predict")
def get_prediction(tf: str = Query("1m", pattern="^(1m|5m|15m|1h|4h)$")):
    """メインデータエンドポイント: system_stateを即返却（AI待機ゼロ）"""
    tf_state = {sym: states.get(tf) for sym, states in system_state.items()}
    return {
        "data": tf_state,
        "overview": market_overview,
        "current_tf": tf,
        "server_time": int(time.time()),
    }


@app.get("/api/chart/{symbol}")
def get_chart(symbol: str, tf: str = Query("1m", pattern="^(1m|5m|15m|1h|4h)$")):
    mapping = {
        "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
        "JP225": "^N225", "XAGUSD": "SI=F", "SILVER": "SI=F",
        "AUDJPY": "AUDJPY=X", "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
    }
    ticker = mapping.get(symbol, symbol)
    return {"data": chart_data.get(ticker, {}).get(tf, [])}


@app.get("/api/history")
def get_history(limit: int = Query(50, le=100)):
    """最新の履歴を返す（Supabaseキャッシュ）"""
    try:
        return {"data": db.get_history(limit=limit)}
    except Exception:
        return {"data": []}
