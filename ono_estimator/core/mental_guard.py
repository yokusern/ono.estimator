"""
mental_guard.py — C-3: 感情バイアス・コンディション警告
"""
from datetime import datetime, timezone
from typing import Dict, List

def check_mental_state(db=None, demo_positions: list = None) -> Dict:
    """
    Returns:
      {
        "condition": "GOOD" | "CAUTION" | "DANGER",
        "warnings": ["...", ...],
        "consecutive_losses": int,
        "consecutive_wins": int,
      }
    """
    warnings: List[str] = []
    consecutive_losses = 0
    consecutive_wins = 0
    condition = "GOOD"

    # 1) Consecutive losses/wins from demo positions
    if demo_positions:
        closed = [p for p in demo_positions if p.get("status") == "CLOSED"]
        closed.sort(key=lambda x: x.get("closed_at", ""), reverse=True)
        streak = 0
        streak_type = None
        for p in closed[:10]:
            r = p.get("result")
            if streak_type is None:
                streak_type = r
            if r == streak_type:
                streak += 1
            else:
                break
        if streak_type == "LOSS":
            consecutive_losses = streak
        elif streak_type == "WIN":
            consecutive_wins = streak

    if consecutive_losses >= 3:
        warnings.append(f"⚠️ {consecutive_losses}連敗中 — 冷静に。閾値を上げて慎重に")
        condition = "DANGER"
    elif consecutive_losses >= 2:
        warnings.append(f"🟡 {consecutive_losses}連敗 — リベンジトレードに注意")
        condition = "CAUTION"

    if consecutive_wins >= 5:
        warnings.append(f"🔶 {consecutive_wins}連勝 — 過信注意。ロット増やしすぎ禁止")
        if condition == "GOOD":
            condition = "CAUTION"

    # 2) Time-based warnings
    now_jst = datetime.now(timezone.utc).hour + 9  # rough JST
    now_jst = now_jst % 24
    if 0 <= now_jst < 6:
        warnings.append("🌙 深夜帯（0〜6時JST） — 薄商い・判断力低下注意")
        if condition == "GOOD":
            condition = "CAUTION"
    elif 23 <= now_jst or now_jst == 0:
        warnings.append("🌙 深夜取引 — 判断力に注意")

    # 3) Day of week
    wd = datetime.now(timezone.utc).weekday()
    if wd == 0:  # Monday
        warnings.append("📅 月曜早朝 — 週初めの流動性低下に注意")
    elif wd == 4 and (now_jst >= 20 or now_jst < 2):  # Friday evening
        warnings.append("📅 金曜夜 — 週末前の持ち越しリスクに注意")

    return {
        "condition":          condition,
        "warnings":           warnings,
        "consecutive_losses": consecutive_losses,
        "consecutive_wins":   consecutive_wins,
    }
