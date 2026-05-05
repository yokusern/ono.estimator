"""
ZoneAnalyzer — 中位足(15m/5m)ゾーン分析モジュール (T-03)
========================================================
実装技術:
  - サポート/レジスタンス自動検出
  - レジサポ転換判定
  - エンベロープ位置
  - BBスクイーズ/エクスパンション
  - チャートパターン検出（T-12連携）
  - 押し目/戻し圏判定
"""
import pandas as pd
import numpy as np
from ono_estimator.core.reasoning_engine import ZoneContext


class ZoneAnalyzer:

    def analyze(self, df: pd.DataFrame, upper_trend: str) -> ZoneContext:
        ctx = ZoneContext()
        if df is None or len(df) < 20:
            return ctx

        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        cur   = float(close.iloc[-1])

        # ── 1) S/R検出 ─────────────────────────────────────────
        ctx.sr_nearest_support, ctx.sr_nearest_resistance = self._find_nearest_sr(
            high, low, cur)

        # ── 2) レジサポ転換判定 ──────────────────────────────
        ctx.reji_support_flip = self._check_reji_support_flip(df, cur)

        # ── 3) BBバンド状態 ──────────────────────────────────
        ctx.bb_state = self._bb_state(close)

        # ── 4) チャートパターン ──────────────────────────────
        ctx.chart_pattern = self._detect_chart_pattern(df)

        # ── 5) ゾーン判定 ────────────────────────────────────
        ctx.zone = self._determine_zone(
            cur, ctx.sr_nearest_support, ctx.sr_nearest_resistance, upper_trend)

        # ── 6) 押し目/戻し圏有効性 ──────────────────────────
        ctx.pullback_valid = self._is_pullback_valid(
            ctx.zone, upper_trend, ctx.bb_state)

        ctx.reason = self._build_reason(ctx)
        return ctx

    # ── S/R自動検出 ──────────────────────────────────────────
    def _find_nearest_sr(self, high: pd.Series, low: pd.Series,
                         cur: float, lookback: int = 50) -> tuple:
        h = high.tail(lookback)
        l = low.tail(lookback)
        # スイングハイ/ローを検出
        sh = h[(h.shift(1) < h) & (h.shift(-1) < h)]
        sl = l[(l.shift(1) > l) & (l.shift(-1) > l)]

        resistances = sorted([float(v) for v in sh if float(v) > cur * 1.0005])
        supports    = sorted([float(v) for v in sl if float(v) < cur * 0.9995], reverse=True)

        r = resistances[0] if resistances else 0.0
        s = supports[0]    if supports    else 0.0
        return s, r

    # ── レジサポ転換 ──────────────────────────────────────────
    def _check_reji_support_flip(self, df: pd.DataFrame, cur: float,
                                 lookback: int = 30) -> bool:
        """過去の高値圏が現在のサポートになっているか（または逆）"""
        recent = df.tail(lookback)
        past_highs = recent["high"].nlargest(5)
        past_lows  = recent["low"].nsmallest(5)
        tol = cur * 0.002
        # 過去の抵抗が現在価格付近にある = レジサポ転換の可能性
        near_past_high = any(abs(float(h) - cur) < tol for h in past_highs)
        near_past_low  = any(abs(float(l) - cur) < tol for l in past_lows)
        return near_past_high or near_past_low

    # ── BBバンド状態 ──────────────────────────────────────────
    def _bb_state(self, close: pd.Series, period: int = 20) -> str:
        ma  = close.rolling(period).mean()
        std = close.rolling(period).std()
        width_now = float((std * 2).iloc[-1])
        width_avg = float((std * 2).rolling(period).mean().iloc[-1])
        if width_avg <= 0:
            return "NORMAL"
        ratio = width_now / width_avg
        if ratio < 0.7:
            return "SQUEEZE"
        if ratio > 1.4:
            return "EXPANSION"
        return "NORMAL"

    # ── チャートパターン検出 ─────────────────────────────────
    def _detect_chart_pattern(self, df: pd.DataFrame) -> str:
        """T-12連携: chart_patterns.pyへのブリッジ"""
        try:
            from ono_estimator.indicators.chart_patterns import ChartPatterns
            return ChartPatterns.detect_primary(df)
        except Exception:
            return "なし"

    # ── ゾーン判定 ───────────────────────────────────────────
    def _determine_zone(self, cur: float, support: float,
                        resistance: float, upper_trend: str) -> str:
        if support <= 0 and resistance <= 0:
            return "MIDDLE"
        tol = cur * 0.003
        if resistance > 0 and abs(cur - resistance) < tol:
            return "RESISTANCE"
        if support > 0 and abs(cur - support) < tol:
            return "SUPPORT"
        if resistance > 0 and support > 0:
            mid = (resistance + support) / 2
            rng = resistance - support
            if rng > 0:
                ratio = (cur - support) / rng
                if upper_trend == "UP":
                    return "PULLBACK" if ratio < 0.4 else "MIDDLE"
                elif upper_trend == "DOWN":
                    return "PULLBACK" if ratio > 0.6 else "MIDDLE"
        return "MIDDLE"

    # ── 押し目/戻し圏有効性 ──────────────────────────────────
    def _is_pullback_valid(self, zone: str, upper_trend: str,
                           bb_state: str) -> bool:
        if zone in ("PULLBACK", "SUPPORT") and upper_trend == "UP":
            return True
        if zone in ("PULLBACK", "RESISTANCE") and upper_trend == "DOWN":
            return True
        # BBスクイーズ後のエクスパンション準備
        if bb_state == "SQUEEZE" and zone == "MIDDLE":
            return True
        return False

    def _build_reason(self, ctx: ZoneContext) -> str:
        parts = [f"ゾーン:{ctx.zone}", f"BB:{ctx.bb_state}"]
        if ctx.reji_support_flip:
            parts.append("レジサポ転換")
        if ctx.chart_pattern != "なし":
            parts.append(f"パターン:{ctx.chart_pattern}")
        if ctx.pullback_valid:
            parts.append("押し目/戻し圏OK")
        return " | ".join(parts)
