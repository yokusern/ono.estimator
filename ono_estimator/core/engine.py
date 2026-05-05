import pandas as pd
from typing import Dict, Optional
from .models import PredictionResult, SignalStatus, TimeFrame
from .data import MTFData
from ..systems import SVSystem, LWSystem, TKSSystem, GenericSystem
from ..filters import EnvironmentFilter, MomentumFilter, TriggerFilter, IronPatternMatcher

# 1-2: GenericSystem対象銘柄
GENERIC_SYMBOLS = {"GOLD", "BTC", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"}


class ONOPredictionEngine:
    """すべてのデータを統合し、最終的な予測結果を生成するメインエンジン"""

    def __init__(self):
        # 1. 基盤システム
        self.systems = [SVSystem(), LWSystem(), TKSSystem()]
        self.generic_system = GenericSystem()

        # 2. 3層フィルター & パターン
        self.env_filter = EnvironmentFilter()
        self.momentum_filter = MomentumFilter()
        self.trigger_filter = TriggerFilter()
        self.pattern_matcher = IronPatternMatcher()

        # 3. 思考型エンジン (T-06)
        self._reasoning_engine = None

    def _get_reasoning(self):
        if self._reasoning_engine is None:
            from .reasoning_engine import ReasoningEngine
            self._reasoning_engine = ReasoningEngine()
        return self._reasoning_engine

    def analyze(self, mtf_data: MTFData = None, symbol: str = "USDJPY", funda_info: dict = None, df_precomputed: pd.DataFrame = None) -> PredictionResult:
        result = PredictionResult()

        # T-06: df_precomputed → ReasoningEngine.think_from_df に接続
        if mtf_data is None and df_precomputed is not None:
            try:
                thinking = self._get_reasoning().think_from_df(df_precomputed, symbol)
                decision = thinking.entry_decision
                confidence = thinking.confidence

                if decision == "BUY":
                    result.status = SignalStatus.BUY_START
                elif decision == "SELL":
                    result.status = SignalStatus.SELL_START
                else:
                    result.status = SignalStatus.STANDBY

                conf_map = {"HIGH": 80, "MEDIUM": 65, "LOW": 50}
                result.win_rate_score = conf_map.get(confidence, 50)
                result.rationale_a = f"【思考型エンジン】{thinking.entry_reason}"
                result.rationale_b = f"PA:{thinking.trigger.pa_signal} / MACD:{thinking.trigger.macd_signal} / RSI:{thinking.trigger.rsi_signal}"
                result.base_system = "ReasoningEngine"
                # thinking_result を外部から参照できるよう格納
                result._thinking = thinking
            except Exception as e:
                # フォールバック: 旧ロジック
                latest = df_precomputed.iloc[-1]
                rsi  = latest.get("rsi", 0) if hasattr(latest, "get") else 0
                macd = latest.get("macd", 0) if hasattr(latest, "get") else 0
                result.win_rate_score = 50
                if rsi > 50: result.win_rate_score += 10
                if macd > 0: result.win_rate_score += 10
                result.status = SignalStatus.STANDBY
                result.rationale_a = f"【Engine fallback】{e}"
                result.rationale_b = f"RSI:{rsi:.1f} / MACD:{macd:.4f}"
            return result

        if funda_info is None:
            funda_info = {"direction": "NEUTRAL", "reason": "No funda data"}
        
        # STEP 1: 基盤システムによる基本判定
        active_systems = []

        # 1-2: GenericSystem対象銘柄（旧来のcontinueをGenericSystemに変更）
        sym_short = symbol.replace("=X", "").replace("-USD", "").replace("^", "").replace("=F", "")
        if sym_short in GENERIC_SYMBOLS or symbol.split("=")[0] in GENERIC_SYMBOLS:
            gen_status = self.generic_system.evaluate(mtf_data)
            if gen_status in (SignalStatus.BUY_START, SignalStatus.BUY_STANDBY,
                              SignalStatus.SELL_START, SignalStatus.SELL_STANDBY,
                              SignalStatus.STANDBY):
                active_systems.append("Generic")
        else:
            for sys in self.systems:
                if symbol == "USDJPY" and sys.name not in ["SV", "LW"]:
                    continue
                if symbol == "JP225" and sys.name != "TKS":
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

        # 2-1: セッションスコア補正
        try:
            from ..filters.session_filter import get_session_score_bonus
            sess_bonus, sess_caution = get_session_score_bonus(symbol)
            base_score += sess_bonus
            if sess_caution:
                result.caution = (result.caution + " " + sess_caution).strip()
        except Exception:
            sess_bonus, sess_caution = 0, ""
            
        funda_dir = funda_info.get("direction", "NEUTRAL")
        env_dir = env_state.get("trend", "RANGE")
        
        is_iron_clad = False
        if (env_dir == "UP" and funda_dir == "UP") or (env_dir == "DOWN" and funda_dir == "DOWN"):
            base_score += 20
            is_iron_clad = True
            
        # 2-3: ATRボラティリティ判定
        try:
            df_for_atr = mtf_data.get_data(TimeFrame.H1) or mtf_data.get_data(TimeFrame.M15)
            if df_for_atr is not None and len(df_for_atr) >= 34:
                from ..indicators.technical import TechnicalIndicators as _TI
                atr_series = _TI.atr(df_for_atr["high"], df_for_atr["low"], df_for_atr["close"], 14)
                if len(atr_series.dropna()) >= 20:
                    cur_atr = float(atr_series.iloc[-1])
                    avg_atr = float(atr_series.iloc[-20:].mean())
                    if avg_atr > 0:
                        atr_ratio = cur_atr / avg_atr
                        if atr_ratio >= 1.5:
                            result.caution = (result.caution + " ⚠️ 高ボラティリティ：スプレッド拡大に注意").strip()
                        elif atr_ratio <= 0.5:
                            result.caution = (result.caution + " ⚠️ 膠着相場：エントリーは様子見推奨").strip()
                        else:
                            base_score += 5
        except Exception:
            pass

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
            # 1-3: バンドウォーク追従（STAY→BUY/SELL_START）
            band_follow = trig_state.get("band_follow", "NONE")
            if band_follow == "BUY_FOLLOW":
                result.status = SignalStatus.BUY_START
            elif band_follow == "SELL_FOLLOW":
                result.status = SignalStatus.SELL_START
            else:
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

        # 3-1: TP/SL自動計算 (ATR×1.5=SL, ATR×3.0=TP)
        try:
            df_atr = mtf_data.get_data(TimeFrame.H1) or mtf_data.get_data(TimeFrame.M15)
            if df_atr is not None and len(df_atr) >= 20:
                from ..indicators.technical import TechnicalIndicators as _TI2
                atr_s = _TI2.atr(df_atr["high"], df_atr["low"], df_atr["close"], 14)
                atr_val = float(atr_s.iloc[-1]) if not atr_s.empty else 0.0
                if atr_val > 0:
                    cur = float(df_atr["close"].iloc[-1])
                    sl_width = atr_val * 1.5
                    tp_width = atr_val * 3.0
                    if result.status in (SignalStatus.BUY_START, SignalStatus.BUY_STANDBY):
                        result.sl_price  = round(cur - sl_width, 5)
                        result.tp_price  = round(cur + tp_width, 5)
                    elif result.status in (SignalStatus.SELL_START, SignalStatus.SELL_STANDBY):
                        result.sl_price  = round(cur + sl_width, 5)
                        result.tp_price  = round(cur - tp_width, 5)
                    if sl_width > 0:
                        result.risk_reward = round(tp_width / sl_width, 2)
                    result.rationale_b += f" | ATR={atr_val:.5f} SL={result.sl_price} TP={result.tp_price} RR=1:{result.risk_reward}"
        except Exception:
            pass

        return result
