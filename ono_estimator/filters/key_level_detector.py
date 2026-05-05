"""
KeyLevelDetector — 水平線（キーレベル）検出 (2-2)
==================================================
日足・4H足の直近High/Lowから集積帯を自動検出。
"""
from __future__ import annotations
import pandas as pd
from typing import Optional


class KeyLevelDetector:

    def __init__(self, cluster_pct: float = 0.003, near_pct: float = 0.005):
        self.cluster_pct = cluster_pct  # ±0.3%内を同一レベルと判断
        self.near_pct    = near_pct     # ±0.5%内なら"付近"と判断

    def detect(self, df_4h: Optional[pd.DataFrame],
               df_1d: Optional[pd.DataFrame],
               current_price: float,
               lookback: int = 50) -> dict:
        """
        戻り値:
          near_key_level: bool
          breakout: bool
          score_bonus: int
          tags: list[str]
          levels: list[float]
          caution: str
        """
        levels = self._collect_levels(df_4h, df_1d, lookback)
        clustered = self._cluster_levels(levels, current_price)

        near = self._is_near(clustered, current_price)
        breakout = self._is_breakout(df_4h, clustered, current_price)

        score_bonus = 0
        tags = []
        caution = ""

        if breakout:
            score_bonus += 15
            tags.append("#KeyLevel_Breakout")
            caution = f"🚀 キーレベル({breakout:.3f})をブレイク — 強いモメンタムの可能性"
        elif near:
            score_bonus += 10
            caution = f"📍 キーレベル付近({near:.3f}) — S/R機能に注意"

        return {
            "near_key_level": bool(near),
            "nearest_level":  float(near) if near else 0.0,
            "breakout":       bool(breakout),
            "breakout_level": float(breakout) if breakout else 0.0,
            "score_bonus":    score_bonus,
            "tags":           tags,
            "levels":         clustered,
            "caution":        caution,
        }

    def _collect_levels(self, df_4h, df_1d, lookback: int) -> list:
        highs, lows = [], []
        for df in (df_4h, df_1d):
            if df is None or len(df) < 5:
                continue
            tail = df.tail(lookback)
            highs.extend(float(v) for v in tail["high"].values)
            lows.extend(float(v) for v in tail["low"].values)
        return highs + lows

    def _cluster_levels(self, levels: list, ref: float) -> list:
        """±cluster_pct以内の価格を1つのレベルに集約"""
        if not levels:
            return []
        sorted_lv = sorted(levels)
        clusters: list[list] = []
        for price in sorted_lv:
            placed = False
            for cl in clusters:
                if abs(price - cl[0]) / (cl[0] + 1e-9) <= self.cluster_pct:
                    cl.append(price)
                    placed = True
                    break
            if not placed:
                clusters.append([price])
        # クラスター内の中央値を代表値とし、3点以上集まったものだけ採用
        result = []
        for cl in clusters:
            if len(cl) >= 2:
                mid = sorted(cl)[len(cl) // 2]
                result.append(round(mid, 6))
        return result

    def _is_near(self, levels: list, price: float) -> float:
        """price がいずれかのレベルの near_pct以内なら そのレベルを返す"""
        for lv in levels:
            if lv <= 0:
                continue
            if abs(price - lv) / lv <= self.near_pct:
                return lv
        return 0.0

    def _is_breakout(self, df_4h, levels: list, price: float) -> float:
        """直近の確定足がレベルを超えたらそのレベルを返す"""
        if df_4h is None or len(df_4h) < 3:
            return 0.0
        prev_close = float(df_4h["close"].iloc[-3])
        curr_close = float(df_4h["close"].iloc[-2])
        for lv in levels:
            if lv <= 0:
                continue
            # 上方ブレイク: 前回足がレベル以下 → 今回足がレベル超え
            if prev_close <= lv < curr_close:
                return lv
            # 下方ブレイク: 前回足がレベル以上 → 今回足がレベル未満
            if prev_close >= lv > curr_close:
                return lv
        return 0.0
