"""
BreakoutDetector — レンジ検出 + ブレイクアウト確認
================================================
純アルゴリズム（AI不使用）でローソク足データを解析する。

検出内容:
  1. レンジ検出    : 過去N本で水平レンジを形成しているか
  2. ブレイクアウト : レンジ上限/下限をクローズで突破したか
  3. リテスト      : ブレイクアウト後に旧レンジ境界を再タッチしたか
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class BreakoutResult:
    # ─── レンジ状態 ───────────────────────────────────────
    in_range: bool = False          # 現在レンジ中か
    range_high: float = 0.0         # レンジ上限
    range_low: float = 0.0          # レンジ下限
    range_width_pct: float = 0.0    # レンジ幅 (%)
    range_bars: int = 0             # レンジ継続バー数

    # ─── ブレイクアウト状態 ─────────────────────────────
    breakout: str = "NONE"          # "UP" / "DOWN" / "NONE"
    breakout_confirmed: bool = False # クローズで完全にブレイクしたか
    breakout_strength: float = 0.0  # 0.0〜1.0 (強さ指標)
    breakout_bars_ago: int = 0      # 何本前にブレイクしたか

    # ─── リテスト状態 ───────────────────────────────────
    retest: bool = False            # リテスト中か (再度レンジ境界に接近)
    retest_direction: str = "NONE"  # リテスト後の方向 "UP" / "DOWN" / "NONE"

    # ─── トレード示唆 ────────────────────────────────────
    entry_signal: str = "NONE"      # "BUY" / "SELL" / "NONE"
    entry_reason: str = ""
    suggested_sl: float = 0.0
    suggested_tp: float = 0.0

    @property
    def has_signal(self) -> bool:
        return self.entry_signal in ("BUY", "SELL")


class BreakoutDetector:
    """
    使い方:
        result = BreakoutDetector().analyze(df_1h)
        if result.has_signal:
            print(result.entry_signal, result.entry_reason)
    """

    # 調整可能パラメータ
    RANGE_LOOKBACK    = 50    # レンジ検索バー数
    RANGE_MAX_WIDTH   = 0.025 # レンジの最大幅 (2.5%)
    RANGE_MIN_BARS    = 15    # レンジ最低バー数
    BREAKOUT_BUFFER   = 0.001 # ブレイク確認バッファ (0.1%)
    RETEST_PROXIMITY  = 0.002 # リテスト判定距離 (0.2%)
    PIVOT_ORDER       = 3     # ピボット検出感度

    def analyze(self, df: pd.DataFrame) -> BreakoutResult:
        result = BreakoutResult()
        if df is None or len(df) < self.RANGE_MIN_BARS + 5:
            return result

        df = df.copy().reset_index(drop=True)
        close = df["close"]
        high  = df["high"]
        low   = df["low"]

        n = len(df)
        lookback = min(self.RANGE_LOOKBACK, n - 5)
        analysis_window = df.iloc[-(lookback + 5):-5].copy().reset_index(drop=True)

        # ── STEP 1: レンジ検出 ───────────────────────────────────
        range_high, range_low = self._detect_range_levels(analysis_window)
        if range_high <= range_low:
            return result

        width_pct = (range_high - range_low) / range_low
        if width_pct > self.RANGE_MAX_WIDTH:
            # レンジ幅が広すぎる → レンジではなくトレンド
            return result

        # レンジ内に収まっているバー数を計算
        in_range_bars = int(
            ((analysis_window["high"] <= range_high * 1.002) &
             (analysis_window["low"]  >= range_low  * 0.998)).sum()
        )
        if in_range_bars < self.RANGE_MIN_BARS:
            return result

        result.in_range      = True
        result.range_high    = round(range_high, 6)
        result.range_low     = round(range_low, 6)
        result.range_width_pct = round(width_pct * 100, 3)
        result.range_bars    = in_range_bars

        # B-3: ATR連動バッファ計算（固定%より高ボラ・低ボラ相場に適応）
        hi_v = df["high"].values.astype(float)
        lo_v = df["low"].values.astype(float)
        cl_v = df["close"].values.astype(float)
        if len(hi_v) >= 15:
            tr_arr = np.maximum(hi_v[1:] - lo_v[1:],
                     np.maximum(np.abs(hi_v[1:] - cl_v[:-1]),
                                np.abs(lo_v[1:] - cl_v[:-1])))
            atr = float(np.mean(tr_arr[-14:]))
        else:
            atr = float(np.mean(hi_v - lo_v))
        atr = atr if atr > 0 else (range_high - range_low) * 0.1
        breakout_buffer   = atr * 0.5   # ブレイク確認: ATRの0.5倍
        retest_proximity  = atr * 1.5   # リテスト判定: ATRの1.5倍

        # ── STEP 2: ブレイクアウト検出 ──────────────────────────
        # 最新5本でブレイクアウトを確認
        recent = df.iloc[-5:].copy().reset_index(drop=True)
        current_close = float(close.iloc[-1])
        current_high  = float(high.iloc[-1])
        current_low   = float(low.iloc[-1])

        breakout_up   = current_close > range_high + breakout_buffer
        breakout_down = current_close < range_low  - breakout_buffer

        rng_width = range_high - range_low  # > 0 は STEP1で保証済み（念のためガード用）
        if breakout_up:
            result.breakout           = "UP"
            result.breakout_confirmed = True
            result.breakout_bars_ago  = 0
            result.breakout_strength  = min(
                (current_close - range_high) / rng_width if rng_width > 0 else 0.0, 1.0
            )
        elif breakout_down:
            result.breakout           = "DOWN"
            result.breakout_confirmed = True
            result.breakout_bars_ago  = 0
            result.breakout_strength  = min(
                (range_low - current_close) / rng_width if rng_width > 0 else 0.0, 1.0
            )
        else:
            # 過去数本でブレイクしたかチェック（ATR連動バッファ）
            for i in range(1, 5):
                c = float(close.iloc[-(i + 1)])
                if c > range_high + breakout_buffer:
                    result.breakout          = "UP"
                    result.breakout_bars_ago = i
                    break
                elif c < range_low - breakout_buffer:
                    result.breakout          = "DOWN"
                    result.breakout_bars_ago = i
                    break

        # ── STEP 3: リテスト検出 ─────────────────────────────────
        if result.breakout != "NONE" and result.breakout_bars_ago >= 1:
            if result.breakout == "UP":
                # 上方ブレイク後、旧レジスタンス（→サポート転換）に接近（ATR連動距離）
                dist = abs(current_low - range_high)
                if dist < retest_proximity and current_close > range_high:
                    result.retest           = True
                    result.retest_direction = "UP"
            elif result.breakout == "DOWN":
                # 下方ブレイク後、旧サポート（→レジスタンス転換）に接近
                dist = abs(current_high - range_low)
                if dist < retest_proximity and current_close < range_low:
                    result.retest           = True
                    result.retest_direction = "DOWN"

        # ── STEP 4: トレードシグナル生成 ─────────────────────────
        result = self._generate_signal(result, current_close)
        return result

    def _detect_range_levels(self, df: pd.DataFrame) -> tuple[float, float]:
        """
        スウィング高値・安値のクラスタリングでレンジ上限・下限を特定する。
        単純な max/min ではなく、繰り返しタッチされた価格帯を優先する。
        """
        high  = df["high"]
        low   = df["low"]

        # スウィング高値・安値を抽出
        peaks   = _find_pivots(high, self.PIVOT_ORDER, mode="high")
        troughs = _find_pivots(low,  self.PIVOT_ORDER, mode="low")

        if len(peaks) >= 2:
            # 最上位のスウィング高値の上位2つの平均をレンジ上限とする
            top_peaks = sorted([float(high.iloc[p]) for p in peaks], reverse=True)[:3]
            range_high = np.mean(top_peaks)
        else:
            range_high = float(high.max())

        if len(troughs) >= 2:
            top_troughs = sorted([float(low.iloc[t]) for t in troughs])[:3]
            range_low = np.mean(top_troughs)
        else:
            range_low = float(low.min())

        return range_high, range_low

    def _generate_signal(self, result: BreakoutResult, price: float) -> BreakoutResult:
        """シグナルとSL/TPを設定する"""
        rng = result.range_high - result.range_low

        # 最高優先: リテスト後エントリー（信頼度最高）
        if result.retest and result.retest_direction == "UP":
            result.entry_signal = "BUY"
            result.suggested_sl = round(result.range_low - rng * 0.1, 6)
            result.suggested_tp = round(result.range_high + rng * 1.0, 6)
            result.entry_reason = (
                f"上方ブレイクアウトリテスト: "
                f"レンジ{result.range_low:.5f}〜{result.range_high:.5f} "
                f"({result.range_width_pct:.2f}%) 旧レジスタンスをサポートとしてタッチ"
            )
            return result

        if result.retest and result.retest_direction == "DOWN":
            result.entry_signal = "SELL"
            result.suggested_sl = round(result.range_high + rng * 0.1, 6)
            result.suggested_tp = round(result.range_low - rng * 1.0, 6)
            result.entry_reason = (
                f"下方ブレイクアウトリテスト: "
                f"レンジ{result.range_low:.5f}〜{result.range_high:.5f} "
                f"({result.range_width_pct:.2f}%) 旧サポートをレジスタンスとしてタッチ"
            )
            return result

        # 次点: 確認済みブレイクアウト
        if result.breakout_confirmed:
            if result.breakout == "UP":
                result.entry_signal = "BUY"
                result.suggested_sl = round(result.range_high - rng * 0.2, 6)
                result.suggested_tp = round(price + rng * 1.5, 6)
                result.entry_reason = (
                    f"上方ブレイクアウト確認: "
                    f"レンジ上限 {result.range_high:.5f} を上抜け "
                    f"(強度 {result.breakout_strength:.2f})"
                )
            elif result.breakout == "DOWN":
                result.entry_signal = "SELL"
                result.suggested_sl = round(result.range_low + rng * 0.2, 6)
                result.suggested_tp = round(price - rng * 1.5, 6)
                result.entry_reason = (
                    f"下方ブレイクアウト確認: "
                    f"レンジ下限 {result.range_low:.5f} を下抜け "
                    f"(強度 {result.breakout_strength:.2f})"
                )

        return result


def _find_pivots(series: pd.Series, order: int, mode: str = "high") -> list[int]:
    """ローカルピボット（高値/安値）のインデックスを返す
    K-2: プラトー（同値複数）対策 — 同値が連続する場合は最初の1本のみ採用する"""
    vals = series.values
    n = len(vals)
    pivots = []
    for i in range(order, n - order):
        window = vals[i - order: i + order + 1]
        center = vals[i]
        if mode == "high":
            if center == max(window):
                # 左隣が同値なら既にそちらがピボット候補のため除外
                if i == order or vals[i - 1] != center:
                    pivots.append(i)
        elif mode == "low":
            if center == min(window):
                if i == order or vals[i - 1] != center:
                    pivots.append(i)
    return pivots
