"""
RiskCalculator — 1トレード1%リスク固定のロットサイズ計算
=========================================================
口座残高 × リスク率 ÷ (SL pips × pip value) = ロットサイズ

pip value の基準 (1標準ロット = 100,000通貨):
  USD建てペア  (EURUSD, GBPUSD, ...) : $10 / pip
  JPY建てペア  (USDJPY, EURJPY, ...) : 計算式が異なる
  クロスペア   (EURJPY など)          : USD換算が必要
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 1標準ロット = 100,000 通貨の pip value (USD換算)
# USD建てペア: pip = 0.0001, 1標準ロットで $10/pip
_USD_QUOTE_SYMBOLS = {
    "EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X",
}
_JPY_QUOTE_SYMBOLS = {
    "USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X",
    "CADJPY=X", "CHFJPY=X", "NZDJPY=X",
}
_MIXED_SYMBOLS = {
    "USDCAD=X", "USDCHF=X", "GC=F",
}

DEFAULT_RISK_PCT = 1.0   # 口座残高の1%
MIN_LOT         = 0.01
MAX_LOT         = 2.0    # 安全のため上限設定


class RiskCalculator:
    def __init__(self, default_balance: float = 10_000.0):
        self._balance = default_balance  # OANDAから取得できない場合のフォールバック

    def set_balance(self, balance: float) -> None:
        self._balance = balance

    def calc_lot(
        self,
        symbol:     str,
        entry:      float,
        sl:         float,
        risk_pct:   float = DEFAULT_RISK_PCT,
        balance:    Optional[float] = None,
        usd_jpy:    float = 150.0,   # USD/JPY レート (JPYペア計算用)
    ) -> float:
        """
        SL までのリスクが口座残高の risk_pct % になるロットサイズを返す。
        """
        bal = balance if balance is not None else self._balance
        if bal <= 0:
            return MIN_LOT

        risk_amount = bal * (risk_pct / 100.0)
        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return MIN_LOT

        # pip サイズとpip値を計算
        pip_size, pip_value_per_standard_lot = _pip_value(
            symbol, entry, usd_jpy
        )
        sl_pips = sl_distance / pip_size

        if sl_pips <= 0 or pip_value_per_standard_lot <= 0:
            return MIN_LOT

        # ロット計算
        lot = risk_amount / (sl_pips * pip_value_per_standard_lot)
        lot = round(max(MIN_LOT, min(lot, MAX_LOT)), 2)

        logger.debug(
            f"[Risk] {symbol}: balance={bal:.0f} risk={risk_pct}% "
            f"sl_pips={sl_pips:.1f} pip_val={pip_value_per_standard_lot:.2f} "
            f"→ lot={lot}"
        )
        return lot

    def expected_loss_usd(
        self, symbol: str, entry: float, sl: float, lot: float, usd_jpy: float = 150.0
    ) -> float:
        """このロットでSLを踏んだ場合の損失(USD)を返す"""
        pip_size, pip_val = _pip_value(symbol, entry, usd_jpy)
        sl_pips = abs(entry - sl) / pip_size
        return round(sl_pips * pip_val * lot, 2)


def _pip_value(symbol: str, entry: float, usd_jpy: float) -> tuple[float, float]:
    """
    (pip_size, pip_value_per_standard_lot_in_usd) を返す。
    pip_size = 1 pip の価格変動幅
    pip_value = 1標準ロット(100k通貨)でのUSD換算pip値
    """
    if symbol in _USD_QUOTE_SYMBOLS:
        # EURUSD等: 1pip = 0.0001, $10/pip/標準ロット
        return 0.0001, 10.0

    if symbol in _JPY_QUOTE_SYMBOLS:
        # USDJPY等: 1pip = 0.01
        # pip_value = 100,000 * 0.01 / entry * 1 (USD換算)
        # USDJPYの場合: pip_val = 1000 / entry
        # EURJPYの場合: pip_val = 1000 / usd_jpy (USD換算)
        if symbol == "USDJPY=X":
            pip_val = 1000.0 / entry if entry > 0 else 6.67
        else:
            pip_val = 1000.0 / usd_jpy
        return 0.01, round(pip_val, 4)

    if symbol == "GC=F":
        # GOLD: 1pip = $0.01, 100oz/lot → $10/pip/標準ロット（近似）
        return 0.01, 10.0

    if symbol == "USDCAD=X":
        # 1pip = 0.0001, pip_val = $10 / CAD/USD rate ≈ $7.5 (近似)
        return 0.0001, 7.5

    if symbol == "USDCHF=X":
        # 1pip = 0.0001, pip_val = $10 / CHF/USD rate ≈ $11 (近似)
        return 0.0001, 11.0

    # 不明ペア: 安全のため控えめな値
    return 0.0001, 8.0
