"""
Step G1: セッション・時間帯フィルター
FX の3セッション（東京・ロンドン・NY）を考慮し、
シグナルの勝率を時間帯別に補正する。
"""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

SESSIONS = {
    "tokyo":  {"start": 8,  "end": 15},   # JST 08:00-15:00
    "london": {"start": 16, "end": 25},   # JST 16:00-01:00 (翌1時 = 25)
    "ny":     {"start": 21, "end": 30},   # JST 21:00-06:00 (翌6時 = 30)
}

# 銘柄×セッションのスコア補正倍率（初期値1.0、バックテスト後に自動更新）
SESSION_MULTIPLIERS: dict = {
    "USDJPY": {"tokyo": 1.2, "london": 1.0, "ny": 1.1, "off": 0.7},
    "EURUSD": {"tokyo": 0.9, "london": 1.3, "ny": 1.2, "off": 0.6},
    "EURJPY": {"tokyo": 1.1, "london": 1.2, "ny": 1.0, "off": 0.7},
    "AUDJPY": {"tokyo": 1.2, "london": 0.9, "ny": 1.0, "off": 0.7},
    "GBPJPY": {"tokyo": 1.0, "london": 1.3, "ny": 1.1, "off": 0.6},
    "GC=F":   {"tokyo": 0.9, "london": 1.1, "ny": 1.3, "off": 0.7},
    "SI=F":   {"tokyo": 0.9, "london": 1.1, "ny": 1.2, "off": 0.7},
    "BTC-USD":{"tokyo": 1.0, "london": 1.0, "ny": 1.1, "off": 0.9},
    "^N225":  {"tokyo": 1.3, "london": 0.7, "ny": 0.8, "off": 0.5},
}

SESSION_LABELS = {
    "tokyo": "🌅 東京セッション",
    "london": "🇬🇧 ロンドンセッション",
    "ny": "🗽 NYセッション",
    "off": "😴 オフセッション",
}


def get_current_session() -> str:
    """現在の JST 時刻から "tokyo" / "london" / "ny" / "off" を返す"""
    now_jst = datetime.now(JST)
    h = now_jst.hour + (now_jst.minute / 60)

    # NY は 21:00〜翌6:00（h >= 21 or h < 6）
    if h >= 21 or h < 6:
        return "ny"
    # London は 16:00〜01:00（h >= 16）
    if h >= 16:
        return "london"
    # Tokyo は 08:00〜15:00
    if 8 <= h < 15:
        return "tokyo"
    return "off"


def get_session_multiplier(symbol: str, session: str) -> float:
    """銘柄×セッションの補正倍率を返す"""
    sym_map = SESSION_MULTIPLIERS.get(symbol) or SESSION_MULTIPLIERS.get(
        symbol.replace("=X", "").replace("-USD", "-USD")
    )
    if not sym_map:
        return 1.0
    return sym_map.get(session, 1.0)


def get_session_label(session: str) -> str:
    return SESSION_LABELS.get(session, session)


def update_multiplier(symbol: str, session: str, win_rate: float):
    """バックテスト結果からセッション補正倍率を動的更新"""
    if symbol not in SESSION_MULTIPLIERS:
        SESSION_MULTIPLIERS[symbol] = {"tokyo": 1.0, "london": 1.0, "ny": 1.0, "off": 0.7}
    # 勝率60%以上 → 1.2, 50%以上 → 1.0, 未満 → 0.8
    if win_rate >= 65:
        new_mult = 1.3
    elif win_rate >= 55:
        new_mult = 1.1
    elif win_rate >= 45:
        new_mult = 1.0
    else:
        new_mult = 0.8
    SESSION_MULTIPLIERS[symbol][session] = new_mult
