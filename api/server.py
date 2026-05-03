"""ONO Estimator Ultra v6.0 — FastAPI Server"""
import asyncio
import os
import time
import traceback
from collections import deque
from datetime import datetime, timedelta

import requests
from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from dotenv import load_dotenv

from ono_estimator.core.hybrid_fetcher import HybridDataFetcher
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
from ono_estimator.core.notifier import Notifier
from ono_estimator.core.database import SupabaseClient
from ono_estimator.core import ONOPredictionEngine
from ono_estimator.core.fred_fetcher import FredFetcher
from ono_estimator.core.event_calendar import EventCalendar
from ono_estimator.core.rate_table import rate_table
from ono_estimator.core.session_filter import get_current_session, get_session_multiplier, get_session_label
from ono_estimator.core.scanner import run_full_scan
from ono_estimator.core.market_status import get_market_status
from ono_estimator.core.market_sentiment import calc_fx_fear_greed
from ono_estimator.core.money_manager import calc_lot, simulate_balance
from ono_estimator.core.backtester import Backtester
from ono_estimator.core.trade_monitor import TradeMonitor
from ono_estimator.core.correlation_monitor import check_correlation
from ono_estimator.core.vision_analyzer import VisionAnalyzer
from ono_estimator.core.mtf_analyzer import analyze_mtf
from ono_estimator.core.cot_fetcher import fetch_cot, get_cot_score_bonus

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
CRYPTO_SYMBOLS = {"BTC-USD", "ETH-USD"}
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ono-estimator.onrender.com")
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

GEMINI_CALL_INTERVAL = 15
MAX_GEMINI_PER_MINUTE = 14  # F1: 14 RPM (安全マージン込み)

# ─── グローバルステート ──────────────────────────────────────
system_state = {
    sym: {tf: {
        "status": "Loading", "score": 0,
        "ai_text": "システム起動中...", "predicted_price": 0,
        "probability": 0, "last_updated": None,
        "direction": "WAIT", "entry": None, "tp1": None, "tp2": None, "sl": None,
        "basis": "", "confidence": "LOW", "cached": False,
        "session": "off", "session_multiplier": 1.0,
        "event_warning": False, "event_message": "",
    } for tf in TIMEFRAMES}
    for sym in SYMBOLS
}
chart_data = {sym: {tf: [] for tf in TIMEFRAMES} for sym in SYMBOLS}
price_cache = {sym: 0.0 for sym in SYMBOLS}
last_ai_analysis = {sym: 0.0 for sym in SYMBOLS}
market_overview = {"global_theme": "市場データを同期中...", "last_update_ts": 0, "mode": "Starting"}
_gemini_call_times: deque = deque(maxlen=60)
_fred_data: dict = {}
_event_risk: dict = {}
_cot_data: dict = {}

# ─── サービス初期化 ──────────────────────────────────────────
db = SupabaseClient()
fetcher = HybridDataFetcher()
engine = ONOPredictionEngine()
ai_analyzer = GeminiAnalyzer(db=db)
notifier = Notifier(db=db)
fred_fetcher = FredFetcher()
event_calendar = EventCalendar()
backtester = Backtester(db=db, price_cache=price_cache)
trade_monitor = TradeMonitor(db=db, notifier=notifier)
vision_analyzer = VisionAnalyzer()


# ─── ユーティリティ ──────────────────────────────────────────
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
    interval = 58 if is_market_open(symbol) else 3600
    return (now - last) > interval

def can_call_gemini() -> bool:
    now = time.time()
    while _gemini_call_times and now - _gemini_call_times[0] > 60:
        _gemini_call_times.popleft()
    return len(_gemini_call_times) < MAX_GEMINI_PER_MINUTE

def record_gemini_call():
    _gemini_call_times.append(time.time())


# ─── データ取得（スレッド実行） ───────────────────────────────
def _sync_fetch_and_analyze(symbol: str) -> dict:
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
        records = [{
            "time": int(idx.timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "rsi": float(row.get("rsi", 0)),
            "macd": float(row.get("macd", 0)),
        } for idx, row in df_tf.tail(100).iterrows()]
        symbol_charts[tf] = records

    # MTF 統合スコアボーナス
    try:
        mtf_result = analyze_mtf(symbol, fetcher)
    except Exception:
        mtf_result = {"agreement": 0, "strength": "WEAK", "score_bonus": 0}

    price_cache[symbol] = float(df_base.iloc[-1]["close"])
    return {
        "symbol": symbol,
        "mtf": mtf_summaries,
        "charts": symbol_charts,
        "result_obj": result,
        "mtf_alignment": mtf_result,
    }


# ─── メイン監視ループ ────────────────────────────────────────
async def estimation_loop():
    print("[Server] ONO Estimator Ultra v6.0 — Started")

    # 起動時 Supabase キャッシュをロード
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
        print(f"[Startup] Preloaded {len(history)} records")
        market_overview["mode"] = "Live"
    except Exception as e:
        print(f"[Startup] Cache preload failed (OK): {e}")

    while True:
        cycle_start = time.time()
        try:
            wday = datetime.utcnow().weekday()
            market_overview["mode"] = "Weekend" if wday >= 5 else "Weekday"

            # FRED / 金利 / イベント / COT を並列更新
            global _fred_data, _event_risk, _cot_data
            try:
                _fred_data, _, _event_risk, _cot_data = await asyncio.gather(
                    fred_fetcher.fetch_all(),
                    rate_table.refresh(),
                    event_calendar.check_upcoming_events(),
                    fetch_cot(),
                    return_exceptions=True,
                )
                if isinstance(_fred_data, Exception): _fred_data = {}
                if isinstance(_event_risk, Exception): _event_risk = {}
                if isinstance(_cot_data, Exception): _cot_data = {}
            except Exception as e:
                print(f"[FRED/Calendar/COT] Update failed: {e}")

            # 全銘柄データ取得（並列）
            tasks = [asyncio.to_thread(_sync_fetch_and_analyze, sym) for sym in SYMBOLS]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            valid_results = []
            for res in results:
                if isinstance(res, Exception) or res is None:
                    continue
                sym = res["symbol"]
                chart_data[sym] = res["charts"]
                open_status = is_market_open(sym)
                mtf_bonus = res.get("mtf_alignment", {}).get("score_bonus", 0)
                cot_bonus = get_cot_score_bonus(sym, _cot_data if isinstance(_cot_data, dict) else {})

                session = get_current_session()
                sess_mult = get_session_multiplier(sym, session)

                for tf in TIMEFRAMES:
                    if not open_status:
                        system_state[sym][tf]["status"] = "Closed"
                    elif tf in res["mtf"]:
                        raw = res["mtf"][tf].get("score", 0)
                        adjusted = int(min(100, (raw + mtf_bonus + cot_bonus) * sess_mult))
                        system_state[sym][tf].update({
                            "status": res["mtf"][tf].get("status", "Wait"),
                            "score": adjusted,
                            "session": session,
                            "session_multiplier": round(sess_mult, 2),
                        })
                valid_results.append(res)

            # 順次AI分析（スロットリング付き）
            performance_data = db.get_performance_summary()

            for res in valid_results:
                sym = res["symbol"]
                if not needs_ai_analysis(sym):
                    continue

                if not can_call_gemini():
                    wait_sec = 60 - (time.time() - _gemini_call_times[0])
                    if wait_sec > 0:
                        print(f"[RateLimiter] Waiting {wait_sec:.1f}s...")
                        await asyncio.sleep(wait_sec + 1)

                session = get_current_session()
                sess_mult = get_session_multiplier(sym, session)
                sym_event_risk = await event_calendar.check_upcoming_events(sym)

                print(f"[Gemini] {get_session_label(session)} → {sym}")
                record_gemini_call()
                ai_data = await asyncio.to_thread(
                    ai_analyzer.analyze_single,
                    sym, res, performance_data,
                    _fred_data if isinstance(_fred_data, dict) else {},
                    sym_event_risk,
                    session, sess_mult,
                )

                if ai_data and ai_data.get("ai_text"):
                    last_ai_analysis[sym] = time.time()
                    multiplier = sym_event_risk.get("score_multiplier", 1.0)
                    for tf in TIMEFRAMES:
                        raw_score = system_state[sym][tf].get("score", 0)
                        system_state[sym][tf].update({
                            "ai_text": ai_data["ai_text"],
                            "predicted_price": ai_data.get("tp1") or ai_data.get("predicted_price", 0),
                            "probability": ai_data.get("probability", 0),
                            "last_updated": datetime.now().isoformat(),
                            "score": int(raw_score * multiplier),
                            "direction": ai_data.get("direction", "WAIT"),
                            "entry": ai_data.get("entry"),
                            "tp1": ai_data.get("tp1"),
                            "tp2": ai_data.get("tp2"),
                            "sl": ai_data.get("sl"),
                            "basis": ai_data.get("basis", ""),
                            "confidence": ai_data.get("confidence", "LOW"),
                            "cached": ai_data.get("cached", False),
                            "event_warning": sym_event_risk.get("warning", False),
                            "event_message": sym_event_risk.get("message", ""),
                        })

                    try:
                        db.save_prediction({
                            "symbol": sym,
                            "status": system_state[sym]["1m"]["status"],
                            "score": system_state[sym]["1m"]["score"],
                            "ai_text": ai_data["ai_text"],
                            "predicted_price": ai_data.get("tp1") or ai_data.get("predicted_price", 0),
                            "probability": ai_data.get("probability", 0),
                            "current_price": price_cache.get(sym, 0),
                        })
                    except Exception as db_e:
                        print(f"[DB] Save error: {db_e}")

                    # TP/SL 監視登録
                    if ai_data.get("entry") and ai_data.get("tp1") and ai_data.get("sl"):
                        try:
                            trade_monitor.register_signal(
                                sym, ai_data.get("direction", "WAIT"),
                                float(ai_data["entry"]),
                                float(ai_data["tp1"]),
                                float(ai_data.get("tp2") or ai_data["tp1"]),
                                float(ai_data["sl"]),
                            )
                        except Exception:
                            pass

                    # 通知（Step 8 条件）
                    score = system_state[sym]["1m"]["score"]
                    if score >= 35 and ai_data.get("probability", 0) >= 80:
                        notifier.notify_if_needed(
                            sym, res.get("result_obj"), ai_data,
                            price_cache.get(sym, 0), session, sym_event_risk,
                        )

                    if market_overview["last_update_ts"] < time.time() - 120:
                        market_overview["global_theme"] = ai_data["ai_text"][:80] + "..."
                        market_overview["last_update_ts"] = int(time.time())
                else:
                    print(f"[Gemini] No response for {sym}")

                await asyncio.sleep(GEMINI_CALL_INTERVAL)

        except Exception as e:
            print(f"[Loop] Critical error: {e}")
            traceback.print_exc()

        elapsed = time.time() - cycle_start
        print(f"[Loop] Cycle done in {elapsed:.1f}s. Next in {max(5, 60-elapsed):.1f}s")
        await asyncio.sleep(max(5, 60 - elapsed))


async def backtest_loop():
    """6時間ごとにバックテスト実行"""
    await asyncio.sleep(60)
    while True:
        try:
            await backtester.run()
        except Exception as e:
            print(f"[Backtest] Error: {e}")
        await asyncio.sleep(21600)


async def trade_monitor_loop():
    """5分ごとに TP/SL チェック"""
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.to_thread(trade_monitor.check_signals, price_cache)
        except Exception as e:
            print(f"[TradeMonitor] Error: {e}")
        await asyncio.sleep(300)


async def scanner_loop():
    """30分ごとに全銘柄スキャン"""
    await asyncio.sleep(90)
    while True:
        try:
            await run_full_scan(fetcher=fetcher, engine=engine, db=db)
        except Exception as e:
            print(f"[Scanner] Error: {e}")
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


# ─── Startup ─────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(estimation_loop())
    asyncio.create_task(backtest_loop())
    asyncio.create_task(anti_sleep_loop())
    asyncio.create_task(trade_monitor_loop())
    asyncio.create_task(scanner_loop())


# ─── 基本エンドポイント ──────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ONO Estimator Ultra v6.0", "time": datetime.now().isoformat()}


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "version": "6.0.0",
        "mode": market_overview.get("mode", "unknown"),
        "gemini_calls_last_min": len(_gemini_call_times),
        "last_sync": market_overview["last_update_ts"],
        "uptime": int(time.time()),
    }


@app.get("/api/predict")
def get_prediction(tf: str = Query("1m", pattern="^(1m|5m|15m|1h|4h)$")):
    tf_state = {sym: states.get(tf) for sym, states in system_state.items()}
    session = get_current_session()
    return {
        "data": tf_state,
        "overview": {**market_overview, "session": session, "session_label": get_session_label(session)},
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
    try:
        return {"data": db.get_history(limit=limit)}
    except Exception:
        return {"data": []}


# ─── マクロ ──────────────────────────────────────────────────
@app.get("/api/macro")
def get_macro():
    rate_diffs = rate_table.get_all_diffs()
    return {
        "fred": _fred_data if isinstance(_fred_data, dict) else {},
        "rate_diffs": rate_diffs,
        "event_risk": _event_risk if isinstance(_event_risk, dict) else {},
        "server_time": int(time.time()),
    }


# ─── 市場ステータス・センチメント（Step 11, 13） ────────────
@app.get("/api/market/status")
def market_status():
    return get_market_status()


@app.get("/api/market/sentiment")
def market_sentiment():
    fred = _fred_data if isinstance(_fred_data, dict) else {}
    vix = (fred.get("VIXCLS") or {}).get("value")
    dxy = (fred.get("DTWEXBGS") or {}).get("diff")
    gold = (fred.get("GC=F") or {}).get("diff")
    result = calc_fx_fear_greed(vix, dxy, gold)
    return {**result, "server_time": int(time.time())}


# ─── 全銘柄サマリー（Step 12） ───────────────────────────────
@app.get("/api/overview")
def get_overview():
    symbols_data = []
    market_st = get_market_status()
    for sym, states in system_state.items():
        d = states.get("1m", {})
        symbols_data.append({
            "symbol": sym,
            "score": d.get("score", 0),
            "direction": d.get("direction", "WAIT"),
            "probability": d.get("probability", 0),
            "status": d.get("status", "Wait"),
            "session": d.get("session", "off"),
            "cached": d.get("cached", False),
            "current_price": price_cache.get(sym, 0),
        })
    return {"symbols": symbols_data, "market": market_st, "server_time": int(time.time())}


# ─── スキャナー（Step E1） ────────────────────────────────────
@app.get("/api/scan/ranking")
async def scan_ranking():
    from ono_estimator.core.scanner import _scan_cache, _scan_ts
    return {"data": _scan_cache, "scanned_at": int(_scan_ts), "server_time": int(time.time())}


@app.post("/api/scan/run")
async def scan_run():
    results = await run_full_scan(fetcher=fetcher, engine=engine, db=db)
    return {"data": results, "count": len(results)}


# ─── 優位性詳細（Step E5） ────────────────────────────────────
@app.get("/api/edge/{symbol}")
def get_edge(symbol: str):
    sym_map = {
        "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
        "JP225": "^N225", "SILVER": "SI=F", "AUDJPY": "AUDJPY=X",
        "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
    }
    ticker = sym_map.get(symbol.upper(), symbol)
    d = system_state.get(ticker, {}).get("1m", {})
    score = d.get("score", 0)
    prob = d.get("probability", 0)
    bt = backtester.get_results(30)
    bt_wr = bt.get("by_symbol", {}).get(ticker, 50.0)

    return {
        "symbol": symbol,
        "edge_score": score,
        "breakdown": {
            "ai_probability":    {"score": int(prob * 0.4), "max": 40, "value": f"{prob}%"},
            "backtest_win_rate": {"score": int(bt_wr * 0.3), "max": 30, "value": f"{bt_wr}%"},
            "volatility_fitness": {"score": 15, "max": 20, "value": "適正"},
            "mtf_alignment":     {"score": d.get("score", 0) // 10, "max": 10, "value": ""},
        },
        "best_session": d.get("session", "unknown"),
        "session_multiplier": d.get("session_multiplier", 1.0),
        "confidence": d.get("confidence", "LOW"),
        "basis": d.get("basis", ""),
        "sample_count": bt.get("total", 0),
    }


# ─── 予測チャート（Step E4） ──────────────────────────────────
@app.get("/api/forecast/{symbol}")
def get_forecast(symbol: str):
    sym_map = {
        "USDJPY": "USDJPY=X", "GOLD": "GC=F", "BTC": "BTC-USD",
        "JP225": "^N225", "SILVER": "SI=F", "AUDJPY": "AUDJPY=X",
        "EURUSD": "EURUSD=X", "EURJPY": "EURJPY=X",
    }
    ticker = sym_map.get(symbol.upper(), symbol)
    current = price_cache.get(ticker, 0)
    d = system_state.get(ticker, {}).get("1m", {})
    tp1 = d.get("tp1")
    tp2 = d.get("tp2")
    tw = d.get("time_window") or {}

    forecast_points = []
    now = datetime.now()
    if tp1:
        forecast_points.append({
            "time": (now + timedelta(minutes=30)).isoformat(),
            "price": tp1,
            "confidence_upper": tp1 * 1.002 if tp1 else None,
            "confidence_lower": tp1 * 0.998 if tp1 else None,
        })
    if tp2:
        forecast_points.append({
            "time": (now + timedelta(hours=2)).isoformat(),
            "price": tp2,
            "confidence_upper": tp2 * 1.003 if tp2 else None,
            "confidence_lower": tp2 * 0.997 if tp2 else None,
        })

    return {
        "symbol": symbol,
        "current_price": current,
        "forecast_points": forecast_points,
        "time_window": tw,
        "entry": d.get("entry"),
        "sl": d.get("sl"),
        "basis": d.get("basis", ""),
        "probability": d.get("probability", 0),
        "generated_at": d.get("last_updated") or datetime.now().isoformat(),
    }


# ─── バックテスト（Step A1, G2, G3） ─────────────────────────
@app.get("/api/backtest/results")
def backtest_results(days: int = Query(30, le=90)):
    return backtester.get_results(days)


@app.get("/api/backtest/by-symbol")
def backtest_by_symbol():
    result = backtester.get_results(30)
    return {"by_symbol": result.get("by_symbol", {}), "overall": result.get("win_rate", 0)}


@app.get("/api/backtest/export")
def backtest_export(days: int = Query(30, le=90)):
    csv_content = backtester.export_csv(days)
    filename = f"backtest_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── 資金管理（Step 9） ──────────────────────────────────────
@app.post("/api/money/calc")
def money_calc(body: dict = Body(...)):
    balance = float(body.get("balance", 1000000))
    risk_pct = float(body.get("risk_pct", 1.0))
    symbol = str(body.get("symbol", "USDJPY"))
    sl_pips = float(body.get("sl_pips", 20))
    tp_pips = float(body.get("tp_pips", sl_pips * 2))

    lot_info = calc_lot(balance, risk_pct, sl_pips, symbol)
    sim_info = simulate_balance(balance, lot_info.get("lot", 0), tp_pips, sl_pips, symbol)
    return {**lot_info, **sim_info, "symbol": symbol}


# ─── Vision 分析（Step 7） ───────────────────────────────────
@app.post("/api/vision/analyze")
async def vision_analyze(body: dict = Body(...)):
    symbol = str(body.get("symbol", "USDJPY"))
    image_b64 = str(body.get("image_base64", ""))
    if not image_b64:
        return {"error": "image_base64 is required"}
    result = await vision_analyzer.analyze_chart_image(symbol, image_b64)
    return result


# ─── デバッグ・診断 ──────────────────────────────────────────
@app.get("/api/debug/fred")
async def debug_fred():
    try:
        data = await fred_fetcher.fetch_all()
        fetched = {k: v for k, v in data.items() if v is not None}
        return {
            "status": "ok" if fetched else "no_data",
            "fred_api_key_set": bool(os.environ.get("FRED_API_KEY")),
            "fetched_count": len(fetched),
            "data": fetched,
            "prompt_preview": fred_fetcher.format_for_prompt(data),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/debug/sources")
def debug_sources():
    """データソース稼働状況を返す"""
    statuses = {}
    for sym in SYMBOLS:
        statuses[sym] = {
            "price": price_cache.get(sym, 0),
            "has_chart": bool(chart_data.get(sym, {}).get("1m")),
            "last_ai": last_ai_analysis.get(sym, 0),
        }
    return {
        "symbols": statuses,
        "fred_ok": bool(isinstance(_fred_data, dict) and _fred_data),
        "gemini_calls_last_min": len(_gemini_call_times),
        "server_time": int(time.time()),
    }
