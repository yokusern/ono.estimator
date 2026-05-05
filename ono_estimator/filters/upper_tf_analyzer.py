"""
UpperTFAnalyzer — 上位足(4h/1h)分析モジュール (T-02)
===================================================
実装技術:
  - ダウ理論: 高値・安値の切り上げ/切り下げ
  - 大循環ステージ判定 (1-6)
  - MAパーフェクトオーダー
  - グランビルの法則 (8パターン)
  - 一目均衡表 三役好転/逆転
  - チャネルライン位置
"""
import pandas as pd
import numpy as np
from typing import Optional
from ono_estimator.core.reasoning_engine import UpperContext
from ono_estimator.indicators.technical import TechnicalIndicators


class UpperTFAnalyzer:

    def analyze(self, df_primary: pd.DataFrame,
                df_secondary: Optional[pd.DataFrame] = None) -> UpperContext:
        ctx = UpperContext()
        if df_primary is None or len(df_primary) < 30:
            return ctx

        close = df_primary["close"]
        high  = df_primary["high"]
        low   = df_primary["low"]

        # ── 1) ダウ理論 ────────────────────────────────────────
        ctx.trend, ctx.dow_reason = self._dow_theory(high, low, close)

        # ── 2) 大循環ステージ (MA5/MA20/MA60) ─────────────────
        ctx.stage, ctx.stage_label = self._dai_circulation_stage(close)

        # ── 3) MAパーフェクトオーダー ──────────────────────────
        ctx.perfect_order = self._perfect_order(close)

        # ── 4) グランビルパターン ──────────────────────────────
        try:
            ma14 = close.rolling(14).mean()
            ctx.granville = TechnicalIndicators.detect_granville(close, ma14)
        except Exception:
            pass

        # ── 5) 一目均衡表 ──────────────────────────────────────
        if len(df_primary) >= 60:
            try:
                ichi = TechnicalIndicators.ichimoku(high, low, close)
                ctx.ichimoku_status = self._ichimoku_label(ichi)
            except Exception:
                pass

        # ── 6) チャネルライン位置 ──────────────────────────────
        ctx.channel_position = self._channel_position(high, low, close)

        # ── 総合スコア ────────────────────────────────────────
        ctx.score = self._calc_score(ctx)
        ctx.reason = self._build_reason(ctx)
        return ctx

    # ── ダウ理論 ─────────────────────────────────────────────
    def _dow_theory(self, high: pd.Series, low: pd.Series,
                    close: pd.Series, lookback: int = 30) -> tuple:
        h = high.tail(lookback)
        l = low.tail(lookback)
        # スイングハイ/ロー（簡易: 3本ローソクで検出）
        swing_highs = h[(h.shift(1) < h) & (h.shift(-1) < h)]
        swing_lows  = l[(l.shift(1) > l) & (l.shift(-1) > l)]

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "RANGE", "スイング不足"

        h1, h2 = float(swing_highs.iloc[-1]), float(swing_highs.iloc[-2])
        l1, l2 = float(swing_lows.iloc[-1]),  float(swing_lows.iloc[-2])

        hh = h1 > h2  # 高値切り上げ
        hl = l1 > l2  # 安値切り上げ
        lh = h1 < h2  # 高値切り下げ
        ll = l1 < l2  # 安値切り下げ

        if hh and hl:
            return "UP",    f"高値切上({h2:.3f}→{h1:.3f}) + 安値切上({l2:.3f}→{l1:.3f})"
        if lh and ll:
            return "DOWN",  f"高値切下({h2:.3f}→{h1:.3f}) + 安値切下({l2:.3f}→{l1:.3f})"
        if hh and ll:
            return "RANGE", f"高値切上 + 安値切下（もみ合い）"
        return "RANGE", f"明確なトレンドなし"

    # ── 大循環ステージ ─────────────────────────────────────────
    def _dai_circulation_stage(self, close: pd.Series) -> tuple:
        ma_s = float(close.ewm(span=5,  adjust=False).mean().iloc[-1])
        ma_m = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ma_l = float(close.ewm(span=60, adjust=False).mean().iloc[-1])

        if   ma_s > ma_m > ma_l: return 1, "上昇トレンド"
        elif ma_m > ma_s > ma_l: return 2, "もみ合い（上→下移行）"
        elif ma_m > ma_l > ma_s: return 3, "もみ合い"
        elif ma_l > ma_m > ma_s: return 4, "下降トレンド"
        elif ma_l > ma_s > ma_m: return 5, "もみ合い（下→上移行）"
        elif ma_s > ma_l > ma_m: return 6, "もみ合い"
        return 0, "不明"

    # ── MAパーフェクトオーダー ────────────────────────────────
    def _perfect_order(self, close: pd.Series) -> str:
        ma_s = float(close.rolling(5).mean().iloc[-1])
        ma_m = float(close.rolling(20).mean().iloc[-1])
        ma_l = float(close.rolling(60).mean().iloc[-1])
        if ma_s > ma_m > ma_l:
            return "UP"
        if ma_s < ma_m < ma_l:
            return "DOWN"
        return "NONE"

    # ── 一目均衡表ラベル ──────────────────────────────────────
    def _ichimoku_label(self, ichi: dict) -> str:
        chikou = ichi.get("chikou_cross", "NONE")
        cloud  = ichi.get("price_vs_cloud", "N/A")
        labels = []
        if chikou == "BULLISH" and cloud == "ABOVE":
            return "三役好転（最強の買いサイン）"
        if chikou == "BEARISH" and cloud == "BELOW":
            return "三役逆転（最強の売りサイン）"
        if chikou == "BULLISH":
            labels.append("遅行スパン好転")
        elif chikou == "BEARISH":
            labels.append("遅行スパン逆転")
        if cloud == "ABOVE":
            labels.append("雲の上")
        elif cloud == "BELOW":
            labels.append("雲の下")
        else:
            labels.append("雲の中（様子見）")
        return " / ".join(labels) if labels else "中立"

    # ── チャネルライン位置 ─────────────────────────────────────
    def _channel_position(self, high: pd.Series, low: pd.Series,
                          close: pd.Series, period: int = 20) -> str:
        h_max = float(high.tail(period).max())
        l_min = float(low.tail(period).min())
        cur   = float(close.iloc[-1])
        if h_max == l_min:
            return "INSIDE"
        ratio = (cur - l_min) / (h_max - l_min)
        if ratio > 0.8:
            return "UPPER"   # チャネル上限付近
        if ratio < 0.2:
            return "LOWER"   # チャネル下限付近
        return "INSIDE"

    # ── スコア計算 ────────────────────────────────────────────
    def _calc_score(self, ctx: UpperContext) -> int:
        score = 50
        if ctx.trend != "RANGE":
            score += 15
        if ctx.stage in (1, 4):
            score += 15
        elif ctx.stage in (2, 3, 5, 6):
            score -= 10
        if ctx.perfect_order != "NONE":
            score += 10
        if "三役好転" in ctx.ichimoku_status or "三役逆転" in ctx.ichimoku_status:
            score += 15
        if "最重要" in ctx.granville or "買い②" in ctx.granville or "売り②" in ctx.granville:
            score += 10
        return min(100, max(0, score))

    def _build_reason(self, ctx: UpperContext) -> str:
        parts = [f"トレンド:{ctx.trend}(ステージ{ctx.stage}={ctx.stage_label})"]
        if ctx.perfect_order != "NONE":
            parts.append(f"PO:{ctx.perfect_order}")
        if ctx.ichimoku_status:
            parts.append(ctx.ichimoku_status)
        if ctx.granville != "なし":
            parts.append(f"グランビル:{ctx.granville}")
        return " | ".join(parts)
