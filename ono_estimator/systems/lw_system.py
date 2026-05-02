from .base import BaseSystem
from ..core.data import MTFData
from ..core.models import SignalStatus, TimeFrame
from ..indicators.technical import TechnicalIndicators

class LWSystem(BaseSystem):
    def __init__(self):
        super().__init__("LW")
        self.ma_short = 25
        self.ma_long = 75
        self.rsi_period = 14

    def evaluate(self, mtf_data: MTFData) -> SignalStatus:
        df = mtf_data.get_data(TimeFrame.M5)
        if df is None or len(df) < self.ma_long:
            return SignalStatus.NONE

        ma25 = TechnicalIndicators.sma(df['close'], self.ma_short)
        ma75 = TechnicalIndicators.sma(df['close'], self.ma_long)
        rsi = TechnicalIndicators.rsi(df['close'], self.rsi_period)
        
        # 確定足(-2)と、その前の足(-3)
        last_rsi = rsi.iloc[-2]
        
        # クロス判定 (前回と今回でMAの上下関係が変わったか)
        last_ma25 = ma25.iloc[-2]
        last_ma75 = ma75.iloc[-2]
        prev_ma25 = ma25.iloc[-3]
        prev_ma75 = ma75.iloc[-3]
        
        is_dead_cross = prev_ma25 >= prev_ma75 and last_ma25 < last_ma75
        is_golden_cross = prev_ma25 <= prev_ma75 and last_ma25 > last_ma75
        
        # 反発の確認 (直近の足が陽線か陰線か)
        last_open = df['open'].iloc[-2]
        last_close = df['close'].iloc[-2]
        is_bull_candle = last_close > last_open
        is_bear_candle = last_close < last_open

        # Buy条件: RSI<=30, デッドクロス発生, 反発(陽線)
        if last_rsi <= 30 and is_dead_cross and is_bull_candle:
            return SignalStatus.STANDBY
            
        # Sell条件: RSI>=70, ゴールデンクロス発生, 反発(陰線)
        if last_rsi >= 70 and is_golden_cross and is_bear_candle:
            return SignalStatus.STANDBY

        return SignalStatus.NONE
