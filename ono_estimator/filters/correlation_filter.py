"""
CorrelationFilter — 複数銘柄相関フィルター (3-2)
=================================================
相関ペアの方向一致で確度を上げ、逆行で警告する。
"""
from __future__ import annotations

# 相関ペア定義: (sym_a, sym_b, relationship)
# relationship: "same" = 同方向で確度UP, "inverse" = 逆方向で確度UP
CORRELATION_PAIRS = [
    ("EURUSD=X", "EURJPY=X",  "same"),     # EUR強弱が同方向
    ("USDJPY=X", "GC=F",      "inverse"),  # ドル強弱 vs GOLD
    ("AUDJPY=X", "^N225",     "same"),     # リスクオン・オフ
]

SCORE_BONUS_ON_CONFIRM = 10
TAG_CONFIRM = "#CorrelationConfirmed"


def check_correlation(symbol: str, system_state: dict, analysis_tf: str) -> dict:
    """
    symbol について相関ペアチェックを行う。
    system_state: {sym: {tf: {"direction": "UP"/"DOWN"/"WAIT", ...}}}
    戻り値: {"score_bonus": int, "tags": list, "caution": str}
    """
    result = {"score_bonus": 0, "tags": [], "caution": ""}

    def _get_dir(sym: str) -> str:
        st = system_state.get(sym, {}).get(analysis_tf, {})
        return (st.get("direction") or st.get("status") or "WAIT").upper()

    my_dir = _get_dir(symbol)
    if my_dir in ("WAIT", "NONE", ""):
        return result

    confirmed = []
    conflicted = []

    for sym_a, sym_b, rel in CORRELATION_PAIRS:
        peer = None
        if sym_a == symbol:
            peer = sym_b
        elif sym_b == symbol:
            peer = sym_a
        else:
            continue

        peer_dir = _get_dir(peer)
        if peer_dir in ("WAIT", "NONE", ""):
            continue

        my_bull  = "BUY" in my_dir
        my_bear  = "SELL" in my_dir
        p_bull   = "BUY" in peer_dir
        p_bear   = "SELL" in peer_dir

        if rel == "same":
            if (my_bull and p_bull) or (my_bear and p_bear):
                confirmed.append(f"{peer}同方向")
            elif (my_bull and p_bear) or (my_bear and p_bull):
                conflicted.append(f"{peer}逆行")
        else:  # inverse
            if (my_bull and p_bear) or (my_bear and p_bull):
                confirmed.append(f"{peer}逆相関確認")
            elif (my_bull and p_bull) or (my_bear and p_bear):
                conflicted.append(f"{peer}逆相関乖離")

    if confirmed:
        result["score_bonus"] += SCORE_BONUS_ON_CONFIRM * len(confirmed)
        result["tags"].append(TAG_CONFIRM)
        result["caution"] = f"✅ 相関確認: {', '.join(confirmed)}"
    if conflicted:
        result["caution"] += f" ⚠️ 相関逆行: {', '.join(conflicted)}"

    return result
