from typing import Dict, Any
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import TechnicalIndicators

class MomentumFilter:
    """Layer 2: 1H/15mのMACD同期、BBエクスパンション、RSI過熱感"""
    
    def evaluate(self, mtf_data: MTFData) -> Dict[str, Any]:
        df_h1 = mtf_data.get_data(TimeFrame.H1)
        df_m15 = mtf_data.get_data(TimeFrame.M15)
        
        result = {
            "sync_direction": "NONE",
            "is_expansion": False,
            "rsi_state": "NEUTRAL",
            "reason": ""
        }
        
        if df_h1 is None or df_m15 is None or len(df_h1) < 30 or len(df_m15) < 30:
            return result
            
        # MACD
        macd_h1 = TechnicalIndicators.macd(df_h1['close'])
        macd_m15 = TechnicalIndicators.macd(df_m15['close'])
        
        # MACDがゼロラインより上か下か、またはヒストグラムの方向
        hist_h1 = macd_h1['hist'].iloc[-1]
        hist_m15 = macd_m15['hist'].iloc[-1]
        
        if hist_h1 > 0 and hist_m15 > 0:
            result['sync_direction'] = "UP"
        elif hist_h1 < 0 and hist_m15 < 0:
            result['sync_direction'] = "DOWN"
            
        # BBエクスパンション (15mで判定)
        bb_m15 = TechnicalIndicators.bollinger_bands(df_m15['close'])
        width_m15 = bb_m15['upper'] - bb_m15['lower']
        # 直近5本のバンド幅が拡大しているか
        width_diff = width_m15.diff().iloc[-5:]
        if (width_diff > 0).all():
            result['is_expansion'] = True
            
        # RSI過熱感 (15m)
        rsi_m15 = TechnicalIndicators.rsi(df_m15['close'])
        last_rsi = rsi_m15.iloc[-1]
        if last_rsi >= 70:
            result['rsi_state'] = "OVERBOUGHT"
        elif last_rsi <= 30:
            result['rsi_state'] = "OVERSOLD"
            
        reasons = []
        if result['sync_direction'] != "NONE":
            reasons.append(f"MACD(1H/15m)同期:{result['sync_direction']}")
        if result['is_expansion']:
            reasons.append("BBエクスパンション発生中")
        if result['rsi_state'] != "NEUTRAL":
            reasons.append(f"RSI:{result['rsi_state']}")
            
        result['reason'] = "、".join(reasons)
        return result
