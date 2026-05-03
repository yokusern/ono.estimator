"""
ONO Estimator Ultra v6.0 — server.py
膨大な過去データ対応版

変更点:
  - fetch_ohlcv(1分足) → fetch_full_ohlcv(TF別長期取得) に移行
  - AI分析にはフルデータ(全期間)を使用
  - チャートには末尾500本を返す
  - メモリキャッシュで高速レスポンス
  - 30m足追加
"""

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

try:
    from ono_estimator.core.engine_v2 import ONOPredictionEngineV2
    _engine_v2_available = True
    print("[Server] ONO Engine v6.0 loaded ✅")
except Exception as _e:
    _engine_v2_available = False
    print(f"[Server] Engine v6.0 fallback to v5: {_e}")

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
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h"]

# チャートAPIで返す足数（TFごと）
CHART_BARS = {
    "1m": 500, "5m": 500, "15m": 500,
    "30m": 500, "1h": 500, "4h": 500,
}

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ono-estimator.onrender.com")
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

MAX_GEMINI_PER_MINUTE = 3
GEMINI_CALL_INTERVAL = 15

# AI分析に使うメイン足（多くの過去データを持つ足）
ANALYSIS_TF = "1h"

# ─── グローバルステート ────────────────────────────────────────
system_state = {
    sym: {tf: {
        "status": "Loading", "score": 0,
        "ai_text": "システム起動中...",
        "predicted_price": 0, "probability": 0,
        "last_updated": None,
        "layers": {}, "aligned": 0, "confidence": "",
        "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "rr": 0,
        "signals": [], "warnings": [], "emoji": "⚪",
        "data_bars": 0,   # ← 何本のデータで分析したか
    } for tf in TIMEFRAMES}
    for sym in SYMBOLS
}

# チャートデータキャッシュ（フロントエンドへ返すもの: tail N本）
chart_cache: dict = {sym: {tf: [] for tf in TIMEFRAMES} for sym in SYMBOLS}

price_cache: dict = {sym: 0.0 for sym in SYMBOLS}
last_ai_analysis: dict = {sym: 0.0 for sym in SYMBOLS}
market_overview: dict = {
    "global_theme": "市場データを同期中...",
    "last_update_ts": 0,
    "mode": "Starting",
    "performance": "",
    "history_stats": {},
    "data_summary": {},   # ← 銘柄別データ取得本数サマリー
}
_gemini_call_times: deque = deque(maxlen=60)

# ─── サービス初期化 ───────────────────────────────────────────
fetcher   = HybridDataFetcher()
engine_v1 = ONOPredictionEngine()
engine_v2 = ONOPredictionEngineV2() if _engine_v2_available else None
ai_analyzer = GeminiAnalyzer()
notifier    = Notifier()
db          = SupabaseClient()


# ─── ユーティリティ ────────────────────────────────────────────
def is_market_open(symbol: str) -> bool:
    if symbol in CRYPTO_SYMBOLS:
        return True
    now = datetime.utcnow()
    wd = now.weekday()
    if wd == 5 or (wd == 6 and now.hour < 21):
        return False
    return True

def needs_ai_analysis(symbol: str) -> bool:
    now = time.time()
    last = last_ai_analysis.get(symbol, 0)
    if symbol in CRYPTO_SYMBOLS:
        return True
    if is_market_open(symbol):
        return (now - last) > 58
    return (now - last) > 3600

def can_call_gemini() -> bool:
    now = time.time()
    while _gemini_call_times and now - _gemini_call_times[0] > 60:
        _gemini_call_times.popleft()
    return len(_gemini_call_times) < MAX_GEMINI_PER_MINUTE

def record_gemini_call():
    _gemini_call_times.append(time.time())

def _sym_short(symbol: str) -> str:
    return (symbol.replace("=X","").replace("-USD","")
            .replace("^","").replace("GC=F","GOLD")
            .replace("SI=F","XAGUSD"))


# ─── 過去データフィードバック ─────────────────────────────────
def _get_history_feedback(symbol: str) -> str:
    try:
        history = db.get_history(limit=100)
        key = _sym_short(symbol)
        rows = [r for r in history if key in r.get("symbol", "")]
        if not rows:
            return db.get_performance_summary()
        scored  = [r for r in rows if r.get("is_scored")]
        correct = [r for r in rows if r.get("is_correct")]
        wr = round(len(correct)/len(scored)*100,1) if scored else None
        lines = [f"【{key}過去実績】 採点済{len(scored)}件, 勝率{wr if wr else 'N/A'}%"]
        for r in rows[:5]:
            tag = "✓WIN" if r.get("is_correct") else ("✗LOSS" if r.get("is_scored") else "pending")
            lines.append(f"  {r.get('status','?')} score:{r.get('score',0)} {tag}")
        return "\n".join(lines)
    except Exception as e:
        return f"History error: {e}"

def _load_history_stats() -> dict:
    try:
        history = db.get_history(limit=200)
        stats: dict = {}
        for row in history:
            sym = row.get("symbol","")
            if not sym: continue
            if sym not in stats:
                stats[sym] = {"total":0,"correct":0,"win_rate":50}
            if row.get("is_scored"):
                stats[sym]["total"] += 1
                if row.get("is_correct"):
                    stats[sym]["correct"] += 1
        for s in stats.values():
            if s["total"] > 0:
                s["win_rate"] = round(s["correct"]/s["total"]*100, 1)
        return stats
    except:
        return {}


# ─── コア分析関数（ブロッキング） ─────────────────────────────
def _analyze_symbol(symbol: str) -> dict:
    """
    1銘柄の全TF分析。
    各TFごとに独立してフルデータを取得 → インジケーター計算 → エンジン分析
    """
    results = {}

    for tf in TIMEFRAMES:
        try:
            # ★ フルデータ取得（TFごと最適化済み）
            df = fetcher.get_analysis_df(symbol, tf)
            if df is None or df.empty or len(df) < 30:
                continue

            bars = len(df)

            # ── v6エンジン ──────────────────────────────────
            v6 = {}
            if engine_v2 and bars >= 50:
                try:
                    import asyncio as _aio
                    loop = _aio.new_event_loop()
                    v6 = loop.run_until_complete(
                        engine_v2.analyze(_sym_short(symbol), df)
                    )
                    loop.close()
                except Exception as e:
                    print(f"[v6] {symbol}/{tf}: {e}")

            # ── v5フォールバック ────────────────────────────
            if not v6:
                r = engine_v1.analyze(None, symbol=symbol, df_precomputed=df)
                v6 = {
                    "direction": r.status.value if r.status else "Wait",
                    "score":     r.win_rate_score,
                    "layers":    {},
                    "aligned":   0,
                }

            score  = int(v6.get("score", 50))
            status = v6.get("direction", "Wait").replace("STRONG_","")
            latest = df.iloc[-1]

            results[tf] = {
                "status":    status,
                "score":     score,
                "rsi":       round(float(latest.get("rsi", 50)), 1),
                "price":     float(latest["close"]),
                "layers":    v6.get("layers", {}),
                "aligned":   v6.get("aligned", 0),
                "confidence":v6.get("confidence", ""),
                "tp1":       v6.get("tp1", 0),
                "tp2":       v6.get("tp", 0),
                "tp3":       v6.get("tp3", 0),
                "sl":        v6.get("sl", 0),
                "rr":        v6.get("rr", 0),
                "signals":   v6.get("signals", [])[:5],
                "warnings":  v6.get("warnings", []),
                "emoji":     v6.get("emoji", "⚪"),
                "gemini_prompt": v6.get("gemini_prompt"),
                "data_bars": bars,
            }

            # ★ チャートデータ（末尾500本）
            chart_cache[symbol][tf] = fetcher.get_chart_data(symbol, tf)

        except Exception as e:
            print(f"[Analyze] {symbol}/{tf}: {e}")
            traceback.print_exc()

    if results:
        # 最新価格をキャッシュ
        latest_close = results.get(ANALYSIS_TF, results.get("1h", {})).get("price", 0)
        if latest_close:
            price_cache[symbol] = latest_close

    return results


# ─── メイン監視ループ ─────────────────────────────────────────
async def estimation_loop():
    print("[Server] ONO Estimator Ultra v6.0 - Engine Started")

    # 起動時: Supabase キャッシュをプリロード
    try:
        history = db.get_history(limit=len(SYMBOLS)*2)
        loaded = 0
        for row in history:
            sym = row.get("symbol")
            if sym and sym in system_state:
                for tf in TIMEFRAMES:
                    if system_state[sym][tf]["status"] == "Loading":
                        system_state[sym][tf].update({
                            "ai_text":        row.get("ai_text", "分析データを読み込み中..."),
                            "score":          row.get("score", 0),
                            "status":         row.get("status", "Wait"),
                            "predicted_price":row.get("predicted_price", 0),
                            "probability":    row.get("probability", 0),
                            "last_updated":   row.get("created_at"),
                        })
                        loaded += 1
                        break
        market_overview["performance"]   = db.get_performance_summary()
        market_overview["history_stats"] = _load_history_stats()
        market_overview["mode"] = "Live"
        print(f"[Startup] Preloaded {loaded} records from Supabase")
    except Exception as e:
        print(f"[Startup] Cache preload failed (OK): {e}")

    data_summary: dict = {}

    while True:
        cycle_start = time.time()
        try:
            for sym in SYMBOLS:
                try:
                    loop = asyncio.get_event_loop()

                    # ★ TFごと独立取得・分析（ブロッキングを別スレッドで）
                    tf_results = await loop.run_in_executor(None, _analyze_symbol, sym)

                    if not tf_results:
                        continue

                    # システムステートを更新
                    for tf, summary in tf_results.items():
                        system_state[sym][tf].update(summary)

                    # データ本数サマリー（ヘルスチェック用）
                    data_summary[sym] = {
                        tf: tf_results[tf]["data_bars"]
                        for tf in tf_results
                    }
                    market_overview["data_summary"] = data_summary

                    # ── Gemini AI 分析 ──────────────────────────
                    if needs_ai_analysis(sym) and can_call_gemini():
                        record_gemini_call()
                        last_ai_analysis[sym] = time.time()

                        feedback = _get_history_feedback(sym)

                        # v6のGeminiプロンプトがあれば使う（長期データに基づく）
                        v6_prompt = tf_results.get(ANALYSIS_TF, {}).get("gemini_prompt")

                        ai_data = ai_analyzer.analyze_single(
                            sym,
                            {"mtf": tf_results},
                            feedback=feedback,
                            gemini_prompt_override=v6_prompt,
                        )

                        if ai_data and ai_data.get("ai_text"):
                            for tf in TIMEFRAMES:
                                system_state[sym][tf].update({
                                    "ai_text":         ai_data["ai_text"],
                                    "predicted_price": ai_data.get("predicted_price", 0),
                                    "probability":     ai_data.get("probability", 0),
                                    "last_updated":    datetime.now().isoformat(),
                                })

                            # Supabase 保存
                            db.save_prediction({
                                "symbol":          sym,
                                "status":          system_state[sym]["1h"]["status"],
                                "score":           system_state[sym]["1h"]["score"],
                                "ai_text":         ai_data["ai_text"],
                                "predicted_price": ai_data.get("predicted_price", 0),
                                "probability":     ai_data.get("probability", 0),
                                "current_price":   price_cache.get(sym, 0),
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
    """30分おきに自己採点 + 戦績更新"""
    await asyncio.sleep(60)
    while True:
        try:
            pending = db.get_unscored_predictions()
            for p in pending:
                sym    = p["symbol"]
                current = price_cache.get(sym, 0)
                if current > 0 and p.get("current_price", 0) > 0:
                    is_buy  = "BUY" in p.get("status","").upper()
                    is_sell = "SELL" in p.get("status","").upper()
                    correct = (is_buy  and current > p["current_price"]) or \
                              (is_sell and current < p["current_price"])
                    db.update_prediction_result(p["id"], current, correct)
                    print(f"[Backtest] {sym}: {'WIN' if correct else 'LOSS'}")

            market_overview["performance"]   = db.get_performance_summary()
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
    return {
        "status":         "healthy",
        "version":        "6.0.0",
        "engine_v2":      _engine_v2_available,
        "mode":           market_overview.get("mode","unknown"),
        "gemini_calls_last_min": len(_gemini_call_times),
        "last_sync":      market_overview["last_update_ts"],
        "performance":    market_overview.get("performance",""),
        "data_summary":   market_overview.get("data_summary", {}),
        "uptime":         int(time.time()),
    }


@app.get("/api/predict")
def get_prediction(tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    tf_state = {sym: states.get(tf) for sym, states in system_state.items()}
    return {
        "data":           tf_state,
        "overview":       market_overview,
        "current_tf":     tf,
        "server_time":    int(time.time()),
        "engine_version": "6.0" if _engine_v2_available else "5.0",
    }


@app.get("/api/chart/{symbol}")
def get_chart(symbol: str, tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    """
    チャートデータを返す。
    メモリキャッシュから末尾N本を返すので高速。
    データがなければ即時フェッチ。
    """
    mapping = {
        "USDJPY":"USDJPY=X","GOLD":"GC=F","BTC":"BTC-USD",
        "JP225":"^N225","XAGUSD":"SI=F","SILVER":"SI=F",
        "AUDJPY":"AUDJPY=X","EURUSD":"EURUSD=X","EURJPY":"EURJPY=X",
    }
    ticker = mapping.get(symbol, symbol)

    cached = chart_cache.get(ticker, {}).get(tf, [])
    if cached:
        return {"data": cached, "bars": len(cached)}

    # キャッシュなし → 同期フェッチ（初回のみ）
    data = fetcher.get_chart_data(ticker, tf)
    if data:
        chart_cache[ticker][tf] = data
    return {"data": data, "bars": len(data)}


@app.get("/api/history")
def get_history(limit: int = Query(50, le=100)):
    try:
        return {
            "data":        db.get_history(limit=limit),
            "performance": market_overview.get("performance",""),
            "stats":       market_overview.get("history_stats",{}),
        }
    except:
        return {"data":[], "performance":"", "stats":{}}


@app.get("/api/history/stats")
def get_history_stats():
    return {
        "overall":        market_overview.get("performance",""),
        "by_symbol":      market_overview.get("history_stats",{}),
        "data_summary":   market_overview.get("data_summary",{}),
        "engine_version": "6.0" if _engine_v2_available else "5.0",
    }
