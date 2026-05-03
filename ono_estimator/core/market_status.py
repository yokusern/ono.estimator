"""
Step 11: 市場停止モード
LIVE / PRE_MARKET / ARCHIVE の3状態を管理する。
"""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def get_market_status() -> dict:
    """
    現在の市場状態を返す。
    LIVE:       月曜 06:00〜土曜 06:00 JST
    ARCHIVE:    土曜 06:00〜月曜 03:00 JST
    PRE_MARKET: 月曜 03:00〜月曜 06:00 JST
    """
    now = datetime.now(JST)
    wd = now.weekday()  # 0=月, 5=土, 6=日
    h = now.hour + now.minute / 60

    if wd == 5 and h >= 6:
        status = "ARCHIVE"
        label = "📴 週末クローズ"
    elif wd == 6:
        status = "ARCHIVE"
        label = "📴 週末クローズ"
    elif wd == 0 and h < 3:
        status = "ARCHIVE"
        label = "📴 週末クローズ"
    elif wd == 0 and 3 <= h < 6:
        status = "PRE_MARKET"
        label = "🌅 マーケット開場準備中"
    else:
        status = "LIVE"
        label = "✅ マーケット稼働中"

    # 次の遷移時刻を計算
    if status == "LIVE":
        # 次の土曜 06:00
        days_to_sat = (5 - wd) % 7 or 7
        next_transition = now.replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(days=days_to_sat)
        next_label = "土曜クローズ"
    elif status == "ARCHIVE":
        # 次の月曜 03:00
        days_to_mon = (7 - wd) % 7 or 7
        next_transition = now.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=days_to_mon)
        next_label = "月曜プレマーケット"
    else:  # PRE_MARKET
        next_transition = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_transition <= now:
            next_transition += timedelta(days=1)
        next_label = "マーケットオープン"

    return {
        "status": status,
        "label": label,
        "next_transition": next_transition.isoformat(),
        "next_label": next_label,
        "is_live": status == "LIVE",
    }
