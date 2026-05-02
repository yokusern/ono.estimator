from typing import Dict, Optional
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from .models import TimeFrame
from .data import MTFData

logger = logging.getLogger(__name__)

class BaseConnector:
    def __init__(self):
        pass

    def fetch_mtf_data(self, symbol: str) -> MTFData:
        raise NotImplementedError
        
    def fetch_news(self, symbol: str) -> list:
        return []

class YFinanceConnector(BaseConnector):
    """Mac/Vercel環境用のyfinanceを用いたデータ取得コネクタ"""
    
    # 内部シンボルからYahoo Finance用シンボルへのマッピング
    SYMBOL_MAP = {
        "USDJPY": "JPY=X",
        "JP225": "^N225",
        "GOLD": "GC=F",
        "BTC": "BTC-USD",
        "XAGUSD": "SI=F",
        "AUDJPY": "AUDJPY=X",
        "EURUSD": "EURUSD=X",
        "EURJPY": "EURJPY=X"
    }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_mtf_data(self, symbol: str) -> MTFData:
        mtf = MTFData()
        yf_symbol = self.SYMBOL_MAP.get(symbol, symbol)
        
        # 取得設定: TimeFrame -> (interval, period)
        tf_settings = {
            TimeFrame.M5: ("5m", "60d"),
            TimeFrame.M15: ("15m", "60d"),
            TimeFrame.H1: ("1h", "730d"),
            TimeFrame.H4: ("1h", "730d"), 
            TimeFrame.D1: ("1d", "5y"),
        }
        
        try:
            ticker = yf.Ticker(yf_symbol)
            for tf in TimeFrame:
                if tf == TimeFrame.H4:
                    df_1h = mtf.get_data(TimeFrame.H1)
                    if df_1h is not None and not df_1h.empty:
                        df_4h = df_1h.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
                        mtf.set_data(tf, df_4h[['open', 'high', 'low', 'close', 'volume']])
                    continue

                interval, period = tf_settings[tf]
                df = ticker.history(period=period, interval=interval)
                
                if not df.empty:
                    self._set_standardized_df(mtf, tf, df)
                else:
                    logger.warning(f"Failed to fetch {tf.value} data for {symbol} via yfinance.")
                    
        except Exception as e:
            logger.error(f"Error fetching data via YFinanceConnector: {e}")
            
        return mtf

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_news(self, symbol: str) -> list:
        yf_symbol = self.SYMBOL_MAP.get(symbol, symbol)
        try:
            ticker = yf.Ticker(yf_symbol)
            return ticker.news
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def _set_standardized_df(self, mtf: MTFData, tf: TimeFrame, df: pd.DataFrame):
        df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
        if df.index.tz is not None:
            df.index = df.index.tz_convert('Asia/Tokyo').tz_localize(None)
        mtf.set_data(tf, df[['open', 'high', 'low', 'close', 'volume']])

class MT5Connector(BaseConnector):
    def __init__(self):
        super().__init__()
        try:
            import MetaTrader5 as mt5
            self.mt5 = mt5
            if not self.mt5.initialize():
                logger.error("MT5 initialize() failed")
        except ImportError:
            logger.error("MetaTrader5 package is not installed or not supported on this OS.")
            self.mt5 = None

    def fetch_mtf_data(self, symbol: str) -> MTFData:
        mtf = MTFData()
        if not self.mt5:
            return mtf
        return mtf
