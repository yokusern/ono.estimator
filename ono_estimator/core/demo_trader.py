"""
DemoTrader — エンジン判断でデモポジションを開き、TP/SL/トレーリングで自動決済する。

トレーリングストップ仕様:
  1R到達 (利益 >= SL幅)    : SL → ブレイクイーブン (元本保護)
  2R到達 (利益 >= SL幅×2)  : SL → 高値/安値から 1×SL幅 引いた位置に追随
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# pip サイズ (1 pip の価格変動幅)
_JPY_SYMBOLS = {
    "USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X",
    "CADJPY=X", "CHFJPY=X", "NZDJPY=X",
}


def _pip_size(symbol: str) -> float:
    return 0.01 if symbol in _JPY_SYMBOLS else 0.0001


class DemoTrader:
    def __init__(self, db, on_close=None):
        self.db = db
        self.open_positions: dict = {}
        self.on_close = on_close

    def open_position(self, sym: str, direction: str, entry: float,
                      tp: float, sl: float, reason: str = "", lot: float = 0.1,
                      confidence: str = "") -> bool:
        if sym in self.open_positions:
            return False
        if not entry or not tp or not sl:
            return False
        pos = {
            "symbol":       sym,
            "direction":    direction,
            "entry_price":  entry,
            "tp_price":     tp,
            "sl_price":     sl,
            "lot":          lot,
            "reason":       reason,
            "confidence":   confidence,
            "opened_at":    datetime.now().isoformat(),
            "status":       "OPEN",
            "peak_price":   entry,   # BUY: 価格最高値追跡
            "trough_price": entry,   # SELL: 価格最安値追跡
        }
        self.open_positions[sym] = pos
        try:
            self.db.save_demo_position(pos)
        except Exception as e:
            logger.warning(f"[DemoTrader] DB save failed: {e}")
        logger.info(f"[DemoTrader] OPEN {sym} {direction} @ {entry:.5f}  TP:{tp:.5f}  SL:{sl:.5f}")
        return True

    def check_and_close(self, price_cache: dict, notifier) -> None:
        for sym, pos in list(self.open_positions.items()):
            p = price_cache.get(sym, 0)
            if not p:
                continue

            entry   = pos["entry_price"]
            sl_dist = abs(entry - pos["sl_price"])

            # ─── トレーリングストップ更新 ──────────────────────────
            if sl_dist > 0:
                self._update_trailing(sym, pos, p, sl_dist)

            sl = pos["sl_price"]
            tp = pos["tp_price"]

            # ─── TP/SL ヒット判定 ─────────────────────────────────
            result = None
            if pos["direction"] == "BUY":
                if p >= tp:   result = "WIN"
                elif p <= sl: result = "LOSS"
            else:
                if p <= tp:   result = "WIN"
                elif p >= sl: result = "LOSS"

            if result:
                pips = abs(p - entry) / _pip_size(sym)
                try:
                    win_rate = self.db.close_demo_position(sym, p, result, pips)
                except Exception:
                    win_rate = None
                del self.open_positions[sym]

                try:
                    notifier.send_demo_result(pos, p, result, pips, win_rate)
                except Exception as e:
                    logger.warning(f"[DemoTrader] Notify failed: {e}")
                if self.on_close:
                    try:
                        self.on_close(pos, result)
                    except Exception as e:
                        logger.warning(f"[DemoTrader] on_close callback failed: {e}")
                logger.info(f"[DemoTrader] CLOSE {sym} {result} @ {p:.5f}  pips={pips:.5f}")

    def _update_trailing(self, sym: str, pos: dict, price: float, sl_dist: float) -> None:
        """
        トレーリングストップロジック:
          1R (profit >= sl_dist)   → SL を ブレイクイーブン (entry) へ
          2R (profit >= sl_dist×2) → SL を 高値/安値 - 1×sl_dist へ追随
        """
        entry     = pos["entry_price"]
        direction = pos["direction"]
        new_sl    = pos["sl_price"]

        if direction == "BUY":
            # 高値更新
            if price > pos.get("peak_price", entry):
                pos["peak_price"] = price
            peak   = pos["peak_price"]
            profit = peak - entry

            if profit >= sl_dist * 2.0:
                # 高値から sl_dist 引いた位置にトレーリング
                candidate = round(peak - sl_dist, 5)
                if candidate > pos["sl_price"]:
                    new_sl = candidate
            elif profit >= sl_dist and pos["sl_price"] < entry:
                # ブレイクイーブン
                new_sl = entry

        else:  # SELL
            # 安値更新
            if price < pos.get("trough_price", entry):
                pos["trough_price"] = price
            trough = pos["trough_price"]
            profit = entry - trough

            if profit >= sl_dist * 2.0:
                # 安値から sl_dist 上げた位置にトレーリング
                candidate = round(trough + sl_dist, 5)
                if candidate < pos["sl_price"]:
                    new_sl = candidate
            elif profit >= sl_dist and pos["sl_price"] > entry:
                # ブレイクイーブン
                new_sl = entry

        if new_sl != pos["sl_price"]:
            label = "BE" if new_sl == entry else "TRAIL"
            logger.info(f"[Trail:{label}] {sym} {direction}  SL {pos['sl_price']:.5f} → {new_sl:.5f}")
            pos["sl_price"] = new_sl
            try:
                self.db.update_demo_sl(sym, new_sl)
            except Exception:
                pass

    def get_open_positions(self) -> dict:
        return dict(self.open_positions)
