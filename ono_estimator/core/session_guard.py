"""
SessionGuard — セッション時間フィルター
======================================
流動性が高い時間帯のみトレードを許可する。

セッション時間 (UTC):
  東京   : 00:00 - 09:00  (JPY ペア向き)
  ロンドン: 08:00 - 17:00  (EUR/GBP ペア向き)
  NY     : 13:00 - 22:00
  最強   : 13:00 - 17:00  (ロンドン-NY オーバーラップ)
  クローズ: 22:00 - 00:00  (取引禁止)

土曜日は全面禁止。日曜 21:00 UTC（シドニー開始）まで禁止。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


# セッション定義 (UTC hour の範囲 [start, end))
_SESSIONS = {
    "TOKYO":   (0,  9),
    "LONDON":  (8,  17),
    "NY":      (13, 22),
    "OVERLAP": (13, 17),   # ロンドン-NY 最高流動性
}

# 通貨ペアごとの最適セッション
_SYMBOL_SESSION: dict[str, list[str]] = {
    # JPY ペア: 東京 + ロンドン + OVERLAP
    "USDJPY=X": ["TOKYO", "LONDON", "OVERLAP", "NY"],
    "EURJPY=X": ["TOKYO", "LONDON", "OVERLAP", "NY"],
    "GBPJPY=X": ["LONDON", "OVERLAP"],  # GBP は東京薄い
    "AUDJPY=X": ["TOKYO", "LONDON", "OVERLAP"],
    "CADJPY=X": ["LONDON", "OVERLAP", "NY"],
    "CHFJPY=X": ["LONDON", "OVERLAP"],
    "NZDJPY=X": ["TOKYO", "LONDON", "OVERLAP"],

    # EUR/GBP: ロンドン中心
    "EURUSD=X": ["LONDON", "OVERLAP", "NY"],
    "GBPUSD=X": ["LONDON", "OVERLAP"],
    "EURGBP":   ["LONDON", "OVERLAP"],

    # コモディティ・USD: ロンドン-NY
    "AUDUSD=X": ["TOKYO", "LONDON", "OVERLAP"],
    "NZDUSD=X": ["TOKYO", "LONDON", "OVERLAP"],
    "USDCAD=X": ["LONDON", "OVERLAP", "NY"],
    "USDCHF=X": ["LONDON", "OVERLAP"],

    # GOLD: ロンドン-NY
    "GC=F":     ["LONDON", "OVERLAP", "NY"],

    # デフォルト (その他すべて)
    "__default__": ["LONDON", "OVERLAP", "NY"],
}


def get_current_session(now_utc: Optional[datetime] = None) -> str:
    """現在のFXセッション名を返す"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    wd   = now_utc.weekday()  # 0=月, 5=土, 6=日
    hour = now_utc.hour

    # 週末チェック
    if wd == 5:
        return "CLOSED"
    if wd == 6 and hour < 21:
        return "CLOSED"

    # 夜間（ニューヨーク引け後〜翌東京前）
    if hour >= 22 or (wd != 6 and hour < 0):
        return "LATE"

    if 13 <= hour < 17:
        return "OVERLAP"
    if 8 <= hour < 17:
        return "LONDON"
    if 13 <= hour < 22:
        return "NY"
    if 0 <= hour < 9:
        return "TOKYO"
    return "TRANSITION"


def is_tradeable(symbol: str, now_utc: Optional[datetime] = None) -> tuple[bool, str]:
    """
    この通貨ペアを今取引してよいか判定する。
    Returns: (ok, reason_if_blocked)
    """
    session = get_current_session(now_utc)

    if session == "CLOSED":
        return False, "週末はクローズ"
    if session == "LATE":
        return False, "22:00-00:00 UTC: 流動性極小のため禁止"

    allowed = _SYMBOL_SESSION.get(symbol, _SYMBOL_SESSION["__default__"])
    if session in allowed:
        return True, ""

    session_label = {
        "TOKYO":      "東京 (00-09UTC)",
        "LONDON":     "ロンドン (08-17UTC)",
        "NY":         "NY (13-22UTC)",
        "OVERLAP":    "ロンドン-NYオーバーラップ",
        "TRANSITION": "セッション切り替え中",
    }.get(session, session)

    best = allowed[0] if allowed else "LONDON"
    return False, f"現在 {session_label} — {symbol} の最適セッション外"


def session_strength_multiplier(session: str) -> float:
    """セッションごとのシグナル強度補正係数"""
    return {
        "OVERLAP":    1.3,
        "LONDON":     1.1,
        "NY":         1.0,
        "TOKYO":      0.9,
        "TRANSITION": 0.7,
        "LATE":       0.0,
        "CLOSED":     0.0,
    }.get(session, 0.8)
