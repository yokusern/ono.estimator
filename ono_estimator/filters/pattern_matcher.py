from typing import List
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import TechnicalIndicators, PriceAction

class IronPatternMatcher:
    """インジケータの掛け合わせによる鉄板パターンの抽出"""
    
    def find_patterns(self, mtf_data: MTFData) -> List[str]:
        patterns = []
        df = mtf_data.get_data(TimeFrame.M15)
        
        if df is None or len(df) < 200:
            return patterns
            
        # 計算
        bb = TechnicalIndicators.bollinger_bands(df['close'])
        macd = TechnicalIndicators.macd(df['close'])
        ma200 = TechnicalIndicators.sma(df['close'], 200)
        
        last_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # [BB × MACD]: エクスパンション ＋ MACD 0ライン突破
        width = bb['upper'] - bb['lower']
        width_diff = width.diff().iloc[-3:]
        is_expansion = (width_diff > 0).all()
        
        macd_line = macd['macd'].iloc[-1]
        prev_macd = macd['macd'].iloc[-2]
        macd_cross_0 = (prev_macd < 0 and macd_line > 0) or (prev_macd > 0 and macd_line < 0)
        
        if is_expansion and macd_cross_0:
            patterns.append("#BB_MACD_Cross")
            
        # [MA(200) × BB]: 長期MA付近でのBB-2σタッチ ＋ 反転ローソク
        last_ma200 = ma200.iloc[-1]
        last_bb_lower = bb['lower'].iloc[-1]
        last_bb_upper = bb['upper'].iloc[-1]
        
        # MA200付近 (価格差が1%以内など簡易的に判定)
        is_near_ma200 = abs(last_close - last_ma200) / last_ma200 < 0.01
        
        # 反転ローソク (ピンバーまたは包み足)
        curr_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        is_pin, _ = PriceAction.is_pin_bar(curr_row['open'], curr_row['high'], curr_row['low'], curr_row['close'])
        is_engulfing, _ = PriceAction.is_engulfing(prev_row['open'], prev_row['close'], curr_row['open'], curr_row['close'])
        is_reversal = is_pin or is_engulfing
        
        # 下限タッチ
        is_touch_lower = last_close <= last_bb_lower * 1.001
        # 上限タッチ
        is_touch_upper = last_close >= last_bb_upper * 0.999
        
        if is_near_ma200 and is_touch_lower and is_reversal:
            patterns.append("#MA200_BB_Reversal_Bullish")
        elif is_near_ma200 and is_touch_upper and is_reversal:
            patterns.append("#MA200_BB_Reversal_Bearish")
            
        return patterns
