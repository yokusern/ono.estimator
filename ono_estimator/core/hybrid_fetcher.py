import os
import time
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from typing import Optional, Dict, List
import traceback
from datetime import datetime, time as dtime

class HybridDataFetcher:
    def __init__(self):
        self.twelve_key = os.environ.get("TWELVE_DATA_API_KEY")
        self.tiingo_key = os.environ.get("TIINGO_API_KEY")
        if not hasattr(HybridDataFetcher, "_source_idx"):
            HybridDataFetcher._source_idx = 0
        self.sources = ["twelve", "tiingo", "yfinance"]

    def is_market_open(self, symbol: str) -> bool:
        """銘柄と現在時刻から市場の開閉を判定 (UTC基準/JST考慮)"""
        # 仮想通貨は常にオープン
        if "BTC" in symbol or "ETH" in symbol:
            return True
        
        now = datetime.utcnow()
        weekday = now.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        
        # 一般的なマーケット（FX/株価指数/ゴールド）の閉場時間:
        # 土曜日(5)の00:00(UTC) 〜 月曜日(0)の00:00(UTC) は概ね閉場
        if weekday == 5 or (weekday == 6 and now.hour < 21): # 土曜全日と日曜の夜まで
            return False
            
        return True

    def fetch_ohlcv(self, symbol: str, interval: str = "1min") -> Optional[pd.DataFrame]:
        """市場状態を確認してからデータを取得"""
        if not self.is_market_open(symbol):
            print(f"[Market] {symbol} is currently CLOSED. Fetching last available data...")
            # 閉場中でも金曜の最終データが必要なため、一度だけ取得を試みる（yfinanceが便利）
            return self._fetch_yfinance(symbol, interval, period="5d")

        source = self.sources[HybridDataFetcher._source_idx]
        HybridDataFetcher._source_idx = (HybridDataFetcher._source_idx + 1) % len(self.sources)
        priority_list = [source] + [s for s in self.sources if s != source]
        
        for s in priority_list:
            try:
                df = None
                if s == "twelve" and self.twelve_key:
                    df = self._fetch_twelve(symbol, interval, 1000)
                elif s == "tiingo" and self.tiingo_key:
                    df = self._fetch_tiingo(symbol, interval)
                elif s == "yfinance":
                    df = self._fetch_yfinance(symbol, interval)
                
                if df is not None and not df.empty:
                    return self._validate_and_fill(df)
            except Exception as e:
                print(f"[Fetcher] {s} error for {symbol}: {e}")
                
        return None

    def _validate_and_fill(self, df: pd.DataFrame) -> pd.DataFrame:
        required = ["open", "high", "low", "close"]
        for col in required:
            if col not in df.columns: return None
        if "volume" not in df.columns: df["volume"] = 0
        df = df.sort_index()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.ffill().dropna()

    def resample_ohlcv(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        if df is None or df.empty: return df
        tf_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
        rule = tf_map.get(timeframe, timeframe)
        try:
            return df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        except: return df

    def _fetch_twelve(self, symbol: str, interval: str, outputsize: int) -> Optional[pd.DataFrame]:
        t_symbol = symbol.replace("=X", "").replace("-USD", "/USD")
        if "/" not in t_symbol and len(t_symbol) == 6: t_symbol = f"{t_symbol[:3]}/{t_symbol[3:]}"
        url = f"https://api.twelvedata.com/time_series?symbol={t_symbol}&interval={interval}&apikey={self.twelve_key}&outputsize={outputsize}"
        res = requests.get(url, timeout=10).json()
        if isinstance(res, dict) and "values" in res:
            df = pd.DataFrame(res["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            return df.set_index("datetime")
        return None

    def _fetch_tiingo(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        t_symbol = symbol.replace("=X", "").lower()
        url = f"https://api.tiingo.com/tiingo/fx/prices?tickers={t_symbol}&resampleFreq={interval}&token={self.tiingo_key}"
        res = requests.get(url, timeout=10).json()
        if res and isinstance(res, list):
            df = pd.DataFrame(res)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                return df.set_index("date")
        return None

    def _fetch_yfinance(self, symbol: str, interval: str, period: str = "5d") -> Optional[pd.DataFrame]:
        try:
            yf_interval = "1m" if interval == "1min" else "5m"
            df = yf.download(symbol, period=period, interval=yf_interval, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df.columns = [str(c).lower() for c in df.columns]
                return df
        except: pass
        return None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['ma25', 'rsi', 'macd', 'signal', 'bb_upper', 'bb_lower']:
            if col not in df.columns: df[col] = 0.0
        if df is None or df.empty or len(df) < 30: return df
        try:
            close = df['close']
            df['ma25'] = close.rolling(25).mean().fillna(close)
            std = close.rolling(20).std().fillna(0)
            df['bb_upper'] = df['ma25'] + (std * 2)
            df['bb_lower'] = df['ma25'] - (std * 2)
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            df['rsi'] = 100 - (100 / (1 + rs.fillna(0)))
            exp1 = close.ewm(span=12, adjust=False).mean()
            exp2 = close.ewm(span=26, adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            return df.fillna(0)
        except: return df
