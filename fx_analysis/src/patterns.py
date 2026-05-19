"""
ローソク足パターン検出。
全パターンは binary 列として df に追加し、
PATTERN_DEFS で方向・名称を定義する。
"""
import pandas as pd
import numpy as np


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]

    body      = (c - o).abs()
    body_top  = c.where(c >= o, o)   # max(open, close)
    body_bot  = o.where(c >= o, c)   # min(open, close)
    upper_w   = h - body_top
    lower_w   = body_bot - l
    bar_range = (h - l).replace(0, np.nan)
    avg_range = bar_range.rolling(20).mean()

    # ── ピンバー系 ──────────────────────────────────────────────────────
    # ハンマー: 下ひげ >= 2 × 実体, 上ひげ小
    df["pat_hammer"] = (
        (lower_w >= 2.0 * body.replace(0, np.nan)) &
        (upper_w <= 0.4 * body.replace(0, np.nan)) &
        (bar_range > 0)
    )
    # シューティングスター: 上ひげ >= 2 × 実体, 下ひげ小
    df["pat_shoot"] = (
        (upper_w >= 2.0 * body.replace(0, np.nan)) &
        (lower_w <= 0.4 * body.replace(0, np.nan)) &
        (bar_range > 0)
    )
    # ブルピンバー（方向不問): 下ひげ >= バーレンジの 55%
    df["pat_pin_bull"] = (lower_w / bar_range >= 0.55)
    # ベアピンバー: 上ひげ >= バーレンジの 55%
    df["pat_pin_bear"] = (upper_w / bar_range >= 0.55)

    # ── 包み足 ─────────────────────────────────────────────────────────
    prev_o, prev_c = o.shift(1), c.shift(1)
    df["pat_bull_engulf"] = (
        (c > o) &                        # 今: 陽線
        (prev_o > prev_c) &              # 前: 陰線
        (o <= prev_c) &
        (c >= prev_o)
    )
    df["pat_bear_engulf"] = (
        (c < o) &                        # 今: 陰線
        (prev_c > prev_o) &              # 前: 陽線
        (o >= prev_c) &
        (c <= prev_o)
    )

    # ── 十字線（ドージ）──────────────────────────────────────────────
    df["pat_doji"] = (body / bar_range <= 0.08)

    # ── インサイドバー ──────────────────────────────────────────────
    df["pat_inside"] = (h <= h.shift(1)) & (l >= l.shift(1))

    # ── 強いモメンタムバー ──────────────────────────────────────────
    df["pat_bull_strong"] = (
        (c > o) &
        (body / bar_range >= 0.70) &
        (bar_range >= avg_range)
    )
    df["pat_bear_strong"] = (
        (c < o) &
        (body / bar_range >= 0.70) &
        (bar_range >= avg_range)
    )

    # ── 3本パターン ─────────────────────────────────────────────────
    # モーニングスター (下降→小さい十字→上昇)
    df["pat_morning_star"] = (
        (o.shift(2) > c.shift(2)) &
        (body.shift(1) < 0.5 * body.shift(2)) &
        (c > o) &
        (c > (o.shift(2) + c.shift(2)) / 2)
    )
    # イブニングスター
    df["pat_evening_star"] = (
        (c.shift(2) > o.shift(2)) &
        (body.shift(1) < 0.5 * body.shift(2)) &
        (c < o) &
        (c < (o.shift(2) + c.shift(2)) / 2)
    )

    # ── ダブルトップ / ダブルボトム（簡易: 20〜60本前の高値/安値と近接）──
    lookback = 30
    tol = 0.003   # 0.3% の許容誤差
    prev_high = h.shift(lookback).rolling(lookback).max()
    prev_low  = l.shift(lookback).rolling(lookback).min()
    df["pat_double_top"]    = ((h - prev_high).abs() / prev_high.replace(0, np.nan) <= tol) & (c < o)
    df["pat_double_bottom"] = ((l - prev_low).abs()  / prev_low.replace(0, np.nan)  <= tol) & (c > o)

    # ── フォールスブレイク（ダマシ）検出 ───────────────────────────
    # 前本の安値を更新したが今本で回復 → 下方ダマシ（強気サイン）
    df["pat_false_break_low"]  = (l < l.shift(1)) & (c > l.shift(1))
    # 前本の高値を更新したが今本で回復 → 上方ダマシ（弱気サイン）
    df["pat_false_break_high"] = (h > h.shift(1)) & (c < h.shift(1))

    # ── インサイドバーブレイク ────────────────────────────────────
    # インサイドバーが確認された後、翌本が上方ブレイク
    inside_prev = (h.shift(1) <= h.shift(2)) & (l.shift(1) >= l.shift(2))
    df["pat_inside_bull_break"] = inside_prev & (c > h.shift(1)) & (c > o)
    df["pat_inside_bear_break"] = inside_prev & (c < l.shift(1)) & (c < o)

    # ── フラッグ / ペナント ────────────────────────────────────────
    # ブルフラッグ: 直近8本で急騰（平均レンジの2倍以上の上昇）→ 3〜8本の小さい押し目 → 上方ブレイク
    pole_up   = (c.shift(4) - c.shift(8)) / avg_range.shift(4).replace(0, np.nan) >= 2.0
    consol_dn = (c.shift(1) < c.shift(4)) & (body.rolling(4).mean() < avg_range * 0.6)
    df["pat_bull_flag"] = pole_up & consol_dn & (c > c.shift(1)) & (c > o)

    pole_dn   = (c.shift(8) - c.shift(4)) / avg_range.shift(4).replace(0, np.nan) >= 2.0
    consol_up = (c.shift(1) > c.shift(4)) & (body.rolling(4).mean() < avg_range * 0.6)
    df["pat_bear_flag"] = pole_dn & consol_up & (c < c.shift(1)) & (c < o)

    # ── ウェッジ（収束パターン）────────────────────────────────────
    # フォーリングウェッジ（買い）: 安値・高値ともに切り下がるが幅が収束
    n = 10
    h_slope = h.diff(n)       # 直近n本の高値の変化
    l_slope = l.diff(n)       # 直近n本の安値の変化
    hl_range = h - l
    avg_hl_range = hl_range.rolling(n).mean()
    # フォーリングウェッジ: 高値・安値ともに下向きだが、安値の傾きが浅くなってきた（収束）
    df["pat_falling_wedge"] = (
        (h_slope < 0) & (l_slope < 0) &
        (l_slope > h_slope) &              # 安値の下落が緩い = 収束
        (hl_range < avg_hl_range * 0.8) &  # レンジ縮小
        (c > o)                            # 陽線で確認
    )
    # ライジングウェッジ（売り）: 高値・安値ともに切り上がるが幅が収束
    df["pat_rising_wedge"] = (
        (h_slope > 0) & (l_slope > 0) &
        (h_slope > l_slope) &              # 高値の上昇が緩い = 収束
        (hl_range < avg_hl_range * 0.8) &
        (c < o)
    )

    # ── 上昇三角形 / 下降三角形 ────────────────────────────────────
    # 上昇三角形（買い）: 水平な上値抵抗 + 切り上がる下値支持
    recent_h_max = h.rolling(15).max()
    l_slope_pos  = l.diff(8) > 0                      # 安値が切り上がっている
    h_flat       = (h - recent_h_max).abs() / recent_h_max.replace(0, np.nan) < 0.002
    df["pat_asc_triangle"] = (
        l_slope_pos & h_flat &
        (c > (recent_h_max * 0.998)) &  # 上値抵抗にタッチ
        (c > o)
    )
    # 下降三角形（売り）: 切り下がる上値抵抗 + 水平な下値支持
    recent_l_min = l.rolling(15).min()
    h_slope_neg  = h.diff(8) < 0
    l_flat       = (l - recent_l_min).abs() / recent_l_min.replace(0, np.nan) < 0.002
    df["pat_desc_triangle"] = (
        h_slope_neg & l_flat &
        (c < (recent_l_min * 1.002)) &
        (c < o)
    )

    # ── ヘッドアンドショルダー（簡易）────────────────────────────
    # ベア H&S: 左肩(peak) → 頭(より高いpeak) → 右肩(左肩に近い低いpeak) → ネックライン割れ
    # 直近30本での近似検出
    roll_max = h.rolling(5, center=True).max()
    is_peak  = (h == roll_max)
    # 直近15本の中で最高値が中央付近にある（頭）
    head_high = h.rolling(30).max()
    left_sh   = h.shift(20).rolling(10).max()
    right_sh  = h.shift(5).rolling(10).max()
    neckline  = l.rolling(30).mean()
    df["pat_hs_bear"] = (
        (head_high > left_sh * 1.01) &     # 頭が左肩より高い
        (right_sh < head_high * 0.99) &    # 右肩が頭より低い
        ((left_sh - right_sh).abs() / left_sh.replace(0, np.nan) < 0.03) &  # 左右肩が近い
        (c < neckline) &                   # ネックライン割れ
        (c < o)
    )
    # ブル 逆H&S
    head_low   = l.rolling(30).min()
    left_sh_l  = l.shift(20).rolling(10).min()
    right_sh_l = l.shift(5).rolling(10).min()
    neck_top   = h.rolling(30).mean()
    df["pat_ihs_bull"] = (
        (head_low < left_sh_l * 0.99) &
        (right_sh_l > head_low * 1.01) &
        ((left_sh_l - right_sh_l).abs() / left_sh_l.replace(0, np.nan).abs() < 0.03) &
        (c > neck_top) &
        (c > o)
    )

    return df.fillna({col: False for col in df.columns if col.startswith("pat_")})


# バックテスト用パターン定義 (列名, 方向, 表示名)
PATTERN_DEFS = [
    ("pat_hammer",             "buy",  "ハンマー"),
    ("pat_shoot",              "sell", "シューティングスター"),
    ("pat_pin_bull",           "buy",  "ブル・ピンバー"),
    ("pat_pin_bear",           "sell", "ベア・ピンバー"),
    ("pat_bull_engulf",        "buy",  "陽線包み足"),
    ("pat_bear_engulf",        "sell", "陰線包み足"),
    ("pat_morning_star",       "buy",  "モーニングスター"),
    ("pat_evening_star",       "sell", "イブニングスター"),
    ("pat_bull_strong",        "buy",  "強い陽線"),
    ("pat_bear_strong",        "sell", "強い陰線"),
    ("pat_double_bottom",      "buy",  "ダブルボトム"),
    ("pat_double_top",         "sell", "ダブルトップ"),
    ("pat_false_break_low",    "buy",  "下方ダマシ（強気反転）"),
    ("pat_false_break_high",   "sell", "上方ダマシ（弱気反転）"),
    ("pat_inside_bull_break",  "buy",  "インサイドバー上抜け"),
    ("pat_inside_bear_break",  "sell", "インサイドバー下抜け"),
    ("pat_bull_flag",          "buy",  "ブルフラッグ"),
    ("pat_bear_flag",          "sell", "ベアフラッグ"),
    ("pat_falling_wedge",      "buy",  "フォーリングウェッジ"),
    ("pat_rising_wedge",       "sell", "ライジングウェッジ"),
    ("pat_asc_triangle",       "buy",  "上昇三角形ブレイク"),
    ("pat_desc_triangle",      "sell", "下降三角形ブレイク"),
    ("pat_hs_bear",            "sell", "ヘッドアンドショルダー"),
    ("pat_ihs_bull",           "buy",  "逆ヘッドアンドショルダー"),
]
