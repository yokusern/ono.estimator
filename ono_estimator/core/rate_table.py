import os
import asyncio
import time
from typing import Optional
import httpx

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

RATE_SERIES = {
    "USD": "FEDFUNDS",
    "EUR": "ECBDFR",
    "JPY": "IRSTCI01JPM156N",
    "GBP": "IUDSOIA",
    "AUD": "IRSTCI01AUM156N",
}

_FALLBACK = {
    "USD": 5.33,
    "EUR": 3.65,
    "JPY": 0.10,
    "GBP": 5.20,
    "AUD": 4.35,
}

class RateTable:
    def __init__(self):
        self.api_key = os.environ.get("FRED_API_KEY", "")
        self._rates: dict = dict(_FALLBACK)
        self._last_update: float = 0.0

    async def _fetch_rate(self, client: httpx.AsyncClient, currency: str) -> Optional[float]:
        series_id = RATE_SERIES.get(currency)
        if not series_id or not self.api_key:
            return None
        try:
            r = await client.get(FRED_BASE, params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "limit": 1,
                "sort_order": "desc",
            }, timeout=10.0)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            values = [o for o in obs if o.get("value") not in (".", "", None)]
            if values:
                return round(float(values[0]["value"]), 3)
        except Exception as e:
            print(f"[RateTable] {currency} fetch failed: {e}")
        return None

    async def refresh(self):
        """全通貨の政策金利を並列取得（1日1回）"""
        if time.time() - self._last_update < 86400:
            return
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *[self._fetch_rate(client, cur) for cur in RATE_SERIES],
                return_exceptions=True,
            )
        for cur, result in zip(RATE_SERIES.keys(), results):
            if not isinstance(result, Exception) and result is not None:
                self._rates[cur] = result
                print(f"[RateTable] {cur}: {result}%")
        self._last_update = time.time()

    def get_rate(self, currency: str) -> float:
        return self._rates.get(currency, 0.0)

    def get_diff(self, base: str, quote: str) -> dict:
        b = self.get_rate(base)
        q = self.get_rate(quote)
        diff = round(b - q, 3)
        return {
            "base": base,
            "base_rate": b,
            "quote": quote,
            "quote_rate": q,
            "diff": diff,
            "badge": "🟢" if diff > 0.5 else "🔴" if diff < -0.5 else "⚪",
        }

    def get_all_diffs(self) -> dict:
        pairs = {
            "USDJPY": ("USD", "JPY"),
            "EURUSD": ("EUR", "USD"),
            "EURJPY": ("EUR", "JPY"),
            "AUDJPY": ("AUD", "JPY"),
            "GBPJPY": ("GBP", "JPY"),
        }
        return {pair: self.get_diff(b, q) for pair, (b, q) in pairs.items()}


rate_table = RateTable()
