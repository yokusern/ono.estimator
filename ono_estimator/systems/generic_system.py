"""
GenericSystem — GOLD・BTC・XAGUSD・EURUSD・AUDJPY・EURJPY 汎用システム (1-2)
=============================================================================
判定ロジック: 200SMA位置 + RSI(14) + MACDクロス の3条件
"""
from .base import BaseSystem
from ..core.data import MTFData
from ..core.models import SignalStatus, TimeFrame
from ..indicators.technical import TechnicalIndicators


class GenericSystem(BaseSystem):

    def __init__(self):
        super().__init__("Generic")

    def evaluate(self, mtf_data: MTFData) -> SignalStatus:
        df = mtf_data.get_data(TimeFrame.H1)
        if df is None or len(df) < 200:
            # 1H足が足りなければ15m足で試みる
            df = mtf_data.get_data(TimeFrame.M15)
        if df is None or len(df) < 200:
            return SignalStatus.NONE

        close = df["close"]
        ma200 = TechnicalIndicators.sma(close, 200)
        rsi   = TechnicalIndicators.rsi(close, 14)
        macd_df = TechnicalIndicators.macd(close)

        cur_price  = float(close.iloc[-1])
        cur_ma200  = float(ma200.iloc[-1])
        cur_rsi    = float(rsi.iloc[-2])

        macd_line  = macd_df["macd"]
        prev_macd  = float(macd_line.iloc[-3])
        last_macd  = float(macd_line.iloc[-2])
        macd_above_zero = last_macd > 0
        macd_below_zero = last_macd < 0
        is_gc = prev_macd < 0 and last_macd >= 0   # ゼロライン上抜けGC
        is_dc = prev_macd > 0 and last_macd <= 0   # ゼロライン下抜けDC

        above_ma200 = cur_price > cur_ma200
        below_ma200 = cur_price < cur_ma200
        rsi_neutral = 40 <= cur_rsi <= 60

        # BUY_START: 200SMA上 + RSI中立 + MACDゴールデンクロス
        if above_ma200 and rsi_neutral and is_gc:
            return SignalStatus.BUY_START

        # BUY_STANDBY: 200SMA上 + RSI中立 + MACDがゼロライン上
        if above_ma200 and rsi_neutral and macd_above_zero:
            return SignalStatus.BUY_STANDBY

        # SELL_START: 200SMA下 + RSI中立 + MACDデッドクロス
        if below_ma200 and rsi_neutral and is_dc:
            return SignalStatus.SELL_START

        # SELL_STANDBY: 200SMA下 + RSI中立 + MACDがゼロライン下
        if below_ma200 and rsi_neutral and macd_below_zero:
            return SignalStatus.SELL_STANDBY

        return SignalStatus.NONE
