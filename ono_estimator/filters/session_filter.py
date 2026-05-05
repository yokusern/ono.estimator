"""
SessionFilter — 時間帯スコア補正フィルター (2-1)
=================================================
JST基準で東京/ロンドン/NYセッションを判定し、銘柄別にスコア補正する。
"""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

# 銘柄グループ × セッション → スコア補正値
_SESSION_BONUS: dict = {
    "tokyo": {
        "USDJPY=X": 10, "AUDJPY=X": 10, "EURJPY=X": 10, "^N225": 15,
    },
    "london": {
        "EURUSD=X": 10, "SI=F": 10, "EURJPY=X": 5, "GC=F": 5,
    },
    "ny": {
        # NY時間は全銘柄 +5
        "__all__": 5,
        "GC=F": 10, "BTC-USD": 10,
    },
    "off": {
        # 深夜閑散: 全銘柄 -10
        "__all__": -10,
    },
}


def _get_session_jst(now_jst_hour: float) -> str:
    h = now_jst_hour
    if h >= 21 or h < 2:   # 21:00-02:00 JST = NY
        return "ny"
    if 2 <= h < 9:          # 02:00-09:00 JST = 深夜オフ
        return "off"
    if 9 <= h < 12:         # 09:00-12:00 JST = 東京コア
        return "tokyo"
    if 16 <= h < 21:        # 16:00-21:00 JST = ロンドン
        return "london"
    return "off"


def get_session_score_bonus(symbol: str) -> tuple[int, str]:
    """
    現在のセッションに基づくスコア補正値と警告文字列を返す。
    Returns: (bonus: int, caution: str)
    """
    now_jst = datetime.now(JST)
    h = now_jst.hour + now_jst.minute / 60
    session = _get_session_jst(h)

    bonuses = _SESSION_BONUS.get(session, {})
    bonus = bonuses.get("__all__", 0) + bonuses.get(symbol, 0)

    caution = ""
    if session == "off":
        caution = f"⚠️ 深夜閑散時間帯（JST {now_jst.hour:02d}:00）—流動性が低い可能性があります"
    elif bonus > 0:
        session_label = {"tokyo": "東京", "london": "ロンドン", "ny": "NY"}.get(session, "")
        caution = f"✅ {session_label}セッション活性時間帯（+{bonus}pt補正）"

    return bonus, caution


def get_current_session_label() -> str:
    now_jst = datetime.now(JST)
    h = now_jst.hour + now_jst.minute / 60
    session = _get_session_jst(h)
    return {"tokyo": "東京", "london": "ロンドン", "ny": "NY", "off": "オフ"}.get(session, "")
