import pandas as pd
import numpy as np


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, lo = df["Close"], df["High"], df["Low"]

    # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────────
    bb_ma = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_mid"]    = bb_ma
    df["bb_upper"]  = bb_ma + 2 * bb_std
    df["bb_lower"]  = bb_ma - 2 * bb_std
    df["bb_upper1"] = bb_ma + bb_std       # +1σ
    df["bb_lower1"] = bb_ma - bb_std       # -1σ

    # ── MACD (12, 26, 9) ─────────────────────────────────────────────────
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"]      = ema12 - ema26
    df["macd_sig"]  = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]

    # ── RSI (14) ──────────────────────────────────────────────────────────
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # ── Moving Averages ───────────────────────────────────────────────────
    df["sma20"]  = c.rolling(20).mean()
    df["sma50"]  = c.rolling(50).mean()
    df["sma200"] = c.rolling(200).mean()

    # ── Stochastic (14, 3) ────────────────────────────────────────────────
    ll14 = lo.rolling(14).min()
    hh14 = h.rolling(14).max()
    k = 100 * (c - ll14) / (hh14 - ll14).replace(0, np.nan)
    df["stoch_k"] = k
    df["stoch_d"] = k.rolling(3).mean()

    return df
