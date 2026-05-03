"""
ONO Estimator Ultra v6.1 — 全機能統合サーバー
- 5-Layer Engine v2 (SMC/Technical/Fundamental/Momentum/Correlation)
- 30m足完全対応
- E3構造化出力
- セッション補正・FREDファンダ・COT・MTF・イベントカレンダー
- Discord通知 (TP/SL到達含む)
- バックテスト自動化
- 全銘柄スキャナー
"""
import asyncio, os, time, traceback, csv, io
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

# ─── Core modules ──────────────────────────────────────────────
from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.database import SupabaseClient
from ono_estimator.core.notifier import Notifier

# ─── Engine v2 ─────────────────────────────────────────────────
try:
    from ono_estimator.core.engine_v2 import ONOPredictionEngineV2
    _V2 = True
    print("[Server] Engine v2 loaded ✅")
except Exception as _e:
    _V2 = False
    print(f"[Server] Engine v2 not available: {_e}")

# ─── Optional modules (graceful degradation) ───────────────────
try:
    from ono_estimator.core.fred_fetcher import FredFetcher
    _fred_fetcher = FredFetcher()
    _HAS_FRED = True
except Exception: _fred_fetcher = None; _HAS_FRED = False

try:
    from ono_estimator.core.session_filter import get_current_session, get_session_multiplier
    _HAS_SESSION = True
except Exception: _HAS_SESSION = False

try:
    from ono_estimator.core.market_status import get_market_status
    _HAS_MARKET = True
except Exception: _HAS_MARKET = False

try:
    from ono_estimator.core.market_sentiment import calc_fx_fear_greed
    _HAS_SENTIMENT = True
except Exception: _HAS_SENTIMENT = False

try:
    from ono_estimator.core.scanner import run_full_scan
    from ono_estimator.core.scanner_config import SCAN_SYMBOLS
    _HAS_SCANNER = True
except Exception: _HAS_SCANNER = False; SCAN_SYMBOLS = []

try:
    from ono_estimator.core.money_manager import calc_lot, simulate_balance
    _HAS_MONEY = True
except Exception: _HAS_MONEY = False

try:
    from ono_estimator.core.backtester import Backtester
    _HAS_BACKTEST = True
except Exception: _HAS_BACKTEST = False

try:
    from ono_estimator.core.trade_monitor import TradeMonitor
    _HAS_MONITOR = True
except Exception: _HAS_MONITOR = False

try:
    from ono_estimator.core.event_calendar import EventCalendar
    _event_cal = EventCalendar()
    _HAS_EVENT = True
except Exception: _event_cal = None; _HAS_EVENT = False

try:
    from ono_estimator.core.mtf_analyzer import MTFAnalyzer
    _mtf = MTFAnalyzer()
    _HAS_MTF = True
except Exception: _mtf = None; _HAS_MTF = False

try:
    from ono_estimator.core.cot_fetcher import fetch_cot, get_cot_score_bonus
    _HAS_COT = True
except Exception: _HAS_COT = False

load_dotenv()

app = FastAPI(title="ONO Estimator Ultra v6.1", version="6.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ─── 設定 ───────────────────────────────────────────────────────
SYMBOLS = ["USDJPY=X", "GC=F", "BTC-USD", "^N225", "SI=F", "AUDJPY=X", "EURUSD=X", "EURJPY=X"]
SYM_SHORT = {
    "USDJPY=X": "USDJPY", "GC=F": "GOLD", "BTC-USD": "BTC",
    "^N225": "JP225", "SI=F": "XAGUSD", "AUDJPY=X": "AUDJPY",
    "EURUSD=X": "EURUSD", "EURJPY=X": "EURJPY",
}
TIMEFRAMES  = ["1m", "5m", "15m", "30m", "1h", "4h"]
ANALYSIS_TF = "1h"
RENDER_URL  = os.environ.get("RENDER_EXTERNAL_URL", "https://ono-estimator.onrender.com")
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

# ─── グローバルステート ──────────────────────────────────────────
def _default_sym_state():
    return {tf: {
        "status": "Loading", "score": 0,
        "ai_text": "AI分析待機中...", "predicted_price": 0, "probability": 0,
        "last_updated": None, "layers": {}, "aligned": 0, "confidence": "",
        "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "rr": 0,
        "signals": [], "warnings": [], "emoji": "⚪", "cached": False,
        "entry": 0, "basis": "", "session": "", "session_multiplier": 1.0,
        "time_window": {}, "hold_time_minutes": 0, "data_bars": 0,
    } for tf in TIMEFRAMES}

system_state = {sym: _default_sym_state() for sym in SYMBOLS}
chart_cache  = {sym: {tf: [] for tf in TIMEFRAMES} for sym in SYMBOLS}
price_cache  = {sym: 0.0 for sym in SYMBOLS}
last_ai_call = {sym: 0.0 for sym in SYMBOLS}
market_overview = {
    "global_theme": "市場データを同期中...",
    "last_update_ts": 0, "mode": "Starting",
    "performance": "", "history_stats": {}, "data_summary": {},
}
scan_cache   = {"results": [], "ts": 0}
fred_cache   = {"data": {}, "ts": 0}
cot_cache    = {"data": {}, "ts": 0}
_gemini_times: deque = deque(maxlen=60)
_startup_done = False

# ─── Services ──────────────────────────────────────────────────
fetcher     = HybridDataFetcher()
engine_v2   = ONOPredictionEngineV2() if _V2 else None
db          = SupabaseClient()
ai_analyzer = GeminiAnalyzer(db=db)   # db渡してAI Memoryを有効化
notifier    = Notifier(db=db)
backtester  = Backtester(db, price_cache) if _HAS_BACKTEST else None
trade_mon   = TradeMonitor(db, notifier) if _HAS_MONITOR else None

# ─── 日次目標管理 ───────────────────────────────────────────────
DAILY_PROFIT_TARGET = float(os.environ.get("DAILY_PROFIT_TARGET_JPY", "0"))
_daily_pnl_cache   = {"date": "", "pnl": 0.0, "locked": False}


# ─── ユーティリティ ────────────────────────────────────────────
def _short(sym: str) -> str:
    return SYM_SHORT.get(sym, sym.replace("=X","").replace("-USD","").replace("^","")
                         .replace("GC=F","GOLD").replace("SI=F","XAGUSD"))

def _is_crypto(sym: str) -> bool:
    return "BTC" in sym or "ETH" in sym

def _is_market_open(sym: str) -> bool:
    if _is_crypto(sym): return True
    now = datetime.utcnow()
    wd = now.weekday()
    if wd == 5 or (wd == 6 and now.hour < 21): return False
    return True

def _needs_ai(sym: str) -> bool:
    now = time.time()
    last = last_ai_call.get(sym, 0)
    if _is_crypto(sym): return True
    if _is_market_open(sym): return (now - last) > 58
    return (now - last) > 3600

def _can_gemini() -> bool:
    now = time.time()
    while _gemini_times and now - _gemini_times[0] > 60: _gemini_times.popleft()
    return len(_gemini_times) < 3

def _record_gemini(): _gemini_times.append(time.time())

async def _get_fred():
    if not _HAS_FRED: return {}
    age = time.time() - fred_cache["ts"]
    if age < 3600 and fred_cache["data"]: return fred_cache["data"]
    try:
        api_key = os.environ.get("FRED_API_KEY", "")
        data = await _fred_fetcher.fetch_all(api_key) if api_key else {}
        fred_cache.update({"data": data, "ts": time.time()})
        return data
    except Exception: return fred_cache["data"]

async def _get_cot():
    if not _HAS_COT: return {}
    age = time.time() - cot_cache["ts"]
    if age < 86400 and cot_cache["data"]: return cot_cache["data"]
    try:
        data = await fetch_cot()
        cot_cache.update({"data": data, "ts": time.time()})
        return data
    except Exception: return cot_cache["data"]

def _load_history_stats() -> dict:
    try:
        history = db.get_history(limit=200)
        stats = {}
        for row in history:
            sym = row.get("symbol", "")
            if not sym: continue
            if sym not in stats:
                stats[sym] = {"total": 0, "correct": 0, "win_rate": 50}
            if row.get("is_scored"):
                stats[sym]["total"] += 1
                if row.get("is_correct"):
                    stats[sym]["correct"] += 1
        for s in stats.values():
            if s["total"] > 0:
                s["win_rate"] = round(s["correct"] / s["total"] * 100, 1)
        return stats
    except Exception: return {}

def _get_feedback(sym: str) -> str:
    try:
        history = db.get_history(limit=100)
        key = _short(sym)
        rows = [r for r in history if key in r.get("symbol", "")]
        if not rows:
            perf = db.get_performance_text() if hasattr(db, "get_performance_text") else ""
            return perf or "学習データ蓄積中..."
        scored  = [r for r in rows if r.get("is_scored")]
        correct = [r for r in rows if r.get("is_correct")]
        wr = round(len(correct)/len(scored)*100,1) if scored else None
        lines = [f"【{key}実績】採点{len(scored)}件 勝率{wr if wr else 'N/A'}%"]
        for r in rows[:3]:
            tag = "✓WIN" if r.get("is_correct") else ("✗LOSS" if r.get("is_scored") else "pending")
            lines.append(f"  {r.get('status','?')} score:{r.get('score',0)} {tag}")
        return "\n".join(lines)
    except Exception as e: return f"History error: {e}"


def _check_daily_lock() -> bool:
    """日次目標達成チェック"""
    global _daily_pnl_cache
    if DAILY_PROFIT_TARGET <= 0:
        return False
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _daily_pnl_cache["date"] != today:
        _daily_pnl_cache = {"date": today, "pnl": 0.0, "locked": False}
    if _daily_pnl_cache["locked"]:
        return True
    try:
        perf = db.get_performance_summary()
        pips = perf.get("total_pips", 0)
        est_pnl = pips * 1000  # 簡易換算（USDJPY 1pip=1000円/lot）
        _daily_pnl_cache["pnl"] = est_pnl
        if est_pnl >= DAILY_PROFIT_TARGET:
            _daily_pnl_cache["locked"] = True
            print(f"[DailyLock] 目標達成 ¥{est_pnl:,.0f} >= ¥{DAILY_PROFIT_TARGET:,.0f}")
            return True
    except Exception:
        pass
    return False


def _calc_mtf_confluence(sym: str) -> dict:
    """全TFの方向一致スコアを計算"""
    directions = {}
    for tf in TIMEFRAMES:
        state = system_state.get(sym, {}).get(tf, {})
        d = state.get("direction") or state.get("status", "WAIT")
        if "BUY" in str(d).upper():
            directions[tf] = "BUY"
        elif "SELL" in str(d).upper():
            directions[tf] = "SELL"
        else:
            directions[tf] = "WAIT"
    buys  = sum(1 for v in directions.values() if v == "BUY")
    sells = sum(1 for v in directions.values() if v == "SELL")
    total = len(TIMEFRAMES)
    if buys > sells:
        dominant = "BUY"
        score = buys
    elif sells > buys:
        dominant = "SELL"
        score = sells
    else:
        dominant = "WAIT"
        score = 0
    return {
        "dominant": dominant,
        "confluence_score": score,
        "total_tfs": total,
        "by_tf": directions,
        "is_max_confluence": score == total,
        "pct": round(score / total * 100, 0) if total else 0,
    }


# ─── コア分析（blocking） ───────────────────────────────────────
def _analyze_symbol_blocking(sym: str) -> dict:
    results = {}
    for tf in TIMEFRAMES:
        try:
            df = fetcher.get_analysis_df(sym, tf)
            if df is None or df.empty or len(df) < 30: continue
            bars = len(df)

            v6 = {}
            if engine_v2 and bars >= 50:
                try:
                    loop = asyncio.new_event_loop()
                    v6 = loop.run_until_complete(
                        engine_v2.analyze(_short(sym), df)
                    )
                    loop.close()
                except Exception as e:
                    print(f"[v6] {sym}/{tf}: {e}")

            # セッション補正
            session = "off"
            sess_mult = 1.0
            if _HAS_SESSION:
                try:
                    session = get_current_session()
                    sess_mult = get_session_multiplier(_short(sym), session)
                except Exception: pass

            score = int(v6.get("score", 0) * sess_mult) if v6 else 0
            status = v6.get("direction", "WAIT").replace("STRONG_", "") if v6 else "Wait"

            latest = df.iloc[-1]
            results[tf] = {
                "status":    status,
                "score":     score,
                "rsi":       round(float(latest.get("rsi", 50)), 1),
                "price":     float(latest["close"]),
                "layers":    v6.get("layers", {}),
                "aligned":   v6.get("aligned", 0),
                "confidence": v6.get("confidence", ""),
                "tp1":       v6.get("tp1", 0),
                "tp2":       v6.get("tp", 0),
                "tp3":       v6.get("tp3", 0),
                "sl":        v6.get("sl", 0),
                "rr":        v6.get("rr", 0),
                "entry":     v6.get("entry", float(latest["close"])),
                "signals":   v6.get("signals", [])[:8],
                "warnings":  v6.get("warnings", []),
                "emoji":     v6.get("emoji", "⚪"),
                "summary":   v6.get("summary", ""),
                "gemini_prompt": v6.get("gemini_prompt"),
                "session":   session,
                "session_multiplier": sess_mult,
                "data_bars": bars,
            }
            chart_cache[sym][tf] = fetcher.get_chart_data(sym, tf)

        except Exception as e:
            print(f"[Analyze] {sym}/{tf}: {e}")
            traceback.print_exc()

    if results:
        ref = results.get(ANALYSIS_TF) or next(iter(results.values()), {})
        price = ref.get("price", 0)
        if price: price_cache[sym] = price

    return results


# ─── 分析ループ ─────────────────────────────────────────────────
async def estimation_loop():
    print("[Server] ONO Estimator Ultra v6.1 started")
    global _startup_done

    # キャッシュプリロード
    try:
        history = db.get_history(limit=len(SYMBOLS)*2)
        for row in history:
            sym = row.get("symbol")
            if sym and sym in system_state:
                for tf in TIMEFRAMES:
                    if system_state[sym][tf]["status"] == "Loading":
                        system_state[sym][tf].update({
                            "ai_text": row.get("ai_text", "読み込み中..."),
                            "score":   row.get("score", 0),
                            "status":  row.get("status", "Wait"),
                            "probability": row.get("probability", 0),
                        })
                        break
        market_overview["performance"]   = db.get_performance_summary()
        market_overview["history_stats"] = _load_history_stats()
        market_overview["mode"] = "Live"
        print("[Startup] Preload complete")
    except Exception as e:
        print(f"[Startup] Preload skip: {e}")

    _startup_done = True

    while True:
        cycle_start = time.time()
        try:
            for sym in SYMBOLS:
                try:
                    loop = asyncio.get_event_loop()
                    tf_results = await loop.run_in_executor(None, _analyze_symbol_blocking, sym)
                    if not tf_results: continue

                    for tf, summary in tf_results.items():
                        system_state[sym][tf].update(summary)

                    market_overview["data_summary"][sym] = {
                        tf: tf_results[tf]["data_bars"] for tf in tf_results
                    }

                    # AI分析
                    if _needs_ai(sym) and _can_gemini():
                        _record_gemini()
                        last_ai_call[sym] = time.time()
                        feedback = _get_feedback(sym)
                        v6_prompt = tf_results.get(ANALYSIS_TF, {}).get("gemini_prompt")
                        ai_data = ai_analyzer.analyze_single(
                            sym, {"mtf": tf_results},
                            feedback=feedback,
                            gemini_prompt_override=v6_prompt,
                        )
                        if ai_data:
                            for tf in TIMEFRAMES:
                                system_state[sym][tf].update({
                                    "ai_text":     ai_data.get("ai_text", ""),
                                    "basis":       ai_data.get("basis", ""),
                                    "probability": ai_data.get("probability", 0),
                                    "direction":   ai_data.get("direction", "WAIT"),
                                    "entry":       ai_data.get("entry") or system_state[sym][tf].get("entry", 0),
                                    "tp1":         ai_data.get("tp1") or system_state[sym][tf].get("tp1", 0),
                                    "tp2":         ai_data.get("tp2") or system_state[sym][tf].get("tp2", 0),
                                    "sl":          ai_data.get("sl") or system_state[sym][tf].get("sl", 0),
                                    "time_window": ai_data.get("time_window", {}),
                                    "hold_time_minutes": ai_data.get("hold_time_minutes", 0),
                                    "cached":      ai_data.get("cached", False),
                                    "last_updated": datetime.now().isoformat(),
                                })
                            ref_state = system_state[sym][ANALYSIS_TF]
                            db.save_prediction({
                                "symbol":        sym,
                                "timeframe":     ANALYSIS_TF,
                                "status":        ref_state.get("status", "Wait"),
                                "score":         ref_state.get("score", 0),
                                "ai_text":       ai_data.get("ai_text", ""),
                                "entry":         ai_data.get("entry") or 0,
                                "tp1":           ai_data.get("tp1") or 0,
                                "tp2":           ai_data.get("tp2") or 0,
                                "sl":            ai_data.get("sl") or 0,
                                "probability":   ai_data.get("probability", 0),
                                "current_price": price_cache.get(sym, 0),
                                "layers":        ref_state.get("layers", {}),
                                "aligned":       ref_state.get("aligned", 0),
                                "session":       ref_state.get("session", "off"),
                            })
                            if market_overview["last_update_ts"] < time.time() - 120:
                                market_overview["global_theme"] = ai_data.get("ai_text","")[:80] + "..."
                                market_overview["last_update_ts"] = int(time.time())

                            # 通知判定: confidence>=75% or (score>=35 & prob>=80 & aligned>=3)
                            score = ref_state.get("score", 0)
                            prob  = ai_data.get("probability", 0)
                            algn  = ref_state.get("aligned", 0)
                            conf  = ai_data.get("confidence", "LOW")
                            is_locked = _check_daily_lock()
                            if not is_locked and (
                                (conf == "HIGH" and prob >= 75) or
                                (abs(score) >= 35 and prob >= 80 and algn >= 3)
                            ):
                                try:
                                    notifier.notify(sym, ref_state, ai_data)
                                except Exception: pass

                        await asyncio.sleep(15)

                except Exception as e:
                    print(f"[Loop] {sym}: {e}")
                    traceback.print_exc()

        except Exception as e:
            print(f"[Loop] Critical: {e}")

        elapsed = time.time() - cycle_start
        await asyncio.sleep(max(5, 60 - elapsed))


async def backtest_loop():
    await asyncio.sleep(120)
    while True:
        try:
            if backtester:
                await asyncio.get_event_loop().run_in_executor(None, backtester.run)
            market_overview["performance"]   = db.get_performance_summary()
            market_overview["history_stats"] = _load_history_stats()
        except Exception as e: print(f"[Backtest] {e}")
        await asyncio.sleep(21600)  # 6h


async def trade_monitor_loop():
    await asyncio.sleep(60)
    while True:
        try:
            if trade_mon:
                await asyncio.get_event_loop().run_in_executor(
                    None, trade_mon.check_signals, price_cache
                )
        except Exception as e: print(f"[TradeMonitor] {e}")
        await asyncio.sleep(300)  # 5min


async def scanner_loop():
    await asyncio.sleep(180)
    while True:
        try:
            if _HAS_SCANNER:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None, lambda: asyncio.run(run_full_scan(fetcher, engine_v2, db))
                ) if engine_v2 else []
                scan_cache.update({"results": results, "ts": time.time()})
                print(f"[Scanner] {len(results)} symbols scanned")
        except Exception as e: print(f"[Scanner] {e}")
        await asyncio.sleep(1800)  # 30min


async def anti_sleep_loop():
    await asyncio.sleep(30)
    while True:
        try:
            requests.get(f"{RENDER_URL}/api/health", timeout=10)
        except Exception: pass
        await asyncio.sleep(240)


async def auto_evaluate_loop():
    """バックテスト自動評価 + AI自己反省ループ (1時間毎)"""
    await asyncio.sleep(300)
    while True:
        try:
            # 未採点予測を評価
            unscored = db.get_unscored_predictions()
            evaluated = 0
            for row in unscored:
                sym_short = row.get("symbol", "")
                ticker = next((k for k, v in SYM_SHORT.items() if v == sym_short), sym_short)
                cur_price = price_cache.get(ticker, 0)
                if not cur_price: continue
                entry = row.get("entry_price") or 0
                direction = row.get("direction", "WAIT")
                if not entry or direction == "WAIT": continue
                if direction == "BUY":
                    pips = (cur_price - entry) * 10000
                    outcome = "WIN" if cur_price > entry else "LOSS"
                else:
                    pips = (entry - cur_price) * 10000
                    outcome = "WIN" if cur_price < entry else "LOSS"
                db.update_prediction_result(row["id"], cur_price, outcome == "WIN", outcome)
                db.save_performance(
                    prediction_id=row["id"], symbol=sym_short, direction=direction,
                    entry_price=entry, exit_price=cur_price, outcome=outcome, pips_result=pips,
                )
                evaluated += 1
            if evaluated > 0:
                print(f"[AutoEval] {evaluated}件 採点完了")
                perf = db.get_performance_summary()
                market_overview["history_stats"] = _load_history_stats()
                # 負けが多い場合はAI反省を生成
                wr = perf.get("win_rate", 0)
                if wr < 55:
                    for sym in ["ALL"] + [_short(s) for s in SYMBOLS[:3]]:
                        try:
                            losses = [l for l in perf.get("logs", []) if l.get("outcome") == "LOSS"][:5]
                            if losses:
                                lesson = ai_analyzer.generate_self_reflection(sym, losses)
                                if lesson:
                                    ai_analyzer.save_ai_lesson(sym, lesson, wr)
                                    print(f"[AIReflect] {sym}: {lesson[:50]}...")
                        except Exception: pass
        except Exception as e:
            print(f"[AutoEval] Error: {e}")
        await asyncio.sleep(3600)  # 1時間毎


@app.on_event("startup")
async def startup():
    asyncio.create_task(estimation_loop())
    asyncio.create_task(backtest_loop())
    asyncio.create_task(trade_monitor_loop())
    asyncio.create_task(scanner_loop())
    asyncio.create_task(auto_evaluate_loop())
    asyncio.create_task(anti_sleep_loop())


# ─── API Endpoints ─────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ONO Estimator Ultra v6.1", "time": datetime.now().isoformat()}


@app.get("/api/health")
def health():
    return {
        "status": "healthy", "version": "6.1.0",
        "engine_v2": _V2,
        "mode": market_overview.get("mode", "starting"),
        "gemini_calls_last_min": len(_gemini_times),
        "last_sync": market_overview["last_update_ts"],
        "performance": market_overview.get("performance", ""),
        "data_summary": market_overview.get("data_summary", {}),
        "startup_done": _startup_done,
    }


@app.get("/api/predict")
def get_prediction(tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    tf_state = {sym: states.get(tf) for sym, states in system_state.items()}
    return {
        "data": tf_state,
        "overview": market_overview,
        "current_tf": tf,
        "server_time": int(time.time()),
        "engine_version": "6.1" if _V2 else "5.0",
    }


@app.get("/api/chart/{symbol}")
def get_chart(symbol: str, tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    mapping = {
        "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
        "JP225": "^N225", "XAGUSD": "SI=F", "SILVER": "SI=F",
        "AUDJPY": "AUDJPY=X", "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
    }
    ticker = mapping.get(symbol, symbol)
    cached = chart_cache.get(ticker, {}).get(tf, [])
    if cached:
        return {"data": cached, "bars": len(cached)}
    data = fetcher.get_chart_data(ticker, tf)
    if data: chart_cache[ticker][tf] = data
    return {"data": data, "bars": len(data)}


@app.get("/api/history")
def get_history(limit: int = Query(50, le=100)):
    try:
        return {
            "data": db.get_history(limit=limit),
            "performance": market_overview.get("performance", ""),
            "stats": market_overview.get("history_stats", {}),
        }
    except Exception: return {"data": [], "performance": "", "stats": {}}


@app.get("/api/history/stats")
def history_stats():
    return {
        "overall": market_overview.get("performance", ""),
        "by_symbol": market_overview.get("history_stats", {}),
        "data_summary": market_overview.get("data_summary", {}),
        "engine_version": "6.1",
    }


@app.get("/api/overview")
def overview():
    results = []
    for sym in SYMBOLS:
        ref = system_state[sym].get(ANALYSIS_TF, {})
        ms = {}
        if _HAS_MARKET:
            try: ms = get_market_status()
            except Exception: pass
        results.append({
            "symbol": _short(sym),
            "ticker": sym,
            "score":  ref.get("score", 0),
            "direction": ref.get("status", "Wait"),
            "probability": ref.get("probability", 0),
            "emoji": ref.get("emoji", "⚪"),
            "aligned": ref.get("aligned", 0),
            "session": ref.get("session", ""),
            "session_multiplier": ref.get("session_multiplier", 1.0),
            "tp1": ref.get("tp1", 0),
            "tp2": ref.get("tp2", 0),
            "sl":  ref.get("sl", 0),
            "price": price_cache.get(sym, 0),
            "market_status": ms.get("status", "LIVE"),
        })
    results.sort(key=lambda x: abs(x["score"]), reverse=True)
    return {"symbols": results, "session_info": _get_session_info()}


def _get_session_info() -> dict:
    if not _HAS_SESSION: return {}
    try:
        sess = get_current_session()
        return {"current": sess, "label": {"tokyo":"東京","london":"ロンドン","ny":"NY","off":"オフ"}.get(sess,sess)}
    except Exception: return {}


@app.get("/api/macro")
async def get_macro():
    fred = await _get_fred()
    sentiment = {}
    if _HAS_SENTIMENT:
        try:
            vix = fred.get("VIXCLS", {}).get("value") or 15.0
            sentiment = calc_fx_fear_greed(vix, 0, 0)
        except Exception: pass
    return {
        "fred": fred,
        "sentiment": sentiment,
        "session": _get_session_info(),
        "cached": bool(fred),
    }


@app.get("/api/market/status")
def market_status():
    if not _HAS_MARKET:
        return {"status": "LIVE", "next_transition": None}
    try: return get_market_status()
    except Exception: return {"status": "LIVE"}


@app.get("/api/market/sentiment")
async def market_sentiment():
    fred = await _get_fred()
    if not _HAS_SENTIMENT: return {"index": 50, "label": "中立", "risk_mode": "NEUTRAL"}
    try:
        vix = fred.get("VIXCLS", {}).get("value") or 15.0
        return calc_fx_fear_greed(vix, 0, 0)
    except Exception: return {"index": 50, "label": "中立"}


@app.get("/api/scan/ranking")
def scan_ranking():
    return {
        "results": scan_cache["results"],
        "scanned_at": scan_cache["ts"],
        "count": len(scan_cache["results"]),
    }


@app.post("/api/scan/run")
async def scan_run():
    if not _HAS_SCANNER or not engine_v2:
        return {"status": "unavailable"}
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: asyncio.run(run_full_scan(fetcher, engine_v2, db))
        )
        scan_cache.update({"results": results, "ts": time.time()})
        return {"status": "ok", "count": len(results)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/api/edge/{symbol}")
def edge(symbol: str):
    mapping = {
        "USDJPY": "USDJPY=X","GOLD":"GC=F","BTC":"BTC-USD",
        "JP225":"^N225","XAGUSD":"SI=F","AUDJPY":"AUDJPY=X",
        "EURUSD":"EURUSD=X","EURJPY":"EURJPY=X",
    }
    ticker = mapping.get(symbol.upper(), symbol)
    ref = system_state.get(ticker, {}).get(ANALYSIS_TF, {})
    layers = ref.get("layers", {})
    prob = ref.get("probability", 0)
    score = abs(ref.get("score", 0))

    # edge_score算出
    ai_score  = min(40, int(prob * 0.4))
    bt_score  = 21  # デフォルト70%想定
    vol_score = 18
    mtf_score = min(10, ref.get("aligned", 0) * 2)
    edge_score = ai_score + bt_score + vol_score + mtf_score

    # 銘柄別勝率
    stats = market_overview.get("history_stats", {}).get(ticker, {})
    win_rate = stats.get("win_rate", 50)
    sample   = stats.get("total", 0)
    if sample > 0:
        bt_score = min(30, int(win_rate * 0.3))
        edge_score = ai_score + bt_score + vol_score + mtf_score

    sess = ref.get("session", "")
    return {
        "symbol": symbol,
        "edge_score": min(100, edge_score),
        "breakdown": {
            "ai_probability":    {"score": ai_score, "max": 40, "value": f"{prob}%"},
            "backtest_win_rate": {"score": bt_score, "max": 30, "value": f"{win_rate}%"},
            "volatility_fitness": {"score": vol_score, "max": 20, "value": "適正"},
            "mtf_alignment":     {"score": mtf_score, "max": 10, "value": f"{ref.get('aligned',0)}/5"},
        },
        "best_session": sess,
        "session_multiplier": ref.get("session_multiplier", 1.0),
        "sample_count": sample,
        "basis": ref.get("basis", ""),
    }


@app.get("/api/forecast/{symbol}")
def forecast(symbol: str):
    mapping = {
        "USDJPY": "USDJPY=X","GOLD":"GC=F","BTC":"BTC-USD",
        "JP225":"^N225","XAGUSD":"SI=F","AUDJPY":"AUDJPY=X",
        "EURUSD":"EURUSD=X","EURJPY":"EURJPY=X",
    }
    ticker = mapping.get(symbol.upper(), symbol)
    ref = system_state.get(ticker, {}).get(ANALYSIS_TF, {})
    price = price_cache.get(ticker, 0)
    prob  = ref.get("probability", 0)

    # 予測ポイント生成（TP1/TP2から算出）
    points = []
    now_jst = datetime.now(timezone.utc) + timedelta(hours=9)
    hold = ref.get("hold_time_minutes", 60) or 60
    tw = ref.get("time_window", {})

    tp1 = ref.get("tp1", 0)
    tp2 = ref.get("tp2", 0)
    atr = abs(tp1 - price) if tp1 and price else price * 0.005

    if tp1:
        t1 = now_jst + timedelta(minutes=hold)
        points.append({
            "time": t1.isoformat(),
            "price": tp1,
            "confidence_upper": round(tp1 + atr * 0.5, 5),
            "confidence_lower": round(tp1 - atr * 0.5, 5),
        })
    if tp2:
        t2 = now_jst + timedelta(minutes=hold*2)
        points.append({
            "time": t2.isoformat(),
            "price": tp2,
            "confidence_upper": round(tp2 + atr, 5),
            "confidence_lower": round(tp2 - atr, 5),
        })

    return {
        "symbol": symbol,
        "current_price": price,
        "forecast_points": points,
        "entry": ref.get("entry", price),
        "sl": ref.get("sl", 0),
        "time_window": tw,
        "basis": ref.get("basis", ""),
        "probability": prob,
        "generated_at": now_jst.isoformat(),
        "cached": ref.get("cached", False),
    }


@app.get("/api/backtest/results")
def backtest_results():
    if not backtester:
        return {"win_rate": 50, "total": 0, "correct": 0, "results": []}
    try:
        return backtester.get_results(30)
    except Exception: return {"win_rate": 50, "total": 0}


@app.get("/api/backtest/by-symbol")
def backtest_by_symbol():
    return market_overview.get("history_stats", {})


@app.get("/api/backtest/export")
def backtest_export():
    if not backtester:
        return {"detail": "unavailable"}
    try:
        csv_str = backtester.export_csv(30)
        fname = f"backtest_{datetime.now().strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            io.StringIO(csv_str),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except Exception as e: return {"detail": str(e)}


@app.post("/api/money/calc")
async def money_calc(body: dict):
    if not _HAS_MONEY: return {"detail": "unavailable"}
    try:
        balance  = float(body.get("balance", 1000000))
        risk_pct = float(body.get("risk_pct", 1.0))
        sl_pips  = float(body.get("sl_pips", 20))
        symbol   = str(body.get("symbol", "USDJPY"))
        result = calc_lot(balance, risk_pct, sl_pips, symbol)
        if result and "lot" in result:
            sim = simulate_balance(balance, result["lot"],
                                   sl_pips * 2, sl_pips, symbol)
            result.update(sim or {})
        return result
    except Exception as e: return {"detail": str(e)}


@app.get("/api/debug/fred")
async def debug_fred():
    fred = await _get_fred()
    return {
        "available": _HAS_FRED,
        "data": fred,
        "ts": fred_cache["ts"],
    }


@app.get("/api/debug/sources")
def debug_sources():
    return {
        "modules": {
            "engine_v2": _V2, "fred": _HAS_FRED, "session": _HAS_SESSION,
            "market": _HAS_MARKET, "sentiment": _HAS_SENTIMENT,
            "scanner": _HAS_SCANNER, "money": _HAS_MONEY,
            "backtest": _HAS_BACKTEST, "trade_monitor": _HAS_MONITOR,
            "event_cal": _HAS_EVENT, "mtf": _HAS_MTF, "cot": _HAS_COT,
        },
        "prices": price_cache,
        "gemini_calls_last_min": len(_gemini_times),
        "startup_done": _startup_done,
    }


# ─── 新規エンドポイント ─────────────────────────────────────────

@app.get("/api/performance/summary")
def performance_summary():
    """パフォーマンス集計 (performance_logから)"""
    try:
        summary = db.get_performance_summary()
        summary["daily_lock"] = _check_daily_lock()
        summary["daily_target"] = DAILY_PROFIT_TARGET
        summary["daily_pnl"] = _daily_pnl_cache.get("pnl", 0)
        return summary
    except Exception as e:
        return {"error": str(e), "win_rate": 0, "total_trades": 0}


@app.get("/api/confluence/{symbol}")
def confluence(symbol: str):
    """MTFコンフルエンス（全TF方向一致スコア）"""
    mapping = {
        "USDJPY": "USDJPY=X","GOLD":"GC=F","BTC":"BTC-USD",
        "JP225":"^N225","XAGUSD":"SI=F","AUDJPY":"AUDJPY=X",
        "EURUSD":"EURUSD=X","EURJPY":"EURJPY=X",
    }
    ticker = mapping.get(symbol.upper(), symbol)
    return _calc_mtf_confluence(ticker)


@app.get("/api/confluence")
def confluence_all():
    """全銘柄MTFコンフルエンス"""
    return {_short(sym): _calc_mtf_confluence(sym) for sym in SYMBOLS}


@app.get("/api/signals/history")
def signals_history(
    symbol: str = Query(None),
    direction: str = Query(None),
    timeframe: str = Query(None),
    limit: int = Query(50, le=200),
):
    """シグナル履歴（フィルタリング対応）"""
    try:
        rows = db.get_predictions(
            symbol=symbol, direction=direction,
            timeframe=timeframe, limit=limit
        )
        return {"count": len(rows), "data": rows}
    except Exception as e:
        return {"count": 0, "data": [], "error": str(e)}


@app.post("/api/backtest/evaluate")
async def backtest_evaluate():
    """バックテスト自動評価: 未採点predictionsを現在価格で評価"""
    try:
        unscored = db.get_unscored_predictions()
        evaluated = 0
        for row in unscored:
            sym = row.get("symbol", "")
            ticker = {v: k for k, v in SYM_SHORT.items()}.get(sym, sym)
            cur_price = price_cache.get(ticker, 0)
            if not cur_price:
                continue
            entry = row.get("entry_price") or 0
            direction = row.get("direction", "WAIT")
            tp1 = row.get("take_profit") or 0
            sl = row.get("stop_loss") or 0
            if not entry or direction == "WAIT":
                continue
            is_correct = False
            outcome = "PENDING"
            pips = 0.0
            if direction == "BUY":
                pips = (cur_price - entry) * 10000
                is_correct = cur_price > entry
                outcome = "WIN" if is_correct else "LOSS"
            elif direction == "SELL":
                pips = (entry - cur_price) * 10000
                is_correct = cur_price < entry
                outcome = "WIN" if is_correct else "LOSS"
            db.update_prediction_result(row["id"], cur_price, is_correct, outcome)
            db.save_performance(
                prediction_id=row["id"], symbol=sym, direction=direction,
                entry_price=entry, exit_price=cur_price,
                outcome=outcome, pips_result=pips,
            )
            evaluated += 1
        perf = db.get_performance_summary()
        return {"evaluated": evaluated, "summary": perf}
    except Exception as e:
        return {"error": str(e), "evaluated": 0}


@app.get("/api/daily/status")
def daily_status():
    """日次目標達成状況"""
    locked = _check_daily_lock()
    return {
        "locked": locked,
        "target_jpy": DAILY_PROFIT_TARGET,
        "current_pnl": _daily_pnl_cache.get("pnl", 0),
        "date": _daily_pnl_cache.get("date", ""),
        "message": "⚠️ 本日の目標達成！新規シグナル停止中" if locked else None,
    }


@app.get("/api/ai/memory/{symbol}")
def ai_memory(symbol: str):
    """AI学習メモ取得"""
    if not db.client:
        return {"lessons": []}
    try:
        res = db.client.table("ai_memory")\
            .select("*")\
            .in_("symbol", [symbol.upper(), "ALL"])\
            .eq("is_active", True)\
            .order("applied_at", desc=True)\
            .limit(10).execute()
        return {"lessons": res.data or []}
    except Exception as e:
        return {"lessons": [], "error": str(e)}


@app.post("/api/ai/reflect")
async def ai_reflect(body: dict):
    """AI自己反省ループのトリガー"""
    symbol = body.get("symbol", "ALL")
    try:
        perf = db.get_performance_summary()
        wr = perf.get("win_rate", 0)
        logs = perf.get("logs", [])
        losses = [l for l in logs if l.get("outcome") == "LOSS"][:5]
        if not losses:
            return {"lesson": None, "message": "負けトレードなし"}
        lesson = ai_analyzer.generate_self_reflection(symbol, losses)
        if lesson:
            ai_analyzer.save_ai_lesson(symbol, lesson, wr)
        return {"lesson": lesson, "win_rate": wr}
    except Exception as e:
        return {"error": str(e)}
