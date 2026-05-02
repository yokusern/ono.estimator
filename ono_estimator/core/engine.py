import pandas as pd
from typing import Dict, Optional
from .models import PredictionResult, SignalStatus, TimeFrame
from .data import MTFData
from ..systems import SVSystem, LWSystem, TKSSystem
from ..filters import EnvironmentFilter, MomentumFilter, TriggerFilter, IronPatternMatcher

class ONOPredictionEngine:
    """すべてのデータを統合し、最終的な予測結果を生成するメインエンジン"""
    
    def __init__(self):
        # 1. 基盤システム
        self.systems = [SVSystem(), LWSystem(), TKSSystem()]
        
        # 2. 3層フィルター & パターン
        self.env_filter = EnvironmentFilter()
        self.momentum_filter = MomentumFilter()
        self.trigger_filter = TriggerFilter()
        self.pattern_matcher = IronPatternMatcher()

    def analyze(self, mtf_data: MTFData = None, symbol: str = "USDJPY", funda_info: dict = None, df_precomputed: pd.DataFrame = None) -> PredictionResult:
        result = PredictionResult()
        
        # mtf_data がなく、計算済みデータがある場合はモック作成
        if mtf_data is None and df_precomputed is not None:
            # 簡易判定ロジック（df_precomputedを使用）
            latest = df_precomputed.iloc[-1]
            rsi = latest.get('rsi', 0)
            macd = latest.get('macd', 0)
            
            result.win_rate_score = 50 # デフォルト
            if rsi > 50: result.win_rate_score += 10
            if macd > 0: result.win_rate_score += 10
            result.status = SignalStatus.STANDBY
            result.rationale_a = "【Ultra Engine】一括計算データに基づき分析完了。"
            result.rationale_b = f"RSI: {rsi:.1f} / MACD: {macd:.4f}"
            return result

        if funda_info is None:
            funda_info = {"direction": "NEUTRAL", "reason": "No funda data"}
        
        # STEP 1: 基盤システムによる基本判定
        active_systems = []
        for sys in self.systems:
            if symbol == "USDJPY" and sys.name not in ["SV", "LW"]:
                continue
            if symbol == "JP225" and sys.name != "TKS":
                continue
            if symbol in ["GOLD", "BTC", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"]:
                continue 
                
            status = sys.evaluate(mtf_data)
            if status in [SignalStatus.STANDBY, SignalStatus.BUY_START, SignalStatus.SELL_START]:
                active_systems.append(sys.name)
        
        if active_systems:
            result.base_system = ",".join(active_systems)
        else:
            result.base_system = "AI"
            
        # STEP 2: AI 3層フィルターの適用
        env_state = self.env_filter.evaluate(mtf_data)
        mom_state = self.momentum_filter.evaluate(mtf_data)
        trig_state = self.trigger_filter.evaluate(mtf_data)
        
        # STEP 3: 鉄板パターンの確認
        iron_patterns = self.pattern_matcher.find_patterns(mtf_data)

        # STEP 4: 総合評価
        base_score = 50
        if env_state.get("trend") != "RANGE": base_score += 10
        if mom_state.get("sync_direction") != "NONE": base_score += 10
        if mom_state.get("is_expansion"): base_score += 5
        if trig_state.get("pa") != "None": base_score += 10
            
        funda_dir = funda_info.get("direction", "NEUTRAL")
        env_dir = env_state.get("trend", "RANGE")
        
        is_iron_clad = False
        if (env_dir == "UP" and funda_dir == "UP") or (env_dir == "DOWN" and funda_dir == "DOWN"):
            base_score += 20
            is_iron_clad = True
            
        result.win_rate_score = min(base_score, 100)
        
        # ステータスの決定
        pa_trigger = trig_state.get("pa") != "None"
        sync_dir = mom_state.get("sync_direction")
        
        if pa_trigger:
            if env_dir == "UP" and (sync_dir == "UP" or funda_dir == "UP"):
                result.status = SignalStatus.BUY_START
            elif env_dir == "DOWN" and (sync_dir == "DOWN" or funda_dir == "DOWN"):
                result.status = SignalStatus.SELL_START
            else:
                result.status = SignalStatus.STANDBY
        elif trig_state.get("is_band_walk"):
            result.status = SignalStatus.STAY
        else:
            # 方向感に基づくStandby
            if env_dir == "UP": result.status = SignalStatus.BUY_STANDBY
            elif env_dir == "DOWN": result.status = SignalStatus.SELL_STANDBY
            else: result.status = SignalStatus.STANDBY
            
        # テキストの組み立て
        funda_text = f"【ファンダ】方向感:{funda_dir} ({funda_info.get('reason', '')})"
        result.rationale_a = f"【環境分析】{env_state.get('reason', '')} / {funda_text}"
        result.rationale_b = f"【勢い分析】{mom_state.get('reason', '')}"
        
        if is_iron_clad: result.rationale_a += " 🌟[鉄板] テクニカルとファンダが一致！"
        
        if mom_state.get("rsi_state") == "OVERBOUGHT":
            result.caution = "RSIが買われすぎ水準です。反落に注意。"
        elif mom_state.get("rsi_state") == "OVERSOLD":
            result.caution = "RSIが売られすぎ水準です。反発に注意。"
            
        result.tags = [f"#{sys}" for sys in active_systems] + iron_patterns
        if trig_state.get("pa") != "None":
            result.tags.append(f"#{trig_state['pa'].replace(' ', '')}")
            
        return result
