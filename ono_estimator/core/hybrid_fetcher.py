import os
import time
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from typing import Optional, Dict

class HybridDataFetcher:
    def __init__(self):
        self.twelve_key = os.environ.get("TWELVE_DATA_API_KEY")
        self.tiingo_key = os.environ.get("TIINGO_API_KEY")

    def fetch_ohlcv(self, symbol: str, interval: str = "5min") -> Optional[pd.DataFrame]:
        """Twelve Data -> Tiingo -> yfinance の順でトライ"""
        
        # 1. Twelve Data (Main)
        if self.twelve_key:
            try:
                url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={self.twelve_key}&outputsize=100"
                res = requests.get(url).json()
                # バリデーション: 辞書型かつ values キーが存在することを確認
                if isinstance(res, dict) and "values" in res and isinstance(res["values"], list):
                    df = pd.DataFrame(res["values"])
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    df = df.set_index("datetime").sort_index()
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = df[col].astype(float)
                    return df
            except Exception as e:
                print(f"[TwelveData] Error: {e}")

        # 2. Tiingo (Backup)
        if self.tiingo_key:
            try:
                # Tiingoは銘柄名を調整する必要がある場合あり
                t_symbol = symbol.lower()
                url = f"https://api.tiingo.com/tiingo/crypto/prices?tickers={t_symbol}&resampleFreq={interval}&token={self.tiingo_key}"
                res = requests.get(url).json()
                if res and isinstance(res, list) and len(res) > 0 and "priceData" in res[0]:
                    df = pd.DataFrame(res[0]["priceData"])
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.set_index("date").sort_index()
                    return df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close"})
            except Exception as e:
                print(f"[Tiingo] Error: {e}")

        # 3. yfinance (Fallback) - 最も厳しい制限があるため最後に実行
        try:
            print(f"[yfinance] Falling back for {symbol}...")
            time.sleep(2) # 強制待機
            ticker = yf.Ticker(symbol if "/" not in symbol else symbol.replace("/", ""))
            df = ticker.history(period="1d", interval="5m")
            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception as e:
            print(f"[yfinance] Error: {e}")

        return None

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """TA-Lib相当の指標を一括計算"""
        close = df['close']
        # MA
        df['ma25'] = close.rolling(25).mean()
        # Bollinger Bands
        std = close.rolling(20).std()
        df['bb_upper'] = df['ma25'] + (std * 2)
        df['bb_lower'] = df['ma25'] - (std * 2)
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['hist'] = df['macd'] - df['signal']
        return df.fillna(0)
