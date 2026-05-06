from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from .config import (
    MIN_RR_HARD,
    MIN_RR_T1,
    MIN_RR_T2,
    MIN_RR_T25,
    MIN_RR_T3,
    MIN_SCORE_T2,
    MIN_SCORE_T25,
    MIN_SCORE_T3,
    LOT_CAP_MULTIPLIER,
    TIER_MODIFIERS,
    CircuitLimits,
)
from .models import ExecutionDecision, ExecutionInput, CircuitState


class ExecutionEngine:
    def __init__(self):
        self.limits = CircuitLimits()
        self.circuit = CircuitState()
        self.tier_loss_streak: Dict[str, int] = {"TIER1": 0, "TIER2": 0, "TIER25": 0, "TIER3": 0}
        self.tier_pause_until: Dict[str, Optional[datetime]] = {"TIER1": None, "TIER2": None, "TIER25": None, "TIER3": None}

    def _log(self, result: str, route: str, reason: str, i: ExecutionInput, lot: float = 0.0, tier: Optional[str] = None) -> ExecutionDecision:
        tier_name = tier or result
        line = (
            "[ONO Estimator 判断ログ]\n"
            f"Result: {tier_name if result != 'NO_TRADE' else f'NO TRADE({reason})'}\n"
            f"Route: {route}\n"
            f"Detail: RR: {i.rr:.2f}, Score: {i.score:.1f}, Lot: {lot:.3f}\n"
            f"Status: MTF: {i.mtf_confluence_count}/6, Range: {i.is_range}\n"
            f"Reason: {reason}"
        )
        return ExecutionDecision(
            result=result,
            should_trade=(result != "NO_TRADE"),
            tier=tier,
            route=route,
            lot=lot,
            reason=reason,
            rr=i.rr,
            score=i.score,
            confluence=i.mtf_confluence_count,
            is_range=i.is_range,
            log_line=line,
        )

    def evaluate(self, i: ExecutionInput) -> ExecutionDecision:
        now = datetime.now(timezone.utc)
        if self.circuit.lock_until and now < self.circuit.lock_until:
            return self._log("NO_TRADE", "-", "Circuit Breaker global lock active", i)

        # STEP 0 Hard Reject
        if i.rr <= 0 or i.rr < MIN_RR_HARD:
            return self._log("NO_TRADE", "-", "RR hard reject (<1.1 or invalid)", i)
        if i.spread > i.spread_max:
            return self._log("NO_TRADE", "-", f"Spread reject ({i.spread:.2f}>{i.spread_max:.2f})", i)
        sl_width = abs(i.entry_price - i.stop_loss) if i.entry_price and i.stop_loss else 0.0
        if sl_width <= 0:
            return self._log("NO_TRADE", "-", "SL width invalid", i)
        if i.wall_distance <= sl_width * 0.5:
            return self._log("NO_TRADE", "-", "Wall proximity reject", i)
        if i.daily_lock:
            return self._log("NO_TRADE", "-", "Daily lock active", i)

        # STEP 1 Route restriction
        allowed = {"D"} if i.is_range else {"A", "B", "C"}
        route = "D" if i.is_range else ("A" if i.mtf_confluence_count >= 6 else "C" if i.timing == "NOW" else "B")
        if route not in allowed:
            return self._log("NO_TRADE", route, "Route mismatch with environment", i)

        # STEP 2 Tier matrix
        tier = None
        if route == "A" and i.mtf_confluence_count >= 6 and i.pullback_ok and i.rr >= MIN_RR_T1:
            tier = "TIER1"
        elif route in {"A", "B", "C"} and i.score >= MIN_SCORE_T2 and i.rr >= MIN_RR_T2 and i.confirmations >= 1:
            tier = "TIER2"
        elif route in {"A", "B", "C"} and i.score >= MIN_SCORE_T25 and i.rr >= MIN_RR_T25 and i.confirmations >= 1:
            tier = "TIER25"
        elif route == "D" and i.timing == "NOW" and i.score >= MIN_SCORE_T3 and i.range_edge_ok and i.rr >= MIN_RR_T3:
            tier = "TIER3"
        if not tier:
            return self._log("NO_TRADE", route, "Tier conditions not satisfied", i)

        # STEP 4 Circuit breaker tier pause
        t_pause = self.tier_pause_until.get(tier)
        if t_pause and now < t_pause:
            return self._log("NO_TRADE", route, f"{tier} paused after losing streak", i)

        # STEP 3 Dynamic sizing
        tier_mod = TIER_MODIFIERS.get(tier, 1.0)
        lot = i.l_base * (0.5 + abs(i.score) / 100.0) * tier_mod
        lot = min(lot, i.l_base * LOT_CAP_MULTIPLIER)

        return self._log("TRADE", route, "Execution conditions passed", i, lot=lot, tier=tier)

    def record_result(self, tier: Optional[str], outcome: str):
        if not tier:
            return
        now = datetime.now(timezone.utc)
        if outcome == "LOSS":
            self.tier_loss_streak[tier] = self.tier_loss_streak.get(tier, 0) + 1
            self.circuit.global_loss_streak += 1
            if self.tier_loss_streak[tier] >= self.limits.tier_loss_limit:
                self.tier_pause_until[tier] = now + timedelta(hours=self.limits.lock_hours)
                self.tier_loss_streak[tier] = 0
            if self.circuit.global_loss_streak >= self.limits.global_loss_limit:
                self.circuit.lock_until = now + timedelta(hours=self.limits.lock_hours)
                self.circuit.global_loss_streak = 0
        elif outcome == "WIN":
            self.tier_loss_streak[tier] = 0
            self.circuit.global_loss_streak = 0
