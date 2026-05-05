"""
ReasoningEngine — 思考型エントリー判断エンジン (T-01)
====================================================
MTカリキュラムの4ステップ思考プロセスを再現する:
  STEP1: 上位足(4h/1h)でトレンド・大局把握
  STEP2: 中位足(15m/5m)でゾーン・押し目確認
  STEP3: 下位足(5m/1m)でエントリートリガー待機
  STEP4: 矛盾チェック → 最終エントリー判断
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class UpperContext:
    trend: str = "RANGE"           # UP / DOWN / RANGE
    stage: int = 0                  # 大循環ステージ 1-6
    stage_label: str = ""           # "上昇トレンド" 等
    perfect_order: str = "NONE"     # UP / DOWN / NONE
    dow_reason: str = ""
    ichimoku_status: str = ""       # "三役好転" / "三役逆転" / "中立"
    granville: str = "なし"         # グランビルパターン
    channel_position: str = "INSIDE"  # UPPER / LOWER / INSIDE
    score: int = 0                  # 0-100: 上位足の方向一致度
    reason: str = ""


@dataclass
class ZoneContext:
    zone: str = "MIDDLE"           # PULLBACK / RESISTANCE / SUPPORT / MIDDLE
    sr_nearest_support: float = 0.0
    sr_nearest_resistance: float = 0.0
    reji_support_flip: bool = False  # レジサポ転換あり
    bb_state: str = "NORMAL"        # SQUEEZE / EXPANSION / NORMAL
    chart_pattern: str = "なし"
    pullback_valid: bool = False    # 上位トレンド方向の押し目/戻し圏内
    reason: str = ""


@dataclass
class TriggerContext:
    pa_signal: str = "None"        # ピンバー, 包み足, リバーサルハイ etc.
    macd_signal: str = "None"      # GC/DC/divergence
    rsi_signal: str = "None"       # oversold/overbought/divergence
    rsi_divergence: str = "None"   # bullish/bearish/hidden_bull/hidden_bear
    stoch_signal: str = "None"
    direction: str = "WAIT"        # BUY / SELL / WAIT
    is_band_walk: bool = False
    band_follow: str = "NONE"      # 1-3: BUY_FOLLOW / SELL_FOLLOW / NONE
    is_counter_trend: bool = False  # 逆張りフラグ
    strength: int = 0              # 0-100
    reason: str = ""


@dataclass
class ThinkingResult:
    """ReasoningEngineの思考結果コンテナ"""
    symbol: str = ""
    upper: UpperContext = field(default_factory=UpperContext)
    mid: ZoneContext = field(default_factory=ZoneContext)
    trigger: TriggerContext = field(default_factory=TriggerContext)
    conflict_flags: list = field(default_factory=list)
    entry_decision: str = "WAIT"   # BUY / SELL / WAIT
    confidence: str = "LOW"        # HIGH / MEDIUM / LOW
    sl_hint: float = 0.0
    tp_hint: float = 0.0
    entry_reason: str = ""         # Geminiに渡す日本語の判断根拠
    risk_ok: bool = True           # ギャン理論ルール通過

    def to_prompt_context(self) -> str:
        """GeminiプロンプトのContext文字列を生成"""
        lines = [
            f"【上位足(4h/1h)分析】",
            f"- トレンド: {self.upper.trend} / 大循環ステージ: {self.upper.stage}({self.upper.stage_label})",
            f"- ダウ理論: {self.upper.dow_reason}",
            f"- MAパーフェクトオーダー: {self.upper.perfect_order}",
            f"- 一目均衡表: {self.upper.ichimoku_status}",
            f"- グランビル: {self.upper.granville}",
            f"",
            f"【中位足(15m)分析】",
            f"- 現在のゾーン: {self.mid.zone}",
            f"- S/R: R={self.mid.sr_nearest_resistance:.3f} / S={self.mid.sr_nearest_support:.3f}",
            f"- レジサポ転換: {'あり' if self.mid.reji_support_flip else 'なし'}",
            f"- BBバンド状態: {self.mid.bb_state}",
            f"- チャートパターン: {self.mid.chart_pattern}",
            f"- 押し目/戻し圏: {'有効' if self.mid.pullback_valid else '無効'}",
            f"",
            f"【下位足(5m/1m)トリガー】",
            f"- プライスアクション: {self.trigger.pa_signal}",
            f"- MACD: {self.trigger.macd_signal}",
            f"- RSI: {self.trigger.rsi_signal}（ダイバージェンス: {self.trigger.rsi_divergence}）",
            f"- ストキャス: {self.trigger.stoch_signal}",
            f"",
            f"【矛盾フラグ】{', '.join(self.conflict_flags) if self.conflict_flags else 'なし'}",
            f"【エントリー判断】{self.entry_decision} / 信頼度: {self.confidence}",
            f"【SL目処】{self.sl_hint:.5f}",
            f"【TP目処】{self.tp_hint:.5f}",
        ]
        return "\n".join(lines)


class ReasoningEngine:
    """熟練トレーダーの思考プロセスを4ステップで再現するエンジン"""

    def __init__(self):
        # 遅延import（循環参照を避けるため）
        self._upper_analyzer = None
        self._zone_analyzer  = None
        self._conflict_det   = None

    def _get_upper(self):
        if self._upper_analyzer is None:
            from ono_estimator.filters.upper_tf_analyzer import UpperTFAnalyzer
            self._upper_analyzer = UpperTFAnalyzer()
        return self._upper_analyzer

    def _get_zone(self):
        if self._zone_analyzer is None:
            from ono_estimator.filters.zone_analyzer import ZoneAnalyzer
            self._zone_analyzer = ZoneAnalyzer()
        return self._zone_analyzer

    def _get_conflict(self):
        if self._conflict_det is None:
            from ono_estimator.core.conflict_detector import ConflictDetector
            self._conflict_det = ConflictDetector()
        return self._conflict_det

    def think(self, df_store: dict, symbol: str) -> ThinkingResult:
        """
        df_store: {"1m": df, "5m": df, "15m": df, "1h": df, "4h": df}
        """
        result = ThinkingResult(symbol=symbol)

        df_4h = df_store.get("4h")
        df_1h = df_store.get("1h")
        df_15m = df_store.get("15m")
        df_5m  = df_store.get("5m")
        df_1m  = df_store.get("1m")

        # ── STEP1: 上位足 ──────────────────────────────────────
        if df_4h is not None and len(df_4h) >= 30:
            result.upper = self._get_upper().analyze(df_4h, df_1h)
        elif df_1h is not None and len(df_1h) >= 30:
            result.upper = self._get_upper().analyze(df_1h, None)

        # ── STEP2: 中位足 ──────────────────────────────────────
        df_mid = df_15m if (df_15m is not None and len(df_15m) >= 20) else df_5m
        if df_mid is not None and len(df_mid) >= 20:
            result.mid = self._get_zone().analyze(df_mid, result.upper.trend)

        # ── STEP3: 下位足トリガー ──────────────────────────────
        df_trig = df_5m if (df_5m is not None and len(df_5m) >= 20) else df_1m
        if df_trig is not None and len(df_trig) >= 20:
            result.trigger = self._analyze_trigger(df_trig, result.upper.trend)

        # ── STEP4: 矛盾チェック・最終判断 ─────────────────────
        result.conflict_flags = self._get_conflict().detect(
            result.upper, result.mid, result.trigger
        )
        result = self._synthesize(result)

        return result

    def think_from_df(self, df: pd.DataFrame, symbol: str) -> ThinkingResult:
        """単一DFからの簡易思考（T-06 df_precomputed用）"""
        result = ThinkingResult(symbol=symbol)
        if df is None or len(df) < 30:
            return result

        # 単一DFの場合はトリガーのみ評価
        result.trigger = self._analyze_trigger(df, "RANGE")
        result.conflict_flags = []

        # 簡易判断
        if result.trigger.direction == "BUY" and not result.conflict_flags:
            result.entry_decision = "BUY"
            result.confidence = "MEDIUM"
        elif result.trigger.direction == "SELL" and not result.conflict_flags:
            result.entry_decision = "SELL"
            result.confidence = "MEDIUM"

        result.entry_reason = f"単一足分析: {result.trigger.reason}"
        return result

    def _analyze_trigger(self, df: pd.DataFrame, upper_trend: str) -> TriggerContext:
        """T-04: 下位足トリガー分析（拡張TriggerFilter相当）"""
        from ono_estimator.filters.trigger import TriggerFilter
        tf = TriggerFilter()
        return tf.evaluate_extended(df, upper_trend)

    def _synthesize(self, result: ThinkingResult) -> ThinkingResult:
        """STEP4: 総合判断"""
        upper = result.upper
        mid   = result.mid
        trig  = result.trigger
        conflicts = result.conflict_flags

        # 矛盾があれば強制WAIT
        if conflicts:
            result.entry_decision = "WAIT"
            result.confidence = "LOW"
            result.entry_reason = f"矛盾フラグあり: {', '.join(conflicts)}"
            return result

        # 方向決定: 上位足 + トリガーの一致
        can_buy  = upper.trend in ("UP",)   and trig.direction == "BUY"
        can_sell = upper.trend in ("DOWN",) and trig.direction == "SELL"

        # 大循環ステージフィルター（1=買い優先, 4=売り優先, 2/3/5/6=様子見）
        if upper.stage in (2, 3, 5, 6):
            result.confidence = "LOW"
        elif upper.stage in (1,):
            can_buy = can_buy  # 問題なし
        elif upper.stage in (4,):
            can_sell = can_sell

        if can_buy:
            result.entry_decision = "BUY"
        elif can_sell:
            result.entry_decision = "SELL"
        elif mid.pullback_valid and trig.direction != "WAIT":
            # 上位足はRANGEでも押し目圏+トリガーなら中精度
            result.entry_decision = trig.direction
            result.confidence = "LOW"
        else:
            result.entry_decision = "WAIT"

        # 信頼度評価
        strong_signals = sum([
            upper.trend != "RANGE",
            mid.pullback_valid,
            trig.pa_signal != "None",
            trig.macd_signal not in ("None", "NEUTRAL"),
            trig.rsi_divergence not in ("None",),
            upper.perfect_order != "NONE",
        ])

        if strong_signals >= 4:
            result.confidence = "HIGH"
        elif strong_signals >= 2:
            result.confidence = "MEDIUM"
        else:
            result.confidence = "LOW"

        # SL/TP目処
        if len(result.symbol) > 0:
            price = 0.0
            if mid.sr_nearest_support > 0 and result.entry_decision == "BUY":
                result.sl_hint = mid.sr_nearest_support
                result.tp_hint = mid.sr_nearest_resistance if mid.sr_nearest_resistance > 0 else 0.0
            elif mid.sr_nearest_resistance > 0 and result.entry_decision == "SELL":
                result.sl_hint = mid.sr_nearest_resistance
                result.tp_hint = mid.sr_nearest_support if mid.sr_nearest_support > 0 else 0.0

        # 根拠文字列
        parts = [f"トレンド:{upper.trend}(ステージ{upper.stage})"]
        if mid.pullback_valid:
            parts.append("押し目/戻し圏内")
        if trig.pa_signal != "None":
            parts.append(f"PA:{trig.pa_signal}")
        if conflicts:
            parts.append(f"矛盾:{','.join(conflicts)}")
        result.entry_reason = " / ".join(parts)

        return result
