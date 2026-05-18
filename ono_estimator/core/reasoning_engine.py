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
    price_vs_ma200: str = "N/A"    # ABOVE / BELOW / N/A (1H 200MA)
    inside_kumo: bool = False       # 一目均衡表の雲の中
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
    volatility_low: bool = False    # BB幅60%以下 or ATR 70%以下
    is_middle_zone: bool = False    # S/R中央50%圏内
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
    ls_detected: bool = False      # Liquidity Sweep検出フラグ
    ls_confirmed: bool = False     # セカンドテスト通過フラグ
    price: float = 0.0             # 執行時の現在価格
    is_counter_trend: bool = False  # 逆張りフラグ
    ema_alignment: str = "NONE"    # PERFECT_UP / PERFECT_DOWN / NONE
    ema_pullback_zone: bool = False # 20EMA/75EMA付近の押し目・戻り
    ema_divergence_pct: float = 0.0 # 20EMAとの乖離率
    rsi_divergence_alert: bool = False # RSI Sniper ダイバージェンス警告
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
    entry_reason: str = ""
    risk_ok: bool = True           # ギャン理論ルール通過

    def to_summary(self) -> str:
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
        データ異常・例外が発生しても ThinkingResult(WAIT) を返して処理を継続する。
        """
        try:
            return self._think_internal(df_store, symbol)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"[ReasoningEngine] {symbol} 分析中に例外: {type(e).__name__}: {e}"
            )
            return ThinkingResult(symbol=symbol)

    def _think_internal(self, df_store: dict, symbol: str) -> ThinkingResult:
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
            result.trigger.price = float(df_trig["close"].iloc[-1])
            
            # ── [2] EMA (20, 75, 200) の物理判定強化 ────────
            close_vals = df_trig["close"]
            e20 = close_vals.ewm(span=20, adjust=False).mean().iloc[-1]
            e75 = close_vals.ewm(span=75, adjust=False).mean().iloc[-1]
            e200 = close_vals.ewm(span=200, adjust=False).mean().iloc[-1]
            cur_p = result.trigger.price
            
            # EMA Alignment — B-4: 最小乖離率0.05%を要求。1本の値動きで反転しない水準
            _MIN_SEP = 0.0005
            if e75 > 0 and e200 > 0:
                if e20 > e75 * (1 + _MIN_SEP) and e75 > e200 * (1 + _MIN_SEP):
                    result.trigger.ema_alignment = "PERFECT_UP"
                elif e20 < e75 * (1 - _MIN_SEP) and e75 < e200 * (1 - _MIN_SEP):
                    result.trigger.ema_alignment = "PERFECT_DOWN"

            # EMA Pullback / Divergence — ゼロ除算ガード
            if e20 > 0:
                dist_e20 = abs(cur_p - e20) / e20
                result.trigger.ema_divergence_pct = (cur_p - e20) / e20 * 100
            else:
                dist_e20 = 1.0
                result.trigger.ema_divergence_pct = 0.0
            if e75 > 0:
                dist_e75 = abs(cur_p - e75) / e75
            else:
                dist_e75 = 1.0
            result.trigger.ema_pullback_zone = (dist_e20 < 0.001 or dist_e75 < 0.001)

            # ── [3] RSI Sniper (ダイバージェンス防衛) ────────
            from ono_estimator.indicators.technical import TechnicalIndicators as _TI
            rsi_s = _TI.rsi(close_vals)
            if len(rsi_s) >= 14:
                cur_rsi = rsi_s.iloc[-1]
                # 価格が直近10本の最高値を更新したが、RSIが更新していない場合
                if cur_p > close_vals.iloc[-10:-1].max() and cur_rsi < rsi_s.iloc[-10:-1].max() and cur_rsi > 70:
                    result.trigger.rsi_divergence_alert = True
                elif cur_p < close_vals.iloc[-10:-1].min() and cur_rsi > rsi_s.iloc[-10:-1].min() and cur_rsi < 30:
                    result.trigger.rsi_divergence_alert = True

            # ── [3] Cloud Guard (一目均衡表の雲) ───────────
            if df_1h is not None and len(df_1h) >= 60:
                ichi = _TI.ichimoku(df_1h["high"], df_1h["low"], df_1h["close"])
                c_top, c_bot = ichi.get("cloud_top", 0), ichi.get("cloud_bot", 0)
                if min(c_top, c_bot) <= cur_p <= max(c_top, c_bot):
                    result.upper.inside_kumo = True

            # [究極の絞り込み] Liquidity Sweep 検出
            try:
                from ono_estimator.indicators.technical import TechnicalIndicators as _TI
                ls_res = _TI.detect_liquidity_sweep(df_trig)
                bull_sweep   = bool(ls_res.get("bull_sweep"))
                bear_sweep   = bool(ls_res.get("bear_sweep"))
                bull_rebreak = bool(ls_res.get("bull_rebreak"))
                bear_rebreak = bool(ls_res.get("bear_rebreak"))
                result.trigger.ls_detected = bull_sweep or bear_sweep or bull_rebreak or bear_rebreak

                # セカンドテスト: 再ブレイク確認 + trigger方向との一致チェック (K-6)
                # bull_rebreak → BUY確認 / bear_rebreak → SELL確認
                trig_dir = result.trigger.direction
                if (bull_rebreak and trig_dir == "BUY") or (bear_rebreak and trig_dir == "SELL"):
                    result.trigger.ls_confirmed = True
                else:
                    result.trigger.ls_confirmed = False
                    if result.trigger.ls_detected:
                        if bull_rebreak or bear_rebreak:
                            # rebreakはあるが方向が逆
                            result.conflict_flags.append("LS方向矛盾（rebreak方向とtrigger方向が逆）")
                        else:
                            # sweep検出のみ、rebreak待ち
                            result.conflict_flags.append("LSセカンドテスト待ち")
            except Exception:
                pass

        # ── 「鉄の掟」用フラグ算出 ──────────────────────────
        
        # 1. 1H 200MA位置の特定 (Step 1)
        if df_1h is not None and len(df_1h) >= 200:
            try:
                ma200 = df_1h["close"].rolling(200).mean().iloc[-1]
                price = float(df_1h["close"].iloc[-1])
                if ma200 > 0 and not pd.isna(ma200):
                    result.upper.price_vs_ma200 = "ABOVE" if price > ma200 else "BELOW"
            except Exception:
                pass

        # 2. ボラティリティ・フィルター (Step 2)
        if df_1m is not None and len(df_1m) >= 20:
            # BB幅が直近平均の60%以下かどうか
            close = df_1m["close"]
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_width = (bb_std * 4) / bb_mid
            avg_width = bb_width.rolling(100).mean().iloc[-1] if len(bb_width) >= 100 else bb_width.mean()
            
            if not pd.isna(bb_width.iloc[-1]) and bb_width.iloc[-1] < (avg_width * 0.6):
                result.mid.volatility_low = True

        # 3. 中央50%圏内の回避判定 (Step 2)
        if result.mid.sr_nearest_resistance > result.mid.sr_nearest_support:
            band = result.mid.sr_nearest_resistance - result.mid.sr_nearest_support
            if df_trig is not None and len(df_trig) > 0:
                price = float(df_trig["close"].iloc[-1])
            else:
                price = 0.0
            mid_low = result.mid.sr_nearest_support + band * 0.25
            mid_high = result.mid.sr_nearest_resistance - band * 0.25
            result.mid.is_middle_zone = mid_low <= price <= mid_high

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

        # 方向決定: 上位足 + トリガーの一致
        # RANGEでもLS再ブレイク確認済みならブレイクアウトエントリーを許可
        can_buy  = trig.direction == "BUY"  and (upper.trend == "UP"   or (upper.trend == "RANGE" and trig.ls_confirmed))
        can_sell = trig.direction == "SELL" and (upper.trend == "DOWN" or (upper.trend == "RANGE" and trig.ls_confirmed))

        if can_buy:
            result.entry_decision = "BUY"
        elif can_sell:
            result.entry_decision = "SELL"
        else:
            result.entry_decision = "WAIT"

        # ── ラウンドナンバー (キリ番) 判定 (GBPUSD 等) ──
        if result.symbol in ["GBPUSD", "EURUSD", "BTCUSD"]:
            price = result.trigger.price
            # 下2桁が00, 50, 000 等に近いか判定
            is_round = (round(price * 100) % 50 == 0) or (round(price) % 1000 == 0)
            if is_round:
                result.trigger.reason += " / ラウンドナンバー接近"

        # ── 鉄の掟：物理ブロック判定 ──────────────────────
        # フラクタル構造の厳格化
        if result.entry_decision != "WAIT":
            if result.upper.trend != "RANGE" and result.upper.trend != result.trigger.direction:
                conflicts.append("フラクタル構造不一致（上位足逆行）")
        
        # 1. 200MAブロック (Step 1)
        if result.entry_decision == "BUY" and upper.price_vs_ma200 == "BELOW":
            conflicts.append("200MA下での買い禁止")
        if result.entry_decision == "SELL" and upper.price_vs_ma200 == "ABOVE":
            conflicts.append("200MA上での売り禁止")

        # 2. ボラティリティ・フィルター (Step 2)
        if mid.volatility_low:
            conflicts.append("ボラティリティ低下（RANGE_WAIT）")

        # 3. レンジ中央回避 (Step 2)
        if mid.is_middle_zone and upper.trend == "RANGE":
            conflicts.append("レンジ中央（優位性なし）")

        # 4. 壁までの距離 (Step 3)
        if result.entry_decision == "BUY" and mid.sr_nearest_resistance > 0:
            if result.tp_hint > mid.sr_nearest_resistance:
                 conflicts.append("TPターゲット手前に強力な抵抗壁あり")

        # 5. ステージ厳格化 (Step 1) — 大循環MA理論
        # ステージ1(5>20>60 上昇): BUY最適 / ステージ6(5>60>20 上昇初期): BUY許容
        # ステージ4(60>20>5 下降): SELL最適 / ステージ3(20>60>5 下降初期): SELL許容
        # RANGE+LS確認済みはステージ制限を緩和（ブレイク方向のみ）
        ls_override = upper.trend == "RANGE" and trig.ls_confirmed
        if result.entry_decision == "BUY" and upper.stage not in (1, 6) and not ls_override:
            conflicts.append(f"ステージ{upper.stage}での買い禁止（ステージ1,6以外）")
        if result.entry_decision == "SELL" and upper.stage not in (3, 4) and not ls_override:
            conflicts.append(f"ステージ{upper.stage}での売り禁止（ステージ3,4以外）")

        # 矛盾があれば強制WAIT
        if conflicts:
            result.entry_decision = "WAIT"
            result.confidence = "LOW"
            result.entry_reason = f"鉄の掟により待機: {', '.join(conflicts)}"
            return result

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
