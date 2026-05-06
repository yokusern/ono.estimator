"""
サポート・レジスタンス分析エンジン
==================================
直近N本のローソク足から水平線を検出し、以下を判定:
  1. 水平線の位置と強度（何回タッチしたか）
  2. 現在価格が水平線の近くにいるか
  3. 反発 or ブレイク の判定
  4. レジサポ転換（過去のレジスタンスが新しいサポートになった等）
  5. レンジ判定（上下の水平線に挟まれているか）
"""
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np
import pandas as pd


@dataclass
class SRLevel:
    """1本の水平線"""
    price: float
    strength: int
    level_type: str           # "RESISTANCE" / "SUPPORT"
    first_touch_index: int
    last_touch_index: int
    is_broken: bool = False
    is_flipped: bool = False


@dataclass
class SRResult:
    """S/R分析結果"""
    resistances: List[SRLevel] = field(default_factory=list)
    supports: List[SRLevel] = field(default_factory=list)

    nearest_resistance: Optional[SRLevel] = None
    nearest_support: Optional[SRLevel] = None

    at_resistance: bool = False
    at_support: bool = False
    bounce_detected: bool = False
    bounce_direction: str = "NONE"
    break_detected: bool = False
    break_direction: str = "NONE"
    flip_detected: bool = False
    flip_type: str = "NONE"

    is_range: bool = False
    range_high: float = 0.0
    range_low: float = 0.0
    range_width_pips: float = 0.0

    score: float = 0.0
    signals: List[str] = field(default_factory=list)


class SupportResistanceAnalyzer:
    """サポート・レジスタンス分析エンジン"""

    def __init__(self, pip_value: float = 0.01):
        self.pip_value = pip_value

    def analyze(self, df: pd.DataFrame, current_price: float = None) -> SRResult:
        result = SRResult()
        if df is None or len(df) < 10:
            return result

        if current_price is None:
            current_price = float(df["close"].iloc[-1])

        high  = df["high"].values
        low   = df["low"].values
        close = df["close"].values
        atr   = self._calc_atr(df)

        levels    = self._detect_levels(high, low, close, atr)
        clustered = self._cluster_levels(levels, atr)

        for level in clustered:
            if level.price > current_price:
                level.level_type = "RESISTANCE"
                result.resistances.append(level)
            else:
                level.level_type = "SUPPORT"
                result.supports.append(level)

        result.resistances.sort(key=lambda x: x.price)
        result.supports.sort(key=lambda x: x.price, reverse=True)

        if result.resistances:
            result.nearest_resistance = result.resistances[0]
        if result.supports:
            result.nearest_support = result.supports[0]

        tolerance = atr * 0.5
        if result.nearest_resistance and abs(current_price - result.nearest_resistance.price) < tolerance:
            result.at_resistance = True
        if result.nearest_support and abs(current_price - result.nearest_support.price) < tolerance:
            result.at_support = True

        self._detect_bounce(df, result, atr)
        self._detect_break(df, result, atr)
        self._detect_flip(df, result, high, low, close, atr)
        self._detect_range(result, current_price, atr)
        self._calc_score(result)

        return result

    def _detect_levels(self, high, low, close, atr) -> List[SRLevel]:
        levels = []
        n = len(high)
        for i in range(2, n - 2):
            if (high[i] > high[i-1] and high[i] > high[i-2] and
                    high[i] > high[i+1] and high[i] > high[i+2]):
                levels.append(SRLevel(
                    price=float(high[i]), strength=1,
                    level_type="RESISTANCE",
                    first_touch_index=i, last_touch_index=i,
                ))
            if (low[i] < low[i-1] and low[i] < low[i-2] and
                    low[i] < low[i+1] and low[i] < low[i+2]):
                levels.append(SRLevel(
                    price=float(low[i]), strength=1,
                    level_type="SUPPORT",
                    first_touch_index=i, last_touch_index=i,
                ))
        return levels

    def _cluster_levels(self, levels: List[SRLevel], atr: float) -> List[SRLevel]:
        if not levels:
            return []
        threshold = atr * 0.3
        levels.sort(key=lambda x: x.price)
        clustered = [levels[0]]
        for lv in levels[1:]:
            if abs(lv.price - clustered[-1].price) < threshold:
                clustered[-1].strength += lv.strength
                clustered[-1].price = (clustered[-1].price + lv.price) / 2
                clustered[-1].last_touch_index = max(
                    clustered[-1].last_touch_index, lv.last_touch_index
                )
            else:
                clustered.append(lv)
        return clustered

    def _detect_bounce(self, df, result: SRResult, atr: float):
        if len(df) < 3:
            return
        last3      = df.tail(3)
        close_vals = last3["close"].values
        low_vals   = last3["low"].values
        high_vals  = last3["high"].values

        if result.nearest_support:
            s = result.nearest_support.price
            if any(abs(l - s) < atr * 0.5 for l in low_vals[:-1]):
                if close_vals[-1] > close_vals[-2]:
                    result.bounce_detected   = True
                    result.bounce_direction  = "UP"
                    result.signals.append(f"🟢 サポート反発検出 @ {s:.5f} → 上昇（BUY候補）")

        if result.nearest_resistance:
            r = result.nearest_resistance.price
            if any(abs(h - r) < atr * 0.5 for h in high_vals[:-1]):
                if close_vals[-1] < close_vals[-2]:
                    result.bounce_detected   = True
                    result.bounce_direction  = "DOWN"
                    result.signals.append(f"🔴 レジスタンス反発検出 @ {r:.5f} → 下落（SELL候補）")

    def _detect_break(self, df, result: SRResult, atr: float):
        if len(df) < 2:
            return
        last      = df.iloc[-1]
        body_high = max(float(last["open"]), float(last["close"]))
        body_low  = min(float(last["open"]), float(last["close"]))

        if result.nearest_resistance:
            r = result.nearest_resistance.price
            if body_high > r:
                result.break_detected   = True
                result.break_direction  = "UP"
                result.nearest_resistance.is_broken = True
                result.signals.append(f"⚡ レジスタンスブレイク @ {r:.5f}（実体突破 → BUY継続候補）")

        if result.nearest_support:
            s = result.nearest_support.price
            if body_low < s:
                result.break_detected   = True
                result.break_direction  = "DOWN"
                result.nearest_support.is_broken = True
                result.signals.append(f"⚡ サポートブレイク @ {s:.5f}（実体突破 → SELL継続候補）")

    def _detect_flip(self, df, result: SRResult, high, low, close, atr: float):
        if len(df) < 5:
            return
        last5      = df.tail(5)
        close_last = float(close[-1])
        tolerance  = atr * 0.5

        for r in result.resistances:
            if r.is_broken:
                if any(abs(float(l) - r.price) < tolerance for l in last5["low"].values):
                    if close_last > r.price:
                        result.flip_detected = True
                        result.flip_type     = "R_TO_S"
                        r.is_flipped         = True
                        result.signals.append(
                            f"🔄 レジサポ転換（R→S）@ {r.price:.5f} — 過去のレジスタンスが新サポートに"
                        )
                        break

        for s in result.supports:
            if s.is_broken:
                if any(abs(float(h) - s.price) < tolerance for h in last5["high"].values):
                    if close_last < s.price:
                        result.flip_detected = True
                        result.flip_type     = "S_TO_R"
                        s.is_flipped         = True
                        result.signals.append(
                            f"🔄 レジサポ転換（S→R）@ {s.price:.5f} — 過去のサポートが新レジスタンスに"
                        )
                        break

        if not result.flip_detected:
            n    = len(close)
            half = n // 2
            if half >= 5:
                first_half_highs = high[:half]
                second_half_lows = low[half:]
                for fh in first_half_highs:
                    for sl_val in second_half_lows:
                        if abs(float(fh) - float(sl_val)) < tolerance:
                            if close_last > float(fh):
                                result.flip_detected = True
                                result.flip_type     = "R_TO_S"
                                result.signals.append(f"🔄 レジサポ転換（R→S）@ {float(fh):.5f}")
                                break
                    if result.flip_detected:
                        break

    def _detect_range(self, result: SRResult, current_price: float, atr: float):
        if result.nearest_resistance and result.nearest_support:
            r     = result.nearest_resistance.price
            s     = result.nearest_support.price
            width = r - s
            if 0 < width < atr * 4:
                result.is_range         = True
                result.range_high       = r
                result.range_low        = s
                result.range_width_pips = width / self.pip_value
                result.signals.append(
                    f"📦 レンジ相場 [{s:.5f}〜{r:.5f}] 幅{result.range_width_pips:.0f}pips"
                )

    def _calc_score(self, result: SRResult):
        score = 0.0
        if result.bounce_detected:
            score += 20 if result.bounce_direction == "UP" else -20
        if result.break_detected:
            score += 15 if result.break_direction == "UP" else -15
        if result.flip_detected:
            score += 25 if result.flip_type == "R_TO_S" else -25
        if result.is_range and not result.break_detected:
            score *= 0.5
        if result.nearest_support and result.nearest_support.strength >= 3:
            score += 5
        if result.nearest_resistance and result.nearest_resistance.strength >= 3:
            score -= 5
        result.score = max(-50, min(50, score))

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if "atr" in df.columns and not df["atr"].isna().all():
            val = df["atr"].iloc[-1]
            if val and val > 0:
                return float(val)
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_val = float(tr.rolling(min(period, len(df))).mean().iloc[-1])
        return atr_val if atr_val > 0 else float(close.iloc[-1]) * 0.003
