"""
Step 13: 市場心理指数（FX Fear & Greed）
VIX・DXY変化率・GOLD変化率から FX 独自の市場心理指数（0〜100）を算出する。
"""


def calc_fx_fear_greed(vix: float, dxy_change: float, gold_change: float) -> dict:
    """
    0〜25: 極度の恐怖
    26〜45: 恐怖
    46〜55: 中立
    56〜75: 貪欲
    76〜100: 極度の貪欲
    """
    # VIX スコア (高VIX → 恐怖、低VIX → 貪欲)
    if vix is None or vix <= 0:
        vix_score = 50
    elif vix >= 40:
        vix_score = 0
    elif vix >= 25:
        vix_score = 20
    elif vix >= 18:
        vix_score = 40
    elif vix >= 12:
        vix_score = 65
    else:
        vix_score = 85

    # DXY スコア (DXY 上昇 → リスクオフ傾向 → 恐怖)
    if dxy_change is None:
        dxy_score = 50
    else:
        dxy_score = max(0, min(100, 50 - dxy_change * 10))

    # GOLD スコア (GOLD 上昇 → 恐怖)
    if gold_change is None:
        gold_score = 50
    else:
        gold_score = max(0, min(100, 50 - gold_change * 5))

    # 加重平均
    index = int(vix_score * 0.5 + dxy_score * 0.3 + gold_score * 0.2)
    index = max(0, min(100, index))

    if index <= 25:
        label = "極度の恐怖"
        risk_mode = "RISK_OFF"
        emoji = "😱"
    elif index <= 45:
        label = "恐怖"
        risk_mode = "RISK_OFF"
        emoji = "😨"
    elif index <= 55:
        label = "中立"
        risk_mode = "NEUTRAL"
        emoji = "😐"
    elif index <= 75:
        label = "貪欲"
        risk_mode = "RISK_ON"
        emoji = "😊"
    else:
        label = "極度の貪欲"
        risk_mode = "RISK_ON"
        emoji = "🤑"

    risk_label = "⚡ リスクオン" if risk_mode == "RISK_ON" else "🛡 リスクオフ" if risk_mode == "RISK_OFF" else "⚖ 中立"

    return {
        "index": index,
        "label": label,
        "emoji": emoji,
        "risk_mode": risk_mode,
        "risk_label": risk_label,
        "summary": f"{risk_label} — VIX {vix or 'N/A'} / DXY変化率 {dxy_change or 'N/A'}%",
        "components": {
            "vix_score": vix_score,
            "dxy_score": dxy_score,
            "gold_score": gold_score,
        },
    }
