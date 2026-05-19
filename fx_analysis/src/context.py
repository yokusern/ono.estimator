"""
市場コンテキスト分析。
セッション・ボラティリティレジーム・トレンド強度・曜日などを df 列として追加。
"""
import pandas as pd
import numpy as np


def add_context(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]

    # ── セッション検出（UTC基準）───────────────────────────────────────
    try:
        if df.index.tz is not None:
            hours = df.index.tz_convert("UTC").hour
        else:
            hours = df.index.hour          # yfinanceはUTCで返すことが多い
    except Exception:
        hours = df.index.hour

    # Tokyo: 00-09 UTC (JST 09-18)
    # London: 07-16 UTC (JST 16-01)
    # NY:     12-21 UTC (JST 21-06)
    df["sess_tokyo"]   = (hours >= 0) & (hours < 9)
    df["sess_london"]  = (hours >= 7) & (hours < 16)
    df["sess_ny"]      = (hours >= 12) & (hours < 21)
    df["sess_overlap"] = (hours >= 12) & (hours < 16)   # London/NY重複（最良）
    df["sess_dead"]    = (hours >= 21) | (hours < 1)     # 静かな時間帯

    # 曜日
    df["dow"]        = df.index.dayofweek
    df["is_monday"]  = df["dow"] == 0
    df["is_friday"]  = df["dow"] == 4   # Friday は流動性低下

    # ── ボラティリティレジーム ──────────────────────────────────────
    bb_width    = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0, np.nan)
    bb_width_ma = bb_width.rolling(20).mean()
    df["regime_trending"] = bb_width > bb_width_ma * 1.1   # BBが拡張 → トレンド相場
    df["regime_ranging"]  = bb_width < bb_width_ma * 0.9   # BBが収縮 → レンジ相場
    df["regime_squeeze"]  = bb_width < bb_width_ma * 0.7   # 超収縮 → ブレイク予兆

    # ── トレンド強度・方向 ──────────────────────────────────────────
    df["ctx_bull"]        = (df["sma20"] > df["sma50"]) & (c > df["sma20"])
    df["ctx_bear"]        = (df["sma20"] < df["sma50"]) & (c < df["sma20"])
    df["ctx_sideways"]    = ~df["ctx_bull"] & ~df["ctx_bear"]

    # 200SMAが存在する場合は強いトレンド判定
    if "sma200" in df.columns:
        df["ctx_strong_bull"] = df["ctx_bull"]  & (df["sma50"] > df["sma200"])
        df["ctx_strong_bear"] = df["ctx_bear"]  & (df["sma50"] < df["sma200"])
    else:
        df["ctx_strong_bull"] = df["ctx_bull"]
        df["ctx_strong_bear"] = df["ctx_bear"]

    # ── BB内のポジション（0=下端, 1=上端）──────────────────────────
    bb_span = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    bb_pct  = (c - df["bb_lower"]) / bb_span
    df["bb_pct"]       = bb_pct
    df["bb_zone_buy"]  = bb_pct <= 0.25   # 下側25% = 買いゾーン
    df["bb_zone_sell"] = bb_pct >= 0.75   # 上側25% = 売りゾーン
    df["bb_zone_mid"]  = (bb_pct > 0.35) & (bb_pct < 0.65)

    # ── 価格とMAの乖離率 ────────────────────────────────────────────
    df["dist_sma20"]  = (c - df["sma20"]) / df["sma20"].replace(0, np.nan)
    df["dist_sma50"]  = (c - df["sma50"]) / df["sma50"].replace(0, np.nan)
    df["pullback_buy"]  = (df["ctx_bull"]) & (df["dist_sma20"] < -0.003)   # トレンド中に押した
    df["pullback_sell"] = (df["ctx_bear"]) & (df["dist_sma20"] >  0.003)   # トレンド中に戻った

    # ── キーレベル（貯金高値・安値）検出 ───────────────────────────────
    # 直近のスイングハイ/ロウ: N本のうち左右に比べて最高/最低な点
    df = _add_key_levels(df)

    return df


def _add_key_levels(df: pd.DataFrame, lookback: int = 60,
                    swing_n: int = 5, near_pct: float = 0.005) -> pd.DataFrame:
    """
    直近lookback本の高値・安値群からキーレベルを検出し、
    現在足の価格との近接判定を行う。
    near_pct: 現在価格の±0.5%以内をキーレベル付近と判断
    """
    h, l, c = df["High"], df["Low"], df["Close"]

    # ── スイングハイ/ロウ判定（左右N本より高い/低い点）────────────
    swing_high = pd.Series(False, index=df.index)
    swing_low  = pd.Series(False, index=df.index)
    for i in range(swing_n, len(df) - swing_n):
        window_h = h.iloc[i - swing_n: i + swing_n + 1]
        window_l = l.iloc[i - swing_n: i + swing_n + 1]
        if h.iloc[i] == window_h.max():
            swing_high.iloc[i] = True
        if l.iloc[i] == window_l.min():
            swing_low.iloc[i] = True

    df["swing_high"] = swing_high
    df["swing_low"]  = swing_low

    # ── 直近lookback本のキーレベルを収集 ─────────────────────────
    recent = df.tail(lookback)
    key_highs = h[swing_high & (df.index.isin(recent.index))].values.tolist()
    key_lows  = l[swing_low  & (df.index.isin(recent.index))].values.tolist()
    all_levels = sorted(set(key_highs + key_lows))

    # ── クラスタリング（±0.3%以内を同一レベルに統合）────────────
    clustered = []
    for lv in all_levels:
        placed = False
        for cl in clustered:
            if abs(lv - cl[0]) / (cl[0] + 1e-9) <= 0.003:
                cl.append(lv)
                placed = True
                break
        if not placed:
            clustered.append([lv])
    key_levels = [round(sum(cl) / len(cl), 6) for cl in clustered]

    # ── 現在価格との近接判定 ──────────────────────────────────────
    curr = c.values
    near_support    = pd.Series(False, index=df.index)
    near_resistance = pd.Series(False, index=df.index)
    nearest_level   = pd.Series(0.0,   index=df.index)
    kl_breakout_up  = pd.Series(False, index=df.index)
    kl_breakout_dn  = pd.Series(False, index=df.index)

    for i in range(len(df)):
        price = curr[i]
        if price == 0:
            continue
        for lv in key_levels:
            dist = abs(price - lv) / lv
            if dist <= near_pct:
                if lv < price:
                    near_support.iloc[i]  = True
                else:
                    near_resistance.iloc[i] = True
                if nearest_level.iloc[i] == 0 or dist < abs(price - nearest_level.iloc[i]) / lv:
                    nearest_level.iloc[i] = lv
        # ブレイクアウト判定: 前足がレベル以下 → 現在足がレベル超え（or逆）
        if i > 0:
            prev = curr[i - 1]
            for lv in key_levels:
                if prev <= lv < price:
                    kl_breakout_up.iloc[i] = True
                elif prev >= lv > price:
                    kl_breakout_dn.iloc[i] = True

    kl_df = pd.DataFrame({
        "kl_near_support":    near_support,
        "kl_near_resistance": near_resistance,
        "kl_nearest":         nearest_level,
        "kl_breakout_up":     kl_breakout_up,
        "kl_breakout_dn":     kl_breakout_dn,
        "kl_levels_count":    len(key_levels),
    }, index=df.index)
    df = pd.concat([df, kl_df], axis=1)
    df.attrs["key_levels"] = key_levels

    return df


def get_key_level_summary(df: pd.DataFrame, pair: str) -> dict:
    """最終バーのキーレベル情報をサマリー辞書で返す。scanner/notifierから使用。"""
    last = df.iloc[-1]
    price = float(last["Close"])
    levels = df.attrs.get("key_levels", [])
    pf = 0.01 if pair in ("USDJPY", "EURJPY") else (0.1 if pair == "XAUUSD" else 0.0001)

    # 直近のサポート・レジスタンスを分類
    supports     = [lv for lv in levels if lv < price]
    resistances  = [lv for lv in levels if lv >= price]
    near_sup     = supports[-1]     if supports     else None
    near_res     = resistances[0]   if resistances  else None

    return {
        "price":          price,
        "near_support":   near_sup,
        "near_resistance":near_res,
        "breakout_up":    bool(last.get("kl_breakout_up", False)),
        "breakout_dn":    bool(last.get("kl_breakout_dn", False)),
        "at_support":     bool(last.get("kl_near_support", False)),
        "at_resistance":  bool(last.get("kl_near_resistance", False)),
        "nearest":        float(last.get("kl_nearest", 0)),
        "all_levels":     levels,
        "support_dist_pips":  abs(price - near_sup)   / pf if near_sup   else None,
        "resist_dist_pips":   abs(near_res - price)   / pf if near_res   else None,
    }
