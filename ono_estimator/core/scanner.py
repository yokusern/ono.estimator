"""
Step E1: 全銘柄スキャナー
全対象銘柄を常時スキャンし「今最も狙える銘柄」をランキング表示する。
"""
import asyncio
import time
import logging
from typing import Optional
import pandas as pd

from .scanner_config import SCAN_SYMBOLS, SYMBOL_DISPLAY
from .session_filter import get_current_session, get_session_multiplier

logger = logging.getLogger(__name__)

# 直近スキャン結果キャッシュ
_scan_cache: list = []
_scan_ts: float = 0.0


def _calc_volatility(df: pd.DataFrame) -> float:
    """直近20本のATR（ボラティリティ指標）"""
    try:
        if df is None or len(df) < 2:
            return 0.0
        returns = df["close"].pct_change().dropna().tail(20)
        return round(float(returns.std() * 100), 4)
    except Exception:
        return 0.0


def _calc_edge_score(ai_prob: int, backtest_wr: float, volatility: float, mtf_agreement: int) -> int:
    """
    優位性スコア算出:
    AI確率  40点
    バックテスト勝率 30点
    ボラティリティ適正度 20点（0.1-0.5% が適正）
    MTF一致度 10点
    """
    ai_score = int(ai_prob * 0.4)
    bt_score = int(backtest_wr * 0.3)

    if 0.05 <= volatility <= 0.6:
        vol_score = 20
    elif volatility < 0.05:
        vol_score = 5
    else:
        vol_score = 10

    mtf_score = {3: 10, 2: 7, 1: 3, 0: 0}.get(mtf_agreement, 0)
    return min(ai_score + bt_score + vol_score + mtf_score, 100)


async def run_full_scan(fetcher=None, engine=None, db=None) -> list:
    """
    全銘柄をスキャンし、優位性スコア順にソートして返す。
    fetcher: HybridDataFetcher
    engine: ONOPredictionEngine
    db: SupabaseClient
    """
    global _scan_cache, _scan_ts

    now = time.time()
    if _scan_cache and (now - _scan_ts) < 1800:
        return _scan_cache

    session = get_current_session()
    results = []

    # バックテスト勝率をDBから取得
    bt_stats = {}
    if db:
        try:
            history = db.get_history(limit=200)
            for row in history:
                sym = row.get("symbol", "")
                is_correct = row.get("is_correct")
                if is_correct is not None:
                    if sym not in bt_stats:
                        bt_stats[sym] = {"wins": 0, "total": 0}
                    bt_stats[sym]["total"] += 1
                    if is_correct:
                        bt_stats[sym]["wins"] += 1
        except Exception as e:
            logger.warning(f"[Scanner] DB stats fetch failed: {e}")

    def _scan_symbol(sym: str) -> Optional[dict]:
        try:
            if fetcher is None:
                return None
            df = fetcher.fetch_ohlcv(sym, interval="1min")
            if df is None or df.empty:
                return None
            df = fetcher.resample_ohlcv(df, "1h") if hasattr(fetcher, "resample_ohlcv") else df
            df = fetcher.calculate_indicators(df) if hasattr(fetcher, "calculate_indicators") else df

            latest = df.iloc[-1]
            rsi = float(latest.get("rsi", 50))
            macd = float(latest.get("macd", 0))

            direction = "BUY" if rsi < 50 and macd > 0 else "SELL" if rsi > 50 and macd < 0 else "WAIT"
            ai_prob = max(0, min(100, int(abs(50 - rsi) * 2)))

            bt = bt_stats.get(sym, {})
            win_rate = (bt["wins"] / bt["total"] * 100) if bt.get("total", 0) > 0 else 50.0
            volatility = _calc_volatility(df)
            session_mult = get_session_multiplier(sym, session)
            edge = int(_calc_edge_score(ai_prob, win_rate, volatility, 1) * session_mult)

            return {
                "symbol": SYMBOL_DISPLAY.get(sym, sym),
                "ticker": sym,
                "edge_score": edge,
                "direction": direction,
                "volatility": round(volatility, 4),
                "win_rate": round(win_rate, 1),
                "probability": ai_prob,
                "recommended": edge >= 70,
                "session": session,
                "session_multiplier": round(session_mult, 2),
            }
        except Exception as e:
            logger.warning(f"[Scanner] {sym} failed: {e}")
            return None

    scan_tasks = [asyncio.to_thread(_scan_symbol, sym) for sym in SCAN_SYMBOLS]
    raw_results = await asyncio.gather(*scan_tasks, return_exceptions=True)

    for r in raw_results:
        if r and not isinstance(r, Exception):
            results.append(r)

    results.sort(key=lambda x: x["edge_score"], reverse=True)
    _scan_cache = results
    _scan_ts = now
    logger.info(f"[Scanner] Full scan complete: {len(results)} symbols")
    return results
