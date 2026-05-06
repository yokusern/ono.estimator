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
from fastapi.responses import StreamingResponse, Response
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
    allow_origins=[],  # 4-3: allow_origin_regex のみで制御（"*"を廃止）
    allow_origin_regex=r"(https://.*\.vercel\.app|http://localhost:3000|http://localhost:\d+)",
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

# TASK 1/2/3: pipsターゲット連動ウィンドウ設定
try:
    from ono_estimator.core.pips_config import get_window_config, DEFAULT_TARGET_PIPS, get_trade_style
    _pips_config = get_window_config(DEFAULT_TARGET_PIPS)
    _HAS_PIPS_CONFIG = True
except Exception as _pe:
    _HAS_PIPS_CONFIG = False
    DEFAULT_TARGET_PIPS = 20
    _pips_config = {"primary": {"tf": "5m", "bars": 48}, "confirm": {"tf": "15m", "bars": 8}, "context": {"tf": "1h", "bars": 6}, "hold_minutes": 60}
    print(f"[PipsConfig] fallback: {_pe}")

CURRENT_TARGET_PIPS = DEFAULT_TARGET_PIPS

def _set_target_pips(pips: Optional[int]) -> int:
    global CURRENT_TARGET_PIPS, _pips_config
    if pips is None:
        return CURRENT_TARGET_PIPS
    try:
        value = int(pips)
    except Exception:
        return CURRENT_TARGET_PIPS
    if value <= 0:
        return CURRENT_TARGET_PIPS
    CURRENT_TARGET_PIPS = value
    if _HAS_PIPS_CONFIG:
        try:
            _pips_config = get_window_config(value)
        except Exception:
            pass
    return CURRENT_TARGET_PIPS
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

# B-1: 積極モード設定
AGGRESSIVE_MODE = os.environ.get("AGGRESSIVE_MODE", "true").lower() == "true"

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
        # A-1/A-5/A-9: 新フィールド
        "trade_style": {}, "entry_timing": {}, "entry_reason_short": "",
        "scenarios": {}, "opportunity_score": 0,
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
# D-1: 通知ログ（直近20件のインメモリキャッシュ）
_notification_log: deque = deque(maxlen=20)
# 3-5: system_state 書き込みロック
system_state_lock: asyncio.Lock = None  # startup後に初期化
# 3-1: anti_sleep失敗カウンター
_anti_sleep_fail_count = 0

# ─── L-2: Correlation Guard ────────────────────────────────────
_CORR_GROUPS = {
    "JPY":   ["USDJPY=X", "AUDJPY=X", "EURJPY=X"],
    "EUR":   ["EURUSD=X", "EURJPY=X"],
    "METAL": ["GC=F", "SI=F"],
}
_CORRELATION_GUARD = os.getenv("CORRELATION_GUARD", "false").lower() == "true"
_corr_notified: dict = {}   # {group: {"sym": sym, "score": score, "ts": ts}}

def _corr_filter_allow(sym: str, score: float, threshold: float = 40) -> bool:
    """B-4: 同グループ内重複通知抑制。ただし両方がthreshold以上なら両方通知。"""
    if not _CORRELATION_GUARD:
        return True
    now = time.time()
    allowed = True
    for group, members in _CORR_GROUPS.items():
        if sym not in members:
            continue
        cached = _corr_notified.get(group, {})
        cached_score = cached.get("score", 0)
        cached_ts    = cached.get("ts", 0)
        # B-4: 両方スコアがthreshold以上なら両方通知を許可
        if now - cached_ts < 1800 and cached_score >= threshold and score >= threshold:
            print(f"[CorrGuard] {sym} ALLOWED (both high-score: {cached_score:.0f} vs {score:.0f})")
            _corr_notified[group] = {"sym": sym, "score": score, "ts": now}
        elif now - cached_ts < 1800 and cached_score >= score:
            print(f"[CorrGuard] {sym} suppressed — {cached.get('sym')} already notified in {group}")
            allowed = False
        else:
            _corr_notified[group] = {"sym": sym, "score": score, "ts": now}
    return allowed

# ─── L-5: Signal Quality Index (SQI) ──────────────────────────
_sqi_loss_streak: dict = {sym: 0 for sym in SYMBOLS}
_sqi_total_scored = 0

# ─── T-07: 日次エントリーカウンター ────────────────────────────
TARGET_DAILY_ENTRIES = 10
_entry_log: dict = {sym: [] for sym in SYMBOLS}

def log_entry_signal(symbol: str) -> None:
    """エントリーシグナル発生時に記録する。"""
    today = datetime.utcnow().date()
    _entry_log[symbol] = [t for t in _entry_log[symbol] if t.date() == today]
    _entry_log[symbol].append(datetime.utcnow())

def get_daily_progress() -> dict:
    """今日の銘柄別エントリー試行回数と合計を返す。"""
    today = datetime.utcnow().date()
    counts = {
        SYM_SHORT.get(sym, sym): len([t for t in _entry_log[sym] if t.date() == today])
        for sym in SYMBOLS
    }
    total = sum(counts.values())
    return {"counts": counts, "total": total, "target": TARGET_DAILY_ENTRIES}

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
    """H-1: 時間経過 or スコアが±10以上変化した場合にAI呼び出し。
    0-1: 5分以上更新がない場合は強制再実行（無限スキップ防止）"""
    now = time.time()
    last = last_ai_call.get(sym, 0)
    current_score = system_state[sym][ANALYSIS_TF].get("score", 0)
    score_changed = abs(current_score - last_ai_score.get(sym, 0)) >= 10
    # 0-1: 5分以上更新なし → 強制フォールバック
    stale = (now - last) > 300
    if _is_crypto(sym): return True
    if _is_market_open(sym): return (now - last) > 58 or score_changed or stale
    return (now - last) > 3600 or score_changed or stale

_gemini_rate_blocked = 0  # 1-2: レート制限ブロック累計カウンター

def _can_gemini() -> bool:
    # 1-2: レート制限設計 — MAX_GEMINI_PER_MINUTE=2, ANALYSIS_TF="1h" キャッシュ流用
    # 通知送信ロジック(notifier.py)はAIを呼ばない設計を徹底している
    global _gemini_rate_blocked
    now = time.time()
    while _gemini_times and now - _gemini_times[0] > 60: _gemini_times.popleft()
    can = len(_gemini_times) < 2
    if not can:
        _gemini_rate_blocked += 1
        if _gemini_rate_blocked % 10 == 1:  # 10回に1回だけログ（spam防止）
            _log_gemini_rate_limit()
    return can

def _log_gemini_rate_limit():
    """1-2: レート制限発生をSupabaseに記録（呼び出し頻度の可視化）"""
    try:
        if db and db.client:
            db.client.table("system_health").insert({
                "event": "gemini_rate_limited",
                "count": _gemini_rate_blocked,
                "ts": datetime.now().isoformat(),
            }).execute()
    except Exception:
        pass

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
    """C-4: スコア帯別勝率 + 直近パターンをGeminiにフィードバック"""
    try:
        history = db.get_history(limit=100)
        key = _short(sym)
        rows = [r for r in history if key in r.get("symbol", "")]
        if not rows:
            perf = db.get_performance_text() if hasattr(db, "get_performance_text") else ""
            return perf or "学習データ蓄積中..."
        scored  = [r for r in rows if r.get("is_scored")]
        correct = [r for r in rows if r.get("is_correct")]
        wr = round(len(correct)/len(scored)*100, 1) if scored else None
        lines = [f"【{key}実績】採点{len(scored)}件 勝率{wr if wr else 'N/A'}%"]
        # C-4: スコア帯別勝率（Geminiが参考にしてバイアス修正する）
        bands: dict = {"30-49": [], "50-69": [], "70+": []}
        for r in scored:
            s = abs(r.get("score", 0))
            win = bool(r.get("is_correct"))
            if s >= 70:   bands["70+"].append(win)
            elif s >= 50: bands["50-69"].append(win)
            elif s >= 30: bands["30-49"].append(win)
        for band, results in bands.items():
            if results:
                bwr = round(sum(results) / len(results) * 100)
                lines.append(f"  スコア{band}: {len(results)}件 勝率{bwr}% {'→ 信頼度高' if bwr >= 60 else '→ 要注意'}")
        for r in rows[:5]:
            tag = "✓WIN" if r.get("is_correct") else ("✗LOSS" if r.get("is_scored") else "pending")
            lines.append(f"  {r.get('status','?')} sc:{r.get('score',0)} {tag}")
        return "\n".join(lines)
    except Exception as e: return f"History error: {e}"


def _detect_entry_tags(engine_signals: dict, ai_data: dict) -> list:
    """D-5: エントリーパターンの自動タグ付け"""
    tags = []
    es = engine_signals or {}
    # エントリータイプタグ
    if es.get("ls_detected") or es.get("liq_bull_rebreak") or es.get("liq_bear_rebreak"):
        tags.append("#liquidity_sweep")
    et = ai_data.get("entry_type", "NONE")
    if et == "BODY_BREAK":  tags.append("#body_break")
    if et == "WICK_DENIAL": tags.append("#wick_denial")
    if et == "HAS_SHOULDER": tags.append("#hs_pattern")
    # テクニカルパターン
    if es.get("saneki_ko") or es.get("saneki_gyaku"): tags.append("#saneki")
    if es.get("macd_divergence") not in ("None", None, ""): tags.append("#macd_div")
    if es.get("rsi_bull_div") or es.get("rsi_bear_div"): tags.append("#rsi_div")
    if es.get("elliott_wave3"): tags.append("#elliott_w3")
    if es.get("squeeze_released"): tags.append("#bb_squeeze_break")
    # スタイルタグ
    style = (ai_data.get("trade_style") or {}).get("main_style", "")
    if "スキャル" in style: tags.append("#scalp")
    elif "デイトレ" in style: tags.append("#day")
    elif "スイング" in style: tags.append("#swing")
    # セッションタグ
    sess = es.get("session", "")
    if sess: tags.append(f"#{sess.lower()}")
    return tags


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


# TASK 6: 3層合意スコア
def calc_agreement_score(context_dir: str, confirm_dir: str, primary_dir: str) -> float:
    """
    context / confirm / primary の方向一致度でスコア倍率を返す。
    全一致→1.0 / 2/3一致→0.7 / 不一致→0.3
    """
    dirs = [context_dir, confirm_dir, primary_dir]
    buy_count  = sum(1 for d in dirs if d and "BUY"  in d)
    sell_count = sum(1 for d in dirs if d and "SELL" in d)
    if buy_count >= 3 or sell_count >= 3:
        return 1.0
    elif buy_count >= 2 or sell_count >= 2:
        return 0.7
    else:
        return 0.3


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

    _signals = {
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
        # T-01/T-06: ReasoningEngine 思考結果 (後で上書きされる)
        "entry_decision":       "WAIT",
        "step1_trend":          "",
        "step2_range":          "",
        "step3_entry_type":     "",
        "conflict_flags":       [],
    }

    # ── T-06: ReasoningEngine で4ステップ思考 ────────────────────
    try:
        from ono_estimator.core.reasoning_engine import ReasoningEngine as _RE
        _re = _RE()
        _thinking = _re.think(df_store, sym)
        # エンジンシグナルに思考結果を上書き
        base_ret = {
            "entry_decision":   _thinking.entry_decision,
            "confidence_level": _thinking.confidence,
            "conflict_flags":   _thinking.conflict_flags,
            "step1_trend":      _thinking.upper.reason,
            "step2_range":      _thinking.mid.reason,
            "step3_entry_type": _thinking.trigger.reason,
            "sl_hint":          _thinking.sl_hint,
            "tp_hint":          _thinking.tp_hint,
            "thinking_reason":  _thinking.entry_reason,
            # 一目均衡表強化 (T-11)
            "saneki_ko":        _thinking.upper.ichimoku_status == "三役好転",
            "saneki_gyaku":     _thinking.upper.ichimoku_status == "三役逆転",
            "ichimoku_label":   _thinking.upper.ichimoku_status,
        }
        # ── ichimoku_result も直接フィールドで更新 ──
        if df1h is not None and len(df1h) >= 60:
            try:
                from ono_estimator.indicators.technical import TechnicalIndicators as _TI
                ichi = _TI.ichimoku(df1h["high"], df1h["low"], df1h["close"])
                base_ret["saneki_ko"]    = ichi.get("saneki_ko", False)
                base_ret["saneki_gyaku"] = ichi.get("saneki_gyaku", False)
                base_ret["ichimoku_label"] = ichi.get("status_label", "")
                base_ret["tenkan_cross"] = ichi.get("tenkan_cross", "NONE")
                base_ret["cloud_thickness"] = ichi.get("cloud_thickness", 0.0)
            except Exception:
                pass
    except Exception as _re_err:
        base_ret = {}
        print(f"[ReasoningEngine] {sym}: {_re_err}")

    # T-06: ReasoningEngine結果で上書き
    _signals.update(base_ret)

    # 3-2: 複数銘柄相関フィルター
    try:
        from ono_estimator.filters.correlation_filter import check_correlation
        corr = check_correlation(sym, system_state, ANALYSIS_TF)
        _signals["corr_score_bonus"] = corr.get("score_bonus", 0)
        _signals["corr_tags"]        = corr.get("tags", [])
        _signals["corr_caution"]     = corr.get("caution", "")
    except Exception as _corr_err:
        _signals["corr_score_bonus"] = 0
        _signals["corr_tags"]        = []
        _signals["corr_caution"]     = ""
        print(f"[CorrelationFilter] {sym}: {_corr_err}")

    # A-3: コードベース Liquidity Sweep 検出 (TASK 5: 直近ウィンドウのみ使用)
    try:
        from ono_estimator.filters.liquidity_sweep import detect_liquidity_sweep as _dls
        _ls_df_raw = df_store.get("5m") if df_store.get("5m") is not None else (
                     df_store.get("1m") if df_store.get("1m") is not None else df1h)
        # TASK 5: primary_bars本に制限してSV検出（長期データで薄まる問題を解消）
        _sv_bars = _pips_config.get("primary", {}).get("bars", 48)
        _ls_df = _ls_df_raw.tail(_sv_bars) if _ls_df_raw is not None else None
        if _ls_df is not None and len(_ls_df) >= 22:
            _ls = _dls(_ls_df)
            _signals["ls_detected"]  = _ls["detected"]
            _signals["ls_direction"] = _ls["direction"]
            _signals["ls_level"]     = _ls["sweep_level"]
            # Sweepが検出されたらスコアに+20
            if _ls["detected"]:
                _signals["ls_score_bonus"] = 20
                iron_patterns.append(f"LiquiditySweep_CODE:{_ls['direction']}")
        else:
            _signals["ls_detected"] = False
            _signals["ls_direction"] = "NONE"
            _signals["ls_level"] = 0.0
            _signals["ls_score_bonus"] = 0
    except Exception as _ls_err:
        _signals["ls_detected"] = False
        _signals["ls_direction"] = "NONE"
        _signals["ls_level"] = 0.0
        _signals["ls_score_bonus"] = 0
        print(f"[LiquiditySweep] {sym}: {_ls_err}")

    # C-1: コードベース エントリータイプ検出
    try:
        from ono_estimator.filters.entry_type_detector import detect_entry_type as _det
        # 1-1: DataFrame の or チェーンは ambiguous エラーになるため explicit に
        _et_df = df_store.get("5m") if df_store.get("5m") is not None else (
                 df_store.get("1m") if df_store.get("1m") is not None else df1h)
        _hs_pat = next((p for p in iron_patterns if "HeadAndShoulders" in str(p)), "なし")
        _detected_et = _det(_et_df, key_levels, _hs_pat)
        _signals["detected_entry_type"] = _detected_et
    except Exception as _et_err:
        _signals["detected_entry_type"] = "NONE"
        print(f"[EntryTypeDetector] {sym}: {_et_err}")

    # C-2: MTF コンフルエンススコア計算
    try:
        _mtf_conf = _calc_mtf_confluence(sym)
        _signals["mtf_confluence_score"]    = _mtf_conf.get("pct", 0)
        _signals["mtf_confluence_dominant"] = _mtf_conf.get("dominant", "WAIT")
        _signals["mtf_confluence_count"]    = _mtf_conf.get("confluence_score", 0)
        if _mtf_conf.get("pct", 0) >= 60:
            _signals["mtf_conf_bonus"] = 15
        else:
            _signals["mtf_conf_bonus"] = 0
    except Exception:
        _signals["mtf_confluence_score"] = 0
        _signals["mtf_conf_bonus"] = 0

    # A-1: トレードスタイル判定
    try:
        from ono_estimator.core.trade_style_detector import detect_trade_style
        _signals["trade_style"] = detect_trade_style(_signals)
    except Exception as _ts_err:
        _signals["trade_style"] = {}
        print(f"[TradeStyleDetector] {sym}: {_ts_err}")

    # A-5: エントリータイミング判定
    try:
        from ono_estimator.core.entry_timing_detector import detect_entry_timing
        _signals["entry_timing"] = detect_entry_timing(_signals, float(price or 0))
    except Exception as _et_err:
        _signals["entry_timing"] = {}
        print(f"[EntryTimingDetector] {sym}: {_et_err}")

    return _signals


# ─── コア分析（blocking） ───────────────────────────────────────
def _analyze_symbol_blocking(sym: str, target_pips: int = None) -> dict:
    if target_pips is None:
        target_pips = DEFAULT_TARGET_PIPS
    w_cfg    = _pips_config if not target_pips or target_pips == DEFAULT_TARGET_PIPS else (
        get_window_config(target_pips) if _HAS_PIPS_CONFIG else _pips_config
    )
    primary_tf  = w_cfg["primary"]["tf"]
    primary_bars = w_cfg["primary"]["bars"]
    confirm_tf  = w_cfg["confirm"]["tf"]
    confirm_bars = w_cfg["confirm"]["bars"]
    context_tf  = w_cfg["context"]["tf"]
    context_bars = w_cfg["context"]["bars"]

    results  = {}
    df_store = {}
    # 3層方向を収集（TASK 6 用）
    _layer_dirs = {"primary": "WAIT", "confirm": "WAIT", "context": "WAIT"}

    # 直近重視は維持しつつ、各レイヤー計算に必要な最小本数を確保
    # （短すぎると 5m / 15m のスコアが 0 固定になりやすい）
    tf_min_recent_bars = {
        "1m": 72,
        "5m": 64,
        "15m": 60,
        "30m": 60,
        "1h": 60,
        "4h": 60,
    }

    for tf in TIMEFRAMES:
        try:
            min_analysis_bars = tf_min_recent_bars.get(tf, 60)
            # TASK 2: TFごとにウィンドウを適用してDFを取得
            if tf == primary_tf:
                df = fetcher.get_analysis_df_windowed(sym, tf, max(primary_bars, min_analysis_bars))
            elif tf == confirm_tf:
                df = fetcher.get_analysis_df_windowed(sym, tf, max(confirm_bars, min_analysis_bars))
            elif tf == context_tf:
                df = fetcher.get_analysis_df_windowed(sym, tf, max(context_bars, min_analysis_bars))
            else:
                df = fetcher.get_analysis_df(sym, tf)
                if df is not None and len(df) > 500:
                    df = df.tail(500)
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
            if engine_v2 and bars >= 30:
                try:
                    loop = asyncio.new_event_loop()
                    v6 = loop.run_until_complete(
                        engine_v2.analyze(_short(sym), df, target_pips=target_pips)
                    )
                    loop.close()
                except Exception as e:
                    print(f"[v6] {sym}/{tf}: {e}")

            # TASK 6: 3層方向を収集
            _v6_dir = (v6.get("direction", "WAIT") if v6 else "WAIT")
            if tf == primary_tf:
                _layer_dirs["primary"] = _v6_dir
            elif tf == confirm_tf:
                _layer_dirs["confirm"] = _v6_dir
            elif tf == context_tf:
                _layer_dirs["context"] = _v6_dir

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

    # TASK 6: 3層合意スコアを primary TF のスコアに適用
    if results and primary_tf in results:
        agreement = calc_agreement_score(
            _layer_dirs["context"], _layer_dirs["confirm"], _layer_dirs["primary"]
        )
        if agreement < 1.0:
            orig_score = results[primary_tf].get("score", 0)
            results[primary_tf]["score"] = round(orig_score * agreement)
            results[primary_tf]["agreement_multiplier"] = agreement
            if agreement <= 0.3:
                results[primary_tf]["warnings"] = results[primary_tf].get("warnings", []) + [
                    "⚠️ 3層不一致 — 方向感なし。WAIT推奨"
                ]

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
                    tf_results = await loop.run_in_executor(None, _analyze_symbol_blocking, sym, CURRENT_TARGET_PIPS)
                    if not tf_results:
                        continue
                    async with system_state_lock:
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
        # T-08: 優先キュー — WAIT以外(BUY/SELL判断あり)の銘柄を先に処理
        def _ai_priority(sym: str) -> int:
            engine_signals = system_state[sym].get("_engine_signals") or {}
            entry_decision = engine_signals.get("entry_decision", "WAIT")
            if entry_decision in ("BUY", "SELL"):
                return 0   # 高優先
            score = system_state[sym][ANALYSIS_TF].get("score", 0)
            return 1 if abs(score) >= 60 else 2

        ordered_symbols = sorted(SYMBOLS, key=_ai_priority)
        for sym in ordered_symbols:
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
                    # 1-2: ALL KEYS EXHAUSTED → reset to force retry; show warning
                    last_ai_call[sym] = 0
                    async with system_state_lock:
                        if not os.environ.get("GEMINI_API_KEY"):
                            for tf in TIMEFRAMES:
                                system_state[sym][tf]["ai_text"] = "APIキー未設定のためAI分析は無効です"
                        else:
                            for tf in TIMEFRAMES:
                                system_state[sym][tf]["ai_text"] = "⚠️ AI分析データ更新中（Gemini一時停止中）"
                    await asyncio.sleep(20)  # 1-4: 15→20s
                    continue

                # 後方互換正規化
                ai_data.setdefault("entry",  ai_data.get("entry_price"))
                ai_data.setdefault("sl",     ai_data.get("sl_price"))
                ai_data.setdefault("tp1",    ai_data.get("tp_price"))
                ai_data.setdefault("direction", "WAIT")
                ai_data.setdefault("basis",  (ai_data.get("ai_text") or "")[:80])

                # A-1/A-5: engine_signals の新フィールドを ai_data に注入
                es_for_update = system_state[sym].get("_engine_signals") or engine_signals
                ai_data.setdefault("trade_style",  es_for_update.get("trade_style", {}))
                ai_data.setdefault("entry_timing", es_for_update.get("entry_timing", {}))
                ai_data["score"] = ref_score  # notifier に渡すため

                # 3-5: system_state 更新（全TF）— ロックで排他制御
                async with system_state_lock:
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
                            "is_range":       ai_data.get("is_range", False),
                            "entry_type":     ai_data.get("entry_type", "NONE"),
                            "predicted_price": ai_data.get("predicted_price", 0),
                            "step1_trend":    ai_data.get("step1_trend", ""),
                            "step2_range":    ai_data.get("step2_range", ""),
                            "step3_entry_type": ai_data.get("step3_entry_type", ""),
                            # A-1/A-5/A-9/D-2 new fields
                            "trade_style":    ai_data.get("trade_style", {}),
                            "entry_timing":   ai_data.get("entry_timing", {}),
                            "entry_reason_short": ai_data.get("entry_reason_short", ""),
                            "scenarios":      ai_data.get("scenarios", {}),
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
                # B-1: AGGRESSIVE_MODE では閾値を大幅引き下げ
                if AGGRESSIVE_MODE:
                    notify_threshold = 50 if (_sqi_total_scored >= 100 and sqi_streak >= 5) else 35
                else:
                    notify_threshold = 70 if (_sqi_total_scored >= 100 and sqi_streak >= 5) else 40

                confidence_level = ai_data.get("confidence", ai_data.get("signal_quality", "LOW"))

                # A-2 / A-5: HIGH confidence または entry_timing==NOW なら強制通知
                entry_timing = ai_data.get("entry_timing", {}) or {}
                if confidence_level == "HIGH" and prob >= 55:
                    should_notify = True
                    ai_data["should_notify"] = True
                if AGGRESSIVE_MODE and entry_timing.get("timing") == "NOW":
                    should_notify = True
                    ai_data["should_notify"] = True

                # L-2: Correlation Guard
                notify_allowed = _corr_filter_allow(sym, score, notify_threshold)

                # B-1: AGGRESSIVE_MODE OR条件（さらに緩和）
                if AGGRESSIVE_MODE:
                    should_send = (
                        should_notify
                        or score >= notify_threshold
                        or prob >= 55
                        or confidence_level == "HIGH"
                        or (ref_state.get("aligned", 0) >= 3 and abs(score) >= 30)
                    )
                else:
                    should_send = (
                        should_notify
                        or score >= notify_threshold
                        or prob >= 55
                        or confidence_level == "HIGH"
                    )

                # D-2: スキップ理由ログ
                if not is_locked and not notify_allowed:
                    skip_reason = "Correlation Guard"
                    print(f"[Notify] {sym} SKIP: {skip_reason}")
                elif is_locked:
                    skip_reason = "Daily Lock"
                    print(f"[Notify] {sym} SKIP: {skip_reason}")
                elif not should_send:
                    skip_reason = f"スコア不足 (score={score}, prob={prob}, conf={confidence_level})"
                    print(f"[Notify] {sym} SKIP: {skip_reason}")
                else:
                    skip_reason = None
                    print(f"[Notify] {sym} SEND: score={score}, prob={prob}, conf={confidence_level}, should_notify={should_notify}")

                # T-07: エントリーシグナル記録
                if should_send and not is_locked:
                    log_entry_signal(sym)

                # H-12: AI熟練トレーダー通知（B-3: base_system渡し）
                base_system = engine_signals.get("base_system", ai_data.get("base_system", "AI"))
                notified = False
                if not is_locked and notify_allowed and should_send:
                    try:
                        notifier.notify_ai_judgment(sym, ai_data, base_system=base_system)
                        notified = True
                    except Exception as ne:
                        print(f"[Notifier] {sym}: {ne}")
                        try:
                            notifier.notify_if_needed(sym, None, ai_data, price_cache.get(sym, 0))
                            notified = True
                        except Exception: pass

                # D-1/D-2: 通知ログ記録（送信/スキップ両方）
                direction_ai = ai_data.get("direction", "WAIT")
                _notification_log.appendleft({
                    "symbol":      _short(sym),
                    "direction":   direction_ai,
                    "score":       score,
                    "probability": prob,
                    "confidence":  confidence_level,
                    "notified":    notified,
                    "skip_reason": skip_reason,
                    "trade_style": (ai_data.get("trade_style") or {}).get("main_style", ""),
                    "timing":      (ai_data.get("entry_timing") or {}).get("timing", ""),
                    "ts":          datetime.utcnow().isoformat(),
                })

                # B-2: 見送りシグナルをSupabaseに保存
                if not notified and direction_ai not in ("WAIT", ""):
                    try:
                        db.save_missed_signal({
                            "symbol":       _short(sym),
                            "direction":    direction_ai,
                            "score":        score,
                            "probability":  prob,
                            "entry":        ai_data.get("entry"),
                            "tp1":          ai_data.get("tp1"),
                            "tp2":          ai_data.get("tp2"),
                            "sl":           ai_data.get("sl"),
                            "skip_reason":  skip_reason,
                            "trade_style":  (ai_data.get("trade_style") or {}).get("main_style", ""),
                        })
                    except Exception: pass

                # H-11/A-5: DemoTrader エントリー (should_enter_demo OR entry_timing==NOW)
                direction_val = ai_data.get("direction", "WAIT")
                is_now_entry = (
                    entry_timing.get("timing") == "NOW"
                    and direction_val in ("BUY", "SELL", "STRONG_BUY", "STRONG_SELL")
                    and not ai_data.get("is_range", False)
                    and abs(score) >= 30
                )
                final_should_demo = (not is_locked) and (should_demo or is_now_entry) and demo_trader
                if final_should_demo:
                    entry = ai_data.get("entry_price") or ai_data.get("entry", 0)
                    tp    = ai_data.get("tp_price")    or ai_data.get("tp1", 0)
                    sl    = ai_data.get("sl_price")    or ai_data.get("sl", 0)
                    reason_base = ai_data.get("entry_reason_short") or ai_data.get("awareness_text", "")
                    reason = reason_base + (" [AUTO⚡NOW]" if is_now_entry and not should_demo else "")
                    if entry and tp and sl:
                        opened = demo_trader.open_position(
                            _short(sym), direction_val,
                            entry, tp, sl, reason
                        )
                        # NOW自動エントリー専用Discordアラート
                        if opened and is_now_entry and not should_demo:
                            try:
                                notifier.send_now_auto_entry(sym, ai_data, score, prob)
                            except Exception as _ne:
                                print(f"[NOW-Entry] Discord notify failed: {_ne}")

                # D-5: エントリータグ保存
                _entry_tags = _detect_entry_tags(engine_signals, ai_data)
                if _entry_tags:
                    try:
                        async with system_state_lock:
                            for tf in TIMEFRAMES:
                                system_state[sym][tf]["entry_tags"] = _entry_tags
                    except Exception: pass

            except Exception as e:
                print(f"[AILoop] {sym}: {e}")
                traceback.print_exc()

            await asyncio.sleep(10)  # B-3: 15→10s（全銘柄2分以内スキャン）

        await asyncio.sleep(15)  # B-3: 30→15s


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
    global _anti_sleep_fail_count
    await asyncio.sleep(30)
    _discord_warn_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    while True:
        try:
            requests.get(f"{RENDER_URL}/api/health", timeout=10)
            _anti_sleep_fail_count = 0
        except Exception as e:
            _anti_sleep_fail_count += 1
            print(f"[AntiSleep] health check failed #{_anti_sleep_fail_count}: {e}")
            if _anti_sleep_fail_count >= 3 and _discord_warn_url:
                try:
                    requests.post(_discord_warn_url, json={
                        "content": f"⚠️ Render HEALTH CHECK FAILED {_anti_sleep_fail_count}回連続 — サーバーダウンの可能性"
                    }, timeout=5)
                    _anti_sleep_fail_count = 0
                except Exception: pass
        await asyncio.sleep(600)  # 4-2: 10分ごとにself-ping（Renderスリープ対策）


async def weekly_summary_loop():
    """C-5: 毎週日曜23:30 JST に週次サマリーをDiscord通知"""
    await asyncio.sleep(60)
    _sent_week = ""
    while True:
        try:
            jst_now = datetime.utcnow().replace(tzinfo=None) + timedelta(hours=9)
            week_key = jst_now.strftime("%Y-W%W")
            if jst_now.weekday() == 6 and jst_now.hour == 23 and 25 <= jst_now.minute <= 35:
                if _sent_week != week_key:
                    _sent_week = week_key
                    # 週次サマリーをDiscordに送信
                    try:
                        from datetime import timedelta as _td
                        one_week_ago = (datetime.utcnow() - _td(days=7)).isoformat()
                        perf = {}
                        if db.client:
                            r = db.client.table("performance_log")\
                                .select("outcome,pips_result,symbol")\
                                .gte("created_at", one_week_ago).execute()
                            rows2 = r.data or []
                            total = len([x for x in rows2 if x.get("outcome") in ("WIN","LOSS")])
                            wins  = len([x for x in rows2 if x.get("outcome") == "WIN"])
                            wr2   = round(wins/total*100, 1) if total else 0
                            pips2 = sum(x.get("pips_result") or 0 for x in rows2)
                            msg = (
                                f"📊 **週次サマリー ({jst_now.strftime('%Y/%m/%d')})**\n"
                                f"トレード数: {total} | 勝率: {wr2}% | 総pips: {pips2:.1f}\n"
                            )
                        else:
                            msg = f"📊 週次サマリー: DB未接続"
                        webhook = os.environ.get("DISCORD_WEBHOOK_URL","")
                        if webhook:
                            requests.post(webhook, json={"content": msg}, timeout=5)
                    except Exception as _we:
                        print(f"[WeeklySummary] Discord error: {_we}")
        except Exception as e:
            print(f"[WeeklyLoop] {e}")
        await asyncio.sleep(300)  # 5分毎チェック


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

            four_hours_ago = (datetime.utcnow() - timedelta(hours=4)).isoformat()
            for row in unscored:
                # 3-4: 4時間以上前の予測はスキップ（古すぎて信頼性がない）
                created_at = row.get("created_at", "")
                if created_at and created_at < four_hours_ago:
                    continue

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
    global system_state_lock
    system_state_lock = asyncio.Lock()  # 3-5: 非同期ロック初期化
    asyncio.create_task(warmup_loop())        # 最優先: スピンアップ直後にキャッシュ温め
    asyncio.create_task(fast_loop())          # H-10: 10秒データループ
    asyncio.create_task(ai_loop())            # H-10: 60秒AIループ
    asyncio.create_task(backtest_loop())
    asyncio.create_task(trade_monitor_loop())
    asyncio.create_task(scanner_loop())
    asyncio.create_task(auto_evaluate_loop())
    asyncio.create_task(weekly_summary_loop())  # C-5: 毎週日曜サマリー
    asyncio.create_task(anti_sleep_loop())
    # 4-1: Engine v2 フォールバック時に Discord 通知（起動時1回）
    if not _V2:
        _dw = os.environ.get("DISCORD_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_AI")
        if _dw:
            try:
                requests.post(_dw, json={
                    "content": "🔴 **Engine v2 フォールバック中** — Engine v5 で稼働しています。精度が低下している可能性があります。"
                }, timeout=5)
            except Exception:
                pass


# ─── API Endpoints ─────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ONO Estimator Ultra v6.1", "time": datetime.now().isoformat()}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    # 1-3: HEAD対応 (Renderスピンアップ監視用・超軽量)
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
def get_prediction(
    tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$"),
    target_pips: int = Query(None, ge=1, le=1000),
):
    applied_target = _set_target_pips(target_pips)
    # フロントは短縮銘柄キー（USDJPY, GOLD…）で参照する。内部は Yahoo ティッカーで保持。
    tf_state = {_short(sym): states.get(tf) for sym, states in system_state.items()}
    return {
        "data": tf_state,
        "overview": market_overview,
        "current_tf": tf,
        "target_pips": applied_target,
        "trade_style": get_trade_style(applied_target) if _HAS_PIPS_CONFIG else "デイトレード",
        "server_time": int(time.time()),
        "engine_version": "6.1" if _V2 else "5.0",
    }


@app.get("/api/config/target_pips")
def get_target_pips():
    p = CURRENT_TARGET_PIPS
    return {
        "target_pips": p,
        "trade_style": get_trade_style(p) if _HAS_PIPS_CONFIG else "デイトレード",
        "window_config": _pips_config,
    }


@app.post("/api/config/target_pips")
def set_target_pips(target_pips: int = Query(..., ge=1, le=1000)):
    p = _set_target_pips(target_pips)
    return {
        "ok": True,
        "target_pips": p,
        "trade_style": get_trade_style(p) if _HAS_PIPS_CONFIG else "デイトレード",
        "window_config": _pips_config,
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


@app.get("/api/funda/{symbol}")
async def get_funda(symbol: str):
    """3-1: ファンダメンタルデータパネル — FRED/政策金利差/COT/センチメント"""
    fred = await _get_fred()

    # 政策金利テーブル（主要中銀の現在のレート）
    RATE_TABLE = {
        "USD": 5.33, "JPY": 0.10, "EUR": 4.50, "GBP": 5.25,
        "AUD": 4.35, "CAD": 5.00, "CHF": 1.75, "NZD": 5.50,
    }
    sym_upper = symbol.upper()
    # 通貨ペアから base/quote を推定
    pairs = {
        "USDJPY": ("USD","JPY"), "AUDJPY": ("AUD","JPY"),
        "EURUSD": ("EUR","USD"), "EURJPY": ("EUR","JPY"),
        "GOLD": ("USD","XAU"), "BTC": ("USD","BTC"),
        "JP225": ("JPY","IDX"), "XAGUSD": ("USD","XAG"),
    }
    base_ccy, quote_ccy = pairs.get(sym_upper, ("USD","JPY"))
    base_rate  = RATE_TABLE.get(base_ccy, 0)
    quote_rate = RATE_TABLE.get(quote_ccy, 0)
    rate_diff  = round(base_rate - quote_rate, 2)
    rate_badge = "🟢" if rate_diff > 1 else "🔴" if rate_diff < -1 else "🟡"

    # FRED指標
    dxy   = (fred.get("DTWEXBGS") or fred.get("DXY") or {}).get("value")
    vix   = (fred.get("VIXCLS") or {}).get("value")
    us10y = (fred.get("DGS10") or {}).get("value")

    # センチメント（VIX ベース Fear & Greed）
    sentiment = {"fear_greed": 50, "label": "中立"}
    if _HAS_SENTIMENT and vix:
        try:
            fg = calc_fx_fear_greed(float(vix), 0, 0)
            sentiment = {"fear_greed": fg.get("index", 50), "label": fg.get("label", "中立")}
        except Exception: pass

    # COT データ（system_state から取得）
    ticker = {
        "USDJPY":"USDJPY=X","GOLD":"GC=F","BTC":"BTC-USD",
        "JP225":"^N225","XAGUSD":"SI=F","AUDJPY":"AUDJPY=X",
        "EURUSD":"EURUSD=X","EURJPY":"EURJPY=X",
    }.get(sym_upper, sym_upper)
    ref = system_state.get(ticker, {}).get(ANALYSIS_TF, {})
    cot_score = ref.get("cot_score", 0)
    cot_signal = "BUY" if cot_score > 5 else "SELL" if cot_score < -5 else "NEUTRAL"

    # セッション情報
    sess_info = _get_session_info()
    sess_label_map = {"tokyo":"東京（中ボラ）","london":"ロンドン（高ボラ）","ny":"NY（高ボラ）","off":"オフ（低ボラ）"}
    sess_label = sess_label_map.get(sess_info.get("current",""), "---")

    return {
        "symbol": symbol,
        "rate_diff": {
            "base": base_ccy, "base_rate": base_rate,
            "quote": quote_ccy, "quote_rate": quote_rate,
            "diff": rate_diff, "badge": rate_badge,
        },
        "fred": {
            "DXY":   round(float(dxy), 2) if dxy else None,
            "VIX":   round(float(vix), 2) if vix else None,
            "US10Y": round(float(us10y), 3) if us10y else None,
        },
        "cot": {
            "net_position": cot_score,
            "signal": cot_signal,
            "score_bonus": abs(cot_score) // 10,
        },
        "sentiment": sentiment,
        "session": sess_label,
        "next_event": None,  # 将来: イベントカレンダー連携
        "ts": int(time.time()),
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
def forecast(symbol: str, tf: str = Query("1h", pattern="^(1m|5m|15m|30m|1h|4h)$")):
    """2-1: 予測チャート用エンドポイント — zigzag_points形式（offset_bars + type + probability）"""
    _SYM_MAP = {
        "USDJPY": "USDJPY=X","GOLD":"GC=F","BTC":"BTC-USD",
        "JP225":"^N225","XAGUSD":"SI=F","AUDJPY":"AUDJPY=X",
        "EURUSD":"EURUSD=X","EURJPY":"EURJPY=X",
    }
    ticker = _SYM_MAP.get(symbol.upper(), symbol)
    ref    = system_state.get(ticker, {}).get(ANALYSIS_TF, {})
    price  = price_cache.get(ticker, 0)
    prob   = ref.get("probability", 0)
    direction = ref.get("status", "WAIT")
    hold   = ref.get("hold_time_minutes", 60) or 60

    # TF別のbar数オフセット計算（分→bar数）
    tf_minutes = {"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240}
    tf_min = tf_minutes.get(tf, 60)

    tp1 = ref.get("tp1", 0)
    tp2 = ref.get("tp2", 0)
    tp3 = ref.get("tp3", ref.get("tp2", 0))
    sl  = ref.get("sl", 0)
    atr = ref.get("atr", abs(tp1 - price) if tp1 and price else (price or 1) * 0.003)

    zigzag_points = []
    if tp1 and price:
        bars1 = max(1, round(hold / tf_min))
        prob_tp1 = min(95, round(prob * 0.95))
        zigzag_points.append({"offset_bars": bars1, "price": round(tp1, 5), "type": "TP1", "probability": prob_tp1})
    if tp2 and price:
        bars2 = max(2, round(hold * 2 / tf_min))
        prob_tp2 = min(85, round(prob * 0.7))
        zigzag_points.append({"offset_bars": bars2, "price": round(tp2, 5), "type": "TP2", "probability": prob_tp2})
    if sl and price:
        bars_sl = max(1, round(hold * 0.6 / tf_min))
        zigzag_points.append({"offset_bars": bars_sl, "price": round(sl, 5), "type": "SL", "probability": round(100 - prob)})

    # 後方互換: forecast_points も維持
    now_jst = datetime.now(timezone.utc) + timedelta(hours=9)
    tw = ref.get("time_window", {})
    legacy_points = []
    if tp1:
        legacy_points.append({"time": (now_jst + timedelta(minutes=hold)).isoformat(), "price": tp1,
                               "confidence_upper": round(tp1 + atr * 0.5, 5), "confidence_lower": round(tp1 - atr * 0.5, 5)})
    if tp2:
        legacy_points.append({"time": (now_jst + timedelta(minutes=hold*2)).isoformat(), "price": tp2,
                               "confidence_upper": round(tp2 + atr, 5), "confidence_lower": round(tp2 - atr, 5)})

    return {
        "symbol": symbol,
        "current_price": price,
        "zigzag_points": zigzag_points,
        "direction": direction.replace("STRONG_", ""),
        "scenario": "A" if prob >= 65 else "B" if prob >= 45 else "C",
        "forecast_points": legacy_points,
        "entry": ref.get("entry", price),
        "sl": sl,
        "time_window": tw,
        "basis": ref.get("basis", ""),
        "probability": prob,
        "atr": round(atr, 5) if atr else 0,
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


@app.get("/api/performance")
def performance_by_symbol():
    """3-3: 銘柄別パフォーマンス（総シグナル数・勝率・平均スコア）"""
    try:
        rows = db.get_performance_by_symbol()
        return {"data": rows, "count": len(rows)}
    except Exception as e:
        return {"data": [], "count": 0, "error": str(e)}


@app.get("/api/notifications")
def notifications():
    """D-1: 直近20件の通知ログ（送信/スキップ含む）"""
    return {"data": list(_notification_log), "count": len(_notification_log)}


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


@app.get("/api/daily/entries")
def daily_entries():
    """T-07: 今日のエントリー試行カウント"""
    return get_daily_progress()


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
        # 4-1: エンジン稼働状態
        "engine_version": "v2" if _V2 else "v5",
        "engine_status": "normal" if _V2 else "fallback",
        "gemini_rate_blocked_total": _gemini_rate_blocked,
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


# ─── A-6: 銘柄優先度ランキング ──────────────────────────────────

@app.get("/api/ranking")
def get_ranking():
    """全8銘柄をopportunity_scoreで降順にランキング"""
    try:
        from ono_estimator.core.opportunity_ranker import rank_opportunities
        ranked = rank_opportunities(system_state, ANALYSIS_TF)
        return {
            "data": ranked,
            "ts": int(time.time()),
            "top3": ranked[:3],
        }
    except Exception as e:
        return {"data": [], "error": str(e)}


# ─── B-2: 見送りシグナルログ ────────────────────────────────────

@app.get("/api/missed")
def get_missed(limit: int = Query(20, le=50)):
    """直近の見送りシグナルを返す"""
    try:
        return {
            "data": db.get_missed_signals(limit=limit),
            "ts": int(time.time()),
        }
    except Exception as e:
        return {"data": [], "error": str(e)}


# ─── A-2: 必要資金計算 ────────────────────────────────────────

from pydantic import BaseModel

class CapitalRequest(BaseModel):
    symbol: str
    current_price: float
    sl_pips: float = 5.0
    risk_pct: float = 1.0
    leverage: int = 25
    capital_jpy: float = 0

@app.post("/api/capital/calc")
def capital_calc(req: CapitalRequest):
    try:
        from ono_estimator.core.capital_calculator import calc_capital
        # Normalize symbol
        mapping = {
            "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
            "JP225": "^N225", "XAGUSD": "SI=F", "AUDJPY": "AUDJPY=X",
            "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
        }
        ticker = mapping.get(req.symbol, req.symbol)
        result = calc_capital(ticker, req.current_price, req.sl_pips,
                              req.risk_pct, req.leverage, req.capital_jpy)
        return result
    except Exception as e:
        return {"error": str(e)}


# ─── C-3: コンディション・メンタルチェック ──────────────────────

@app.get("/api/mental_check")
def mental_check():
    try:
        from ono_estimator.core.mental_guard import check_mental_state
        demo_pos = db.get_demo_positions(limit=30)
        result = check_mental_state(db=db, demo_positions=demo_pos)
        return result
    except Exception as e:
        return {"condition": "GOOD", "warnings": [], "error": str(e)}


# ─── C-2: 自己分析ダッシュボード ────────────────────────────────

@app.get("/api/analytics")
def analytics():
    """勝率・期待値・プロフィットファクター・スコア区間別分析"""
    try:
        perf = db.get_performance_summary()
        by_sym = db.get_performance_by_symbol(limit=500)

        # スコア区間別勝率（predictions テーブルから）
        score_bands: dict = {"30-40": {}, "40-50": {}, "50-60": {}, "60+": {}}
        if db.client:
            try:
                r = db.client.table("predictions")\
                    .select("score,is_correct,is_scored")\
                    .eq("is_scored", True).limit(500).execute()
                for row in (r.data or []):
                    s = abs(float(row.get("score", 0)))
                    band = "60+" if s >= 60 else "50-60" if s >= 50 else "40-50" if s >= 40 else "30-40"
                    if band not in score_bands:
                        score_bands[band] = {}
                    b = score_bands[band]
                    b["total"] = b.get("total", 0) + 1
                    if row.get("is_correct"):
                        b["wins"] = b.get("wins", 0) + 1
                for band, b in score_bands.items():
                    t = b.get("total", 0)
                    w = b.get("wins", 0)
                    b["win_rate"] = round(w / t * 100, 1) if t > 0 else None
            except Exception: pass

        # 期待値
        wr = perf.get("win_rate", 0) / 100
        avg_win_pips  = perf.get("avg_win_pips", 15)
        avg_loss_pips = perf.get("avg_loss_pips", 8)
        expected_value = round(wr * avg_win_pips - (1 - wr) * avg_loss_pips, 2)

        score_bands_list = [
            {"band": band, **data}
            for band, data in score_bands.items()
            if data
        ]

        return {
            "summary": perf,
            "by_symbol": by_sym,
            "score_bands": score_bands_list,
            "expected_value": expected_value,
            "ts": int(time.time()),
        }
    except Exception as e:
        return {"score_bands": [], "by_session": {}, "error": str(e)}


# ─── A-7: 保有ポジション継続判断 ────────────────────────────────

class PositionCheckRequest(BaseModel):
    symbol: str
    direction: str
    entry_price: float
    lot: float = 0.1
    entry_time: str = ""

@app.post("/api/position/check")
def position_check(req: PositionCheckRequest):
    """保有中ポジションの HOLD / TAKE_PROFIT / MOVE_SL / EXIT_NOW を判定"""
    try:
        mapping = {
            "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
            "JP225": "^N225", "XAGUSD": "SI=F", "AUDJPY": "AUDJPY=X",
            "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
        }
        ticker = mapping.get(req.symbol, req.symbol)
        cur = price_cache.get(ticker, 0)
        if not cur:
            return {"judgment": "HOLD", "reason": "価格取得中"}

        es = system_state.get(ticker, {}).get("_engine_signals") or {}
        tf_state = system_state.get(ticker, {}).get(ANALYSIS_TF, {})
        direction = req.direction.upper()
        tp1 = tf_state.get("tp1", 0)
        sl  = tf_state.get("sl", 0)
        is_range = tf_state.get("is_range", False)
        ai_dir   = tf_state.get("direction", "WAIT")
        entry    = req.entry_price

        # TP/SL到達チェック
        if direction == "BUY":
            pips_float = (cur - entry) * (100 if "JPY" in req.symbol or "GOLD" in req.symbol else 10000)
            if tp1 and cur >= tp1:
                return {"judgment": "TAKE_PROFIT", "reason": f"TP1到達 ({cur:.3f})", "cur_price": cur, "pips": round(pips_float, 1)}
            if sl and cur <= sl:
                return {"judgment": "EXIT_NOW", "reason": f"SL到達 ({cur:.3f})", "cur_price": cur, "pips": round(pips_float, 1)}
            if ai_dir == "SELL":
                return {"judgment": "EXIT_NOW", "reason": "逆方向シグナル発生（SELL）", "cur_price": cur, "pips": round(pips_float, 1)}
        elif direction == "SELL":
            pips_float = (entry - cur) * (100 if "JPY" in req.symbol or "GOLD" in req.symbol else 10000)
            if tp1 and cur <= tp1:
                return {"judgment": "TAKE_PROFIT", "reason": f"TP1到達 ({cur:.3f})", "cur_price": cur, "pips": round(pips_float, 1)}
            if sl and cur >= sl:
                return {"judgment": "EXIT_NOW", "reason": f"SL到達 ({cur:.3f})", "cur_price": cur, "pips": round(pips_float, 1)}
            if ai_dir == "BUY":
                return {"judgment": "EXIT_NOW", "reason": "逆方向シグナル発生（BUY）", "cur_price": cur, "pips": round(pips_float, 1)}

        if is_range:
            return {"judgment": "EXIT_NOW", "reason": "レンジ転換 — 決済推奨", "cur_price": cur}

        return {"judgment": "HOLD", "reason": "トレンド継続中", "cur_price": cur}
    except Exception as e:
        return {"judgment": "HOLD", "reason": f"判定エラー: {e}"}


# ─── C-5: 週次・月次サマリー ────────────────────────────────────

@app.get("/api/summary/weekly")
def weekly_summary():
    try:
        from datetime import timedelta
        one_week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        data: dict = {}
        if db.client:
            r = db.client.table("performance_log")\
                .select("outcome,pips_result,symbol,direction,rr_achieved")\
                .gt("closed_at", one_week_ago)\
                .neq("outcome", "PENDING").execute()
            rows = r.data or []
            total = len(rows)
            wins  = sum(1 for r2 in rows if r2.get("outcome") == "WIN")
            pips  = sum(float(r2.get("pips_result") or 0) for r2 in rows)
            rrs   = [float(r2.get("rr_achieved") or 0) for r2 in rows if r2.get("rr_achieved")]
            data = {
                "period": "weekly",
                "total": total,
                "wins": wins,
                "win_rate": round(wins / total * 100, 1) if total else 0,
                "total_pips": round(pips, 1),
                "avg_rr": round(sum(rrs)/len(rrs), 2) if rrs else 0,
            }
        return data
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/summary/monthly")
def monthly_summary():
    try:
        from datetime import timedelta
        one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        data: dict = {}
        if db.client:
            r = db.client.table("performance_log")\
                .select("outcome,pips_result,symbol,direction,rr_achieved")\
                .gt("closed_at", one_month_ago)\
                .neq("outcome", "PENDING").execute()
            rows = r.data or []
            total = len(rows)
            wins  = sum(1 for r2 in rows if r2.get("outcome") == "WIN")
            pips  = sum(float(r2.get("pips_result") or 0) for r2 in rows)
            rrs   = [float(r2.get("rr_achieved") or 0) for r2 in rows if r2.get("rr_achieved")]
            data = {
                "period": "monthly",
                "total": total,
                "wins": wins,
                "win_rate": round(wins / total * 100, 1) if total else 0,
                "total_pips": round(pips, 1),
                "avg_rr": round(sum(rrs)/len(rrs), 2) if rrs else 0,
            }
        return data
    except Exception as e:
        return {"error": str(e)}
