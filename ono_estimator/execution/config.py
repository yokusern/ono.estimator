from dataclasses import dataclass


MIN_RR_HARD = 1.1
MIN_RR_T1 = 1.5
MIN_RR_T2 = 1.3
MIN_RR_T25 = 1.2
MIN_RR_T3 = 1.1

MIN_SCORE_T2 = 30
MIN_SCORE_T25 = 25
MIN_SCORE_T3 = 20

LOT_CAP_MULTIPLIER = 1.5

TIER_MODIFIERS = {
    "TIER1": 1.2,
    "TIER2": 1.0,
    "TIER25": 0.5,
    "TIER3": 0.3,
}

SPREAD_MAX_BY_SYMBOL = {
    "USDJPY": 1.2,
    "EURUSD": 1.0,
    "EURJPY": 1.4,
    "AUDJPY": 1.6,
    "GOLD": 30.0,
    "XAGUSD": 0.12,
    "BTC": 150.0,
    "JP225": 12.0,
}


@dataclass
class CircuitLimits:
    tier_loss_limit: int = 3
    global_loss_limit: int = 5
    lock_hours: int = 24
