"""
entry_timing_detector.py — A-5: NOW/WAIT/LIMIT エントリータイミング判定
"""
from typing import Dict, Optional

def detect_entry_timing(engine_signals: dict, current_price: float = 0.0) -> dict:
    """
    Returns:
      {
        "timing": "NOW" | "WAIT" | "LIMIT",
        "limit_price": float | None,
        "reason": str,
        "confidence": "HIGH" | "MEDIUM" | "LOW"
      }
    """
    ls_det      = engine_signals.get("ls_detected", False)
    ls_dir      = engine_signals.get("ls_direction", "NONE")
    liq_rebr    = engine_signals.get("liq_bull_rebreak", False) or engine_signals.get("liq_bear_rebreak", False)
    is_range    = engine_signals.get("is_range", False)
    rsi_1h      = float(engine_signals.get("rsi_1h", 50))
    momentum_d  = engine_signals.get("momentum_decaying", False)
    decay_ratio = float(engine_signals.get("decay_ratio", 1.0))
    bb_score    = int(engine_signals.get("bb_score", 0))
    mtf_pct     = float(engine_signals.get("mtf_confluence_score", 0))
    key_levels  = engine_signals.get("key_levels", {})
    atr_1h      = float(engine_signals.get("atr_1h", 0.0001))
    session     = engine_signals.get("session", "")
    inside_sq   = engine_signals.get("inside_bar_squeeze", False)
    squeeze_rel = engine_signals.get("squeeze_released", False)
    chikou     = engine_signals.get("chikou_cross", "NONE")
    direction   = engine_signals.get("entry_decision", engine_signals.get("mtf_confluence_dominant", "WAIT"))

    now_score   = 0
    wait_score  = 0
    reasons_now  = []
    reasons_wait = []

    # ── NOW conditions ──
    if ls_det and liq_rebr:
        now_score += 50
        reasons_now.append("Liquidity Sweep完成・再ブレイク確認")
    elif ls_det:
        now_score += 30
        reasons_now.append("Liquidity Sweep検出")
    if squeeze_rel:
        now_score += 25
        reasons_now.append("BBスクイーズ解放")
    if chikou in ("BULL_CROSS", "BEAR_CROSS"):
        now_score += 20
        reasons_now.append(f"遅行スパン{chikou}")
    if mtf_pct >= 66:
        now_score += 20
        reasons_now.append(f"MTF{mtf_pct:.0f}%一致")
    if "NY_Overlap" in session or "London" in session:
        now_score += 10
        reasons_now.append("高ボラセッション")

    # ── WAIT conditions ──
    if is_range:
        wait_score += 50
        reasons_wait.append("レンジ中（ブレイク待ち）")
    if momentum_d and decay_ratio < 0.7:
        wait_score += 30
        reasons_wait.append("勢い減衰中")
    if inside_sq and not squeeze_rel:
        wait_score += 25
        reasons_wait.append("インサイドバー+BB未解放")
    if rsi_1h > 75 or rsi_1h < 25:
        wait_score += 15
        reasons_wait.append(f"RSI極端({rsi_1h:.0f})")
    if "Tokyo（" in session and "低ボラ" in session:
        wait_score += 15
        reasons_wait.append("東京低ボラ時間帯")

    # ── Decision ──
    if wait_score >= 50 and wait_score > now_score:
        # LIMIT: suggest a better entry price
        limit_price = None
        if current_price and atr_1h:
            r = engine_signals.get("key_levels", {}).get("S", [])
            s = r[0] if r else 0
            if s and abs(s - current_price) < atr_1h * 3:
                limit_price = round(s, 5)
            else:
                offset = atr_1h * 0.5
                if "BUY" in direction.upper():
                    limit_price = round(current_price - offset, 5)
                elif "SELL" in direction.upper():
                    limit_price = round(current_price + offset, 5)

        if limit_price:
            return {
                "timing": "LIMIT",
                "limit_price": limit_price,
                "reason": "、".join(reasons_wait) or "価格改善を待つ",
                "confidence": "MEDIUM",
            }
        return {
            "timing": "WAIT",
            "limit_price": None,
            "reason": "、".join(reasons_wait) or "条件整合待ち",
            "confidence": "LOW" if wait_score >= 50 else "MEDIUM",
        }

    if now_score >= 30:
        conf = "HIGH" if now_score >= 60 else "MEDIUM"
        return {
            "timing": "NOW",
            "limit_price": None,
            "reason": "、".join(reasons_now) or "エントリー条件充足",
            "confidence": conf,
        }

    return {
        "timing": "WAIT",
        "limit_price": None,
        "reason": "条件未充足",
        "confidence": "LOW",
    }
