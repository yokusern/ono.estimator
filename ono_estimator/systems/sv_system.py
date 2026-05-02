from .base import BaseSystem
from ..core.data import MTFData
from ..core.models import SignalStatus, TimeFrame
from ..indicators.technical import TechnicalIndicators

class SVSystem(BaseSystem):
    def __init__(self):
        super().__init__("SV")
        self.ma_period = 2880
        self.env_period = 14
        self.env_dev = 0.1

    def evaluate(self, mtf_data: MTFData) -> SignalStatus:
        df = mtf_data.get_data(TimeFrame.M5)
        if df is None or len(df) < self.ma_period:
            return SignalStatus.NONE

        # インジケータ計算 (実運用では外部で事前計算して使い回す方が効率的)
        ma2880 = TechnicalIndicators.sma(df['close'], self.ma_period)
        env = TechnicalIndicators.envelope(df['close'], self.env_period, self.env_dev)
        
        # 確定足の厳守: -1は形成中の足の可能性があるため、-2(確定した直近の足)と-3(その前の足)を見る
        last_close = df['close'].iloc[-2]
        prev_close = df['close'].iloc[-3]
        
        last_ma = ma2880.iloc[-2]
        
        last_env_lower = env['lower'].iloc[-2]
        prev_env_lower = env['lower'].iloc[-3]
        
        last_env_upper = env['upper'].iloc[-2]
        prev_env_upper = env['upper'].iloc[-3]

        # Buy条件: 2880MAより下、前回が下限を下抜け、今回が下限を上抜け
        if last_close < last_ma:
            if prev_close < prev_env_lower and last_close > last_env_lower:
                return SignalStatus.STANDBY
                
        # Sell条件: 2880MAより上、前回が上限を上抜け、今回が上限を下抜け
        if last_close > last_ma:
            if prev_close > prev_env_upper and last_close < last_env_upper:
                return SignalStatus.STANDBY
                
        return SignalStatus.NONE
