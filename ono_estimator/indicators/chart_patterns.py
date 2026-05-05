"""
ChartPatterns — チャートパターン自動検出 (T-12)
================================================
実装パターン:
  - ダブルトップ / ダブルボトム
  - 三尊 / 逆三尊（ヘッドアンドショルダー）
  - 三角保ち合い (上昇/下降/対称)
  - フラッグ / ペナント
  - ウェッジ
"""
from __future__ import annotations
import pandas as pd
import numpy as np


class ChartPatterns:

    @staticmethod
    def detect_primary(df: pd.DataFrame, lookback: int = 60) -> str:
        """最も顕著なパターンを1つ返す（ZoneAnalyzer向け）"""
        if df is None or len(df) < 20:
            return "なし"
        try:
            df = df.tail(lookback).copy().reset_index(drop=True)
            high  = df["high"]
            low   = df["low"]
            close = df["close"]

            # 優先順位順にチェック
            result = ChartPatterns._double_top(high, close)
            if result:
                return result

            result = ChartPatterns._double_bottom(low, close)
            if result:
                return result

            result = ChartPatterns._head_and_shoulders(high, low)
            if result:
                return result

            result = ChartPatterns._triangle(high, low)
            if result:
                return result

            result = ChartPatterns._flag_pennant(high, low, close)
            if result:
                return result

            result = ChartPatterns._wedge(high, low)
            if result:
                return result

            return "なし"
        except Exception:
            return "なし"

    # ── ダブルトップ ──────────────────────────────────────────
    @staticmethod
    def _double_top(high: pd.Series, close: pd.Series) -> str:
        """2つの高値がほぼ同じ高さで出現"""
        peaks = _find_peaks(high, order=5)
        if len(peaks) < 2:
            return ""
        p1, p2 = float(high.iloc[peaks[-2]]), float(high.iloc[peaks[-1]])
        tol = max(p1, p2) * 0.003
        if abs(p1 - p2) < tol and p1 > float(close.iloc[-1]) * 1.001:
            return "ダブルトップ"
        return ""

    # ── ダブルボトム ──────────────────────────────────────────
    @staticmethod
    def _double_bottom(low: pd.Series, close: pd.Series) -> str:
        """2つの安値がほぼ同じ深さで出現"""
        troughs = _find_troughs(low, order=5)
        if len(troughs) < 2:
            return ""
        t1, t2 = float(low.iloc[troughs[-2]]), float(low.iloc[troughs[-1]])
        tol = min(t1, t2) * 0.003
        if abs(t1 - t2) < tol and t1 < float(close.iloc[-1]) * 0.999:
            return "ダブルボトム"
        return ""

    # ── ヘッドアンドショルダー ──────────────────────────────
    @staticmethod
    def _head_and_shoulders(high: pd.Series, low: pd.Series) -> str:
        peaks = _find_peaks(high, order=4)
        if len(peaks) < 3:
            return ""
        left, head, right = (float(high.iloc[peaks[-3]]),
                             float(high.iloc[peaks[-2]]),
                             float(high.iloc[peaks[-1]]))
        # 頭が左右の肩より高い
        if head > left and head > right:
            shoulder_diff = abs(left - right) / head
            if shoulder_diff < 0.03:
                return "三尊（ヘッドアンドショルダー）"

        troughs = _find_troughs(low, order=4)
        if len(troughs) < 3:
            return ""
        left_t, head_t, right_t = (float(low.iloc[troughs[-3]]),
                                   float(low.iloc[troughs[-2]]),
                                   float(low.iloc[troughs[-1]]))
        if head_t < left_t and head_t < right_t:
            shoulder_diff = abs(left_t - right_t) / abs(head_t)
            if shoulder_diff < 0.03:
                return "逆三尊（逆ヘッドアンドショルダー）"
        return ""

    # ── 三角保ち合い ──────────────────────────────────────────
    @staticmethod
    def _triangle(high: pd.Series, low: pd.Series) -> str:
        n = len(high)
        if n < 15:
            return ""
        # 高値トレンド（線形回帰の傾き）
        x = np.arange(n)
        h_slope = np.polyfit(x, high.values, 1)[0]
        l_slope = np.polyfit(x, low.values,  1)[0]

        h_norm = h_slope / (float(high.mean()) + 1e-9)
        l_norm = l_slope / (float(low.mean())  + 1e-9)

        if h_norm < -0.0005 and l_norm > 0.0005:
            return "対称三角保ち合い"
        if h_norm < -0.0005 and abs(l_norm) < 0.0002:
            return "下降三角保ち合い"
        if abs(h_norm) < 0.0002 and l_norm > 0.0005:
            return "上昇三角保ち合い"
        return ""

    # ── フラッグ / ペナント ───────────────────────────────────
    @staticmethod
    def _flag_pennant(high: pd.Series, low: pd.Series, close: pd.Series) -> str:
        n = len(close)
        if n < 15:
            return ""
        # 直近10本の値動き幅 vs 前の10本の値動き幅
        prev_range  = float(high.iloc[:n//2].max() - low.iloc[:n//2].min())
        recent_range = float(high.iloc[n//2:].max() - low.iloc[n//2:].min())
        if prev_range <= 0:
            return ""
        compression = recent_range / prev_range

        # 前半が強いトレンドで後半が圧縮
        prev_move = float(close.iloc[n//2] - close.iloc[0])
        if compression < 0.4 and abs(prev_move) > prev_range * 0.4:
            if prev_move > 0:
                return "強気フラッグ（上昇継続示唆）"
            else:
                return "弱気フラッグ（下降継続示唆）"
        return ""

    # ── ウェッジ ──────────────────────────────────────────────
    @staticmethod
    def _wedge(high: pd.Series, low: pd.Series) -> str:
        n = len(high)
        if n < 15:
            return ""
        x = np.arange(n)
        h_slope = np.polyfit(x, high.values, 1)[0]
        l_slope = np.polyfit(x, low.values,  1)[0]

        h_norm = h_slope / (float(high.mean()) + 1e-9)
        l_norm = l_slope / (float(low.mean())  + 1e-9)

        # 両方が同方向に収縮
        if h_norm > 0.0003 and l_norm > 0.0003 and h_norm < l_norm:
            return "上昇ウェッジ（反転示唆）"
        if h_norm < -0.0003 and l_norm < -0.0003 and h_norm > l_norm:
            return "下降ウェッジ（反転示唆）"
        return ""

    # ── 全パターン検出（詳細版） ──────────────────────────────
    @staticmethod
    def detect_all(df: pd.DataFrame) -> list[str]:
        """検出された全パターンをリストで返す"""
        if df is None or len(df) < 20:
            return []
        results = []
        df = df.tail(60).copy().reset_index(drop=True)
        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        for fn in (
            lambda: ChartPatterns._double_top(high, close),
            lambda: ChartPatterns._double_bottom(low, close),
            lambda: ChartPatterns._head_and_shoulders(high, low),
            lambda: ChartPatterns._triangle(high, low),
            lambda: ChartPatterns._flag_pennant(high, low, close),
            lambda: ChartPatterns._wedge(high, low),
        ):
            try:
                r = fn()
                if r:
                    results.append(r)
            except Exception:
                pass
        return results


# ── ヘルパー関数 ──────────────────────────────────────────────
def _find_peaks(series: pd.Series, order: int = 5) -> list[int]:
    """ローカル最大値のインデックスリストを返す"""
    vals = series.values
    n = len(vals)
    peaks = []
    for i in range(order, n - order):
        window = vals[i - order: i + order + 1]
        if vals[i] == max(window):
            peaks.append(i)
    return peaks


def _find_troughs(series: pd.Series, order: int = 5) -> list[int]:
    """ローカル最小値のインデックスリストを返す"""
    vals = series.values
    n = len(vals)
    troughs = []
    for i in range(order, n - order):
        window = vals[i - order: i + order + 1]
        if vals[i] == min(window):
            troughs.append(i)
    return troughs
