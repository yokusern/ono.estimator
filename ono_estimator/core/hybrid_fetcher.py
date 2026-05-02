import os
import time
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from typing import Optional, Dict, List
import traceback

class HybridDataFetcher:
    def __init__(self):
        self.twelve_key = os.environ.get("TWELVE_DATA_API_KEY")
        self.tiingo_key = os.environ.get("TIINGO_API_KEY")
        # 内部的なインデックス管理 (グローバルで共有)
        if not hasattr(HybridDataFetcher, "_source_idx"):
            HybridDataFetcher._source_idx = 0
        self.sources = ["twelve", "tiingo", "yfinance"]

    def fetch_ohlcv(self, symbol: str, interval: str = "1min") -> Optional[pd.DataFrame]:
        """APIローテーションを強制適用し、レート制限を回避"""
        source = self.sources[HybridDataFetcher._source_idx]
        HybridDataFetcher._source_idx = (HybridDataFetcher._source_idx + 1) % len(self.sources)
        
        # 優先順位を並び替え
        priority_list = [source] + [s for s in self.sources if s != source]
        
        outputsize = 1000 if interval == "1min" else 100
        
        for s in priority_list:
            try:
                df = None
                if s == "twelve" and self.twelve_key:
                    df = self._fetch_twelve(symbol, interval, outputsize)
                elif s == "tiingo" and self.tiingo_key:
                    df = self._fetch_tiingo(symbol, interval)
                elif s == "yfinance":
                    df = self._fetch_yfinance(symbol, interval)
                
                if df is not None and not df.empty and len(df) > 10:
                    # カラムの正規化とバリデーション
                    df = self._validate_and_fill(df)
                    print(f"[Fetcher] Success using {s} for {symbol}")
                    return df
            except Exception as e:
                print(f"[Fetcher] {s} failed for {symbol}: {e}")
                
        return None

    def _validate_and_fill(self, df: pd.DataFrame) -> pd.DataFrame:
        """データの欠落を補完"""
        required = ["open", "high", "low", "close"]
        for col in required:
            if col not in df.columns: return None
        
        # ボリュームがない場合は0埋め (FXなど)
        if "volume" not in df.columns:
            df["volume"] = 0
            
        df = df.sort_index()
        # 型変換
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df.ffill().dropna()

    def resample_ohlcv(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """1分足データを指定の時間足にリサンプリング (Pandas v2 対応)"""
        if df is None or df.empty: return df
        
        tf_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
        rule = tf_map.get(timeframe, timeframe)
        
        try:
            resampled = df.resample(rule).agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()
            return resampled
        except:
            return df

    def _fetch_twelve(self, symbol: str, interval: str, outputsize: int) -> Optional[pd.DataFrame]:
        t_symbol = symbol.replace("=X", "").replace("-USD", "/USD")
        if "/" not in t_symbol and len(t_symbol) == 6:
            t_symbol = f"{t_symbol[:3]}/{t_symbol[3:]}"
        
        url = f"https://api.twelvedata.com/time_series?symbol={t_symbol}&interval={interval}&apikey={self.twelve_key}&outputsize={outputsize}"
        res = requests.get(url, timeout=10).json()
        if isinstance(res, dict) and "values" in res:
            df = pd.DataFrame(res["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
            return df
        return None

    def _fetch_tiingo(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        t_symbol = symbol.replace("=X", "").lower()
        url = f"https://api.tiingo.com/tiingo/fx/prices?tickers={t_symbol}&resampleFreq={interval}&token={self.tiingo_key}"
        res = requests.get(url, timeout=10).json()
        if res and isinstance(res, list):
            df = pd.DataFrame(res)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
                return df
        return None

    def _fetch_yfinance(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            yf_interval = "1m" if interval == "1min" else "5m"
            df = yf.download(symbol, period="5d", interval=yf_interval, progress=False)
            if not df.empty:
                # MultiIndexカラムをフラット化
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                # 文字列変換して小文字化
                df.columns = [str(c).lower() for c in df.columns]
                return df
        except Exception as e:
            print(f"[Fetcher] yfinance error for {symbol}: {e}")
        return None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """指標計算の堅牢化 (カラムの存在を保証)"""
        # 必須カラムの初期化 (エラー防止)
        for col in ['ma25', 'rsi', 'macd', 'signal', 'bb_upper', 'bb_lower']:
            if col not in df.columns:
                df[col] = 0.0

        if df is None or df.empty or len(df) < 30: 
            return df
            
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
        except Exception as e:
            print(f"[Indicators] Calculation error: {e}")
            return df
