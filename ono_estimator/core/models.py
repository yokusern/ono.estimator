from enum import Enum
from typing import List

class TimeFrame(Enum):
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1wk"

class SignalStatus(Enum):
    NONE = "Wait"
    STANDBY = "Standby"
    BUY_STANDBY = "Buy_Standby"
    SELL_STANDBY = "Sell_Standby"
    BUY_START = "Buy Start"
    SELL_START = "Sell Start"
    STAY = "Stay"
    WIN_FINISH = "Win Finish"
    LOSS_FINISH = "Stop Loss Finish"

class PredictionResult:
    def __init__(self):
        self.status: SignalStatus = SignalStatus.NONE
        self.base_system: str = ""
        self.win_rate_score: float = 0.0
        self.rationale_a: str = ""
        self.rationale_b: str = ""
        self.caution: str = ""
        self.tags: List[str] = []
        # 3-1: TP/SL自動計算フィールド
        self.tp_price: float = 0.0
        self.sl_price: float = 0.0
        self.risk_reward: float = 0.0

    def __repr__(self):
        return f"<PredictionResult status={self.status.value} system={self.base_system} score={self.win_rate_score} tags={self.tags}>"
