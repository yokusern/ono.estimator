"""
多因子確率エンジン。
現在のバーで「どの条件が揃っているか」を判定し、
過去の同条件バーを検索してその勝率を計算する。

アプローチ（優先順）:
 1. 全アクティブ条件が同時に揃った過去バーの実測勝率 (≥8サンプル)
 2. 上位3条件のみで絞った過去バーの実測勝率 (≥8サンプル)
 3. 個別条件の重み付き平均勝率 (フォールバック)
"""
import pandas as pd
import numpy as np
from typing import Optional

MIN_SAMPLES = 8   # 信頼できる勝率計算に必要な最低サンプル数

# ── 買い・売り条件リスト (列名, 表示名, 重み) ────────────────────────────
# 重みは「優位性の高さ」の主観的評価（高いほど出力に大きく表示）
BUY_CONDS = [
    # (column, label, weight)
    ("ctx_strong_bull",    "強い上昇トレンド(SMA20>50>200)",    3),
    ("ctx_bull",           "上昇トレンド(SMA20>50)",            2),
    ("pullback_buy",       "トレンド中の押し目",                3),
    ("sig_bb_buy",         "BB -2σ タッチ",                    2),
    ("bb_zone_buy",        "BB 買いゾーン(下25%)",              2),
    ("sig_macd_buy",       "MACD ゴールデンクロス",             2),
    ("sig_rsi_buy",        "RSI 30回復",                        2),
    ("sig_stoch_buy",      "Stoch GC(<30)",                     1),
    ("sig_div_buy",        "ダイバージェンス(買い)",            2),
    ("sig_ma_bull",        "MA強気並び",                        2),
    ("pat_hammer",         "ハンマー",                          2),
    ("pat_pin_bull",       "ブル・ピンバー",                    2),
    ("pat_bull_engulf",    "陽線包み足",                        2),
    ("pat_morning_star",   "モーニングスター",                  2),
    ("pat_false_break_low","下方ダマシ反転",                    2),
    ("pat_double_bottom",  "ダブルボトム",                      2),
    ("sess_overlap",       "ロンドン/NY重複時間",               1),
    ("sess_london",        "ロンドン時間",                      1),
    ("sess_ny",            "NY時間",                            1),
    ("regime_trending",    "トレンド相場(BBが拡張中)",          1),
]

SELL_CONDS = [
    ("ctx_strong_bear",    "強い下降トレンド(SMA20<50<200)",    3),
    ("ctx_bear",           "下降トレンド(SMA20<50)",            2),
    ("pullback_sell",      "トレンド中の戻り",                  3),
    ("sig_bb_sell",        "BB +2σ タッチ",                    2),
    ("bb_zone_sell",       "BB 売りゾーン(上25%)",              2),
    ("sig_macd_sell",      "MACD デッドクロス",                 2),
    ("sig_rsi_sell",       "RSI 70割れ",                        2),
    ("sig_stoch_sell",     "Stoch DC(>70)",                     1),
    ("sig_div_sell",       "ダイバージェンス(売り)",            2),
    ("sig_ma_bear",        "MA弱気並び",                        2),
    ("pat_shoot",          "シューティングスター",              2),
    ("pat_pin_bear",       "ベア・ピンバー",                    2),
    ("pat_bear_engulf",    "陰線包み足",                        2),
    ("pat_evening_star",   "イブニングスター",                  2),
    ("pat_false_break_high","上方ダマシ反転",                   2),
    ("pat_double_top",     "ダブルトップ",                      2),
    ("sess_overlap",       "ロンドン/NY重複時間",               1),
    ("sess_london",        "ロンドン時間",                      1),
    ("sess_ny",            "NY時間",                            1),
    ("regime_trending",    "トレンド相場(BBが拡張中)",          1),
]


def _wr(df_hist: pd.DataFrame, mask: pd.Series, lookahead: int,
        pf: float, direction: str) -> Optional[dict]:
    """maskがTrueのバーの lookahead 本後勝率を計算。"""
    idx_list = df_hist.index[mask.fillna(False)]
    results = []
    for idx in idx_list:
        pos = df_hist.index.searchsorted(idx)
        if pos + lookahead >= len(df_hist):
            continue
        entry  = float(df_hist["Close"].iloc[pos])
        future = float(df_hist["Close"].iloc[pos + lookahead])
        move   = (future - entry) / pf
        if direction == "sell":
            move = -move
        results.append(move)

    if len(results) < MIN_SAMPLES:
        return None

    wins   = [m for m in results if m > 0]
    losses = [abs(m) for m in results if m <= 0]
    wr     = len(wins) / len(results)
    avg_w  = sum(wins)   / len(wins)   if wins   else 0
    avg_l  = sum(losses) / len(losses) if losses else 0
    ev     = wr * avg_w - (1 - wr) * avg_l
    pf_val = sum(wins) / sum(losses) if losses else float("inf")

    return {
        "count": len(results), "wins": len(wins),
        "win_rate": wr * 100,
        "avg_win": avg_w, "avg_loss": avg_l,
        "ev": ev, "profit_factor": pf_val,
    }


def _build_factor_list(df_hist: pd.DataFrame, current: pd.Series,
                       conds: list, lookahead: int, pf: float,
                       direction: str) -> list:
    """各条件について: アクティブか + 過去勝率を計算して辞書リストで返す。"""
    factors = []
    for col, label, weight in conds:
        if col not in df_hist.columns:
            continue
        active  = bool(current.get(col, False))
        wr_data = _wr(df_hist, df_hist[col], lookahead, pf, direction)
        factors.append({
            "col": col, "label": label, "weight": weight,
            "active": active,
            "wr": wr_data["win_rate"] if wr_data else None,
            "count": wr_data["count"] if wr_data else 0,
            "ev": wr_data["ev"] if wr_data else None,
        })
    return factors


def _combined_wr(df_hist: pd.DataFrame, active_cols: list,
                 lookahead: int, pf: float, direction: str) -> Optional[dict]:
    """アクティブ列が全部揃った過去バーの勝率。サンプル不足なら None。"""
    if not active_cols:
        return None
    mask = pd.Series(True, index=df_hist.index)
    for col in active_cols:
        if col in df_hist.columns:
            mask = mask & df_hist[col].fillna(False)
    return _wr(df_hist, mask, lookahead, pf, direction)


def _weighted_avg(factors: list, direction: str) -> Optional[float]:
    """アクティブ条件の重み付き平均勝率。"""
    active = [f for f in factors if f["active"] and f["wr"] is not None]
    if not active:
        return None
    total_w = sum(f["weight"] for f in active)
    total_wr = sum(f["wr"] * f["weight"] for f in active)
    return total_wr / total_w


def analyze_current(df: pd.DataFrame, pf: float, lookahead: int) -> dict:
    """
    最新バーの買い・売り確率を全過去データと比較して計算する。
    df は indicators + signals + patterns + context 全て済みのデータ。
    """
    df_hist = df.iloc[:-1]   # 最後の1本は「現在」として除外
    current = df.iloc[-1]

    # ── 因子リスト構築 ──────────────────────────────────────────────
    buy_factors  = _build_factor_list(df_hist, current, BUY_CONDS,  lookahead, pf, "buy")
    sell_factors = _build_factor_list(df_hist, current, SELL_CONDS, lookahead, pf, "sell")

    active_buy  = [f["col"] for f in buy_factors  if f["active"]]
    active_sell = [f["col"] for f in sell_factors if f["active"]]

    # ── 組み合わせ勝率（全条件 → 上位3条件 → 重み平均の順でフォールバック）──
    def best_combined(active_cols, direction, all_factors):
        # 全条件一致
        r = _combined_wr(df_hist, active_cols, lookahead, pf, direction)
        if r and r["count"] >= MIN_SAMPLES:
            r["method"] = f"全{len(active_cols)}条件一致({r['count']}件)"
            return r

        # 重み × |勝率 - 50| でスコアの高い上位3条件に絞る
        scored = sorted(
            [f for f in all_factors if f["active"] and f["wr"] is not None],
            key=lambda f: f["weight"] * abs(f["wr"] - 50),
            reverse=True,
        )[:3]
        top_cols = [f["col"] for f in scored]
        if top_cols:
            r = _combined_wr(df_hist, top_cols, lookahead, pf, direction)
            if r and r["count"] >= MIN_SAMPLES:
                r["method"] = f"上位3条件一致({r['count']}件)"
                return r

        # 重み付き平均
        wa = _weighted_avg(all_factors, direction)
        if wa is not None:
            return {"win_rate": wa, "count": None, "ev": None, "method": "重み付き平均"}
        return None

    buy_result  = best_combined(active_buy,  "buy",  buy_factors)
    sell_result = best_combined(active_sell, "sell", sell_factors)

    return {
        "current":      current,
        "buy_factors":  buy_factors,
        "sell_factors": sell_factors,
        "buy":          buy_result,
        "sell":         sell_result,
        "active_buy_n": len(active_buy),
        "active_sell_n":len(active_sell),
    }
