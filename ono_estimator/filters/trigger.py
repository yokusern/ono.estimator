"""
TriggerFilter — 下位足エントリートリガー (T-04 大幅拡張)
=========================================================
追加実装:
  - リバーサルハイ/ロー
  - インサイド/アウトサイドバー
  - スラストアップ/ダウン
  - ランウェイアップ/ダウン
  - MACDダイバージェンス
  - RSIダイバージェンス/ヒドゥン
  - ストキャスGC/DC + 過熱ゾーン
"""
from __future__ import annotations
from typing import Dict, Any
import pandas as pd
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import TechnicalIndicators, PriceAction


class TriggerFilter:
    """Layer 3: 短期足(5m/15m)のプライスアクション、バンドウォーク"""

    def evaluate(self, mtf_data: MTFData) -> Dict[str, Any]:
        df = mtf_data.get_data(TimeFrame.M5)
        if df is None or len(df) < 20:
            df = mtf_data.get_data(TimeFrame.M15)

        result = {"pa": "None", "is_band_walk": False, "reason": ""}

        if df is None or len(df) < 20:
            return result

        ext = self.evaluate_extended(df, "RANGE")
        result["pa"]           = ext.pa_signal
        result["is_band_walk"] = ext.is_band_walk
        result["reason"]       = ext.reason
        return result

    def evaluate_extended(self, df: pd.DataFrame, upper_trend: str):
        """完全拡張トリガー分析 → TriggerContext を返す"""
        from ono_estimator.core.reasoning_engine import TriggerContext
        ctx = TriggerContext()

        if df is None or len(df) < 20:
            return ctx

        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        open_ = df["open"]

        # ── プライスアクション ─────────────────────────────────
        ctx.pa_signal = self._detect_pa(df)

        # ── バンドウォーク + 追従 (1-3) ───────────────────────
        ctx.is_band_walk = self._band_walk(close)
        ctx.band_follow  = self._band_follow_signal(close, open_) if ctx.is_band_walk else "NONE"

        # ── MACD ──────────────────────────────────────────────
        ctx.macd_signal = self._macd_signal(close)

        # ── RSI ───────────────────────────────────────────────
        ctx.rsi_signal, ctx.rsi_divergence = self._rsi_signal(close)

        # ── ストキャス ─────────────────────────────────────────
        ctx.stoch_signal = self._stoch_signal(high, low, close)

        # ── 方向決定 ──────────────────────────────────────────
        ctx.direction = self._decide_direction(ctx, upper_trend)

        # ── 逆張りフラグ ──────────────────────────────────────
        ctx.is_counter_trend = (
            (upper_trend == "UP"   and ctx.direction == "SELL") or
            (upper_trend == "DOWN" and ctx.direction == "BUY")
        )

        # ── 強度スコア ────────────────────────────────────────
        ctx.strength = self._calc_strength(ctx)

        ctx.reason = self._build_reason(ctx)
        return ctx

    # ── プライスアクション検出 ────────────────────────────────
    def _detect_pa(self, df: pd.DataFrame) -> str:
        if len(df) < 4:
            return "None"
        curr = df.iloc[-2]
        prev = df.iloc[-3]
        pre2 = df.iloc[-4]

        # ピンバー
        is_pin, pin_type = PriceAction.is_pin_bar(
            curr["open"], curr["high"], curr["low"], curr["close"])
        if is_pin:
            return f"{pin_type} PinBar"

        # 包み足
        is_eng, eng_type = PriceAction.is_engulfing(
            prev["open"], prev["close"], curr["open"], curr["close"])
        if is_eng:
            return f"{eng_type} Engulfing"

        # リバーサルハイ: 前々足より高い高値を更新後に反落
        is_rev_high = (
            curr["high"] > prev["high"] and
            curr["close"] < prev["close"] and
            (curr["high"] - curr["close"]) > abs(curr["close"] - curr["open"]) * 1.5
        )
        if is_rev_high:
            return "ReversalHigh"

        # リバーサルロー: 前々足より低い安値を更新後に反発
        is_rev_low = (
            curr["low"] < prev["low"] and
            curr["close"] > prev["close"] and
            (curr["close"] - curr["low"]) > abs(curr["close"] - curr["open"]) * 1.5
        )
        if is_rev_low:
            return "ReversalLow"

        # インサイドバー: 前足のhigh/lowの内側に収まる
        is_inside = (curr["high"] <= prev["high"] and curr["low"] >= prev["low"])
        if is_inside:
            return "InsideBar"

        # アウトサイドバー: 前足のhigh/lowを両方超える
        is_outside = (curr["high"] > prev["high"] and curr["low"] < prev["low"])
        if is_outside:
            return "OutsideBar"

        # スラストアップ: 実体が前足実体高値を上回る強い陽線
        curr_body_high = max(curr["open"], curr["close"])
        prev_body_high = max(prev["open"], prev["close"])
        if curr["close"] > curr["open"] and curr_body_high > prev_body_high * 1.002:
            return "ThrustUp"

        # スラストダウン: 実体が前足実体安値を下回る強い陰線
        curr_body_low = min(curr["open"], curr["close"])
        prev_body_low = min(prev["open"], prev["close"])
        if curr["close"] < curr["open"] and curr_body_low < prev_body_low * 0.998:
            return "ThrustDown"

        # ランウェイアップ: 3本連続陽線で各足が前足終値を上回る
        if (len(df) >= 5 and
            df.iloc[-2]["close"] > df.iloc[-2]["open"] and
            df.iloc[-3]["close"] > df.iloc[-3]["open"] and
            df.iloc[-4]["close"] > df.iloc[-4]["open"] and
            df.iloc[-2]["close"] > df.iloc[-3]["close"] > df.iloc[-4]["close"]):
            return "RunwayUp"

        # ランウェイダウン: 3本連続陰線で各足が前足終値を下回る
        if (len(df) >= 5 and
            df.iloc[-2]["close"] < df.iloc[-2]["open"] and
            df.iloc[-3]["close"] < df.iloc[-3]["open"] and
            df.iloc[-4]["close"] < df.iloc[-4]["open"] and
            df.iloc[-2]["close"] < df.iloc[-3]["close"] < df.iloc[-4]["close"]):
            return "RunwayDown"

        return "None"

    # ── バンドウォーク ─────────────────────────────────────────
    def _band_walk(self, close: pd.Series) -> bool:
        bb = TechnicalIndicators.bollinger_bands(close)
        std    = bb["std"].iloc[-4:-1]
        basis  = bb["basis"].iloc[-4:-1]
        closes = close.iloc[-4:-1]
        if (closes > basis + std).all():
            return True
        if (closes < basis - std).all():
            return True
        return False

    # ── 1-3: バンドウォーク追従シグナル ─────────────────────────
    def _band_follow_signal(self, close: pd.Series, open_: pd.Series) -> str:
        """バンドウォーク中の押し目・戻し追従エントリー検出。
        直近2本が「陰線→陽線」ならBUY_FOLLOW（押し目買い追従）
        直近2本が「陽線→陰線」ならSELL_FOLLOW（戻り売り追従）
        """
        if len(close) < 3:
            return "NONE"
        c1, c2 = float(close.iloc[-3]), float(close.iloc[-2])
        o1, o2 = float(open_.iloc[-3]),  float(open_.iloc[-2])
        is_bear_then_bull = (c1 < o1) and (c2 > o2)
        is_bull_then_bear = (c1 > o1) and (c2 < o2)
        if is_bear_then_bull:
            return "BUY_FOLLOW"
        if is_bull_then_bear:
            return "SELL_FOLLOW"
        return "NONE"

    # ── MACDシグナル ──────────────────────────────────────────
    def _macd_signal(self, close: pd.Series) -> str:
        if len(close) < 35:
            return "None"
        try:
            macd_df = TechnicalIndicators.macd(close)
            hist    = macd_df["hist"]
            macd_line = macd_df["macd"]
            signal    = macd_df["signal"]

            # GC/DC
            if macd_line.iloc[-2] < signal.iloc[-2] and macd_line.iloc[-1] >= signal.iloc[-1]:
                return "GC（買いサイン）"
            if macd_line.iloc[-2] > signal.iloc[-2] and macd_line.iloc[-1] <= signal.iloc[-1]:
                return "DC（売りサイン）"

            # ダイバージェンス（価格が上昇、MACDが下降）
            price_rising  = close.iloc[-1] > close.iloc[-5]
            price_falling = close.iloc[-1] < close.iloc[-5]
            macd_rising   = float(macd_line.iloc[-1]) > float(macd_line.iloc[-5])
            macd_falling  = float(macd_line.iloc[-1]) < float(macd_line.iloc[-5])

            if price_rising and macd_falling:
                return "ベアリッシュダイバージェンス"
            if price_falling and macd_rising:
                return "ブリッシュダイバージェンス"

            if float(hist.iloc[-1]) > 0:
                return "ヒスト正（上昇モメンタム）"
            return "ヒスト負（下降モメンタム）"
        except Exception:
            return "None"

    # ── RSIシグナル + ダイバージェンス ──────────────────────
    def _rsi_signal(self, close: pd.Series) -> tuple:
        if len(close) < 20:
            return "None", "None"
        try:
            rsi = TechnicalIndicators.rsi(close)
            rsi_val  = float(rsi.iloc[-1])
            rsi_prev = float(rsi.iloc[-5])
            cur      = float(close.iloc[-1])
            prev5    = float(close.iloc[-5])

            # 過熱判定
            if rsi_val > 70:
                signal = f"overbought({rsi_val:.0f})"
            elif rsi_val < 30:
                signal = f"oversold({rsi_val:.0f})"
            else:
                signal = f"neutral({rsi_val:.0f})"

            # ダイバージェンス
            price_up  = cur > prev5
            price_dn  = cur < prev5
            rsi_up    = rsi_val > rsi_prev
            rsi_dn    = rsi_val < rsi_prev

            if price_up and rsi_dn:
                div = "bearish_divergence"
            elif price_dn and rsi_up:
                div = "bullish_divergence"
            elif price_up and rsi_up and rsi_prev < 50:
                div = "hidden_bullish"   # 押し目の確認
            elif price_dn and rsi_dn and rsi_prev > 50:
                div = "hidden_bearish"   # 戻しの確認
            else:
                div = "None"

            return signal, div
        except Exception:
            return "None", "None"

    # ── ストキャス ─────────────────────────────────────────────
    def _stoch_signal(self, high: pd.Series, low: pd.Series, close: pd.Series) -> str:
        if len(close) < 20:
            return "None"
        try:
            st = TechnicalIndicators.stochastic(high, low, close)
            k, d = st.get("k", 50), st.get("d", 50)
            gc   = st.get("golden_cross", False)
            dc   = st.get("dead_cross", False)
            if gc:
                return f"GC（売られすぎからの反発 K={k:.0f}）"
            if dc:
                return f"DC（買われすぎからの反落 K={k:.0f}）"
            if k > 80:
                return f"買われすぎ K={k:.0f}"
            if k < 20:
                return f"売られすぎ K={k:.0f}"
            return f"中立 K={k:.0f}"
        except Exception:
            return "None"

    # ── 方向決定 ──────────────────────────────────────────────
    def _decide_direction(self, ctx, upper_trend: str) -> str:
        buy_signals  = 0
        sell_signals = 0

        pa = ctx.pa_signal
        if pa in ("ReversalLow", "RunwayUp", "ThrustUp") or "BullPin" in pa or "Bull" in pa:
            buy_signals += 2
        if pa in ("ReversalHigh", "RunwayDown", "ThrustDown") or "BearPin" in pa or "Bear" in pa:
            sell_signals += 2

        macd = ctx.macd_signal
        if "GC" in macd or "ブリッシュ" in macd:
            buy_signals += 1
        if "DC" in macd or "ベアリッシュ" in macd:
            sell_signals += 1

        rsi = ctx.rsi_signal
        div = ctx.rsi_divergence
        if "oversold" in rsi or "bullish" in div:
            buy_signals += 1
        if "overbought" in rsi or "bearish" in div:
            sell_signals += 1

        stoch = ctx.stoch_signal
        if "GC" in stoch:
            buy_signals += 1
        if "DC" in stoch:
            sell_signals += 1

        if buy_signals > sell_signals and buy_signals >= 2:
            return "BUY"
        if sell_signals > buy_signals and sell_signals >= 2:
            return "SELL"
        return "WAIT"

    def _calc_strength(self, ctx) -> int:
        score = 0
        if ctx.pa_signal != "None":
            score += 30
        if ctx.macd_signal not in ("None", "ヒスト正（上昇モメンタム）", "ヒスト負（下降モメンタム）"):
            score += 20
        if ctx.rsi_divergence != "None":
            score += 20
        if "GC" in ctx.stoch_signal or "DC" in ctx.stoch_signal:
            score += 15
        if ctx.is_band_walk:
            score += 15
        return min(100, score)

    def _build_reason(self, ctx) -> str:
        parts = []
        if ctx.pa_signal != "None":
            parts.append(f"PA:{ctx.pa_signal}")
        if ctx.macd_signal != "None":
            parts.append(f"MACD:{ctx.macd_signal}")
        if ctx.rsi_divergence != "None":
            parts.append(f"RSIダイバージェンス:{ctx.rsi_divergence}")
        if ctx.stoch_signal != "None":
            parts.append(f"Stoch:{ctx.stoch_signal}")
        if ctx.is_band_walk:
            parts.append("バンドウォーク中")
        return "、".join(parts) if parts else "トリガーなし"
