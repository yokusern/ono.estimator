"""
OandaOrderManager — OANDA Practice 口座への実注文管理
=====================================================
シグナル発火 → OANDA API v20 経由でデモ口座に成行注文
TP/SL はサーバーサイドオーダーとして設定。

必要な環境変数:
  OANDA_API_KEY      : OANDA APIトークン
  OANDA_ACCOUNT_ID   : OANDAアカウントID
  OANDA_PRACTICE     : "true" (必須 — プラクティス専用)

デフォルトロット: OANDA_DEFAULT_LOT (デフォルト 0.03)
"""
from __future__ import annotations

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# yfinance形式 → OANDA instrument名
_INSTRUMENT_MAP = {
    "USDJPY=X": "USD_JPY", "EURUSD=X": "EUR_USD", "GBPUSD=X": "GBP_USD",
    "AUDUSD=X": "AUD_USD", "USDCAD=X": "USD_CAD", "USDCHF=X": "USD_CHF",
    "NZDUSD=X": "NZD_USD", "EURJPY=X": "EUR_JPY", "GBPJPY=X": "GBP_JPY",
    "AUDJPY=X": "AUD_JPY", "CADJPY=X": "CAD_JPY", "CHFJPY=X": "CHF_JPY",
    "GC=F":     "XAU_USD",
}

# OANDA instrument → 価格小数点桁数
_PRICE_PRECISION = {
    "USD_JPY": 3, "EUR_JPY": 3, "GBP_JPY": 3, "AUD_JPY": 3,
    "CAD_JPY": 3, "CHF_JPY": 3, "NZD_JPY": 3,
    "EUR_USD": 5, "GBP_USD": 5, "AUD_USD": 5, "USD_CAD": 5,
    "USD_CHF": 5, "NZD_USD": 5,
    "XAU_USD": 2,  # Gold
}

# OANDA instrument → 1ロット = 何単位
_UNITS_PER_LOT = {
    "XAU_USD": 100,    # 100 troy oz / lot
}


class OandaOrderManager:
    """OANDA プラクティス口座への注文管理クラス。"""

    def __init__(self):
        key      = os.environ.get("OANDA_API_KEY", "")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        practice = os.environ.get("OANDA_PRACTICE", "false").lower() == "true"

        if not practice:
            logger.warning("[OandaOrder] OANDA_PRACTICE=true でないため注文はスキップされます")

        self.enabled = bool(key and self.account_id and practice)
        self.base = "https://api-fxpractice.oanda.com/v3"
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
        }
        self.default_lot = float(os.environ.get("OANDA_DEFAULT_LOT", "0.03"))
        logger.info(
            f"[OandaOrder] enabled={self.enabled} "
            f"account={self.account_id[:8]}... lot={self.default_lot}"
        )

    def supports(self, symbol: str) -> bool:
        return symbol in _INSTRUMENT_MAP

    def _instrument(self, symbol: str) -> str:
        return _INSTRUMENT_MAP[symbol]

    def _precision(self, instrument: str) -> int:
        return _PRICE_PRECISION.get(instrument, 5)

    def _lot_to_units(self, instrument: str, lot: float) -> int:
        """ロット → OANDA units 変換（BUY: 正, SELL: 負）"""
        per_lot = _UNITS_PER_LOT.get(instrument, 100_000)  # FX default 100,000
        return int(lot * per_lot)

    def get_account_balance(self) -> Optional[float]:
        """口座残高を取得（JPY）。"""
        if not self.enabled:
            return None
        try:
            r = requests.get(
                f"{self.base}/accounts/{self.account_id}/summary",
                headers=self.headers, timeout=10
            )
            if r.status_code == 200:
                acc = r.json().get("account", {})
                return float(acc.get("balance", 0))
        except Exception as e:
            logger.error(f"[OandaOrder] 残高取得失敗: {e}")
        return None

    def get_open_positions(self) -> list:
        """OANDA 口座のオープンポジション一覧を返す。"""
        if not self.enabled:
            return []
        try:
            r = requests.get(
                f"{self.base}/accounts/{self.account_id}/openPositions",
                headers=self.headers, timeout=10
            )
            if r.status_code == 200:
                return r.json().get("positions", [])
        except Exception as e:
            logger.error(f"[OandaOrder] ポジション取得失敗: {e}")
        return []

    def place_market_order(
        self,
        symbol:    str,
        direction: str,   # "BUY" | "SELL"
        lot:       float,
        tp_price:  float,
        sl_price:  float,
        comment:   str = "",
    ) -> Optional[dict]:
        """
        成行注文を発注する。TP / SL をサーバーサイドで設定。

        Returns:
            成功時 → {"order_id": str, "units": int, "instrument": str, ...}
            失敗時 → None
        """
        if not self.enabled:
            logger.info("[OandaOrder] 無効 (OANDA_PRACTICE 未設定) — 注文スキップ")
            return None

        if not self.supports(symbol):
            logger.info(f"[OandaOrder] {symbol} は非対応 — スキップ")
            return None

        instrument = self._instrument(symbol)
        prec       = self._precision(instrument)
        units      = self._lot_to_units(instrument, lot)
        if direction == "SELL":
            units = -units

        body = {
            "order": {
                "type":        "MARKET",
                "instrument":  instrument,
                "units":       str(units),
                "timeInForce": "FOK",
                "takeProfitOnFill": {
                    "price": f"{tp_price:.{prec}f}",
                },
                "stopLossOnFill": {
                    "price":       f"{sl_price:.{prec}f}",
                    "timeInForce": "GTC",
                },
            }
        }
        if comment:
            body["order"]["clientExtensions"] = {"comment": comment[:128]}

        try:
            r = requests.post(
                f"{self.base}/accounts/{self.account_id}/orders",
                headers=self.headers,
                json=body,
                timeout=15,
            )
            data = r.json()

            if r.status_code in (200, 201):
                filled = data.get("orderFillTransaction", {})
                trade_id = filled.get("tradeOpened", {}).get("tradeID")
                price    = filled.get("price", "?")
                logger.info(
                    f"[OandaOrder] ✅ {direction} {instrument} "
                    f"{lot}lot @ {price}  TP:{tp_price:.{prec}f}  SL:{sl_price:.{prec}f}  "
                    f"tradeID:{trade_id}"
                )
                return {
                    "order_id":   trade_id,
                    "units":      units,
                    "instrument": instrument,
                    "fill_price": price,
                    "tp":         tp_price,
                    "sl":         sl_price,
                }
            else:
                err = data.get("errorMessage") or data.get("errorCode") or str(data)[:200]
                logger.error(f"[OandaOrder] ✗ 注文失敗 {r.status_code}: {err}")
                return None

        except Exception as e:
            logger.error(f"[OandaOrder] 注文エラー: {e}")
            return None

    def close_trade(self, trade_id: str) -> bool:
        """指定トレードを成行決済する（強制クローズ用）。"""
        if not self.enabled:
            return False
        try:
            r = requests.put(
                f"{self.base}/accounts/{self.account_id}/trades/{trade_id}/close",
                headers=self.headers, timeout=10,
                json={"units": "ALL"},
            )
            ok = r.status_code in (200, 201)
            if ok:
                pnl = r.json().get("orderFillTransaction", {}).get("pl", "?")
                logger.info(f"[OandaOrder] ✅ 決済 tradeID:{trade_id}  P/L:{pnl}")
            else:
                logger.error(f"[OandaOrder] ✗ 決済失敗 {r.status_code}: {r.text[:200]}")
            return ok
        except Exception as e:
            logger.error(f"[OandaOrder] 決済エラー: {e}")
            return False

    def get_trade(self, trade_id: str) -> Optional[dict]:
        """トレード状態を取得する（OPEN / CLOSED 判定用）。"""
        if not self.enabled:
            return None
        try:
            r = requests.get(
                f"{self.base}/accounts/{self.account_id}/trades/{trade_id}",
                headers=self.headers, timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("trade")
        except Exception as e:
            logger.error(f"[OandaOrder] トレード取得失敗: {e}")
        return None
