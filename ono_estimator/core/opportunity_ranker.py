"""
opportunity_ranker.py — A-6: 銘柄優先度ランキング
"""
from typing import List, Dict

SYM_SHORT = {
    "USDJPY=X": "USDJPY", "GC=F": "GOLD", "BTC-USD": "BTC",
    "^N225": "JP225", "SI=F": "XAGUSD", "AUDJPY=X": "AUDJPY",
    "EURUSD=X": "EURUSD", "EURJPY=X": "EURJPY",
}

def rank_opportunities(system_state: dict, analysis_tf: str = "1h") -> List[Dict]:
    """
    Returns list of dicts sorted by opportunity_score descending:
    [
      {
        "symbol": "USDJPY",
        "direction": "BUY",
        "score": 72,
        "probability": 68,
        "opportunity_score": 85.2,
        "style": "daytrading",
        "reason": "MTF一致 + LiquiditySweep",
        "entry": 149.85,
      },
      ...
    ]
    """
    results = []

    for ticker, short in SYM_SHORT.items():
        state = system_state.get(ticker, {})
        tf_state = state.get(analysis_tf, {})
        if not tf_state:
            continue

        score       = float(tf_state.get("score", 0))
        prob        = float(tf_state.get("probability", 0))
        direction   = str(tf_state.get("direction", tf_state.get("status", "WAIT")))
        confidence  = str(tf_state.get("signal_quality", tf_state.get("confidence", "LOW")))
        aligned     = int(tf_state.get("aligned", 0))
        is_range    = bool(tf_state.get("is_range", False))
        entry_type  = str(tf_state.get("entry_type", "NONE"))
        session_m   = float(tf_state.get("session_multiplier", 1.0))

        es = state.get("_engine_signals") or {}
        mtf_pct  = float(es.get("mtf_confluence_score", 0))
        ls_det   = bool(es.get("ls_detected", False))
        style    = str(es.get("trade_style", {}).get("main_style", "daytrading") if isinstance(es.get("trade_style"), dict) else "daytrading")
        style_em = {"scalping": "🏃", "daytrading": "📅", "swing": "🌊"}.get(style, "📅")

        if is_range or "WAIT" in direction.upper():
            opportunity_score = 0.0
        else:
            conf_w = {"HIGH": 1.5, "MEDIUM": 1.1, "LOW": 0.8}.get(confidence, 1.0)
            ls_bonus = 20 if ls_det else 0
            opportunity_score = (
                abs(score) * 0.4
                + prob * 0.4
                + mtf_pct * 0.1
                + ls_bonus
                + aligned * 3
            ) * conf_w * session_m

        # Build short reason
        reasons = []
        if ls_det:         reasons.append("💦L.Sweep")
        if mtf_pct >= 60:  reasons.append(f"MTF{mtf_pct:.0f}%")
        if aligned >= 4:   reasons.append(f"{aligned}/5レイヤー")
        if entry_type not in ("NONE", ""): reasons.append(entry_type.replace("_", " "))
        reason = " + ".join(reasons) if reasons else "標準シグナル"

        results.append({
            "symbol":            short,
            "ticker":            ticker,
            "direction":         direction.replace("STRONG_", ""),
            "score":             int(score),
            "probability":       int(prob),
            "opportunity_score": round(opportunity_score, 1),
            "style":             style,
            "style_emoji":       style_em,
            "reason":            reason,
            "is_range":          is_range,
            "entry":             tf_state.get("entry", 0),
            "tp1":               tf_state.get("tp1", 0),
            "sl":                tf_state.get("sl", 0),
            "confidence":        confidence,
        })

    results.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return results
