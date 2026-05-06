from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ExecutionInput:
    symbol: str
    direction: str
    score: float
    rr: float
    is_range: bool
    timing: str
    mtf_confluence_count: int
    current_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    spread: float
    spread_max: float
    daily_lock: bool
    wall_distance: float
    confirmations: int
    pullback_ok: bool
    range_edge_ok: bool
    l_base: float


@dataclass
class ExecutionDecision:
    result: str
    should_trade: bool
    tier: Optional[str]
    route: Optional[str]
    lot: float
    reason: str
    rr: float
    score: float
    confluence: int
    is_range: bool
    log_line: str


@dataclass
class CircuitState:
    global_loss_streak: int = 0
    lock_until: Optional[datetime] = None
