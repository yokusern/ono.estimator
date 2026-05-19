import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime

PAIR_TICKERS = {
    "USDJPY": "USDJPY=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "EURJPY": "EURJPY=X",
    "XAUUSD": "GC=F",      # CME ゴールド先物
    "USDZAR": "USDZAR=X",
}

# 1pip = この価格差
PIP_FACTORS = {
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDZAR": 0.0001,
    "XAUUSD": 0.1,
}

# yfinanceの時間足ごとの最大取得期間
_MAX_PERIOD = {
    "1m":  "7d",
    "5m":  "60d",
    "15m": "60d",
    "30m": "60d",
    "1h":  "2y",
    "4h":  "2y",
    "1d":  "10y",
}

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
_CACHE_TTL_H = 6


def pip_factor(pair: str) -> float:
    return PIP_FACTORS.get(pair.upper(), 0.0001)


def fetch(pair: str, interval: str = "1h", period: str = "2y") -> pd.DataFrame:
    """OHLCVデータ取得（6時間キャッシュ付き）。
    interval: 1m/5m/15m/30m/1h/4h/1d
    4h は 1h から自動リサンプル。短期足は期間を自動キャップ。
    """
    if interval == "4h":
        df_1h = _download(pair, "1h", _cap_period("1h", period))
        return _resample_4h(df_1h)
    return _download(pair, interval, _cap_period(interval, period))


def _cap_period(interval: str, period: str) -> str:
    """yfinanceの取得上限を超えないよう期間をキャップ"""
    max_p = _MAX_PERIOD.get(interval)
    if max_p is None:
        return period
    # 日数に変換して比較
    def to_days(p: str) -> int:
        unit = p[-1]
        val  = int(p[:-1])
        return {"d": val, "m": val * 30, "y": val * 365}.get(unit, 9999)

    if to_days(period) > to_days(max_p):
        return max_p
    return period


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.resample("4h", label="left", closed="left")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Close"])
    )


def _download(pair: str, interval: str, period: str) -> pd.DataFrame:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _CACHE_DIR / f"{pair.upper()}_{interval}_{period}.csv"

    if cache.exists():
        age_h = (datetime.now().timestamp() - cache.stat().st_mtime) / 3600
        if age_h < _CACHE_TTL_H:
            return pd.read_csv(cache, index_col=0, parse_dates=True)

    sym = PAIR_TICKERS.get(pair.upper(), pair)
    df = yf.download(sym, interval=interval, period=period, auto_adjust=True, progress=False)

    # yfinanceがMultiIndexを返すことがある
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.to_csv(cache)
    return df
