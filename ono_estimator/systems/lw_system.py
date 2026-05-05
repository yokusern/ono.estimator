from .base import BaseSystem
from ..core.data import MTFData
from ..core.models import SignalStatus, TimeFrame
from ..indicators.technical import TechnicalIndicators


class LWSystem(BaseSystem):
    """1-1: 条件緩和版 LWSystem（RSI閾値拡大 + MA接近中でSTANDBY）"""

    def __init__(self):
        super().__init__("LW")
        self.ma_short = 25
        self.ma_long = 75
        self.rsi_period = 14

    def evaluate(self, mtf_data: MTFData) -> SignalStatus:
        df = mtf_data.get_data(TimeFrame.M5)
        if df is None or len(df) < self.ma_long:
            return SignalStatus.NONE

        ma25 = TechnicalIndicators.sma(df["close"], self.ma_short)
        ma75 = TechnicalIndicators.sma(df["close"], self.ma_long)
        rsi  = TechnicalIndicators.rsi(df["close"], self.rsi_period)

        last_rsi  = float(rsi.iloc[-2])
        last_ma25 = float(ma25.iloc[-2])
        last_ma75 = float(ma75.iloc[-2])
        prev_ma25 = float(ma25.iloc[-3])
        prev_ma75 = float(ma75.iloc[-3])

        is_dead_cross   = prev_ma25 >= prev_ma75 and last_ma25 < last_ma75
        is_golden_cross = prev_ma25 <= prev_ma75 and last_ma25 > last_ma75

        # MA接近中（差が前本より縮まっている）
        gap_now  = abs(last_ma25 - last_ma75)
        gap_prev = abs(prev_ma25 - prev_ma75)
        is_approaching_bull = last_ma25 < last_ma75 and gap_now < gap_prev  # DC前の接近
        is_approaching_bear = last_ma25 > last_ma75 and gap_now < gap_prev  # GC前の接近

        last_open  = float(df["open"].iloc[-2])
        last_close = float(df["close"].iloc[-2])
        is_bull_candle = last_close > last_open
        is_bear_candle = last_close < last_open

        # Buy条件1: RSI≤40 + デッドクロス + 陽線（緩和）
        if last_rsi <= 40 and is_dead_cross and is_bull_candle:
            return SignalStatus.STANDBY

        # Buy条件2: RSI≤40 + MA接近中（クロス前）
        if last_rsi <= 40 and is_approaching_bull:
            return SignalStatus.STANDBY

        # Buy代替条件: RSI≤35 + MA25 > MA75（上昇環境）
        if last_rsi <= 35 and last_ma25 > last_ma75:
            return SignalStatus.STANDBY

        # Sell条件1: RSI≥60 + ゴールデンクロス + 陰線（緩和）
        if last_rsi >= 60 and is_golden_cross and is_bear_candle:
            return SignalStatus.STANDBY

        # Sell条件2: RSI≥60 + MA接近中（クロス前）
        if last_rsi >= 60 and is_approaching_bear:
            return SignalStatus.STANDBY

        # Sell代替条件: RSI≥65 + MA25 < MA75（下降環境）
        if last_rsi >= 65 and last_ma25 < last_ma75:
            return SignalStatus.STANDBY

        return SignalStatus.NONE
