"""
EntryTypeDetector — C-1
コード側でエントリータイプを判定する。Geminiのテキスト解釈に依存しない。
  LIQUIDITY_SWEEP : スイング高値/安値を一時的に超えた後に実体が戻る
  BODY_BREAK      : 抵抗/支持レベルをローソク実体が超えた
  WICK_DENIAL     : 前足ヒゲ先端を現在足実体が塗りつぶした
  HAS_SHOULDER    : 三尊/逆三尊の右肩崩れ（pattern_matcherと連携）
  NONE            : 上記に該当しない
"""
from __future__ import annotations
import pandas as pd
from .liquidity_sweep import detect_liquidity_sweep


def detect_entry_type(
    df: pd.DataFrame,
    key_levels: dict | None = None,
    has_pattern: str = "なし",
) -> str:
    """
    df         : OHLCV DataFrame（最低5本）
    key_levels : {"R": [float,...], "S": [float,...]}
    has_pattern: IronPatternMatcherから渡される三尊/逆三尊パターン文字列
    """
    if df is None or len(df) < 5:
        return "NONE"

    # 1. Liquidity Sweep が最優先
    sweep = detect_liquidity_sweep(df)
    if sweep["detected"]:
        return "LIQUIDITY_SWEEP"

    cur  = df.iloc[-1]
    prev = df.iloc[-2]

    cur_open  = float(cur["open"])
    cur_close = float(cur["close"])
    cur_high  = float(cur["high"])
    cur_low   = float(cur["low"])
    prev_high = float(prev["high"])
    prev_low  = float(prev["low"])

    body_top    = max(cur_open, cur_close)
    body_bottom = min(cur_open, cur_close)

    # 2. Wick Denial: 前足のヒゲ先端を現在足実体が塗りつぶした
    # 上ヒゲ否定（SELL）: 前足の上ヒゲ先端 > 前足実体上端 かつ 現在実体がそれを覆った
    prev_body_top    = max(float(prev["open"]), float(prev["close"]))
    prev_body_bottom = min(float(prev["open"]), float(prev["close"]))
    prev_upper_wick  = prev_high - prev_body_top
    prev_lower_wick  = prev_body_bottom - prev_low

    if prev_upper_wick > 0 and body_top >= prev_high:
        return "WICK_DENIAL"
    if prev_lower_wick > 0 and body_bottom <= prev_low:
        return "WICK_DENIAL"

    # 3. Body Break: キーレベルを実体でブレイク
    if key_levels:
        r_levels = key_levels.get("R", [])
        s_levels = key_levels.get("S", [])
        for lvl in r_levels:
            if isinstance(lvl, (int, float)) and body_top > lvl > body_bottom:
                return "BODY_BREAK"
            if isinstance(lvl, (int, float)) and prev_body_top < lvl and body_close_above(cur_close, lvl):
                return "BODY_BREAK"
        for lvl in s_levels:
            if isinstance(lvl, (int, float)) and body_bottom < lvl < body_top:
                return "BODY_BREAK"

    # 4. H&S 右肩崩れ
    if has_pattern in ("#HeadAndShoulders", "#InverseHeadAndShoulders",
                       "HeadAndShoulders", "InverseHeadAndShoulders",
                       "三尊", "逆三尊"):
        return "HAS_SHOULDER"

    return "NONE"


def body_close_above(close: float, level: float) -> bool:
    return close > level
