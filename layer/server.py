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

# ─── v6.0 新エンジン ──────────────────────────────────────────
try:
    from ono_estimator.core.engine_v2 import ONOPredictionEngineV2
    _engine_v2_available = True
    print("[Server] ONO Engine v6.0 loaded ✅")
except Exception as _e:
    _engine_v2_available = False
    print(f"[Server] Engine v6.0 not available, using v5: {_e}")

load_dotenv()

app = FastAPI(title="ONO Estimator Ultra v6.0", version="6.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ─── 設定 ────────────────────────────────────────────────────
SYMBOLS = ["USDJPY=X", "GC=F", "BTC-USD", "^N225", "SI=F", "AUDJPY=X", "EURUSD=X", "EURJPY=X"]
CRYPTO_SYMBOLS = {"BTC-USD"}
# 30m足を追加
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h"]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ono-estimator.onrender.com")
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

MAX_GEMINI_PER_MINUTE = 3
GEMINI_CALL_INTERVAL = 15

# ─── グローバルステート ────────────────────────────────────────
system_state = {
    sym: {tf: {
        "status": "Loading",
        "score": 0,
        "ai_text": "システム起動中...",
        "predicted_price": 0,
        "probability": 0,
        "last_updated": None,
        # v6.0 追加フィールド
        "layers": {},
        "aligned": 0,
        "confidence": "",
        "tp1": 0,
        "tp2": 0,
        "tp3": 0,
        "sl": 0,
        "rr": 0,
        "signals": [],
        "warnings": [],
        "emoji": "⚪",
    } for tf in TIMEFRAMES}
    for sym in SYMBOLS
}
chart_data = {sym: {tf: [] for tf in TIMEFRAMES} for sym in SYMBOLS}
price_cache = {sym: 0.0 for sym in SYMBOLS}
last_ai_analysis = {sym: 0.0 for sym in SYMBOLS}
market_overview = {
    "global_theme": "市場データを同期中...",
    "last_update_ts": 0,
    "mode": "Starting",
    "performance": "",   # 過去データ戦績サマリー
    "history_stats": {}, # 銘柄別勝率
}

_gemini_call_times: deque = deque(maxlen=60)

# ─── サービス初期化 ───────────────────────────────────────────
fetcher = HybridDataFetcher()
engine_v1 = ONOPredictionEngine()
engine_v2 = ONOPredictionEngineV2() if _engine_v2_available else None
ai_analyzer = GeminiAnalyzer()
notifier = Notifier()
db = SupabaseClient()


# ─── ユーティリティ ────────────────────────────────────────────
def is_market_open(symbol: str) -> bool:
    if symbol in CRYPTO_SYMBOLS:
        return True
    now = datetime.utcnow()
    wd = now.weekday()
    if wd == 5:
        return False
    if wd == 6 and now.hour < 21:
        return False
    return True

def needs_ai_analysis(symbol: str) -> bool:
    now = time.time()
    last = last_ai_analysis.get(symbol, 0)
    if symbol in CRYPTO_SYMBOLS:
        return True
    if is_market_open(symbol):
        return (now - last) > 58
    else:
        return (now - last) > 3600

def can_call_gemini() -> bool:
    now = time.time()
    while _gemini_call_times and now - _gemini_call_times[0] > 60:
        _gemini_call_times.popleft()
    return len(_gemini_call_times) < MAX_GEMINI_PER_MINUTE

def record_gemini_call():
    _gemini_call_times.append(time.time())


# ─── 過去データ統計の取得 ─────────────────────────────────────
def _load_history_stats() -> dict:
    """Supabaseから銘柄別勝率を集計"""
    try:
        history = db.get_history(limit=200)
        if not history:
            return {}
        stats = {}
        for row in history:
            sym = row.get("symbol", "")
            if not sym:
                continue
            if sym not in stats:
                stats[sym] = {"total": 0, "correct": 0, "win_rate": 50}
            if row.get("is_scored"):
                stats[sym]["total"] += 1
                if row.get("is_correct"):
                    stats[sym]["correct"] += 1
        for sym, s in stats.items():
            if s["total"] > 0:
                s["win_rate"] = round(s["correct"] / s["total"] * 100, 1)
        return stats
    except Exception as e:
        print(f"[HistoryStats] Error: {e}")
        return {}


def _get_history_feedback_for_symbol(symbol: str) -> str:
    """指定銘柄の過去予測履歴をAI向けのフィードバック文字列として返す"""
    try:
        history = db.get_history(limit=100)
        sym_key = symbol.replace("=X", "").replace("-USD", "").replace("^", "").replace("GC=F", "GOLD").replace("SI=F", "XAGUSD")
        rows = [r for r in history if sym_key in r.get("symbol", "")]
        if not rows:
            return db.get_performance_summary()

        total = len([r for r in rows if r.get("is_scored")])
        correct = len([r for r in rows if r.get("is_correct")])
        recent = rows[:5]

        lines = [f"【{sym_key}固有の過去実績】 採点済{total}件, 勝率{round(correct/total*100,1) if total else 'N/A'}%"]
        for r in recent:
            direction = r.get("status", "?")
            scored = "✓WIN" if r.get("is_correct") else ("✗LOSS" if r.get("is_scored") else "pending")
            lines.append(f"  - {direction} | score:{r.get('score',0)} | {scored}")
        return "\n".join(lines)
    except Exception as e:
        return f"History load error: {e}"


# ─── データ取得・分析（ブロッキング） ────────────────────────
def _sync_fetch_and_analyze(symbol: str) -> dict:
    """データ取得 + テクニカル分析（v6エンジン統合）"""
    df_base = fetcher.fetch_ohlcv(symbol, interval="1min")
    if df_base is None or df_base.empty:
        return None

    mtf_summaries = {}
    symbol_charts = {}
    result_v6 = None

    for tf in TIMEFRAMES:
        df_tf = fetcher.resample_ohlcv(df_base, tf)
        df_tf = fetcher.calculate_indicators(df_tf)
        if df_tf.empty:
            continue

        # v6エンジン使用（30m足も対応）
        if engine_v2 and len(df_tf) >= 30:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                v6 = loop.run_until_complete(engine_v2.analyze(
                    symbol.replace("=X","").replace("-USD","").replace("^","").replace("GC=F","GOLD").replace("SI=F","XAGUSD"),
                    df_tf
                ))
                loop.close()
                if tf == "1h":  # メイン足としてv6結果を保存
                    result_v6 = v6
                score = int(v6.get("score", 50))
                status = v6.get("direction", "WAIT").replace("STRONG_", "")
            except Exception as e:
                print(f"[v6] {symbol}/{tf}: {e}")
                result_legacy = engine_v1.analyze(None, symbol=symbol, df_precomputed=df_tf)
                score = result_legacy.win_rate_score
                status = result_legacy.status.value if result_legacy.status else "Wait"
                v6 = {}
        else:
            result_legacy = engine_v1.analyze(None, symbol=symbol, df_precomputed=df_tf)
            score = result_legacy.win_rate_score
            status = result_legacy.status.value if result_legacy.status else "Wait"
            v6 = {}

        latest = df_tf.iloc[-1]
        mtf_summaries[tf] = {
            "status": status,
            "score": score,
            "rsi": round(float(latest.get("rsi", 0)), 1),
            "price": float(latest["close"]),
            # v6追加フィールド
            "layers": v6.get("layers", {}),
            "aligned": v6.get("aligned", 0),
            "tp1": v6.get("tp1", 0),
            "tp2": v6.get("tp", 0),
            "tp3": v6.get("tp3", 0),
            "sl": v6.get("sl", 0),
            "rr": v6.get("rr", 0),
            "signals": v6.get("signals", [])[:5],
            "warnings": v6.get("warnings", []),
            "emoji": v6.get("emoji", "⚪"),
            "confidence": v6.get("confidence", ""),
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
        "result_v6": result_v6,
    }


# ─── メイン監視ループ ─────────────────────────────────────────
async def estimation_loop():
    print("[Server] ONO Estimator Ultra v6.0 - Engine Started")

    # 起動時: Supabaseから最新キャッシュをロード
    try:
        history = db.get_history(limit=len(SYMBOLS) * 2)
        loaded = 0
        for row in history:
            sym = row.get("symbol")
            if sym and sym in system_state:
                for tf in TIMEFRAMES:
                    if system_state[sym][tf]["status"] == "Loading":
                        system_state[sym][tf].update({
                            "ai_text": row.get("ai_text", "分析データを読み込み中..."),
                            "score": row.get("score", 0),
                            "status": row.get("status", "Wait"),
                            "predicted_price": row.get("predicted_price", 0),
                            "probability": row.get("probability", 0),
                            "last_updated": row.get("created_at"),
                        })
                        loaded += 1
                        break
        # 戦績サマリーをロード
        market_overview["performance"] = db.get_performance_summary()
        market_overview["history_stats"] = _load_history_stats()
        print(f"[Startup] Preloaded {loaded} records. Performance: {market_overview['performance']}")
        market_overview["mode"] = "Live"
    except Exception as e:
        print(f"[Startup] Cache preload failed (OK): {e}")

    while True:
        cycle_start = time.time()
        try:
            for sym in SYMBOLS:
                try:
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(None, _sync_fetch_and_analyze, sym)
                    if not data:
                        continue

                    mtf = data["mtf"]
                    charts = data["charts"]
                    result_v6 = data.get("result_v6")

                    # チャートデータ更新
                    for tf, records in charts.items():
                        if records:
                            chart_data[sym][tf] = records

                    # システムステート更新（v6フィールドも）
                    for tf, summary in mtf.items():
                        system_state[sym][tf].update({
                            "status": summary.get("status", "Wait"),
                            "score": summary.get("score", 0),
                            "layers": summary.get("layers", {}),
                            "aligned": summary.get("aligned", 0),
                            "tp1": summary.get("tp1", 0),
                            "tp2": summary.get("tp2", 0),
                            "tp3": summary.get("tp3", 0),
                            "sl": summary.get("sl", 0),
                            "rr": summary.get("rr", 0),
                            "signals": summary.get("signals", []),
                            "warnings": summary.get("warnings", []),
                            "emoji": summary.get("emoji", "⚪"),
                            "confidence": summary.get("confidence", ""),
                        })

                    # AI分析（Geminiレート制限考慮）
                    if needs_ai_analysis(sym) and can_call_gemini():
                        record_gemini_call()
                        last_ai_analysis[sym] = time.time()

                        # 過去データフィードバックを取得
                        history_feedback = _get_history_feedback_for_symbol(sym)

                        # v6のgemini_promptがあれば使う
                        gemini_prompt_override = result_v6.get("gemini_prompt") if result_v6 else None

                        ai_data = ai_analyzer.analyze_single(
                            sym,
                            {"mtf": mtf},
                            feedback=history_feedback,
                            gemini_prompt_override=gemini_prompt_override,
                        )
                        if ai_data and ai_data.get("ai_text"):
                            for tf in TIMEFRAMES:
                                system_state[sym][tf].update({
                                    "ai_text": ai_data["ai_text"],
                                    "predicted_price": ai_data.get("predicted_price", 0),
                                    "probability": ai_data.get("probability", 0),
                                    "last_updated": datetime.now().isoformat(),
                                })
                            # Supabase保存
                            db.save_prediction({
                                "symbol": sym,
                                "status": system_state[sym]["1h"]["status"],
                                "score": system_state[sym]["1h"]["score"],
                                "ai_text": ai_data["ai_text"],
                                "predicted_price": ai_data.get("predicted_price", 0),
                                "probability": ai_data.get("probability", 0),
                                "current_price": price_cache.get(sym, 0),
                            })
                            if market_overview["last_update_ts"] < time.time() - 120:
                                market_overview["global_theme"] = ai_data["ai_text"][:80] + "..."
                                market_overview["last_update_ts"] = int(time.time())

                        await asyncio.sleep(GEMINI_CALL_INTERVAL)

                except Exception as e:
                    print(f"[Loop] Error for {sym}: {e}")
                    traceback.print_exc()

        except Exception as e:
            print(f"[Loop] Critical error: {e}")
            traceback.print_exc()

        elapsed = time.time() - cycle_start
        sleep_time = max(5, 60 - elapsed)
        print(f"[Loop] Cycle done in {elapsed:.1f}s. Next in {sleep_time:.1f}s")
        await asyncio.sleep(sleep_time)


async def backtest_loop():
    """30分おきに予測の自己採点 + 戦績キャッシュ更新"""
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
            # 戦績サマリー更新
            market_overview["performance"] = db.get_performance_summary()
            market_overview["history_stats"] = _load_history_stats()
        except Exception as e:
            print(f"[Backtest] Error: {e}")
        await asyncio.sleep(1800)


async def anti_sleep_loop():
    await asyncio.sleep(30)
    while True:
        try:
            r = requests.get(f"{RENDER_URL}/api/health", timeout=10)
            print(f"[AntiSleep] Ping OK ({r.status_code})")
        except Exception as e:
            print(f"[AntiSleep] Ping failed: {e}")
        await asyncio.sleep(240)


# ─── API エンドポイント ────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())
    asyncio.create_task(backtest_loop())
    asyncio.create_task(anti_sleep_loop())


@app.get("/")
def root():
    return {"status": "ONO Estimator Ultra v6.0", "time": datetime.now().isoformat()}


@app.get("/api/health")
def health():
    gemini_calls = len(_gemini_call_times)
    return {
        "status": "healthy",
        "version": "6.0.0",
        "engine_v2": _engine_v2_available,
        "mode": market_overview.get("mode", "unknown"),
        "gemini_calls_last_min": gemini_calls,
        "last_sync": market_overview["last_update_ts"],
        "performance": market_overview.get("performance", ""),
        "uptime": int(time.time()),
    }


@app.get("/api/predict")
def get_prediction(tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    """メインデータエンドポイント"""
    tf_state = {sym: states.get(tf) for sym, states in system_state.items()}
    return {
        "data": tf_state,
        "overview": market_overview,
        "current_tf": tf,
        "server_time": int(time.time()),
        "engine_version": "6.0" if _engine_v2_available else "5.0",
    }


@app.get("/api/chart/{symbol}")
def get_chart(symbol: str, tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    mapping = {
        "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
        "JP225": "^N225", "XAGUSD": "SI=F", "SILVER": "SI=F",
        "AUDJPY": "AUDJPY=X", "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
    }
    ticker = mapping.get(symbol, symbol)
    return {"data": chart_data.get(ticker, {}).get(tf, [])}


@app.get("/api/history")
def get_history(limit: int = Query(50, le=100)):
    """最新の履歴を返す"""
    try:
        return {
            "data": db.get_history(limit=limit),
            "performance": market_overview.get("performance", ""),
            "stats": market_overview.get("history_stats", {}),
        }
    except Exception:
        return {"data": [], "performance": "", "stats": {}}


@app.get("/api/history/stats")
def get_history_stats():
    """銘柄別・全体の勝率統計"""
    return {
        "overall": market_overview.get("performance", ""),
        "by_symbol": market_overview.get("history_stats", {}),
        "engine_version": "6.0" if _engine_v2_available else "5.0",
    }
