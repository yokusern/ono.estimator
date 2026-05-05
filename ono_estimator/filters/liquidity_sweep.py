"""
LiquiditySweepDetector — A-3
ローソク足データから直接 Liquidity Sweep を検出する。
スイング高値/安値を上抜け後に戻した場合をSweep確定とする。
"""
from __future__ import annotations
import pandas as pd


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> dict:
    """
    df: OHLCV DataFrame (columns: open, high, low, close)
    返り値:
      detected  : bool
      direction : "BUY" / "SELL" / "NONE"
      sweep_level: float  (スイープされたレベル価格)
      wick_ratio : float  (ヒゲ長さ / 実体長さ)
    """
    result = {"detected": False, "direction": "NONE", "sweep_level": 0.0, "wick_ratio": 0.0}

    if df is None or len(df) < lookback + 2:
        return result

    # 最新足と直前足
    cur  = df.iloc[-1]
    body = abs(float(cur["close"]) - float(cur["open"]))
    if body < 1e-9:
        return result

    # ── スイング高値/安値をlookback本から取得 ──
    window = df.iloc[-(lookback + 1):-1]   # 最新足を除く直近lookback本
    swing_high = float(window["high"].max())
    swing_low  = float(window["low"].min())

    cur_high  = float(cur["high"])
    cur_low   = float(cur["low"])
    cur_close = float(cur["close"])
    cur_open  = float(cur["open"])

    # ── 上方Sweep（SELL候補）: highがスイング高値を超え、closeが以下に戻った ──
    if cur_high > swing_high and cur_close <= swing_high:
        upper_wick = cur_high - max(cur_close, cur_open)
        if upper_wick > body * 1.5:          # ヒゲが実体の1.5倍以上
            result["detected"]    = True
            result["direction"]   = "SELL"
            result["sweep_level"] = swing_high
            result["wick_ratio"]  = round(upper_wick / body, 2)
            return result

    # ── 下方Sweep（BUY候補）: lowがスイング安値を下抜け、closeが以上に戻った ──
    if cur_low < swing_low and cur_close >= swing_low:
        lower_wick = min(cur_close, cur_open) - cur_low
        if lower_wick > body * 1.5:
            result["detected"]    = True
            result["direction"]   = "BUY"
            result["sweep_level"] = swing_low
            result["wick_ratio"]  = round(lower_wick / body, 2)
            return result

    return result
