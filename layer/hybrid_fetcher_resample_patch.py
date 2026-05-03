"""
hybrid_fetcher.py への差分パッチ
resample_ohlcv の TF_MAP / RESAMPLE_MAP に "30m" を追加する。

既存の resample_ohlcv メソッドを以下に置き換える:
"""

PATCH_RESAMPLE_METHOD = '''
    def resample_ohlcv(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """1分足データを指定タイムフレームにリサンプル (30m対応)"""
        TF_MAP = {
            "1m":  "1min",
            "5m":  "5min",
            "15m": "15min",
            "30m": "30min",   # ← 追加
            "1h":  "1h",
            "4h":  "4h",
        }
        rule = TF_MAP.get(timeframe, "1h")
        try:
            resampled = df.resample(rule).agg({
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
            }).dropna()
            return resampled
        except Exception as e:
            print(f"[Fetcher] resample error ({timeframe}): {e}")
            return df
'''
