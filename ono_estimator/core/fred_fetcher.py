import os
import asyncio
import time
from typing import Optional
import httpx

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "FEDFUNDS": "FF金利",
    "CPIAUCSL": "米CPI",
    "UNRATE":   "米失業率",
    "T10Y2Y":   "逆イールド",
    "VIXCLS":   "VIX",
    "DFF":      "実効FF金利",
    "T10YIE":   "期待インフレ率",
    "DTWEXBGS": "実効DXY",
}

class FredFetcher:
    def __init__(self):
        self.api_key = os.environ.get("FRED_API_KEY", "")
        self._cache: dict = {}
        self._cache_ts: float = 0.0

    async def _fetch_series(self, client: httpx.AsyncClient, series_id: str) -> Optional[dict]:
        if not self.api_key:
            return None
        try:
            r = await client.get(FRED_BASE, params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "limit": 2,
                "sort_order": "desc",
            }, timeout=10.0)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            values = [o for o in obs if o.get("value") not in (".", "", None)]
            if not values:
                return None
            latest = float(values[0]["value"])
            prev = float(values[1]["value"]) if len(values) > 1 else latest
            diff = round(latest - prev, 4)
            return {
                "value": round(latest, 3),
                "prev": round(prev, 3),
                "diff": diff,
                "direction": "上昇" if diff > 0 else "下落" if diff < 0 else "横ばい",
                "date": values[0]["date"],
            }
        except Exception as e:
            print(f"[FRED] {series_id} fetch failed: {e}")
            return None

    async def fetch_all(self) -> dict:
        """全指標を並列取得。1時間キャッシュあり"""
        now = time.time()
        if self._cache and (now - self._cache_ts) < 3600:
            return self._cache

        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *[self._fetch_series(client, sid) for sid in SERIES],
                return_exceptions=True,
            )

        data = {}
        for series_id, result in zip(SERIES.keys(), results):
            data[series_id] = None if isinstance(result, Exception) else result

        # 実質金利を計算 (DFF - T10YIE)
        if data.get("DFF") and data.get("T10YIE"):
            real = round(data["DFF"]["value"] - data["T10YIE"]["value"], 3)
            data["REAL_RATE"] = {"value": real, "diff": 0, "direction": "計算値"}

        self._cache = data
        self._cache_ts = now
        fetched = sum(1 for v in data.values() if v)
        print(f"[FRED] Fetched {fetched} / {len(SERIES)} series")
        return data

    def format_for_prompt(self, data: dict) -> str:
        def fmt(d, unit="%"):
            if not d:
                return "N/A"
            sign = "+" if d.get("diff", 0) >= 0 else ""
            return f"{d['value']}{unit}（前回比 {sign}{d['diff']}{unit} {d.get('direction', '')}）"

        return "\n".join([
            f"FF金利: {fmt(data.get('FEDFUNDS'))}",
            f"米CPI: {fmt(data.get('CPIAUCSL'))}",
            f"米失業率: {fmt(data.get('UNRATE'))}",
            f"逆イールド(10Y-2Y): {fmt(data.get('T10Y2Y'))}",
            f"VIX恐怖指数: {fmt(data.get('VIXCLS'), '')}",
            f"実効DXY: {fmt(data.get('DTWEXBGS'), '')}",
            f"実質金利: {fmt(data.get('REAL_RATE'))}",
            f"期待インフレ率: {fmt(data.get('T10YIE'))}",
        ])
