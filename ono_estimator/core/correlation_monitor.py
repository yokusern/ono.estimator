"""
Step 10: 相関監視（Correlation Monitor）
API リクエストを消費しない内部計算で実装する。
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

# 監視する相関ペアと期待相関係数
MONITORED_PAIRS = [
    ("USDJPY=X", "GC=F",   -0.6),  # USDJPY と GOLD は逆相関
    ("USDJPY=X", "BTC-USD", 0.3),   # 弱い正相関
    ("GC=F",     "SI=F",    0.8),   # GOLD と SILVER は強い正相関
    ("^N225",    "USDJPY=X", 0.5),  # 日経と USDJPY は正相関
    ("EURUSD=X", "GBPUSD=X", 0.7), # EUR と GBP は正相関
]


def calc_correlation(price_a: pd.Series, price_b: pd.Series) -> Optional[float]:
    """ピアソン相関係数を計算"""
    try:
        if len(price_a) < 5 or len(price_b) < 5:
            return None
        min_len = min(len(price_a), len(price_b))
        a = price_a.tail(min_len).values.astype(float)
        b = price_b.tail(min_len).values.astype(float)
        corr = float(np.corrcoef(a, b)[0, 1])
        return round(corr, 3) if not np.isnan(corr) else None
    except Exception as e:
        logger.warning(f"[Corr] calc failed: {e}")
        return None


async def check_correlation(chart_data: dict, window: int = 20) -> dict:
    """
    直近 window 本のローソク足を使い、銘柄間のピアソン相関係数を計算。
    本来の相関から ±0.3 以上乖離した場合に歪みフラグを返す。
    chart_data: { symbol: [{"close": float, ...}, ...] }
    """
    pairs_result = {}
    alerts = []

    for sym_a, sym_b, expected in MONITORED_PAIRS:
        data_a = chart_data.get(sym_a) or chart_data.get(sym_a.replace("=X", "").replace("-USD", ""))
        data_b = chart_data.get(sym_b) or chart_data.get(sym_b.replace("=X", "").replace("-USD", ""))

        if not data_a or not data_b:
            continue

        try:
            closes_a = pd.Series([c["close"] for c in data_a[-window:]])
            closes_b = pd.Series([c["close"] for c in data_b[-window:]])
            corr = calc_correlation(closes_a, closes_b)

            if corr is None:
                continue

            deviation = round(corr - expected, 3)
            alert = abs(deviation) >= 0.3

            pair_key = f"{SYMBOL_DISPLAY.get(sym_a, sym_a)}-{SYMBOL_DISPLAY.get(sym_b, sym_b)}"
            pairs_result[pair_key] = {
                "corr": corr,
                "expected": expected,
                "deviation": deviation,
                "alert": alert,
            }

            if alert:
                direction = "乖離" if deviation > 0 else "逆転"
                alerts.append(f"⚠️ 相関{direction}検知: {pair_key} (実{corr:.2f} vs 期待{expected})")
        except Exception as e:
            logger.warning(f"[Corr] {sym_a}-{sym_b}: {e}")

    return {
        "pairs": pairs_result,
        "alerts": alerts,
        "summary": alerts[0] if alerts else "相関異常なし",
        "alert_count": len(alerts),
    }


SYMBOL_DISPLAY = {
    "USDJPY=X": "USDJPY", "GC=F": "GOLD", "SI=F": "SILVER",
    "BTC-USD": "BTC", "^N225": "JP225", "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
}
