"""
Step A3: COT Report 統合
CFTC の週次 CSV からネットポジションを取得し、スコアに加算する。
データソース: https://www.cftc.gov/dea/newcot/FinFutWk.txt
"""
import logging
import asyncio
import time
from typing import Optional
import httpx
import io

logger = logging.getLogger(__name__)

CFTC_URL = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"

# 対象先物 → 銘柄マッピング
FUTURES_MAP = {
    "JAPANESE YEN": "USDJPY=X",
    "EURO FX": "EURUSD=X",
    "GOLD": "GC=F",
    "BRITISH POUND": "GBPUSD=X",
    "SWISS FRANC": "USDCHF=X",
    "AUSTRALIAN DOLLAR": "AUDUSD=X",
    "CANADIAN DOLLAR": "USDCAD=X",
}

_cache: dict = {}
_cache_ts: float = 0.0


async def fetch_cot() -> dict:
    """COT データを取得してネットポジションの前週比を返す"""
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < 86400 * 3:  # 3日キャッシュ
        return _cache

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(CFTC_URL, timeout=30.0)
            r.raise_for_status()
            text = r.text

        result = _parse_cot(text)
        _cache = result
        _cache_ts = now
        logger.info(f"[COT] Fetched {len(result)} records")
        return result
    except Exception as e:
        logger.warning(f"[COT] Fetch failed: {e}")
        return _cache or {}


def _parse_cot(text: str) -> dict:
    """CFTC CSV をパースしてネットポジションを返す"""
    result = {}
    lines = text.strip().split("\n")
    header = None

    for line in lines:
        cols = [c.strip().strip('"') for c in line.split(",")]
        if header is None:
            header = [c.upper() for c in cols]
            continue

        if len(cols) < 10:
            continue

        try:
            name = cols[0].upper()
            for key, symbol in FUTURES_MAP.items():
                if key in name:
                    # Non-Commercial Long/Short を探す
                    long_idx = next((i for i, h in enumerate(header) if "NONCOMM_POSITIONS_LONG_ALL" in h.replace(" ", "_").upper()), None)
                    short_idx = next((i for i, h in enumerate(header) if "NONCOMM_POSITIONS_SHORT_ALL" in h.replace(" ", "_").upper()), None)

                    if long_idx and short_idx and long_idx < len(cols) and short_idx < len(cols):
                        longs = int(cols[long_idx].replace(",", "") or 0)
                        shorts = int(cols[short_idx].replace(",", "") or 0)
                        net = longs - shorts
                        result[symbol] = {"net": net, "longs": longs, "shorts": shorts}
                    break
        except Exception:
            continue

    return result


def get_cot_score_bonus(symbol: str, cot_data: dict) -> int:
    """ネットポジションの方向に基づきスコアボーナスを返す (+10 or -10 or 0)"""
    if not cot_data or symbol not in cot_data:
        return 0
    net = cot_data[symbol].get("net", 0)
    if net > 10000:
        return 10
    elif net < -10000:
        return -10
    return 0
