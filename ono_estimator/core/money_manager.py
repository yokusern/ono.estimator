"""
Step 9: 資金管理（Money Management）＆ 残高予測
"""

PIP_VALUE = {
    "USDJPY": 0.01,  "EURUSD": 0.0001, "GBPUSD": 0.0001,
    "AUDUSD": 0.0001,"USDCAD": 0.0001, "USDCHF": 0.0001,
    "NZDUSD": 0.0001,"EURJPY": 0.01,   "GBPJPY": 0.01,
    "AUDJPY": 0.01,  "CADJPY": 0.01,   "CHFJPY": 0.01,
    "GOLD":   0.1,   "SILVER": 0.001,  "BTC":    1.0,
    "ETH":    0.01,
}


def _get_pip(symbol: str) -> float:
    for key, val in PIP_VALUE.items():
        if key in symbol.upper():
            return val
    return 0.0001


def calc_lot(balance: float, risk_pct: float, sl_pips: float, symbol: str) -> dict:
    """
    許容リスクと SL 幅から推奨ロット数を算出。
    戻り値: { "lot": float, "risk_amount": float, "reward_amount": float }
    """
    if sl_pips <= 0 or balance <= 0 or risk_pct <= 0:
        return {"lot": 0.0, "risk_amount": 0.0, "reward_amount": 0.0, "error": "invalid input"}

    risk_amount = balance * (risk_pct / 100)
    pip_val = _get_pip(symbol)

    # 1lot = 100,000通貨 として計算
    lot_value_per_pip = 100_000 * pip_val
    if lot_value_per_pip <= 0:
        return {"lot": 0.0, "risk_amount": risk_amount, "reward_amount": 0.0}

    lot = round(risk_amount / (sl_pips * lot_value_per_pip), 2)
    lot = max(0.01, min(lot, 100.0))  # 0.01〜100lot に制限

    # RR 2:1 想定
    reward_amount = risk_amount * 2

    return {
        "lot": lot,
        "risk_amount": round(risk_amount, 0),
        "reward_amount": round(reward_amount, 0),
        "pip_value": pip_val,
        "rr_ratio": 2.0,
    }


def simulate_balance(balance: float, lot: float, tp_pips: float, sl_pips: float, symbol: str) -> dict:
    """
    TP 到達時・SL 到達時それぞれの残高予測を返す。
    戻り値: { "if_tp": float, "if_sl": float, "rr_ratio": float }
    """
    pip_val = _get_pip(symbol)
    lot_val = lot * 100_000 * pip_val

    profit_if_tp = round(lot_val * tp_pips, 0)
    loss_if_sl = round(lot_val * sl_pips, 0)
    rr = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0

    return {
        "if_tp": round(balance + profit_if_tp, 0),
        "if_sl": round(balance - loss_if_sl, 0),
        "rr_ratio": rr,
        "profit_if_tp": profit_if_tp,
        "loss_if_sl": loss_if_sl,
    }
