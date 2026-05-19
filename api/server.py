"""
ONO Estimator v8.0 — リアルタイムFX + リスク管理 + 相関ガード版
- OandaFetcher: FXペアをリアルタイム取得 (15分遅延解消)
- SessionGuard: ロンドン/NYセッションのみトレード許可
- RiskCalculator: 1%リスク固定ロットサイズ計算
- CorrelationGuard: 相関ペア二重エントリー防止
- BacktesterV2: /api/backtest/{symbol} でウォークフォワード検証
"""
import asyncio
import json
import logging
import os
import time
import traceback
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.oanda_fetcher import OandaFetcher
from ono_estimator.core.database import SupabaseClient
from ono_estimator.core.notifier import Notifier
from ono_estimator.core.demo_trader import DemoTrader
from ono_estimator.core.reasoning_engine import ReasoningEngine
from ono_estimator.core.funda_engine import FundaEngine
from ono_estimator.core.breakout_detector import BreakoutDetector
from ono_estimator.core.session_guard import is_tradeable
from ono_estimator.core.risk_calculator import RiskCalculator
from ono_estimator.core.correlation_guard import CorrelationGuard
from ono_estimator.core.backtester_v2 import BacktesterV2
from ono_estimator.core.scanner_config import SCAN_SYMBOLS, SYMBOL_DISPLAY
from ono_estimator.indicators.chart_patterns import ChartPatterns

# ─── チートシグナル スキャナー ──────────────────────────────────────
try:
    import sys as _sys
    from pathlib import Path as _Path
    _ono_root = _Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(_ono_root))
    _sys.path.insert(0, str(_ono_root / "fx_analysis"))
    from cheat_signal_runner import run_cheat_scan as _run_cheat_scan
    _cheat_available = True
    logger.info("[Startup] チートシグナル スキャナー ロード完了")
except Exception as _ce:
    _cheat_available = False
    logger.warning(f"[Startup] チートシグナル スキャナー unavailable: {_ce}")

# ─── App ──────────────────────────────────────────────────────────
app = FastAPI(title="ONO Estimator v8.0", version="8.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── シングルトン ──────────────────────────────────────────────────
_fetcher   = HybridDataFetcher()
_oanda     = OandaFetcher()
_db        = SupabaseClient()
_notifier  = Notifier(db=_db)
_demo      = DemoTrader(db=_db)
_engine    = ReasoningEngine()
_funda     = FundaEngine()
_breakout  = BreakoutDetector()
_risk      = RiskCalculator()
_corr      = CorrelationGuard()
_bt        = BacktesterV2()

# ─── インメモリ状態 ───────────────────────────────────────────────
_latest_signals: list = []
_price_cache:    dict = {}
_scan_running:   bool = False
_last_scan_at:   Optional[str] = None

# E-5: シグナルキャッシュファイル — 再起動後の空シグナル問題を防ぐ
_SIGNALS_CACHE_FILE = "/tmp/ono_signals_cache.json"
_SIGNALS_CACHE_TTL  = 1800  # 30分以内のキャッシュのみ復元


def _save_signals_cache(signals: list, scanned_at: str) -> None:
    try:
        with open(_SIGNALS_CACHE_FILE, "w") as f:
            json.dump({"signals": signals, "scanned_at": scanned_at, "ts": time.time()}, f)
    except Exception:
        pass


def _load_signals_cache() -> tuple:
    try:
        with open(_SIGNALS_CACHE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) < _SIGNALS_CACHE_TTL:
            return data.get("signals", []), data.get("scanned_at")
    except Exception:
        pass
    return [], None

# ─── サーキットブレーカー ─────────────────────────────────────────
_daily_loss_count: int = 0          # 当日の連続損失カウント
_circuit_open:     bool = False     # True = エントリー全停止
_circuit_date:     str = ""         # サーキットがリセットされた日付
DAILY_LOSS_LIMIT   = int(os.environ.get("DAILY_LOSS_LIMIT", "3"))  # 3連敗でCB発動


def _check_circuit_breaker() -> bool:
    """当日の損失件数がDailyLossLimitに達していればTrueを返す（エントリー禁止）"""
    global _daily_loss_count, _circuit_open, _circuit_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _circuit_date != today:
        _daily_loss_count = 0
        _circuit_open = False
        _circuit_date = today
    return _circuit_open


def notify_loss_for_circuit(symbol: str) -> None:
    """損失決済時にサーキットブレーカーカウンターを更新する。DemoTraderから呼ぶ。"""
    global _daily_loss_count, _circuit_open
    _daily_loss_count += 1
    if _daily_loss_count >= DAILY_LOSS_LIMIT and not _circuit_open:
        _circuit_open = True
        logger.error(f"[CircuitBreaker] 本日{_daily_loss_count}連敗 — 新規エントリー停止 (DAILY_LOSS_LIMIT={DAILY_LOSS_LIMIT})")
        _notifier.send_alert(f"サーキットブレーカー発動: 本日{_daily_loss_count}連敗。本日の新規エントリーを停止します。")


SCAN_INTERVAL_SEC    = 300   # 5分ごと自動スキャン
ENTRY_MIN_CONFIDENCE = {"HIGH", "MEDIUM"}

# ─── ヘルス ──────────────────────────────────────────────────────
@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    sigs   = _latest_signals
    active = [s for s in sigs if s.get("direction") != "WAIT"]
    stream_active = getattr(_oanda, "_stream_running", False) and bool(getattr(_oanda, "_live_prices", {}))
    return {
        "status":      "ok",
        "version":     "8.0.0",
        "last_scan":   _last_scan_at,
        "oanda_ready": _oanda.is_configured,
        "oanda_streaming": stream_active,
        "oanda_live_prices": len(getattr(_oanda, "_live_prices", {})),
        "scan": {
            "total_symbols":    len(sigs),
            "active_signals":   len(active),
            "high":             sum(1 for s in active if s.get("confidence") == "HIGH"),
            "medium":           sum(1 for s in active if s.get("confidence") == "MEDIUM"),
            "breakouts":        sum(1 for s in sigs if s.get("breakout_signal")),
            "demo_opened_this_scan": sum(1 for s in sigs if s.get("demo_opened")),
        },
        "positions": {
            "open":    len(_demo.get_open_positions()),
            "symbols": list(_demo.get_open_positions().keys()),
            "corr_guard": _corr.open_positions,
        },
    }

# ─── OANDA 接続確認 ──────────────────────────────────────────────
@app.get("/api/oanda/status")
async def oanda_status():
    """OANDA APIの接続状態・口座残高・ストリーミング状態を返す。
    OANDA_API_KEY / OANDA_ACCOUNT_ID 設定直後の動作確認用。"""
    if not _oanda.is_configured:
        return {
            "configured": False,
            "error": "OANDA_API_KEY または OANDA_ACCOUNT_ID が未設定。.env を確認してください。",
        }
    try:
        balance = await asyncio.to_thread(_oanda.get_account_balance)
    except Exception as e:
        balance = None
        balance_error = str(e)
    else:
        balance_error = None

    live_prices = {}
    for sym in ["USDJPY=X", "EURUSD=X", "GC=F"]:
        p = _oanda.get_stream_price(sym) or await asyncio.to_thread(_oanda.get_live_price, sym)
        if p:
            live_prices[sym] = round(p, 5)

    stream_syms = list(getattr(_oanda, "_live_prices", {}).keys())
    return {
        "configured":   True,
        "practice_mode": os.environ.get("OANDA_PRACTICE", "false").lower() == "true",
        "balance":      balance,
        "balance_error": balance_error,
        "streaming": {
            "active":  getattr(_oanda, "_stream_running", False),
            "symbols": stream_syms,
            "tick_count": len(stream_syms),
        },
        "sample_prices": live_prices,
    }

# ─── マクロ情報 ───────────────────────────────────────────────────
@app.get("/api/macro")
def get_macro():
    ctx = _funda.get_macro()
    return {
        "usd_bias":           ctx.usd_bias,
        "risk_sentiment":     ctx.risk_sentiment,
        "dxy_trend":          ctx.dxy_trend,
        "dxy_value":          ctx.dxy_value,
        "vix":                ctx.vix,
        "vix_level":          ctx.vix_level,
        "yield_10y":          ctx.yield_10y,
        "yield_curve":        ctx.yield_curve,
        "ff_rate":            ctx.ff_rate,
        "high_impact_events": ctx.high_impact_events,
        "summary":            ctx.summary,
        "updated_at":         datetime.fromtimestamp(ctx.updated_at).isoformat() if ctx.updated_at else None,
    }

# ─── シグナル ─────────────────────────────────────────────────────
@app.get("/api/signals")
def get_signals(limit: int = 30):
    return {"signals": _latest_signals[:limit], "scanned_at": _last_scan_at}

# ─── デモポジション ───────────────────────────────────────────────
@app.get("/api/demo/positions")
def get_demo_positions():
    return {"positions": list(_demo.get_open_positions().values())}

@app.get("/api/demo/history")
def get_demo_history(limit: int = 50):
    return {"history": _db.get_demo_positions(limit)}

# ─── パフォーマンス ───────────────────────────────────────────────
@app.get("/api/performance")
def get_performance():
    return _db.get_performance_summary()

# ─── バックテストWR vs 実WR 乖離レポート (L-4) ──────────────────
@app.get("/api/performance/compare")
async def compare_bt_vs_live():
    """バックテスト勝率と実際のデモ勝率を銘柄ごとに比較し、乖離を返す。"""
    live_summary = _db.get_performance_summary()
    live_by_sym: dict = live_summary.get("by_symbol", {})

    # 主要シンボルだけバックテストを実行（重い処理なのでキャッシュ相当の上位5銘柄のみ）
    bt_targets = [s for s in SCAN_SYMBOLS if _oanda.supports(s)][:5]

    async def _run_one(sym: str):
        try:
            df_1h = await asyncio.to_thread(_fetch_ohlcv, sym, "1h")
            df_4h = await asyncio.to_thread(_fetch_ohlcv, sym, "4h")
            if df_1h is None or df_1h.empty:
                return sym, None
            res = await asyncio.to_thread(_bt.run, sym, df_1h, df_4h)
            return sym, res.summary()
        except Exception:
            return sym, None

    bt_results = await asyncio.gather(*[_run_one(s) for s in bt_targets])

    comparison = []
    for sym, bt in bt_results:
        live = live_by_sym.get(sym, {})
        live_wr = live.get("win_rate")
        bt_wr   = bt.get("win_rate") if bt else None
        gap     = round(bt_wr - live_wr, 1) if (bt_wr is not None and live_wr is not None) else None
        comparison.append({
            "symbol":       sym,
            "bt_win_rate":  bt_wr,
            "live_win_rate": live_wr,
            "gap":          gap,
            "bt_trades":    bt.get("total") if bt else None,
            "live_trades":  live.get("total"),
            "note": (
                "乖離大（バックテスト楽観的）" if gap and gap > 15
                else "乖離小（良好）" if gap is not None
                else "データ不足"
            ),
        })

    return {
        "comparison": comparison,
        "live_overall_win_rate": live_summary.get("win_rate"),
        "live_total_trades":     live_summary.get("total_trades"),
    }


# ─── バックテスト ─────────────────────────────────────────────────
@app.get("/api/backtest/{symbol}")
async def run_backtest(symbol: str):
    """
    指定シンボルのウォークフォワードバックテスト。
    1h / 4h / 1d データを使い、過去シグナルを再生して統計を返す。
    """
    def _fetch_and_run():
        df_1h = _fetch_ohlcv(symbol, "1h")
        df_4h = _fetch_ohlcv(symbol, "4h")
        df_1d = _fetch_ohlcv(symbol, "1d")

        if df_1h is None or df_1h.empty:
            return {"error": f"{symbol}: 1hデータ取得失敗"}

        result = _bt.run(symbol, df_1h, df_4h, df_1d)
        return result.summary()

    try:
        summary = await asyncio.to_thread(_fetch_and_run)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── 手動スキャン ─────────────────────────────────────────────────
@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    if _scan_running:
        return {"status": "already_running"}
    background_tasks.add_task(_run_scan)
    return {"status": "started"}


@app.get("/api/dictionary")
def get_dictionary():
    """FX トレード辞典（fx_analysis/FX_トレード辞典.md）を構造化して返す"""
    import re
    from pathlib import Path as _P
    _ono = _P(__file__).resolve().parent.parent
    paths = [
        _ono / "fx_analysis" / "FX_トレード辞典.md",
        _ono / "FX_トレード辞典.md",
    ]
    content = None
    for p in paths:
        if p.exists():
            content = p.read_text(encoding="utf-8")
            break
    if content is None:
        return {"sections": [], "error": "辞典ファイルが見つかりません"}

    def _parse_block(title: str, body: str) -> dict:
        wr_matches = re.findall(r'(\d{2,3}\.\d)%', body)
        win_rate = max((float(w) for w in wr_matches), default=None)
        ev_m = re.findall(r'期待値[^\n]*?([+\-]?\d+\.?\d*(?:pips|\$|ドル))', body)
        ev = ev_m[0] if ev_m else None
        tags: list[str] = []
        for pair in ["XAUUSD", "USDJPY", "EURUSD", "GBPUSD", "EURJPY"]:
            if pair in body: tags.append(pair)
        for tf in ["5m", "15m", "30m", "1h", "4h", "1d"]:
            if tf in body: tags.append(tf)
        for kw in ["買い", "売り", "反転", "ブレイク", "ダイバージェンス", "MTF", "スキャルピング"]:
            if kw in body: tags.append(kw)
        return {
            "title": title, "body": body,
            "win_rate": win_rate, "ev": ev,
            "tags": list(dict.fromkeys(tags)),
        }

    sections = []
    current_section = ""

    # Split entire content into heading blocks (## and ###)
    # Strategy: split by any heading line, keep heading with its body
    blocks = re.split(r'\n(?=#{2,3} )', content)
    for block in blocks:
        m2 = re.match(r'^## (.+)', block)
        m3 = re.match(r'^### (.+)', block)
        if m2:
            title = m2.group(1).strip()
            if "目次" in title:
                continue
            body = "\n".join(block.split("\n")[1:]).strip()
            current_section = title
            # Only add ## sections that have no ### children (standalone sections)
            # Check by seeing if body itself has substantial content without ###
            if "###" not in body:
                sections.append(_parse_block(title, body))
        elif m3:
            title = m3.group(1).strip()
            body = "\n".join(block.split("\n")[1:]).strip()
            entry = _parse_block(title, body)
            entry["section"] = current_section
            sections.append(entry)

    return {"sections": sections, "total": len(sections)}

# ─── データ取得ヘルパー ────────────────────────────────────────────
def _fetch_ohlcv(symbol: str, tf: str):
    """FXペアはOanda、その他はHybridFetcherで取得する"""
    if _oanda.is_configured and _oanda.supports(symbol):
        df = _oanda.fetch_full_ohlcv(symbol, tf)
        if df is not None and not df.empty:
            return df
    return _fetcher.fetch_full_ohlcv(symbol, tf)

# ─── スキャンロジック ─────────────────────────────────────────────
async def _run_scan():
    global _scan_running, _last_scan_at, _latest_signals, _price_cache

    if _scan_running:
        return
    _scan_running = True
    logger.info(f"[Scan] Start @ {datetime.now().strftime('%H:%M:%S')}")

    # マクロコンテキストをスキャン開始時に1回取得（全銘柄共通）
    try:
        macro = await asyncio.to_thread(_funda.get_macro)
    except Exception as e:
        logger.warning(f"[Scan] Macro fetch error: {e}")
        from ono_estimator.core.funda_engine import MacroContext
        macro = MacroContext()

    # 口座残高取得してRiskCalculatorへ反映
    try:
        balance = await asyncio.to_thread(_oanda.get_account_balance)
        if balance:
            _risk.set_balance(balance)
    except Exception:
        pass

    # 全シンボルを並列分析（sequential → asyncio.gather で高速化）
    async def _analyze_one(sym: str):
        try:
            res = await asyncio.to_thread(_analyze_symbol, sym, macro)
            return res
        except Exception as e:
            logger.error(f"[Scan] {sym} error: {e}", exc_info=True)
            return None

    results = await asyncio.gather(*[_analyze_one(sym) for sym in SCAN_SYMBOLS])
    signals = []
    for sym, result in zip(SCAN_SYMBOLS, results):
        if result:
            signals.append(result)
            _price_cache[sym] = result.get("price", 0)

    # HIGH/MEDIUM + ブレイクアウトシグナルを優先
    conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    signals.sort(key=lambda x: (
        x["direction"] == "WAIT",
        not x.get("breakout_signal"),
        conf_order.get(x["confidence"], 9),
        -x.get("macro_score", 0),
    ))

    _latest_signals = signals
    _last_scan_at   = datetime.now().isoformat()
    _save_signals_cache(signals, _last_scan_at)

    # デモポジション TP/SL 確認 + 相関ガード同期 + サーキットブレーカー更新
    positions_before = set(_demo.get_open_positions().keys())
    closed_results = _demo.check_and_close(_price_cache, _notifier)
    for sym in positions_before - set(_demo.get_open_positions().keys()):
        _corr.register_close(sym)
        # 損失決済があればCBカウンターを増やす
        if isinstance(closed_results, dict) and closed_results.get(sym) == "LOSS":
            notify_loss_for_circuit(sym)

    _scan_running = False
    active = sum(1 for s in signals if s["direction"] != "WAIT")
    bo     = sum(1 for s in signals if s.get("breakout_signal"))
    logger.info(f"[Scan] Done — {len(signals)} symbols | {active} signals | {bo} breakouts")


def _analyze_symbol(symbol: str, macro) -> Optional[dict]:
    """1銘柄の完全分析（テクニカル + ファンダ + ブレイクアウト + パターン）"""

    # ── セッションフィルター ────────────────────────────────────
    tradeable, session_block = is_tradeable(symbol)
    if not tradeable:
        return None   # 流動性の低い時間帯はスキップ

    # ── データ取得 ──────────────────────────────────────────────
    timeframes = ["1m", "5m", "15m", "1h", "4h"]
    df_store = {}
    for tf in timeframes:
        df = _fetch_ohlcv(symbol, tf)
        if df is not None and not df.empty:
            df_store[tf] = df

    if not df_store:
        return None

    ref_df = df_store.get("5m") or df_store.get("1m") or next(iter(df_store.values()))

    # リアルタイム価格: ストリーミング > REST poll > OHLCV終値の優先順
    live_price = None
    if _oanda.is_configured and _oanda.supports(symbol):
        live_price = _oanda.get_stream_price(symbol) or _oanda.get_live_price(symbol)
    price = live_price if live_price else float(ref_df["close"].iloc[-1])

    # ── 4ステップ ReasoningEngine ──────────────────────────────
    thinking = _engine.think(df_store, symbol)

    # ── チャートパターン（1h足で検出） ────────────────────────
    patterns: list = []
    df_1h = df_store.get("1h") or df_store.get("4h")
    if df_1h is not None and len(df_1h) >= 30:
        try:
            patterns = ChartPatterns.detect_all(df_1h)
        except Exception:
            pass

    # ── ブレイクアウト検出（1h / 4h） ─────────────────────────
    breakout_res    = None
    breakout_signal = False
    bo_sl = bo_tp   = 0.0
    bo_reason       = ""

    for tf_key in ("1h", "4h"):
        df_bo = df_store.get(tf_key)
        if df_bo is not None and len(df_bo) >= 30:
            try:
                bo = _breakout.analyze(df_bo)
                if bo.has_signal:
                    breakout_res    = bo
                    breakout_signal = True
                    bo_sl           = bo.suggested_sl
                    bo_tp           = bo.suggested_tp
                    bo_reason       = bo.entry_reason
                    break
            except Exception:
                pass

    # ── マクロフィルター ───────────────────────────────────────
    macro_score = macro.macro_score_for(symbol, thinking.entry_decision)
    event_risk  = macro.has_event_risk()
    event_names = [e["title"] for e in macro.high_impact_events[:2]]

    # ── シグナル組み立て ───────────────────────────────────────
    final_direction = thinking.entry_decision
    final_sl        = thinking.sl_hint
    final_tp        = thinking.tp_hint
    final_reason    = thinking.entry_reason
    final_conf      = thinking.confidence
    conflicts       = list(thinking.conflict_flags)

    if breakout_signal and breakout_res:
        if thinking.entry_decision == breakout_res.entry_signal:
            final_conf = "HIGH"
        elif thinking.entry_decision == "WAIT":
            final_direction = breakout_res.entry_signal
            final_conf      = "MEDIUM"
            final_sl        = bo_sl
            final_tp        = bo_tp
            final_reason    = bo_reason
            # RANGE・ステージ系のみクリア。セッション/200MA/RR等の物理ブロックは残す
            _range_kw = ("レンジ", "ステージ", "フラクタル", "大循環", "LS")
            conflicts = [c for c in conflicts if not any(k in c for k in _range_kw)]
        elif breakout_res.entry_signal not in ("WAIT", "NONE", "") and thinking.entry_decision != "WAIT":
            # BO方向とReasoningが真逆 → 矛盾フラグ追加
            if breakout_res.entry_signal != thinking.entry_decision:
                conflicts.append(f"BO方向矛盾({breakout_res.entry_signal}↔{thinking.entry_decision})")

    # マクロが逆風 (-2) かつ重要指標前はWAITに落とす
    if macro_score <= -2 and event_risk:
        conflicts.append(f"マクロ逆風+重要指標前({','.join(event_names[:1])})")
        final_direction = "WAIT"

    # F-5: マクロデータ取得失敗時は新規エントリーを抑制（macro_score=0は誤魔化し）
    if not macro.data_available and final_direction != "WAIT":
        conflicts.append("マクロデータ未取得（API障害）")

    # ── ロットサイズ計算 (1%リスク) ───────────────────────────
    lot = 0.01
    if final_direction != "WAIT" and final_sl > 0:
        lot = _risk.calc_lot(symbol=symbol, entry=price, sl=final_sl)

    signal = {
        "symbol":         symbol,
        "display":        SYMBOL_DISPLAY.get(symbol, symbol),
        "price":          round(price, 5),
        "direction":      final_direction,
        "confidence":     final_conf,
        "entry":          round(price, 5),
        "sl":             round(final_sl, 5) if final_sl else 0,
        "tp":             round(final_tp, 5) if final_tp else 0,
        "lot":            lot,
        "reason":         final_reason,
        "conflicts":      conflicts,
        "upper_trend":    thinking.upper.trend,
        "stage":          thinking.upper.stage,
        "pa_signal":      thinking.trigger.pa_signal,
        "macd_signal":    thinking.trigger.macd_signal,
        "rsi_signal":     thinking.trigger.rsi_signal,
        "patterns":       patterns,
        "breakout_signal":breakout_signal,
        "breakout": {
            "direction":  breakout_res.breakout          if breakout_res else "NONE",
            "confirmed":  breakout_res.breakout_confirmed if breakout_res else False,
            "in_range":   breakout_res.in_range           if breakout_res else False,
            "range_high": breakout_res.range_high         if breakout_res else 0,
            "range_low":  breakout_res.range_low          if breakout_res else 0,
            "retest":     breakout_res.retest             if breakout_res else False,
            "reason":     bo_reason,
        } if breakout_res else None,
        "macro": {
            "score":      macro_score,
            "usd_bias":   macro.usd_bias,
            "sentiment":  macro.risk_sentiment,
            "vix":        macro.vix,
            "dxy_trend":  macro.dxy_trend,
            "summary":    macro.summary,
            "event_risk": event_risk,
            "events":     event_names,
        },
        "scanned_at":     datetime.now().isoformat(),
    }

    # ── デモエントリー判定 ────────────────────────────────────
    circuit_blocked = _check_circuit_breaker()
    if circuit_blocked:
        conflicts.append(f"サーキットブレーカー発動（本日{_daily_loss_count}連敗）")

    should_enter = (
        final_direction != "WAIT"
        and final_conf in ENTRY_MIN_CONFIDENCE
        and final_sl > 0
        and final_tp > 0
        and not conflicts
        and not event_risk
        and macro_score >= 0
        and not circuit_blocked
    )

    if should_enter:
        # H-6: check_and_register でチェックと登録をアトミックに実行（並列スキャン race condition 防止）
        corr_ok, corr_block = _corr.check_and_register(symbol, final_direction)
        if not corr_ok:
            signal["corr_block"] = corr_block
            return signal

        opened = _demo.open_position(
            sym=symbol,
            direction=final_direction,
            entry=price,
            tp=final_tp,
            sl=final_sl,
            reason=f"[MacroScore:{macro_score:+d}] {final_reason}",
            lot=lot,
            confidence=final_conf,
        )
        if not opened:
            # DemoTrader が重複検出した場合は相関ガード登録を取り消す
            _corr.register_close(symbol)
        else:
            pattern_str = " · ".join(patterns[:2]) if patterns else ""
            bo_str = f"⚡BO:{breakout_res.breakout}" if breakout_signal and breakout_res else ""
            extra  = " | ".join(filter(None, [pattern_str, bo_str]))

            _notifier.send_signal(
                symbol=symbol,
                direction=final_direction,
                confidence=final_conf,
                entry=price,
                sl=final_sl,
                tp=final_tp,
                reason=f"{final_reason}{(' | ' + extra) if extra else ''}",
                macro_summary=macro.summary,
            )
            signal["demo_opened"] = True
            signal["lot"] = lot

    return signal


# ─── チートシグナル 4分周期ループ ────────────────────────────────────
async def _cheat_signal_loop():
    await asyncio.sleep(120)   # 起動後2分待って初回スキャン
    while True:
        start = time.time()
        try:
            loop = asyncio.get_event_loop()
            fired = await loop.run_in_executor(None, _run_cheat_scan)
            if fired:
                logger.info(f"[CheatSignal] {len(fired)}件のシグナルを通知")
            else:
                logger.debug("[CheatSignal] 条件を満たすシグナルなし")
        except Exception as e:
            logger.error(f"[CheatSignal] エラー: {e}", exc_info=True)
        await asyncio.sleep(max(10, 240 - (time.time() - start)))


# ─── 自動スキャンループ ───────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global _latest_signals, _last_scan_at
    # E-5: キャッシュからシグナルを復元（再起動直後の空シグナルを防ぐ）
    cached_sigs, cached_at = _load_signals_cache()
    if cached_sigs:
        _latest_signals = cached_sigs
        _last_scan_at   = cached_at
        logger.info(f"[Startup] シグナルキャッシュ復元: {len(cached_sigs)}件 (at {cached_at})")

    # ── DBからOPENポジションを復元 (再起動時の状態ロスを防ぐ) ──
    try:
        open_rows = _db.get_open_demo_positions()
        for row in open_rows:
            sym       = row.get("symbol")
            direction = row.get("direction")
            if sym and direction and sym not in _demo.open_positions:
                _demo.open_positions[sym] = row
                _corr.register_open(sym, direction)
        if open_rows:
            logger.info(f"[Startup] {len(open_rows)} OPEN positions restored from DB")
    except Exception as e:
        logger.error(f"[Startup] Position restore error: {e}")

    # OANDAストリーミング開始（FXペア + ゴールドをティック受信）
    oanda_stream_syms = [s for s in SCAN_SYMBOLS if _oanda.supports(s)]
    if oanda_stream_syms and _oanda.is_configured:
        _oanda.start_price_stream(oanda_stream_syms)
        logger.info(f"[Startup] OANDA Streaming 開始: {len(oanda_stream_syms)}シンボル")
    elif not _oanda.is_configured:
        logger.warning("[Startup] OANDA未設定 — リアルタイムFXデータはyfinanceで代替（15分遅延）")

    asyncio.create_task(_auto_scan_loop())
    # ボラティリティ警告は無効化（通知が多すぎるため）
    # asyncio.create_task(_volatility_watch_loop())
    if _cheat_available:
        asyncio.create_task(_cheat_signal_loop())


async def _auto_scan_loop():
    await asyncio.sleep(5)
    while True:
        try:
            await _run_scan()
        except Exception as e:
            logger.error(f"[AutoScan] Error: {e}", exc_info=True)
        await asyncio.sleep(SCAN_INTERVAL_SEC)


# ─── ボラティリティ異常監視ループ (60秒周期) ─────────────────────
# ISSUES A-6/A-8: フラッシュクラッシュ・暴落の初期検知
# 1m足で直近3本の値幅がATR(14)の3倍を超えたら緊急アラートを送る
VOL_WATCH_INTERVAL  = 60    # 秒
VOL_SPIKE_THRESHOLD = 3.0   # ATR比率: これ以上で異常判定
# 監視対象シンボル（主要FXペアとゴールドのみ。全スキャン対象より絞る）
VOL_WATCH_SYMBOLS = [
    "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X",
    "EURJPY=X", "GBPJPY=X", "GC=F",
]
_vol_alerted: dict = {}   # {symbol: last_alert_ts}  重複通知防止


async def _volatility_watch_loop():
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.to_thread(_check_volatility_spikes)
        except Exception as e:
            logger.warning(f"[VolWatch] Error: {e}")
        await asyncio.sleep(VOL_WATCH_INTERVAL)


def _check_volatility_spikes():
    import time as _time
    import numpy as np

    now = _time.time()
    for symbol in VOL_WATCH_SYMBOLS:
        try:
            df1m = _fetch_ohlcv(symbol, "1m")
            if df1m is None or len(df1m) < 20:
                continue

            # ATR(14) 計算
            hi = df1m["high"].values.astype(float)
            lo = df1m["low"].values.astype(float)
            cl = df1m["close"].values.astype(float)
            tr = np.maximum(hi[1:] - lo[1:],
                 np.maximum(abs(hi[1:] - cl[:-1]),
                            abs(lo[1:] - cl[:-1])))
            atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))
            if atr <= 0:
                continue

            # 直近3本の値幅 (high - low)
            recent_range = float(df1m["high"].iloc[-3:].max() - df1m["low"].iloc[-3:].min())
            ratio = recent_range / atr

            if ratio >= VOL_SPIKE_THRESHOLD:
                # 重複アラート: 同シンボルは10分に1回まで
                last = _vol_alerted.get(symbol, 0)
                if now - last < 600:
                    continue
                _vol_alerted[symbol] = now

                direction = "急落" if float(df1m["close"].iloc[-1]) < float(df1m["open"].iloc[-3]) else "急騰"
                price = float(df1m["close"].iloc[-1])
                msg = (
                    f"ボラティリティ異常検知: {symbol}\n"
                    f"  {direction} | 直近3本レンジ={recent_range:.5f} (ATR比 {ratio:.1f}x)\n"
                    f"  現在値: {price:.5f}"
                )
                logger.warning(f"[VolWatch] {msg}")
                _notifier.send_alert(msg)
        except Exception:
            pass
