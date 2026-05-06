"""
capital_calculator.py — A-2: 必要資金・証拠金計算
"""
from typing import Dict

# 1 pip = このprice単位
PIP_VALUE = {
    "USDJPY=X": 0.01, "AUDJPY=X": 0.01, "EURJPY=X": 0.01,
    "EURUSD=X": 0.0001, "GC=F": 0.1, "SI=F": 0.01,
    "BTC-USD": 1.0, "^N225": 1.0,
}
# 1 lot のコントラクトサイズ
LOT_SIZE = {
    "USDJPY=X": 100_000, "AUDJPY=X": 100_000, "EURJPY=X": 100_000,
    "EURUSD=X": 100_000, "GC=F": 100, "SI=F": 5000,
    "BTC-USD": 1, "^N225": 1,
}
# JPY換算係数（概算。USDJPY=150を基準）
JPY_RATE = {
    "USDJPY=X": 1.0, "AUDJPY=X": 1.0, "EURJPY=X": 1.0,
    "EURUSD=X": 150.0, "GC=F": 150.0, "SI=F": 150.0,
    "BTC-USD": 150.0, "^N225": 1.0,
}

def calc_capital(
    symbol: str,
    current_price: float,
    sl_pips: float,
    risk_pct: float = 1.0,
    leverage: int = 25,
    capital_jpy: float = 0,
) -> Dict:
    """
    Returns:
      {
        "margin_per_lot":        必要証拠金（円）per 1 lot,
        "sl_loss_per_lot":       SL到達時損失（円）per 1 lot,
        "min_capital_jpy":       最低必要資金（円）,
        "recommended_capital":   余裕ある推奨資金 (min×3),
        "lot_for_risk_pct":      capital_jpyの risk_pct% リスクに適したロット数,
        "sl_pips":               入力SL幅(pips),
      }
    """
    pip    = PIP_VALUE.get(symbol, 0.01)
    lotmul = LOT_SIZE.get(symbol, 100_000)
    jpy    = JPY_RATE.get(symbol, 150.0)

    # 証拠金 = price × lot_size / leverage × jpy_rate
    margin_per_lot = current_price * lotmul / leverage * jpy if current_price else 0
    # SL損失 = sl_pips × pip × lot_size × jpy_rate
    sl_loss_per_lot = sl_pips * pip * lotmul * jpy if sl_pips else 0

    min_capital = max(margin_per_lot * 2, sl_loss_per_lot * 10)
    recommended = min_capital * 3

    lot_for_risk = 0.0
    if capital_jpy > 0 and sl_loss_per_lot > 0:
        risk_jpy = capital_jpy * risk_pct / 100
        lot_for_risk = round(risk_jpy / sl_loss_per_lot, 2)

    return {
        "margin_per_lot":      round(margin_per_lot),
        "sl_loss_per_lot":     round(sl_loss_per_lot),
        "min_capital_jpy":     round(min_capital),
        "recommended_capital": round(recommended),
        "lot_for_risk_pct":    lot_for_risk,
        "sl_pips":             sl_pips,
        "risk_pct":            risk_pct,
    }
