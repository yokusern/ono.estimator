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
last_ai_call  = {sym: 0.0 for sym in SYMBOLS}
last_ai_score = {sym: 0   for sym in SYMBOLS}  # H-1: スコア変化検知用
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

# ─── L-2: Correlation Guard ────────────────────────────────────
_CORR_GROUPS = {
    "JPY":   ["USDJPY=X", "AUDJPY=X", "EURJPY=X"],
    "EUR":   ["EURUSD=X", "EURJPY=X"],
    "METAL": ["GC=F", "SI=F"],
}
_CORRELATION_GUARD = os.getenv("CORRELATION_GUARD", "false").lower() == "true"
_corr_notified: dict = {}   # {group: {"sym": sym, "score": score, "ts": ts}}

def _corr_filter_allow(sym: str, score: float) -> bool:
    """同グループ内で直近30分以内に高スコアが通知済みなら抑制。"""
    if not _CORRELATION_GUARD:
        return True
    now = time.time()
    allowed = True
    for group, members in _CORR_GROUPS.items():
        if sym not in members:
            continue
        cached = _corr_notified.get(group, {})
        if now - cached.get("ts", 0) < 1800 and cached.get("score", 0) >= score:
            print(f"[CorrGuard] {sym} suppressed — {cached.get('sym')} already notified in {group}")
            allowed = False
        else:
            _corr_notified[group] = {"sym": sym, "score": score, "ts": now}
    return allowed

# ─── L-5: Signal Quality Index (SQI) ──────────────────────────
_sqi_loss_streak: dict = {sym: 0 for sym in SYMBOLS}
_sqi_total_scored = 0

# ─── Services ──────────────────────────────────────────────────
fetcher     = HybridDataFetcher()
engine_v2   = ONOPredictionEngineV2() if _V2 else None
db          = SupabaseClient()
ai_analyzer = GeminiAnalyzer()
ai_analyzer.set_db(db)
notifier    = Notifier(db=db)
backtester  = Backtester(db, price_cache) if _HAS_BACKTEST else None
trade_mon   = TradeMonitor(db, notifier) if _HAS_MONITOR else None

# H-11: DemoTrader（ai_analyzerを注入して自己学習ループを完成）
try:
    from ono_estimator.core.demo_trader import DemoTrader
    demo_trader = DemoTrader(db, ai_analyzer=ai_analyzer)
    print("[Server] DemoTrader loaded ✅")
except Exception as _e:
    demo_trader = None
    print(f"[Server] DemoTrader not available: {_e}")

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

def get_active_session(utc_hour: int) -> str:
    """M-2: UTCアワーからセッション名を返す"""
    if 0  <= utc_hour <  8:  return "Tokyo（低ボラ・様子見推奨）"
    if 8  <= utc_hour < 13:  return "London（中〜高ボラ）"
    if 13 <= utc_hour < 16:  return "NY_Overlap（最高ボラ・最重要）"
    if 16 <= utc_hour < 21:  return "NY（高ボラ）"
    return "Off-hours"

def _needs_ai(sym: str) -> bool:
    """H-1: 時間経過 or スコアが±10以上変化した場合にAI呼び出し"""
    now = time.time()
    last = last_ai_call.get(sym, 0)
    current_score = system_state[sym][ANALYSIS_TF].get("score", 0)
    score_changed = abs(current_score - last_ai_score.get(sym, 0)) >= 10
    if _is_crypto(sym): return True
    if _is_market_open(sym): return (now - last) > 58 or score_changed
    return (now - last) > 3600 or score_changed

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


# ─── H-9: エンジンシグナル構築（全指標統合） ────────────────────
# DFキャッシュ: fast_loop が更新し、ai_loop が参照する
_df_cache: dict = {sym: {} for sym in SYMBOLS}


def _build_engine_signals(sym: str, tf_results: dict, df_store: dict) -> dict:
    """H-17: 全テクニカル指標（スキャルピング戦略含む全指標）を統合"""
    from ono_estimator.filters.momentum import MomentumFilter
    from ono_estimator.indicators.technical import TechnicalIndicators

    ref    = tf_results.get(ANALYSIS_TF, {})
    price  = ref.get("price", 0)
    layers = ref.get("layers", {})

    # ── BBスコア ──
    bb_result = {}
    if "15m" in df_store and "1h" in df_store:
        try:
            bb_result = MomentumFilter()._calc_bb_score(
                df_store["15m"], df_store["1h"], df_store.get("4h")
            )
        except Exception as e:
            print(f"[BBScore] {sym}: {e}")

    # ── ATR + ボラ ──
    atr_1h     = 0.0
    vol_result = {"regime": "NORMAL", "ratio": 1.0}
    df1h = df_store.get("1h")
    if df1h is not None and all(c in df1h.columns for c in ["high", "low", "close"]):
        try:
            vr = TechnicalIndicators.volatility_regime(df1h["high"], df1h["low"], df1h["close"])
            atr_1h     = vr.get("atr", 0.0)
            vol_result = vr
        except Exception: pass

    # ── グランビルパターン（H-4）1H ──
    granville_pattern = "なし"
    if df1h is not None and len(df1h) >= 4:
        try:
            ma14 = df1h["close"].rolling(14).mean()
            granville_pattern = TechnicalIndicators.detect_granville(df1h["close"], ma14)
        except Exception: pass

    # ── ストキャスティクス 1H ──
    stoch_result = {"k": 50.0, "d": 50.0, "golden_cross": False, "dead_cross": False,
                    "oversold": False, "overbought": False}
    if df1h is not None and len(df1h) >= 20 and all(c in df1h.columns for c in ["high", "low", "close"]):
        try:
            stoch_result = TechnicalIndicators.stochastic(df1h["high"], df1h["low"], df1h["close"])
        except Exception: pass

    # ── 一目均衡表 1H ──
    ichimoku_result = {"chikou_cross": "NONE", "price_vs_cloud": "N/A",
                       "cloud_top": 0.0, "cloud_bot": 0.0, "tenkan": 0.0, "kijun": 0.0}
    if df1h is not None and len(df1h) >= 60 and all(c in df1h.columns for c in ["high", "low", "close"]):
        try:
            ichimoku_result = TechnicalIndicators.ichimoku(df1h["high"], df1h["low"], df1h["close"])
        except Exception: pass

    # ── UPLOWバンド 1H ──
    uplow_result = {"state": "INSIDE", "ma": 0.0}
    if df1h is not None and len(df1h) >= 14:
        try:
            uplow_result = TechnicalIndicators.uplow_bands(df1h["close"])
        except Exception: pass

    # ── フィボナッチ（H-15）1H ──
    fib_result = {"fib_500": 0.0, "fib_618": 0.0, "near_fib_level": None,
                  "swing_high": 0.0, "swing_low": 0.0}
    if df1h is not None and len(df1h) >= 5:
        try:
            fib_result = TechnicalIndicators.fibonacci_levels(df1h)
        except Exception: pass

    # ── S/Rキーレベル ──
    key_levels = {}
    if df1h is not None:
        try:
            key_levels = TechnicalIndicators.find_key_levels(df1h)
        except Exception: pass

    # ── スキャルピング戦略指標（H-5〜H-11）: 1m足で算出 ──
    df1m = df_store.get("1m")

    # H-5: Liquidity Sweep（最重要）
    liq_result = {"bull_sweep": False, "bear_sweep": False, "bull_rebreak": False,
                  "bear_rebreak": False, "swept_high": 0.0, "swept_low": 0.0, "signal": "NONE"}
    if df1m is not None and len(df1m) >= 22:
        try:
            liq_result = TechnicalIndicators.detect_liquidity_sweep(df1m)
        except Exception: pass

    # H-7: ヒゲ否定
    wick_result = {"bull_denial": False, "bear_denial": False,
                   "denied_wick_high": 0.0, "denied_wick_low": 0.0}
    if df1m is not None and len(df1m) >= 2:
        try:
            wick_result = TechnicalIndicators.detect_wick_denial(df1m)
        except Exception: pass

    # H-8: 勢い減衰
    decay_result = {"is_decaying": False, "decay_ratio": 1.0, "signal": "NONE"}
    if df1m is not None and len(df1m) >= 5:
        try:
            decay_result = TechnicalIndicators.detect_momentum_decay(df1m)
        except Exception: pass

    # H-10: レンジ状態
    range_result = {"is_range": False, "bb_squeezed": False, "atr_compressed": False,
                    "bb_width_ratio": 1.0, "atr_ratio": 1.0,
                    "range_high": 0.0, "range_low": 0.0,
                    "breakout_up": False, "breakout_down": False}
    if df1m is not None and len(df1m) >= 21:
        try:
            range_result = TechnicalIndicators.detect_range_state(df1m)
        except Exception: pass

    # H-11: RSI on BB
    rsi_bb_result = {"rsi": 50.0, "rsi_bb_upper": 70.0, "rsi_bb_lower": 30.0,
                     "rsi_bb_mid": 50.0, "above_bb": False, "below_bb": False,
                     "bearish_divergence": False, "bullish_divergence": False}
    if df1m is not None and len(df1m) >= 34:
        try:
            rsi_bb_result = TechnicalIndicators.rsi_with_bb(df1m["close"])
        except Exception: pass

    # MA200 on 1m
    ma200_1m = 0.0
    price_vs_ma200 = "N/A"
    if df1m is not None and len(df1m) >= 200:
        try:
            ma200_s = df1m["close"].rolling(200).mean()
            ma200_1m = float(ma200_s.iloc[-1])
            cur_1m = float(df1m["close"].iloc[-1])
            price_vs_ma200 = "ABOVE" if cur_1m > ma200_1m else "BELOW"
        except Exception: pass

    # ── M-1: EMAクロス検出（短期/中期の角度も評価）1H ──
    ema_result = {"golden_cross": False, "dead_cross": False, "fast_above": False,
                  "angle_deg": 0.0, "fast_ema": 0.0, "slow_ema": 0.0, "signal": "NONE"}
    if df1h is not None and len(df1h) >= 24:
        try:
            ema_result = TechnicalIndicators.detect_ema_cross(df1h["close"])
        except Exception: pass

    # ── M-5: 吸収（Absorption）検出 1m ──
    absorption_result = {"bull_absorption": False, "bear_absorption": False,
                         "vol_spike": False, "wick_ratio": 0.0, "signal": "NONE"}
    if df1m is not None and len(df1m) >= 5:
        try:
            absorption_result = TechnicalIndicators.detect_absorption(df1m)
        except Exception: pass

    # ── RSIダイバージェンス（M-3）──
    divergence = "None"
    if df1h is not None:
        try:
            rsi_s = TechnicalIndicators.rsi(df1h["close"])
            divergence = TechnicalIndicators.detect_divergence(df1h["close"], rsi_s)
        except Exception: pass

    # ── MACDダイバージェンス（M-2）──
    macd_divergence = "None"
    if df1h is not None:
        try:
            macd_df   = TechnicalIndicators.macd(df1h["close"])
            macd_divergence = TechnicalIndicators.detect_macd_divergence(
                df1h["close"], macd_df["macd"])
        except Exception: pass

    # ── インサイドバー（M-1）──
    inside_bar = {"detected": False, "squeeze_confirmed": False}
    if df1h is not None and len(df1h) >= 21:
        try:
            inside_bar = TechnicalIndicators.detect_inside_bar(df1h)
        except Exception: pass

    # ── 三尊・逆三尊（M-4）──
    head_shoulders = {"pattern": "なし", "neckline": 0.0, "bias": "NONE"}
    if df1h is not None and len(df1h) >= 10:
        try:
            head_shoulders = TechnicalIndicators.detect_head_shoulders(df1h)
        except Exception: pass

    # ── エリオット波動（M-5）──
    elliott = {"wave_count": 0, "wave_label": "不明", "wave3_detected": False}
    if df1h is not None and len(df1h) >= 10:
        try:
            elliott = TechnicalIndicators.count_elliott_wave(df1h["close"])
        except Exception: pass

    # ── L-1: 勢い枯れ早期警告（Momentum Exhaustion Detector）1H ──
    exhaustion_result = {"exhausted": False, "score": 0, "signal": "NONE",
                         "direction_bias": "NONE", "reasons": []}
    if df1h is not None and len(df1h) >= 30:
        try:
            exhaustion_result = TechnicalIndicators.detect_momentum_exhaustion(df1h)
        except Exception: pass

    # ── L-6: 週足（W1）トレンド ──
    weekly_trend = "N/A"
    weekly_ma200_position = "N/A"
    try:
        df_wk = fetcher.get_analysis_df(sym, "1wk")
        if df_wk is not None and len(df_wk) >= 200:
            ma200_wk = df_wk["close"].rolling(200).mean()
            cur_wk   = float(df_wk["close"].iloc[-1])
            weekly_ma200_position = "ABOVE" if cur_wk > float(ma200_wk.iloc[-1]) else "BELOW"
            # 週足ダウ理論（簡易）: 直近3週の高値・安値
            h1, h2, h3 = df_wk["high"].iloc[-1], df_wk["high"].iloc[-4], df_wk["high"].iloc[-8]
            l1, l2, l3 = df_wk["low"].iloc[-1],  df_wk["low"].iloc[-4],  df_wk["low"].iloc[-8]
            if h1 > h2 > h3 and l1 > l2 > l3:
                weekly_trend = "WEEKLY_UP"
            elif h1 < h2 < h3 and l1 < l2 < l3:
                weekly_trend = "WEEKLY_DOWN"
            else:
                weekly_trend = "WEEKLY_RANGE"
    except Exception: pass

    # ── Fear&Greed ──
    vix_val = fred_cache.get("data", {}).get("VIXCLS", {})
    if isinstance(vix_val, dict): vix_val = vix_val.get("value", 20)
    fear_greed_str = f"VIX={vix_val}" if vix_val else "不明"

    # ── MACD/RSI from engine momentum layer ──
    mom_layer = {}
    if isinstance(layers, dict):
        for k in ("momentum", "Momentum", "mom"):
            if k in layers:
                mom_layer = layers[k] if isinstance(layers[k], dict) else {}
                break

    iron_patterns = list(ref.get("signals", []))
    if divergence != "None":
        iron_patterns.append(divergence)
    if macd_divergence != "None":
        iron_patterns.append(macd_divergence)
    if inside_bar.get("detected"):
        label = "インサイドバー+BBスクイーズ" if inside_bar.get("squeeze_confirmed") else "インサイドバー"
        iron_patterns.append(label)
    if head_shoulders.get("pattern") != "なし":
        iron_patterns.append(head_shoulders["pattern"])
    # スキャルピングシグナルをiron_patternsに追加
    liq_sig = liq_result.get("signal", "NONE")
    if liq_sig not in ("NONE", ""):
        iron_patterns.append(f"LiquiditySweep:{liq_sig}")
    if wick_result.get("bull_denial"):
        iron_patterns.append("WickDenial:BULL")
    elif wick_result.get("bear_denial"):
        iron_patterns.append("WickDenial:BEAR")
    if decay_result.get("signal") == "MOMENTUM_DECAY":
        iron_patterns.append("MomentumDecay")
    if range_result.get("is_range"):
        iron_patterns.append("RANGE_WAIT")
    if fib_result.get("near_fib_level"):
        iron_patterns.append(f"Fib:{fib_result['near_fib_level']}")
    # M-1: EMAクロス
    ema_sig = ema_result.get("signal", "NONE")
    if ema_sig not in ("NONE", ""):
        iron_patterns.append(f"EMA:{ema_sig}")
    # M-5: Absorption
    abs_sig = absorption_result.get("signal", "NONE")
    if abs_sig not in ("NONE", ""):
        iron_patterns.append(f"Absorption:{abs_sig}")
    # L-1: 勢い枯れ
    exh_sig = exhaustion_result.get("signal", "NONE")
    if exh_sig not in ("NONE", ""):
        iron_patterns.append(f"Exhaustion:{exh_sig}")

    session_str = get_active_session(datetime.utcnow().hour)

    return {
        "current_price":    price,
        "session":          session_str,
        # BB
        "bb_score":         bb_result.get("bb_score", 0),
        "bb_reasons":       bb_result.get("bb_reasons", []),
        "bb_4h_dir":        bb_result.get("bb_4h_dir", "FLAT"),
        "bb_15m_dir":       bb_result.get("bb_15m_dir", "FLAT"),
        "squeeze_released": bb_result.get("squeeze_released", False),
        # ATR / ボラ
        "atr_1h":           atr_1h,
        "vol_regime":       vol_result.get("regime", "NORMAL"),
        "vol_ratio":        vol_result.get("ratio", 1.0),
        # グランビル (H-4)
        "granville_pattern": granville_pattern,
        # ストキャス
        "stoch_k":           stoch_result.get("k", 50.0),
        "stoch_d":           stoch_result.get("d", 50.0),
        "stoch_gc":          stoch_result.get("golden_cross", False),
        "stoch_dc":          stoch_result.get("dead_cross", False),
        "stoch_oversold":    stoch_result.get("oversold", False),
        "stoch_overbought":  stoch_result.get("overbought", False),
        # 一目
        "chikou_cross":      ichimoku_result.get("chikou_cross", "NONE"),
        "price_vs_cloud":    ichimoku_result.get("price_vs_cloud", "N/A"),
        "cloud_top":         ichimoku_result.get("cloud_top", 0.0),
        "cloud_bot":         ichimoku_result.get("cloud_bot", 0.0),
        # UPLOW
        "uplow_state":       uplow_result.get("state", "INSIDE"),
        "uplow_ma":          uplow_result.get("ma", 0.0),
        # Momentum (MACD/RSI)
        "macd_sync":         mom_layer.get("sync_direction", "N/A"),
        "hist_h1":           mom_layer.get("hist_h1", 0),
        "hist_15m":          mom_layer.get("hist_15m", 0),
        "band_walk":         any("バンドウォーク" in str(s) for s in iron_patterns),
        "rsi_15m":           mom_layer.get("rsi_15m", ref.get("rsi", 50)),
        "rsi_1h":            mom_layer.get("rsi_1h", ref.get("rsi", 50)),
        "rsi_state":         mom_layer.get("rsi_state", "NEUTRAL"),
        # Trigger
        "pa_trigger":        next((s for s in iron_patterns if "ピンバー" in str(s) or "包み足" in str(s)), "None"),
        "iron_patterns":     iron_patterns,
        "key_levels":        key_levels,
        # Fundamentals
        "fear_greed":        fear_greed_str,
        "is_iron_clad":      any("IronClad" in str(s) or "鉄板" in str(s) for s in iron_patterns),
        # M-1: インサイドバー
        "inside_bar":        inside_bar.get("detected", False),
        "inside_bar_squeeze": inside_bar.get("squeeze_confirmed", False),
        # M-2: MACDダイバージェンス
        "macd_divergence":   macd_divergence,
        # M-4: 三尊・逆三尊
        "hs_pattern":        head_shoulders.get("pattern", "なし"),
        "hs_neckline":       head_shoulders.get("neckline", 0.0),
        "hs_bias":           head_shoulders.get("bias", "NONE"),
        # M-5: エリオット波動
        "elliott_wave":      elliott.get("wave_label", "不明"),
        "elliott_wave3":     elliott.get("wave3_detected", False),
        # H-5: Liquidity Sweep（最重要スキャルピングシグナル）
        "liq_signal":        liq_result.get("signal", "NONE"),
        "liq_bull_sweep":    liq_result.get("bull_sweep", False),
        "liq_bear_sweep":    liq_result.get("bear_sweep", False),
        "liq_bull_rebreak":  liq_result.get("bull_rebreak", False),
        "liq_bear_rebreak":  liq_result.get("bear_rebreak", False),
        "liq_swept_high":    liq_result.get("swept_high", 0.0),
        "liq_swept_low":     liq_result.get("swept_low", 0.0),
        # H-7: ヒゲ否定
        "wick_bull_denial":  wick_result.get("bull_denial", False),
        "wick_bear_denial":  wick_result.get("bear_denial", False),
        "wick_denied_high":  wick_result.get("denied_wick_high", 0.0),
        "wick_denied_low":   wick_result.get("denied_wick_low", 0.0),
        # H-8: 勢い減衰
        "momentum_decaying": decay_result.get("is_decaying", False),
        "decay_ratio":       decay_result.get("decay_ratio", 1.0),
        "decay_signal":      decay_result.get("signal", "NONE"),
        # H-10: レンジ状態
        "is_range":          range_result.get("is_range", False),
        "range_high":        range_result.get("range_high", 0.0),
        "range_low":         range_result.get("range_low", 0.0),
        "bb_width_ratio":    range_result.get("bb_width_ratio", 1.0),
        # H-11: RSI on BB
        "rsi_val":           rsi_bb_result.get("rsi", 50.0),
        "rsi_above_bb":      rsi_bb_result.get("above_bb", False),
        "rsi_below_bb":      rsi_bb_result.get("below_bb", False),
        "rsi_bearish_div":   rsi_bb_result.get("bearish_divergence", False),
        "rsi_bullish_div":   rsi_bb_result.get("bullish_divergence", False),
        # H-15: フィボナッチ
        "fib_500":           fib_result.get("fib_500", 0.0),
        "fib_618":           fib_result.get("fib_618", 0.0),
        "near_fib_level":    fib_result.get("near_fib_level"),
        "fib_swing_high":    fib_result.get("swing_high", 0.0),
        "fib_swing_low":     fib_result.get("swing_low", 0.0),
        # MA200 on 1m
        "ma200_1m":          ma200_1m,
        "price_vs_ma200":    price_vs_ma200,
        # M-1: EMAクロス
        "ema_signal":        ema_result.get("signal", "NONE"),
        "ema_golden_cross":  ema_result.get("golden_cross", False),
        "ema_dead_cross":    ema_result.get("dead_cross", False),
        "ema_fast_above":    ema_result.get("fast_above", False),
        "ema_angle":         ema_result.get("angle_deg", 0.0),
        # M-5: 吸収（Absorption）
        "absorption_signal": absorption_result.get("signal", "NONE"),
        "bull_absorption":   absorption_result.get("bull_absorption", False),
        "bear_absorption":   absorption_result.get("bear_absorption", False),
        "absorption_wick_ratio": absorption_result.get("wick_ratio", 0.0),
        # L-1: 勢い枯れ早期警告
        "exhaustion_signal":    exhaustion_result.get("signal", "NONE"),
        "exhausted":            exhaustion_result.get("exhausted", False),
        "exhaustion_bias":      exhaustion_result.get("direction_bias", "NONE"),
        "exhaustion_reasons":   exhaustion_result.get("reasons", []),
        # L-6: 週足トレンド
        "weekly_trend":         weekly_trend,
        "weekly_ma200":         weekly_ma200_position,
    }


# ─── コア分析（blocking） ───────────────────────────────────────
def _analyze_symbol_blocking(sym: str) -> dict:
    results  = {}
    df_store = {}   # H-7: DFを保持してengine_signals構築に使う
    for tf in TIMEFRAMES:
        try:
            df = fetcher.get_analysis_df(sym, tf)
            # M-8: Supabaseキャッシュからフォールバック
            if (df is None or df.empty or len(df) < 30):
                snap = db.get_latest_snapshot(sym, tf)
                if snap and snap.get("ohlcv"):
                    try:
                        import pandas as _snap_pd
                        ohlcv_rows = snap["ohlcv"]
                        snap_df = _snap_pd.DataFrame(ohlcv_rows)
                        if "timestamp" in snap_df.columns:
                            snap_df = snap_df.rename(columns={"timestamp": "date"})
                        if len(snap_df) >= 30:
                            df = snap_df
                            print(f"[M-8] {sym}/{tf}: using Supabase snapshot ({len(df)} bars)")
                    except Exception as _snap_e:
                        print(f"[M-8] snapshot parse error {sym}/{tf}: {_snap_e}")
            if df is None or df.empty or len(df) < 30: continue
            df_store[tf] = df   # H-7: 保存
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
            # レイヤーキーを小文字に正規化 (SMC→smc, Technical→technical, etc.)
            raw_layers = v6.get("layers", {})
            norm_layers = {k.lower(): v for k, v in raw_layers.items()} if raw_layers else {}
            results[tf] = {
                "status":    status,
                "score":     score,
                "rsi":       round(float(latest.get("rsi", 50)), 1),
                "price":     float(latest["close"]),
                "layers":    norm_layers,
                "aligned":   v6.get("aligned", v6.get("aligned_layers", 0)),
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

            # M-8: 正常取得時にSupabaseへスナップショット保存（非同期的に静かに）
            if tf == ANALYSIS_TF:
                try:
                    ohlcv_list = df[["open", "high", "low", "close", "volume"]].tail(200).to_dict("records") if hasattr(df, "columns") else []
                    db.save_snapshot(sym, tf, ohlcv_list, norm_layers)
                except Exception:
                    pass

        except Exception as e:
            print(f"[Analyze] {sym}/{tf}: {e}")
            traceback.print_exc()

    if results:
        ref = results.get(ANALYSIS_TF) or next(iter(results.values()), {})
        price = ref.get("price", 0)
        if price: price_cache[sym] = price

    # H-9: DFキャッシュを更新（ai_loopが参照）
    if df_store:
        _df_cache[sym] = df_store

    # H-9: engine_signals を構築してresultsに付加
    if results and df_store:
        try:
            es = _build_engine_signals(sym, results, df_store)
            results["_engine_signals"] = es
            # ai_loop が直接参照できるよう system_state にも保存
            system_state[sym]["_engine_signals"] = es
        except Exception as e:
            print(f"[EngineSignals] {sym}: {e}")

    return results


# ─── H-10: 高速データループ（10秒）─────────────────────────────
async def fast_loop():
    """データ取得・スコア更新専用。AIは呼ばない。"""
    print("[Server] ONO Estimator Ultra v6.2 started (fast_loop)")
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
            loop = asyncio.get_event_loop()
            for sym in SYMBOLS:
                try:
                    tf_results = await loop.run_in_executor(None, _analyze_symbol_blocking, sym)
                    if not tf_results:
                        continue
                    for tf, summary in tf_results.items():
                        if tf in TIMEFRAMES:
                            system_state[sym][tf].update(summary)
                    market_overview["data_summary"][sym] = {
                        tf: tf_results[tf]["data_bars"]
                        for tf in tf_results
                        if tf in TIMEFRAMES and "data_bars" in tf_results[tf]
                    }
                except Exception as e:
                    print(f"[FastLoop] {sym}: {e}")

            # H-11: DemoTrader 決済チェック
            if demo_trader:
                try:
                    demo_trader.check_and_close(price_cache, notifier)
                except Exception as e:
                    print(f"[DemoTrader] check error: {e}")

        except Exception as e:
            print(f"[FastLoop] Critical: {e}")

        elapsed = time.time() - cycle_start
        await asyncio.sleep(max(5, 10 - elapsed))


# ─── H-10: AIループ（60秒+）────────────────────────────────────
async def ai_loop():
    """Gemini分析・通知・DemoTraderエントリー専用。"""
    await asyncio.sleep(30)  # fast_loopが1周するのを待つ
    while True:
        for sym in SYMBOLS:
            try:
                if not _needs_ai(sym):
                    continue
                if not _can_gemini():
                    await asyncio.sleep(5)
                    continue

                _record_gemini()
                last_ai_call[sym] = time.time()
                ref_score = system_state[sym][ANALYSIS_TF].get("score", 0)
                last_ai_score[sym] = ref_score

                feedback       = _get_feedback(sym)
                engine_signals = system_state[sym].get("_engine_signals") or {}
                engine_signals["current_price"] = price_cache.get(sym, 0)

                ai_data = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda s=sym, es=engine_signals, fb=feedback: ai_analyzer.analyze_single(
                        s, {"current_price": price_cache.get(s, 0)},
                        feedback=fb, engine_signals=es,
                    )
                )
                if not ai_data:
                    await asyncio.sleep(15)
                    continue

                # 後方互換正規化
                ai_data.setdefault("entry",  ai_data.get("entry_price"))
                ai_data.setdefault("sl",     ai_data.get("sl_price"))
                ai_data.setdefault("tp1",    ai_data.get("tp_price"))
                ai_data.setdefault("direction", "WAIT")
                ai_data.setdefault("basis",  (ai_data.get("ai_text") or "")[:80])

                # system_state 更新（全TF）— スキャルピングフィールドも含む
                for tf in TIMEFRAMES:
                    system_state[sym][tf].update({
                        "ai_text":        ai_data.get("ai_text", ""),
                        "awareness_text": ai_data.get("awareness_text", ""),
                        "basis":          ai_data.get("basis", ""),
                        "probability":    ai_data.get("probability", 0),
                        "direction":      ai_data.get("direction", "WAIT"),
                        "entry":          ai_data.get("entry") or system_state[sym][tf].get("entry", 0),
                        "tp1":            ai_data.get("tp1") or system_state[sym][tf].get("tp1", 0),
                        "tp2":            ai_data.get("tp2") or system_state[sym][tf].get("tp2", 0),
                        "sl":             ai_data.get("sl") or system_state[sym][tf].get("sl", 0),
                        "signal_quality": ai_data.get("signal_quality", ai_data.get("confidence", "LOW")),
                        "should_notify":  ai_data.get("should_notify", False),
                        "rr_ratio":       ai_data.get("rr_ratio"),
                        "cached":         False,
                        "last_updated":   datetime.now().isoformat(),
                        # スキャルピング特化フィールド（フロント表示用）
                        "is_range":       ai_data.get("is_range", False),
                        "entry_type":     ai_data.get("entry_type", "NONE"),
                        "predicted_price": ai_data.get("predicted_price", 0),
                        "step1_trend":    ai_data.get("step1_trend", ""),
                        "step2_range":    ai_data.get("step2_range", ""),
                        "step3_entry_type": ai_data.get("step3_entry_type", ""),
                    })

                ref_state = system_state[sym][ANALYSIS_TF]
                score     = ref_state.get("score", 0)
                prob      = ai_data.get("probability", 0)
                should_notify  = ai_data.get("should_notify", False)
                should_demo    = ai_data.get("should_enter_demo", False)
                is_locked      = _check_daily_lock()

                # M-10: DB保存条件整理（should_enter_demo=true または通知判断 or 高スコア）
                if should_demo or should_notify or abs(score) >= 70:
                    db.save_prediction({
                        "symbol":        sym,
                        "timeframe":     ANALYSIS_TF,
                        "status":        ref_state.get("status", "Wait"),
                        "score":         score,
                        "ai_text":       ai_data.get("ai_text", ""),
                        "entry":         ai_data.get("entry") or 0,
                        "tp1":           ai_data.get("tp1") or 0,
                        "sl":            ai_data.get("sl") or 0,
                        "probability":   prob,
                        "current_price": price_cache.get(sym, 0),
                        "layers":        ref_state.get("layers", {}),
                        "aligned":       ref_state.get("aligned", 0),
                        "session":       ref_state.get("session", "off"),
                    })

                # マーケット概況更新
                if market_overview["last_update_ts"] < time.time() - 120:
                    market_overview["global_theme"] = (ai_data.get("ai_text") or "")[:80] + "..."
                    market_overview["last_update_ts"] = int(time.time())

                # L-5: SQI — 連敗5以上の場合は通知閾値を引き上げ
                sqi_streak = _sqi_loss_streak.get(sym, 0)
                notify_threshold = 80 if (_sqi_total_scored >= 100 and sqi_streak >= 5) else 45

                # L-2: Correlation Guard（同グループ内重複通知抑制）
                notify_allowed = _corr_filter_allow(sym, score)

                # H-12: AI熟練トレーダー通知
                if not is_locked and notify_allowed and (should_notify or abs(score) >= notify_threshold or prob >= 75):
                    try:
                        notifier.notify_ai_judgment(sym, ai_data)
                    except Exception as ne:
                        print(f"[Notifier] {sym}: {ne}")
                        try:
                            notifier.notify_if_needed(sym, None, ai_data, price_cache.get(sym, 0))
                        except Exception: pass

                # H-11: DemoTrader エントリー
                if not is_locked and should_demo and demo_trader:
                    entry = ai_data.get("entry_price") or ai_data.get("entry", 0)
                    tp    = ai_data.get("tp_price")    or ai_data.get("tp1", 0)
                    sl    = ai_data.get("sl_price")    or ai_data.get("sl", 0)
                    reason = ai_data.get("awareness_text", ai_data.get("basis", ""))
                    if entry and tp and sl:
                        demo_trader.open_position(
                            _short(sym), ai_data.get("direction", "WAIT"),
                            entry, tp, sl, reason
                        )

            except Exception as e:
                print(f"[AILoop] {sym}: {e}")
                traceback.print_exc()

            await asyncio.sleep(15)  # 銘柄間インターバル

        await asyncio.sleep(30)  # 全銘柄完了後に待機


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
        await asyncio.sleep(120)


async def auto_evaluate_loop():
    """バックテスト自動評価 + AI自己反省ループ (1時間毎)

    TP/SL到達判定: TP到達→WIN、SL到達→LOSS、どちらも未到達→現在価格で評価
    """
    await asyncio.sleep(300)
    while True:
        try:
            unscored = db.get_unscored_predictions()
            evaluated = 0
            losses_this_run = []

            for row in unscored:
                sym_short = row.get("symbol", "")
                ticker = next((k for k, v in SYM_SHORT.items() if v == sym_short), sym_short)
                cur_price = price_cache.get(ticker, 0)
                if not cur_price:
                    continue

                entry = row.get("entry_price") or row.get("entry") or 0
                direction = row.get("direction", "WAIT")
                tp1 = row.get("take_profit") or row.get("tp1") or 0
                sl  = row.get("stop_loss")  or row.get("sl")  or 0

                if not entry or direction == "WAIT":
                    continue

                # TP/SL到達判定（より正確なWIN/LOSS判定）
                outcome = "PENDING"
                is_correct = False
                pips = 0.0

                if direction == "BUY":
                    if tp1 and cur_price >= tp1:
                        outcome = "WIN"; is_correct = True; pips = (tp1 - entry) * 10000
                    elif sl and cur_price <= sl:
                        outcome = "LOSS"; is_correct = False; pips = (sl - entry) * 10000
                    else:
                        pips = (cur_price - entry) * 10000
                        is_correct = cur_price > entry
                        outcome = "WIN" if is_correct else "LOSS"
                elif direction == "SELL":
                    if tp1 and cur_price <= tp1:
                        outcome = "WIN"; is_correct = True; pips = (entry - tp1) * 10000
                    elif sl and cur_price >= sl:
                        outcome = "LOSS"; is_correct = False; pips = (entry - sl) * 10000
                    else:
                        pips = (entry - cur_price) * 10000
                        is_correct = cur_price < entry
                        outcome = "WIN" if is_correct else "LOSS"

                if outcome == "PENDING":
                    continue

                db.update_prediction_result(row["id"], cur_price, is_correct, outcome)
                db.save_performance(
                    prediction_id=row["id"], symbol=sym_short, direction=direction,
                    entry_price=entry, exit_price=cur_price, outcome=outcome, pips_result=pips,
                )
                evaluated += 1

                if not is_correct:
                    losses_this_run.append({
                        "symbol": sym_short, "direction": direction,
                        "entry_price": entry, "exit_price": cur_price, "pips_result": pips,
                    })

                # L-5: SQI — 連敗カウント更新
                ticker_key = next((k for k, v in SYM_SHORT.items() if v == sym_short), sym_short)
                if outcome == "LOSS":
                    _sqi_loss_streak[ticker_key] = _sqi_loss_streak.get(ticker_key, 0) + 1
                elif outcome == "WIN":
                    _sqi_loss_streak[ticker_key] = 0

            if evaluated > 0:
                # L-5: 採点総数を更新（100件以上でSQI有効化）
                global _sqi_total_scored
                try:
                    perf_total = db.get_performance_summary()
                    _sqi_total_scored = sum(
                        v.get("total", 0)
                        for v in (perf_total.get("by_symbol") or {}).values()
                        if isinstance(v, dict)
                    )
                except Exception: pass
                print(f"[AutoEval] {evaluated}件 採点完了 (LOSS: {len(losses_this_run)}件)")
                perf = db.get_performance_summary()
                market_overview["history_stats"] = _load_history_stats()
                market_overview["performance"]   = perf

                # 勝率55%未満 or 今回のLOSSが2件以上 → AI自己反省を生成
                wr = perf.get("win_rate", 0)
                if wr < 55 or len(losses_this_run) >= 2:
                    all_losses = losses_this_run or [
                        l for l in perf.get("logs", []) if l.get("outcome") == "LOSS"
                    ][:5]
                    if all_losses:
                        for sym_key in ["ALL"] + list({l["symbol"] for l in all_losses}):
                            try:
                                sym_losses = (
                                    all_losses if sym_key == "ALL"
                                    else [l for l in all_losses if l["symbol"] == sym_key]
                                )
                                if not sym_losses:
                                    continue
                                lesson = ai_analyzer.generate_self_reflection(sym_key, sym_losses)
                                if lesson:
                                    ai_analyzer.save_ai_lesson(sym_key, lesson, wr)
                                    print(f"[AIReflect] {sym_key}: {lesson[:60]}...")
                            except Exception as e:
                                print(f"[AIReflect] {sym_key}: {e}")

        except Exception as e:
            print(f"[AutoEval] Error: {e}")
            traceback.print_exc()

        await asyncio.sleep(3600)  # 1時間毎


_warmup_done = False
_warmup_ts: float = 0.0
_last_ai_success: float = 0.0


async def warmup_loop():
    """スピンアップ直後にUSDJPY/1hを先読みしてキャッシュを温める"""
    global _warmup_done, _warmup_ts
    await asyncio.sleep(5)
    try:
        loop = asyncio.get_event_loop()
        warmup_sym = "USDJPY=X"
        print("[Warmup] Preloading USDJPY/1h...")
        df = await loop.run_in_executor(None, lambda: fetcher.get_analysis_df(warmup_sym, "1h"))
        if df is not None and not df.empty:
            chart = await loop.run_in_executor(None, lambda: fetcher.get_chart_data(warmup_sym, "1h"))
            chart_cache[warmup_sym]["1h"] = chart or []
            price = float(df.iloc[-1]["close"])
            price_cache[warmup_sym] = price
            system_state[warmup_sym]["1h"]["status"] = "Warm"
            system_state[warmup_sym]["1h"]["price"] = price
            _warmup_ts = time.time()
            print(f"[Warmup] ✅ USDJPY={price:.3f} ({len(df)} bars cached)")
        else:
            print("[Warmup] No data returned")
    except Exception as e:
        print(f"[Warmup] Error: {e}")
    finally:
        _warmup_done = True


@app.on_event("startup")
async def startup():
    asyncio.create_task(warmup_loop())        # 最優先: スピンアップ直後にキャッシュ温め
    asyncio.create_task(fast_loop())          # H-10: 10秒データループ
    asyncio.create_task(ai_loop())            # H-10: 60秒AIループ
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
    # 超軽量: DB接続なし・即時応答 (Renderスピンアップ監視用)
    return {"status": "ok", "ts": int(time.time())}


@app.get("/api/status")
def status():
    # 詳細ステータス (内部確認用)
    return {
        "status": "healthy", "version": "6.3.0",
        "engine_v2": _V2,
        "mode": market_overview.get("mode", "starting"),
        "gemini_calls_last_min": len(_gemini_times),
        "last_sync": market_overview["last_update_ts"],
        "startup_done": _startup_done,
    }


@app.get("/api/predict")
def get_prediction(tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    # フロントは短縮銘柄キー（USDJPY, GOLD…）で参照する。内部は Yahoo ティッカーで保持。
    tf_state = {_short(sym): states.get(tf) for sym, states in system_state.items()}
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
        gen_fn = getattr(ai_analyzer, "generate_self_reflection", None)
        lesson = gen_fn(symbol, losses) if gen_fn else None
        if lesson:
            save_fn = getattr(ai_analyzer, "save_ai_lesson", None)
            if save_fn: save_fn(symbol, lesson, wr)
        return {"lesson": lesson, "win_rate": wr}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/system/status")
async def system_status():
    """システム自己診断ダッシュボード (管理者用)"""
    now = int(time.time())

    # Gemini APIキー状態 (新APIに対応)
    gemini_keys = getattr(ai_analyzer, "api_keys", getattr(ai_analyzer, "_keys", []))
    gemini_keys_count = len(gemini_keys)
    current_key_idx   = getattr(ai_analyzer, "_key_idx", 0)
    fallback_models   = getattr(ai_analyzer, "fallback_models", ["gemini-2.0-flash"])
    current_model     = getattr(ai_analyzer, "model_name", fallback_models[0])

    # Supabase テーブル行数
    table_counts = {}
    if db.client:
        for tbl in ["predictions", "performance_log", "system_health", "ai_memory",
                    "active_signals", "notification_logs"]:
            try:
                r = db.client.table(tbl).select("id", count="exact").limit(1).execute()
                table_counts[tbl] = r.count or 0
            except Exception:
                table_counts[tbl] = -1
    else:
        table_counts = {"error": "Supabase not connected"}

    # 当日のシグナル数
    today_signals = {"total": 0, "buy": 0, "sell": 0, "wait": 0}
    if db.client:
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
            r = db.client.table("predictions").select("direction")\
                .gt("created_at", today_start).execute()
            for row in (r.data or []):
                d = row.get("direction", "WAIT")
                today_signals["total"] += 1
                today_signals[d.lower()] = today_signals.get(d.lower(), 0) + 1
        except Exception:
            pass

    # パフォーマンス
    try:
        perf = db.get_performance_summary()
        win_rate = perf.get("win_rate", 0)
        total_trades = perf.get("total_trades", 0)
    except Exception:
        win_rate = 0
        total_trades = 0

    return {
        "timestamp": now,
        "uptime_seconds": now - int(_warmup_ts) if _warmup_ts else None,
        "warmup_done": _warmup_done,
        "startup_done": _startup_done,

        "gemini": {
            "keys_configured": gemini_keys_count,
            "current_key_index": current_key_idx,
            "current_model": current_model,
            "calls_last_minute": len(_gemini_times),
            "ai_active": getattr(ai_analyzer, "model", None) is not None,
        },

        "supabase": {
            "connected": db.client is not None,
            "table_counts": table_counts,
        },

        "market": {
            "mode": market_overview.get("mode", "starting"),
            "last_update_ts": market_overview["last_update_ts"],
            "last_update_ago_sec": now - market_overview["last_update_ts"],
            "prices": {_short(k): v for k, v in price_cache.items() if v},
        },

        "performance": {
            "win_rate": win_rate,
            "total_trades": total_trades,
            "today_signals": today_signals,
            "daily_locked": _check_daily_lock(),
        },

        "modules": {
            "engine_v2": _V2, "fred": _HAS_FRED, "session": _HAS_SESSION,
            "market": _HAS_MARKET, "scanner": _HAS_SCANNER, "backtest": _HAS_BACKTEST,
            "trade_monitor": _HAS_MONITOR, "cot": _HAS_COT,
            "demo_trader": demo_trader is not None,
        },
    }


# ─── H-11: DemoTrader API ───────────────────────────────────────

@app.get("/api/demo/positions")
def demo_positions():
    """デモポジション一覧"""
    open_pos  = demo_trader.get_open_positions() if demo_trader else {}
    history   = db.get_demo_positions(limit=20)
    win_rate  = db.get_demo_win_rate()
    return {
        "open":     list(open_pos.values()),
        "history":  history,
        "win_rate": win_rate,
        "active_count": len(open_pos),
    }


@app.post("/api/demo/close/{symbol}")
def demo_close(symbol: str):
    """手動でデモポジションを強制決済"""
    if not demo_trader:
        return {"status": "unavailable"}
    pos = demo_trader.open_positions.get(symbol.upper())
    if not pos:
        return {"status": "no_position", "symbol": symbol}
    cur = price_cache.get(symbol.upper(), 0)
    pips = abs(cur - pos["entry_price"]) if cur else 0
    result = "MANUAL"
    try:
        db.close_demo_position(symbol.upper(), cur, result, pips)
    except Exception: pass
    demo_trader.open_positions.pop(symbol.upper(), None)
    return {"status": "closed", "symbol": symbol, "close_price": cur, "pips": pips}
