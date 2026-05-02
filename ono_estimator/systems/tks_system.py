from .base import BaseSystem
from ..core.data import MTFData
from ..core.models import SignalStatus, TimeFrame

class TKSSystem(BaseSystem):
    def __init__(self):
        super().__init__("TKS")

    def evaluate(self, mtf_data: MTFData) -> SignalStatus:
        df = mtf_data.get_data(TimeFrame.M15)
        if df is None or len(df) < 4:
            return SignalStatus.NONE

        # 15分足の直近時刻を取得
        # 仮のロジックとして、時刻が09:45であればStandbyとする (10:00にStartになる準備)
        # dfのインデックスがDatetimeIndexであることを想定
        if not hasattr(df.index, 'hour'):
            return SignalStatus.NONE
            
        last_time = df.index[-1]
        
        if last_time.hour == 9 and last_time.minute == 45:
            # 9:00-9:45の4本分のローソク足から高値/安値等を計算して条件判定
            recent_4 = df.iloc[-4:]
            highest = recent_4['high'].max()
            lowest = recent_4['low'].min()
            
            # 条件を満たせばStandby (モック)
            if highest > lowest: 
                return SignalStatus.STANDBY

        return SignalStatus.NONE
