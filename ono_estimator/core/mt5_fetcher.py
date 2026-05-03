"""
Step E2: MT5 Python API データ取得モジュール
MetaTrader5 が起動していない場合は None を返し、次のソースへフォールバックする。
"""
import logging
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.info("[MT5] MetaTrader5 library not installed — skipping")

TF_MAP = {
    "1min": 1,   # mt5.TIMEFRAME_M1
    "5min": 5,   # mt5.TIMEFRAME_M5
    "15min": 15, # mt5.TIMEFRAME_M15
    "1h": 16385, # mt5.TIMEFRAME_H1
    "4h": 16388, # mt5.TIMEFRAME_H4
    "1d": 16408, # mt5.TIMEFRAME_D1
}

MT5_SYMBOLS = {
    "USDJPY=X": "USDJPY", "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD",
    "AUDUSD=X": "AUDUSD", "USDCAD=X": "USDCAD", "NZDUSD=X": "NZDUSD",
    "EURJPY=X": "EURJPY", "GBPJPY=X": "GBPJPY", "AUDJPY=X": "AUDJPY",
    "GC=F": "XAUUSD", "SI=F": "XAGUSD", "CL=F": "USOIL.cash",
    "^N225": "JP225", "^DJI": "US30", "^GSPC": "US500", "^NDX": "USTEC",
    "BTC-USD": "BTCUSD", "ETH-USD": "ETHUSD",
}


def fetch_ohlcv(symbol: str, timeframe: str = "1h", bars: int = 500) -> Optional[pd.DataFrame]:
    """
    MT5 から OHLCV データを取得して DataFrame で返す。
    MT5 が起動していない・接続できない場合は None を返す（次のソースへフォールバック）。
    """
    if not MT5_AVAILABLE:
        return None

    mt5_sym = MT5_SYMBOLS.get(symbol, symbol)
    tf = TF_MAP.get(timeframe, 1)

    try:
        if not mt5.initialize():
            return None

        rates = mt5.copy_rates_from_pos(mt5_sym, tf, 0, bars)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={
            "time": "datetime",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "tick_volume": "volume",
        })
        df = df.set_index("datetime")
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.warning(f"[MT5] {symbol}: {e}")
        return None
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
