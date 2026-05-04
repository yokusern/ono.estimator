from typing import Dict, Any, Optional
import pandas as pd
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import TechnicalIndicators

class MomentumFilter:
    """Layer 2: 1H/15mのMACD同期、BBスコアリング、RSI過熱感"""

    def evaluate(self, mtf_data: MTFData) -> Dict[str, Any]:
        df_h1  = mtf_data.get_data(TimeFrame.H1)
        df_m15 = mtf_data.get_data(TimeFrame.M15)

        result = {
            "sync_direction": "NONE",
            "is_expansion":   False,
            "rsi_state":      "NEUTRAL",
            "rsi_15m":        50.0,
            "rsi_1h":         50.0,
            "hist_h1":        0.0,
            "hist_15m":       0.0,
            "reason":         "",
        }

        if df_h1 is None or df_m15 is None or len(df_h1) < 30 or len(df_m15) < 30:
            return result

        # MACD
        macd_h1  = TechnicalIndicators.macd(df_h1['close'])
        macd_m15 = TechnicalIndicators.macd(df_m15['close'])
        hist_h1  = float(macd_h1['hist'].iloc[-1])
        hist_m15 = float(macd_m15['hist'].iloc[-1])
        result['hist_h1']  = hist_h1
        result['hist_15m'] = hist_m15

        if hist_h1 > 0 and hist_m15 > 0:
            result['sync_direction'] = "UP"
        elif hist_h1 < 0 and hist_m15 < 0:
            result['sync_direction'] = "DOWN"

        # BBエクスパンション (15m)
        bb_m15   = TechnicalIndicators.bollinger_bands(df_m15['close'])
        width_m15 = bb_m15['upper'] - bb_m15['lower']
        if (width_m15.diff().iloc[-5:] > 0).all():
            result['is_expansion'] = True

        # RSI (15m + 1H)
        rsi_m15 = TechnicalIndicators.rsi(df_m15['close'])
        rsi_h1  = TechnicalIndicators.rsi(df_h1['close'])
        last_rsi_15m = float(rsi_m15.iloc[-1])
        last_rsi_1h  = float(rsi_h1.iloc[-1])
        result['rsi_15m'] = round(last_rsi_15m, 1)
        result['rsi_1h']  = round(last_rsi_1h, 1)

        if last_rsi_15m >= 70:
            result['rsi_state'] = "OVERBOUGHT"
        elif last_rsi_15m <= 30:
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

    def _calc_bb_score(self, df_15m: pd.DataFrame, df_1h: pd.DataFrame,
                       df_4h: Optional[pd.DataFrame]) -> dict:
        """BBスコアリング完全版（最大83点）H-5"""
        score = 0
        reasons = []
        bb_4h_dir  = "FLAT"
        bb_15m_dir = "FLAT"
        squeezed_val   = 0.0
        expanding_val  = 0.0

        try:
            bb_15m = TechnicalIndicators.bollinger_bands(df_15m['close'], 20, 2.0)
            bb_1h  = TechnicalIndicators.bollinger_bands(df_1h['close'],  20, 2.0)
            width_15m = bb_15m['upper'] - bb_15m['lower']
            width_1h  = bb_1h['upper']  - bb_1h['lower']

            # ① エクスパンション継続（15m 直近5本全て拡大）: +12点
            if len(width_15m) >= 6 and (width_15m.diff().iloc[-5:] > 0).all():
                score += 12
                reasons.append("BB15mエクスパンション継続中(+12)")

            # ② スクイーズ→爆発（直前3本収縮→直近2本で130%超拡大）: +18点
            if len(width_15m) >= 6:
                squeezed_val  = float(width_15m.iloc[-6:-3].mean())
                expanding_val = float(width_15m.iloc[-2:].mean())
                if squeezed_val > 0 and expanding_val > squeezed_val * 1.3:
                    score += 18
                    reasons.append("🔥 BBスクイーズ解放・ブレイクアウト検知(+18)")

            # ③ 1Hバンドウォーク（直近4本が±1σ以上を維持）: +15点
            if len(bb_1h) >= 6:
                std_1h   = bb_1h['std'].iloc[-5:-1]
                basis_1h = bb_1h['basis'].iloc[-5:-1]
                c_1h     = df_1h['close'].iloc[-5:-1]
                if (c_1h > basis_1h + std_1h).all():
                    score += 15
                    reasons.append("1Hバンドウォーク上昇中(+15)")
                elif (c_1h < basis_1h - std_1h).all():
                    score += 15
                    reasons.append("1Hバンドウォーク下降中(+15)")

            # ④ BB±2σ実タッチ + 反転ローソク（15m）: +20点
            if len(df_15m) >= 3:
                last_close = float(df_15m['close'].iloc[-2])
                last_open  = float(df_15m['open'].iloc[-2])
                upper_2s   = float(bb_15m['upper'].iloc[-2])
                lower_2s   = float(bb_15m['lower'].iloc[-2])
                if last_close <= lower_2s * 1.002 and last_close > last_open:
                    score += 20
                    reasons.append("🎯 BB-2σ実タッチ＋陽線反転(+20)")
                elif last_close >= upper_2s * 0.998 and last_close < last_open:
                    score += 20
                    reasons.append("🎯 BB+2σ実タッチ＋陰線反転(+20)")

            # ⑤ 4H/15m BB方向一致（上位足フィルター）: +10点
            if df_4h is not None and len(df_4h) >= 3:
                bb_4h = TechnicalIndicators.bollinger_bands(df_4h['close'], 20, 2.0)
                bb_4h_dir  = "UP" if float(bb_4h['basis'].iloc[-1])  > float(bb_4h['basis'].iloc[-2])  else "DOWN"
                bb_15m_dir = "UP" if float(bb_15m['basis'].iloc[-1]) > float(bb_15m['basis'].iloc[-2]) else "DOWN"
                if bb_4h_dir == bb_15m_dir:
                    score += 10
                    reasons.append(f"4H/15m BB方向一致({bb_4h_dir})(+10)")
            elif len(bb_15m) >= 3:
                bb_15m_dir = "UP" if float(bb_15m['basis'].iloc[-1]) > float(bb_15m['basis'].iloc[-2]) else "DOWN"

            # ⑥ 1H幅が過去20本平均の50%以下（超収縮）: +8点
            if len(width_1h) >= 21:
                avg_width_1h = float(width_1h.rolling(20).mean().iloc[-1])
                if avg_width_1h > 0 and float(width_1h.iloc[-1]) < avg_width_1h * 0.5:
                    score += 8
                    reasons.append("1H BB超収縮→ブレイク待機(+8)")

        except Exception as e:
            print(f"[BBScore] Error: {e}")

        return {
            "bb_score":        min(score, 83),
            "bb_reasons":      reasons,
            "bb_4h_dir":       bb_4h_dir,
            "bb_15m_dir":      bb_15m_dir,
            "squeeze_released": (squeezed_val > 0 and expanding_val > squeezed_val * 1.3),
        }
