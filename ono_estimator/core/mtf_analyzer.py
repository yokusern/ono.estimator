"""
Step A2: マルチタイムフレーム（MTF）統合
1h / 4h / 1d の3TF を分析し、一致度スコアを返す。
"""
import logging
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

TF_LIST = ["1h", "4h", "1d"]


def _detect_bias(df: pd.DataFrame) -> str:
    """RSI + MACD + EMA で方向性を判定"""
    try:
        latest = df.iloc[-1]
        rsi = float(latest.get("rsi", 50))
        macd = float(latest.get("macd", 0))
        ema_fast = float(latest.get("ema_fast", 0))
        ema_slow = float(latest.get("ema_slow", 0))

        signals = []
        if rsi > 55:
            signals.append("BUY")
        elif rsi < 45:
            signals.append("SELL")

        if macd > 0:
            signals.append("BUY")
        elif macd < 0:
            signals.append("SELL")

        if ema_fast > 0 and ema_slow > 0:
            if ema_fast > ema_slow:
                signals.append("BUY")
            else:
                signals.append("SELL")

        buy_count = signals.count("BUY")
        sell_count = signals.count("SELL")

        if buy_count > sell_count:
            return "BUY"
        elif sell_count > buy_count:
            return "SELL"
        return "WAIT"
    except Exception:
        return "WAIT"


def analyze_mtf(symbol: str, fetcher) -> dict:
    """
    各 TF の OHLCV を取得して方向性を判定し、一致度を返す。
    戻り値: { "1h": "BUY", "4h": "BUY", "1d": "WAIT", "agreement": 2, "strength": "NORMAL", "score_bonus": 14 }
    """
    try:
        df_base = fetcher.fetch_ohlcv(symbol, interval="1min")
        if df_base is None or df_base.empty:
            return {"agreement": 0, "strength": "WEAK", "score_bonus": 0}

        tf_biases = {}
        for tf in TF_LIST:
            try:
                df_tf = fetcher.resample_ohlcv(df_base, tf)
                df_tf = fetcher.calculate_indicators(df_tf)
                tf_biases[tf] = _detect_bias(df_tf)
            except Exception:
                tf_biases[tf] = "WAIT"

        biases = list(tf_biases.values())
        buy_count = biases.count("BUY")
        sell_count = biases.count("SELL")
        agreement = max(buy_count, sell_count)

        if agreement == 3:
            strength = "STRONG"
            score_bonus = 20
        elif agreement == 2:
            strength = "NORMAL"
            score_bonus = 14
        else:
            strength = "WEAK"
            score_bonus = 0

        return {**tf_biases, "agreement": agreement, "strength": strength, "score_bonus": score_bonus}
    except Exception as e:
        logger.warning(f"[MTF] {symbol}: {e}")
        return {"agreement": 0, "strength": "WEAK", "score_bonus": 0}
