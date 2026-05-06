"""
trade_style_detector.py — A-1: スキャル/デイ/スイング自動判定
"""
import os
from typing import Dict

STYLE_HOLD_TIMES = {
    "scalping":  {"min": 1,    "max": 15,   "label": "1〜15分",  "emoji": "🏃"},
    "daytrading":{"min": 60,   "max": 480,  "label": "1〜8時間", "emoji": "📅"},
    "swing":     {"min": 1440, "max": 7200, "label": "1〜5日",   "emoji": "🌊"},
}

def detect_trade_style(engine_signals: dict, atr_1h: float = 0.0) -> dict:
    """
    Returns:
      {
        "main_style": "scalping" | "daytrading" | "swing",
        "sub_style":  "scalping" | "daytrading" | "swing",
        "score": {"scalping": 0-100, "daytrading": 0-100, "swing": 0-100},
        "hold_time": "1〜15分",
        "emoji": "🏃",
        "reason": "..."
      }
    """
    scalp_score = 0
    day_score   = 0
    swing_score = 0

    session   = engine_signals.get("session", "")
    vol_ratio = float(engine_signals.get("vol_ratio", 1.0))
    atr       = float(engine_signals.get("atr_1h", atr_1h) or 0.0)
    rsi_15m   = float(engine_signals.get("rsi_15m", 50))
    rsi_1h    = float(engine_signals.get("rsi_1h",  50))
    ls_det    = engine_signals.get("ls_detected", False)
    is_range  = engine_signals.get("is_range", False)
    bb_score  = int(engine_signals.get("bb_score", 0))
    weekly_tr = engine_signals.get("weekly_trend", "N/A")
    ema_sig   = engine_signals.get("ema_signal", "NONE")
    stoch_gc  = engine_signals.get("stoch_gc", False)
    stoch_dc  = engine_signals.get("stoch_dc", False)
    saneki_ko  = engine_signals.get("saneki_ko", False)
    saneki_gy  = engine_signals.get("saneki_gyaku", False)
    mtf_pct    = float(engine_signals.get("mtf_confluence_score", 0))
    inside_bar = engine_signals.get("inside_bar", False)
    inside_sq  = engine_signals.get("inside_bar_squeeze", False)

    # ── スキャルピング要因 ──
    if ls_det:               scalp_score += 40   # Liquidity Sweep = scalp signal
    if stoch_gc or stoch_dc: scalp_score += 20
    if "NY_Overlap" in session or "NY（" in session: scalp_score += 20
    if vol_ratio > 1.2:      scalp_score += 15
    if bb_score > 20:        scalp_score += 10
    if is_range:             scalp_score -= 20   # range = bad for scalp
    if inside_bar and inside_sq: scalp_score += 15  # inside bar breakout = scalp

    # ── デイトレード要因 ──
    if "London" in session or "NY" in session: day_score += 30
    if mtf_pct >= 50:        day_score += 25
    if ema_sig in ("GOLDEN_CROSS", "DEAD_CROSS"): day_score += 20
    if 40 < rsi_1h < 60:    day_score += 10
    if bb_score > 30:        day_score += 15

    # ── スイング要因 ──
    if saneki_ko or saneki_gy: swing_score += 50  # 三役好転/逆転
    if "WEEKLY_UP" in weekly_tr or "WEEKLY_DOWN" in weekly_tr: swing_score += 30
    if mtf_pct >= 80:          swing_score += 20
    if bb_score > 50:          swing_score += 15
    if vol_ratio < 0.8:        swing_score -= 10  # low vol bad for swing entry

    # Normalize to 0-100
    total = max(scalp_score + day_score + swing_score, 1)
    scores = {
        "scalping":   max(0, min(100, int(scalp_score / total * 100))),
        "daytrading": max(0, min(100, int(day_score   / total * 100))),
        "swing":      max(0, min(100, int(swing_score / total * 100))),
    }

    styles_ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    main_style = styles_ranked[0]
    sub_style  = styles_ranked[1]

    # Reason generation
    reasons = []
    if ls_det:         reasons.append("Liquidity Sweep検出")
    if saneki_ko:      reasons.append("三役好転")
    if saneki_gy:      reasons.append("三役逆転")
    if mtf_pct >= 60:  reasons.append(f"MTF一致{mtf_pct:.0f}%")
    if inside_sq:      reasons.append("インサイドバー+BB")
    if "NY_Overlap" in session: reasons.append("NY重複時間")
    reason = "、".join(reasons) if reasons else "総合判断"

    info = STYLE_HOLD_TIMES[main_style]
    return {
        "main_style":  main_style,
        "sub_style":   sub_style,
        "score":       scores,
        "hold_time":   info["label"],
        "emoji":       info["emoji"],
        "reason":      reason,
    }
