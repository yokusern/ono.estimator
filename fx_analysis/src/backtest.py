import pandas as pd
from typing import Optional
from .signals import SIGNAL_DEFS


def evaluate(
    df: pd.DataFrame,
    sig_col: str,
    direction: str,
    lookahead: int,
    pf: float,
    min_samples: int = 8,
) -> Optional[dict]:
    """
    シグナル発生から lookahead 本後の終値で勝敗を判定し、期待値等を返す。
    pf: 1pip に相当する価格差 (pip_factor)
    """
    signals = df.index[df[sig_col].fillna(False)]
    results = []

    for idx in signals:
        pos = df.index.searchsorted(idx)
        if pos + lookahead >= len(df):
            continue
        entry = float(df["Close"].iloc[pos])
        future = df["Close"].iloc[pos + lookahead]
        move_pips = (float(future) - entry) / pf
        if direction == "sell":
            move_pips = -move_pips
        results.append(move_pips)

    if len(results) < min_samples:
        return None

    wins   = [m for m in results if m > 0]
    losses = [abs(m) for m in results if m <= 0]

    win_rate = len(wins) / len(results)
    avg_win  = sum(wins)   / len(wins)   if wins   else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pf_val   = sum(wins) / sum(losses)   if losses else float("inf")
    ev       = win_rate * avg_win - (1 - win_rate) * avg_loss

    return {
        "count":  len(results),
        "win_rate": win_rate * 100,
        "avg_win":  avg_win,
        "avg_loss": avg_loss,
        "profit_factor": pf_val,
        "ev": ev,
    }


def run_all(df: pd.DataFrame, pf: float, lookahead: int = 20) -> list:
    """全SIGNAL_DEFSを評価して期待値順にソートして返す。"""
    results = []
    for col, direction, label in SIGNAL_DEFS:
        if col not in df.columns:
            continue
        stats = evaluate(df, col, direction, lookahead, pf)
        if stats:
            results.append({"signal": label, "col": col, **stats})
    results.sort(key=lambda x: x["ev"], reverse=True)
    return results
