import os
import time
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from typing import Optional, Dict, List

class HybridDataFetcher:
    def __init__(self):
        self.twelve_key = os.environ.get("TWELVE_DATA_API_KEY")
        self.tiingo_key = os.environ.get("TIINGO_API_KEY")
        self.sources = ["twelve", "tiingo", "yfinance"]
        self.current_source_idx = 0

    def fetch_ohlcv(self, symbol: str, interval: str = "1min") -> Optional[pd.DataFrame]:
        """APIローテーションを使用してデータを取得 (1分足対応)"""
        source = self.sources[self.current_source_idx]
        self.current_source_idx = (self.current_source_idx + 1) % len(self.sources)
        
        priority_list = [source] + [s for s in self.sources if s != source]
        
        # 1分足取得時は多めに取得する (1000件)
        outputsize = 1000 if interval == "1min" else 100
        
        for s in priority_list:
            df = None
            if s == "twelve" and self.twelve_key:
                df = self._fetch_twelve(symbol, interval, outputsize)
            elif s == "tiingo" and self.tiingo_key:
                df = self._fetch_tiingo(symbol, interval)
            elif s == "yfinance":
                df = self._fetch_yfinance(symbol, interval)
            
            if df is not None and not df.empty:
                return df
                
        return None

    def resample_ohlcv(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """1分足データを指定の時間足にリサンプリング"""
        if df is None or df.empty: return df
        
        # 時間枠のマッピング
        tf_map = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "1h": "1H",
            "4h": "4H"
        }
        rule = tf_map.get(timeframe, timeframe)
        
        resampled = df.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()
        
        return resampled

    def _fetch_twelve(self, symbol: str, interval: str, outputsize: int = 100) -> Optional[pd.DataFrame]:
        try:
            t_symbol = symbol.replace("=X", "").replace("-USD", "/USD")
            if "/" not in t_symbol and len(t_symbol) == 6:
                t_symbol = f"{t_symbol[:3]}/{t_symbol[3:]}"
            
            url = f"https://api.twelvedata.com/time_series?symbol={t_symbol}&interval={interval}&apikey={self.twelve_key}&outputsize={outputsize}"
            res = requests.get(url).json()
            if isinstance(res, dict) and "values" in res:
                df = pd.DataFrame(res["values"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime").sort_index()
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = df[col].astype(float)
                return df
        except Exception as e:
            print(f"[TwelveData] Error: {e}")
        return None

    def _fetch_tiingo(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            t_symbol = symbol.replace("=X", "").lower()
            url = f"https://api.tiingo.com/tiingo/fx/prices?tickers={t_symbol}&resampleFreq={interval}&token={self.tiingo_key}"
            res = requests.get(url).json()
            if res and isinstance(res, list) and len(res) > 0:
                df = pd.DataFrame(res)
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                return df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close"})
        except Exception as e:
            print(f"[Tiingo] Error: {e}")
        return None

    def _fetch_yfinance(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            yf_interval = "1m" if interval == "1min" else "5m"
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d", interval=yf_interval) # MTF用に多めに取得
            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception as e:
            print(f"[yfinance] Error: {e}")
        return None

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """TA-Lib相当の指標を一括計算"""
        if df is None or df.empty or len(df) < 25: return df
        close = df['close']
        df['ma25'] = close.rolling(25).mean()
        std = close.rolling(20).std()
        df['bb_upper'] = df['ma25'] + (std * 2)
        df['bb_lower'] = df['ma25'] - (std * 2)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['hist'] = df['macd'] - df['signal']
        return df.fillna(0)
