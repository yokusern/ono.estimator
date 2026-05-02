from typing import Dict, Any
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import TechnicalIndicators, PriceAction

class TriggerFilter:
    """Layer 3: 短期足(5m/15m)のプライスアクション、バンドウォーク"""
    
    def evaluate(self, mtf_data: MTFData) -> Dict[str, Any]:
        df = mtf_data.get_data(TimeFrame.M5)
        if df is None or len(df) < 20:
            df = mtf_data.get_data(TimeFrame.M15)
            
        result = {
            "pa": "None",
            "is_band_walk": False,
            "reason": ""
        }
        
        if df is None or len(df) < 20:
            return result
            
        reasons = []
        
        # 直近2本の確定足
        curr_row = df.iloc[-2]
        prev_row = df.iloc[-3]
        
        # ピンバー判定
        is_pin, pin_type = PriceAction.is_pin_bar(
            curr_row['open'], curr_row['high'], curr_row['low'], curr_row['close']
        )
        if is_pin:
            result['pa'] = pin_type + " PinBar"
            reasons.append(f"PA:{result['pa']}")
            
        # 包み足判定
        is_engulfing, engulfing_type = PriceAction.is_engulfing(
            prev_row['open'], prev_row['close'], curr_row['open'], curr_row['close']
        )
        if is_engulfing:
            result['pa'] = engulfing_type + " Engulfing"
            reasons.append(f"PA:{result['pa']}")
            
        # バンドウォーク判定 (確定足の直近3本がBB+1σ以上、または-1σ以下)
        bb = TechnicalIndicators.bollinger_bands(df['close'])
        std = bb['std'].iloc[-4:-1]
        basis = bb['basis'].iloc[-4:-1]
        closes = df['close'].iloc[-4:-1]
        
        if (closes > basis + std).all():
            result['is_band_walk'] = True
            reasons.append("上方バンドウォーク中")
        elif (closes < basis - std).all():
            result['is_band_walk'] = True
            reasons.append("下方バンドウォーク中")
            
        result['reason'] = "、".join(reasons)
        return result
