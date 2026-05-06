"""
HybridDataFetcher v2 — 膨大な過去データ対応版
================================================
タイムフレームごとに最適な取得方法を使い分け:

  1m  : yfinance  7日分  (~10,000本)
  5m  : yfinance 60日分  (~17,000本)
  15m : yfinance 60日分  ( ~5,700本)
  30m : yfinance 60日分  ( ~2,800本)
  1h  : yfinance  2年分  (~17,500本)
  4h  : yfinance  5年分  (~10,900本)
  1d  : yfinance 20年分  ( ~7,300本)

チャート送信本数:
  短期(1m/5m)  : 最新500本
  中期(15m/30m): 最新500本
  長期(1h/4h)  : 最新500本
  超長期(1d)   : 最新1000本

→ メモリ内に各TFのフルデータを保持し、
  AI分析には全データ、チャートには末尾N本を送信
"""

import os
import time
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from typing import Optional, Dict
import traceback
from datetime import datetime

# ─── TFごとの取得設定 ──────────────────────────────────────────
TF_FETCH_CONFIG = {
    # timeframe: (yf_interval, yf_period, chart_bars)
    "1m":  ("1m",  "7d",    500),
    "5m":  ("5m",  "60d",   500),
    "15m": ("15m", "60d",   500),
    "30m": ("30m", "60d",   500),
    "1h":  ("1h",  "730d",  500),
    "4h":  ("1h",  "730d",  500),   # 1h取得→4hリサンプル
    "1d":  ("1d",  "20y",  1000),
    "1wk": ("1wk", "20y",   200),   # L-6: 週足（最上位トレンドフィルター）
}

# Supabaseに長期OHLCVを保存するテーブル名
OHLCV_TABLE = "ohlcv_cache"


class HybridDataFetcher:
    def __init__(self):
        self.twelve_key = os.environ.get("TWELVE_DATA_API_KEY")
        self.tiingo_key = os.environ.get("TIINGO_API_KEY")
        if not hasattr(HybridDataFetcher, "_source_idx"):
            HybridDataFetcher._source_idx = 0
        self.sources = ["twelve", "tiingo", "yfinance"]

        # ── メモリキャッシュ ───────────────────────────────────
        # { symbol: { tf: DataFrame } }
        # AI分析にはフルデータ、チャートにはtail(N)を使う
        self._cache: Dict[str, Dict[str, pd.DataFrame]] = {}
        self._cache_ts: Dict[str, Dict[str, float]] = {}   # 最終更新時刻

    # ─── 公開API ───────────────────────────────────────────────

    def is_market_open(self, symbol: str) -> bool:
        if "BTC" in symbol or "ETH" in symbol:
            return True
        now = datetime.utcnow()
        wd = now.weekday()
        if wd == 5 or (wd == 6 and now.hour < 21):
            return False
        return True

    def fetch_full_ohlcv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        指定TFの膨大な過去データをまるごと取得・キャッシュして返す。
        AI分析・インジケーター計算用。
        """
        cfg = TF_FETCH_CONFIG.get(timeframe)
        if cfg is None:
            return None

        yf_interval, yf_period, _ = cfg

        # キャッシュが新鮮なら再利用
        cache_age = self._get_cache_age(symbol, timeframe)
        max_age = 60 if timeframe in ("1m", "5m") else 300  # 1m/5m:1分, それ以上:5分
        if cache_age < max_age:
            return self._cache.get(symbol, {}).get(timeframe)

        # 4hは1hを取得してリサンプル
        if timeframe == "4h":
            df_1h = self.fetch_full_ohlcv(symbol, "1h")
            if df_1h is not None and not df_1h.empty:
                df_4h = df_1h.resample("4h").agg({
                    "open": "first", "high": "max",
                    "low": "min",   "close": "last", "volume": "sum"
                }).dropna()
                self._set_cache(symbol, "4h", df_4h)
                return df_4h
            return None

        df = self._fetch_yfinance_full(symbol, yf_interval, yf_period)

        if df is None or df.empty:
            # フォールバック: Twelve Data / Tiingo (短期のみ)
            if timeframe in ("1m", "5m", "15m"):
                df = self._fetch_from_apis(symbol, "1min" if timeframe == "1m" else timeframe)

        if df is not None and not df.empty:
            df = self._validate_and_fill(df)
            if df is not None:
                self._set_cache(symbol, timeframe, df)
                return df

        return None

    def fetch_ohlcv(self, symbol: str, interval: str = "1min") -> Optional[pd.DataFrame]:
        """後方互換: 1分足を返す（既存コードから呼ばれる）"""
        return self.fetch_full_ohlcv(symbol, "1m")

    def resample_ohlcv(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """1分足DFを任意TFにリサンプル（後方互換）"""
        tf_map = {
            "1m":  "1min",
            "5m":  "5min",
            "15m": "15min",
            "30m": "30min",
            "1h":  "1h",
            "4h":  "4h",
        }
        rule = tf_map.get(timeframe, "1h")
        try:
            return df.resample(rule).agg({
                "open": "first", "high": "max",
                "low": "min",   "close": "last", "volume": "sum"
            }).dropna()
        except Exception as e:
            print(f"[Fetcher] resample error ({timeframe}): {e}")
            return df

    def get_chart_data(self, symbol: str, timeframe: str) -> list:
        """
        チャート表示用データ（末尾N本 + インジケーター付き）を返す。
        フルデータからスライスするので初回以外は高速。
        """
        df = self.fetch_full_ohlcv(symbol, timeframe)
        if df is None or df.empty:
            return []

        cfg = TF_FETCH_CONFIG.get(timeframe, ("1m", "7d", 500))
        chart_bars = cfg[2]

        df_ind = self.calculate_indicators(df.copy())
        df_chart = df_ind.tail(chart_bars)

        records = []
        for idx, row in df_chart.iterrows():
            t = int(idx.timestamp()) if hasattr(idx, "timestamp") else int(idx)
            records.append({
                "time":     t,
                "open":     float(row["open"]),
                "high":     float(row["high"]),
                "low":      float(row["low"]),
                "close":    float(row["close"]),
                "volume":   float(row.get("volume", 0)),
                "ma25":     float(row.get("ma25", 0)),
                "ma200":    float(row.get("ma200", 0)),
                "rsi":      float(row.get("rsi", 50)),
                "macd":     float(row.get("macd", 0)),
                "bb_upper": float(row.get("bb_upper", 0)),
                "bb_lower": float(row.get("bb_lower", 0)),
                "atr":      float(row.get("atr", 0)),
            })
        return records

    def get_analysis_df(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        AI分析エンジン用: フルデータ + インジケーター付きDFを返す。
        チャートより多くの本数（全期間）を使う。
        """
        df = self.fetch_full_ohlcv(symbol, timeframe)
        if df is None or df.empty:
            return None
        return self.calculate_indicators(df.copy())

    def get_analysis_df_windowed(self, symbol: str, timeframe: str, bars: int) -> Optional[pd.DataFrame]:
        """
        分析用: フルデータ取得 → インジケーター計算 → 末尾bars本だけ返す。
        インジケーター計算はフルデータで行い（MA200等の精度を保つ）、
        スコア計算用のDFだけをスライスして返す。
        """
        df = self.fetch_full_ohlcv(symbol, timeframe)
        if df is None or df.empty:
            return None
        df_full = self.calculate_indicators(df.copy())
        return df_full.tail(bars)

    # ─── インジケーター計算 ────────────────────────────────────

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """MA/BB/RSI/MACD/ATR/EMA200 を一括計算"""
        for col in ["ma25", "ma200", "rsi", "macd", "signal",
                    "bb_upper", "bb_lower", "atr", "ema200"]:
            if col not in df.columns:
                df[col] = 0.0

        if df is None or df.empty or len(df) < 30:
            return df

        try:
            close = df["close"]
            high  = df["high"]
            low   = df["low"]

            # 移動平均
            df["ma25"]  = close.rolling(25).mean().ffill().fillna(close)
            df["ma200"] = close.rolling(200).mean().ffill().fillna(close)
            df["ema200"] = close.ewm(span=200, adjust=False).mean()

            # ボリンジャーバンド (20期間)
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std().fillna(0)
            df["bb_upper"] = bb_mid + bb_std * 2
            df["bb_lower"] = bb_mid - bb_std * 2

            # RSI (14)
            delta = close.diff()
            gain  = delta.where(delta > 0, 0).rolling(14).mean()
            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs    = gain / loss.replace(0, np.nan)
            df["rsi"] = (100 - 100 / (1 + rs)).fillna(50)

            # MACD (12/26/9)
            exp12 = close.ewm(span=12, adjust=False).mean()
            exp26 = close.ewm(span=26, adjust=False).mean()
            df["macd"]   = exp12 - exp26
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

            # ATR (14)
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs(),
            ], axis=1).max(axis=1)
            df["atr"] = tr.rolling(14).mean().fillna(0)

            return df.fillna(0)

        except Exception as e:
            print(f"[Fetcher] indicator error: {e}")
            return df

    # ─── 内部: yfinance フルデータ取得 ────────────────────────

    def _fetch_yfinance_full(
        self, symbol: str, yf_interval: str, yf_period: str
    ) -> Optional[pd.DataFrame]:
        """
        yfinance でできる限り長期のOHLCVを取得。
        yfinance の制限:
          1m  → 最大7日
          5m  → 最大60日
          15m → 最大60日
          30m → 最大60日
          1h  → 最大730日
          1d  → 制限なし (20年以上取得可能)
        """
        try:
            df = yf.download(
                symbol,
                period=yf_period,
                interval=yf_interval,
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                return None

            # MultiIndex 解消
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]

            # adj close → close に統一
            if "adj close" in df.columns and "close" not in df.columns:
                df = df.rename(columns={"adj close": "close"})
            elif "adj close" in df.columns:
                df = df.drop(columns=["adj close"])

            # timezone 除去 → tz-naive に統一
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            print(f"[Fetcher] yfinance {symbol}/{yf_interval}/{yf_period}: {len(df)}本 取得")
            return df

        except Exception as e:
            print(f"[Fetcher] yfinance error {symbol}/{yf_interval}: {e}")
            return None

    # ─── 内部: Twelve Data / Tiingo フォールバック ────────────

    def _fetch_from_apis(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """短期データのフォールバック（既存ロジック流用）"""
        if not hasattr(HybridDataFetcher, "_source_idx"):
            HybridDataFetcher._source_idx = 0
        source = self.sources[HybridDataFetcher._source_idx]
        HybridDataFetcher._source_idx = (HybridDataFetcher._source_idx + 1) % len(self.sources)
        priority = [source] + [s for s in self.sources if s != source]

        for s in priority:
            try:
                df = None
                if s == "twelve" and self.twelve_key:
                    df = self._fetch_twelve(symbol, interval, 1000)
                elif s == "tiingo" and self.tiingo_key:
                    df = self._fetch_tiingo(symbol, interval)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                print(f"[Fetcher] {s} error for {symbol}: {e}")
        return None

    def _fetch_twelve(self, symbol: str, interval: str, outputsize: int) -> Optional[pd.DataFrame]:
        t_symbol = symbol.replace("=X", "").replace("-USD", "/USD")
        if "/" not in t_symbol and len(t_symbol) == 6:
            t_symbol = f"{t_symbol[:3]}/{t_symbol[3:]}"
        url = (f"https://api.twelvedata.com/time_series"
               f"?symbol={t_symbol}&interval={interval}"
               f"&apikey={self.twelve_key}&outputsize={outputsize}")
        res = requests.get(url, timeout=10).json()
        if isinstance(res, dict) and "values" in res:
            df = pd.DataFrame(res["values"])
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime").sort_index()
            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        return None

    def _fetch_tiingo(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        t_symbol = symbol.replace("=X", "").lower()
        url = (f"https://api.tiingo.com/tiingo/fx/prices"
               f"?tickers={t_symbol}&resampleFreq={interval}&token={self.tiingo_key}")
        res = requests.get(url, timeout=10).json()
        if res and isinstance(res, list):
            df = pd.DataFrame(res)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                return df
        return None

    # ─── 内部: キャッシュ管理 ─────────────────────────────────

    def _set_cache(self, symbol: str, tf: str, df: pd.DataFrame):
        if symbol not in self._cache:
            self._cache[symbol] = {}
            self._cache_ts[symbol] = {}
        self._cache[symbol][tf] = df
        self._cache_ts[symbol][tf] = time.time()

    def _get_cache_age(self, symbol: str, tf: str) -> float:
        """キャッシュが何秒前に更新されたか（存在しなければ∞）"""
        ts = self._cache_ts.get(symbol, {}).get(tf, 0)
        if ts == 0:
            return float("inf")
        return time.time() - ts

    def _validate_and_fill(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        required = ["open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                return None
        if "volume" not in df.columns:
            df["volume"] = 0
        df = df.sort_index()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.ffill().dropna(subset=["close"])
