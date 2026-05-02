from typing import Dict, Any
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import DowTheory, TechnicalIndicators

class EnvironmentFilter:
    """Layer 1: 日足/4Hのダウ理論、200SMAの位置、日足BBの向き"""
    
    def evaluate(self, mtf_data: MTFData) -> Dict[str, Any]:
        df_d1 = mtf_data.get_data(TimeFrame.D1)
        df_h4 = mtf_data.get_data(TimeFrame.H4)
        
        result = {
            "trend": "RANGE",
            "score": 50,
            "reason": "データ不足または明確なトレンドなし"
        }
        
        if df_d1 is None or len(df_d1) < 200:
            return result
            
        # 200SMA
        ma200_d1 = TechnicalIndicators.sma(df_d1['close'], 200)
        last_ma200 = ma200_d1.iloc[-1]
        last_close_d1 = df_d1['close'].iloc[-1]
        
        # ボリンジャーバンド
        bb_d1 = TechnicalIndicators.bollinger_bands(df_d1['close'], 20, 2.0)
        last_bb_basis = bb_d1['basis'].iloc[-1]
        prev_bb_basis = bb_d1['basis'].iloc[-2]
        
        bb_direction = "UP" if last_bb_basis > prev_bb_basis else "DOWN"
        
        # ダウ理論 (簡易的に計算)
        df_d1_dow = DowTheory.calculate_swing_high_low(df_d1.copy())
        dow_trend_d1 = df_d1_dow['dow_trend'].iloc[-1]
        
        reasons = []
        
        is_up_trend = False
        is_down_trend = False
        
        if last_close_d1 > last_ma200:
            reasons.append("日足200SMAより上")
            if dow_trend_d1 == "UP":
                reasons.append("日足ダウ理論上昇トレンド")
                if bb_direction == "UP":
                    reasons.append("日足BB上向き")
                    is_up_trend = True
        elif last_close_d1 < last_ma200:
            reasons.append("日足200SMAより下")
            if dow_trend_d1 == "DOWN":
                reasons.append("日足ダウ理論下降トレンド")
                if bb_direction == "DOWN":
                    reasons.append("日足BB下向き")
                    is_down_trend = True
                    
        if is_up_trend:
            result["trend"] = "UP"
            result["score"] = 80
            result["reason"] = "、".join(reasons)
        elif is_down_trend:
            result["trend"] = "DOWN"
            result["score"] = 80
            result["reason"] = "、".join(reasons)
        else:
            result["reason"] = "、".join(reasons) if reasons else "明確なトレンドなし"
            
        return result
