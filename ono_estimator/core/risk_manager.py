"""
RiskManager — ギャン理論ルールの組み込み (T-14)
================================================
ルール1:  1回の損失は資金の1/10以下
ルール6:  迷ったらWAIT（矛盾フラグが1つでもあればWAIT）
ルール7:  もみ合い（レンジ）には手を出さない
ルール13: ナンピン禁止
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ono_estimator.core.reasoning_engine import ThinkingResult


class RiskManager:

    def __init__(self, account_balance: float = 100_000.0, risk_ratio: float = 0.10):
        self.account_balance = account_balance
        self.risk_ratio = risk_ratio          # ルール1: 最大損失割合
        self._open_positions: dict = {}       # {symbol: entry_price}

    # ── ルール1: ポジションサイズ計算 ─────────────────────────
    def max_loss_amount(self) -> float:
        """1回の損失上限額"""
        return self.account_balance * self.risk_ratio

    def check_sl_valid(self, entry: float, sl: float, lot: float,
                       pip_value: float = 1000.0) -> tuple[bool, str]:
        """SLが1/10ルール内かチェック。"""
        if entry <= 0 or sl <= 0:
            return True, ""
        pips   = abs(entry - sl)
        loss   = pips * pip_value * lot
        limit  = self.max_loss_amount()
        if loss > limit:
            return False, f"損失額{loss:.0f}円が上限{limit:.0f}円を超過（ルール1違反）"
        return True, ""

    # ── ルール6: 矛盾フラグによる強制WAIT ─────────────────────
    @staticmethod
    def check_conflict_rule(thinking: "ThinkingResult") -> tuple[bool, str]:
        """矛盾フラグが1つでもあれば False を返す（見送り推奨）。"""
        if thinking.conflict_flags:
            flags = ", ".join(thinking.conflict_flags)
            return False, f"迷い要因あり → WAIT推奨（ルール6）: {flags}"
        return True, ""

    # ── ルール7: レンジ相場フィルター ─────────────────────────
    @staticmethod
    def check_range_rule(upper_trend: str, entry_decision: str) -> tuple[bool, str]:
        """上位足RANGEかつBUY/SELLはルール7違反。"""
        if upper_trend == "RANGE" and entry_decision != "WAIT":
            return False, "レンジ相場エントリー禁止（ルール7）"
        return True, ""

    # ── ルール13: ナンピン禁止 ─────────────────────────────────
    def check_nanpin(self, symbol: str, new_direction: str,
                     current_direction: str) -> tuple[bool, str]:
        """同一方向で既にポジション保有中の場合、追加エントリーを禁止。"""
        if symbol in self._open_positions:
            existing = self._open_positions[symbol].get("direction", "")
            if existing == new_direction:
                return False, f"ナンピン禁止（ルール13）: {symbol}は既に{new_direction}ポジションあり"
        return True, ""

    # ── 全ルール一括チェック ──────────────────────────────────
    def evaluate(self, thinking: "ThinkingResult",
                 entry: float = 0.0, sl: float = 0.0,
                 lot: float = 0.01) -> dict:
        """
        全ギャンルールを評価し、エントリー可否と理由を返す。
        戻り値: {"ok": bool, "violations": [str]}
        """
        violations = []

        # ルール6
        ok6, msg6 = self.check_conflict_rule(thinking)
        if not ok6:
            violations.append(msg6)

        # ルール7
        ok7, msg7 = self.check_range_rule(thinking.upper.trend, thinking.entry_decision)
        if not ok7:
            violations.append(msg7)

        # ルール1 (entry/sl が渡された場合のみ)
        if entry > 0 and sl > 0:
            ok1, msg1 = self.check_sl_valid(entry, sl, lot)
            if not ok1:
                violations.append(msg1)

        # ルール13
        ok13, msg13 = self.check_nanpin(
            thinking.symbol, thinking.entry_decision,
            self._open_positions.get(thinking.symbol, {}).get("direction", ""))
        if not ok13:
            violations.append(msg13)

        risk_ok = len(violations) == 0
        return {"ok": risk_ok, "violations": violations}

    # ── ポジション管理 ────────────────────────────────────────
    def open_position(self, symbol: str, direction: str, price: float) -> None:
        self._open_positions[symbol] = {"direction": direction, "price": price}

    def close_position(self, symbol: str) -> None:
        self._open_positions.pop(symbol, None)
