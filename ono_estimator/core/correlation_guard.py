"""
CorrelationGuard — 相関ペアの二重エントリー防止
================================================
高相関ペアを同方向で同時に保有するのはリスクの二重取りになる。
例: EURUSD BUY + GBPUSD BUY = 実質 USD SELL を2倍取っている。

グループ定義:
  Group A (USD quote): EURUSD, GBPUSD, AUDUSD, NZDUSD → 同方向禁止
  Group B (JPY pairs): EURJPY, GBPJPY, AUDJPY, CADJPY, CHFJPY, USDJPY
                       → 2ペア以上同方向禁止
  Group C (USD base): USDCAD, USDCHF, USDJPY → 同方向禁止

GOLD は独立扱い（相関グループ外）。
"""
from __future__ import annotations

import threading
from typing import Optional

# 相関グループ: 同グループ内で2ペア以上同方向NG
CORRELATION_GROUPS: list[frozenset[str]] = [
    # Group A: USDを売り買いするペア（EUR,GBP,AUD,NZD側）
    frozenset({"EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X"}),

    # Group B: JPY クロス (リスクセンチメント連動)
    frozenset({"EURJPY=X", "GBPJPY=X", "AUDJPY=X", "CADJPY=X", "CHFJPY=X"}),

    # Group C: USD が左側（USD buy/sell のシグナル）
    frozenset({"USDCAD=X", "USDCHF=X", "USDJPY=X"}),
]

# Group A 内で方向が逆（EURUSD BUY + USDCAD BUY = どちらも USD SELL/BUY で矛盾しない）
# 実際には Group A の BUY = USD SELL、Group C の BUY = USD BUY なので逆相関
INVERSE_PAIRS: list[tuple[str, str]] = [
    ("EURUSD=X", "USDCAD=X"),   # EUR/USD と USD/CAD は逆相関
    ("EURUSD=X", "USDCHF=X"),
    ("GBPUSD=X", "USDCAD=X"),
    ("GBPUSD=X", "USDCHF=X"),
]


class CorrelationGuard:
    def __init__(self):
        self._open: dict[str, str] = {}   # {symbol: direction}
        self._lock = threading.Lock()     # H-6: 並列スキャン中の race condition 防止

    def register_open(self, symbol: str, direction: str) -> None:
        """ポジションオープンを記録する"""
        with self._lock:
            self._open[symbol] = direction

    def register_close(self, symbol: str) -> None:
        """ポジションクローズを記録する"""
        with self._lock:
            self._open.pop(symbol, None)

    def is_allowed(self, symbol: str, direction: str) -> tuple[bool, str]:
        """
        このシンボルにこの方向でエントリーしてよいか確認。
        Returns: (allowed, block_reason)
        """
        with self._lock:
            return self._is_allowed_locked(symbol, direction)

    def _is_allowed_locked(self, symbol: str, direction: str) -> tuple[bool, str]:
        """ロック保持済みの内部チェック"""
        # 同一銘柄は常に許可（DemoTraderが重複チェックする）
        if symbol in self._open:
            return True, ""

        for group in CORRELATION_GROUPS:
            if symbol not in group:
                continue
            for existing_sym, existing_dir in self._open.items():
                if existing_sym not in group:
                    continue
                if existing_dir == direction:
                    return (
                        False,
                        f"相関ガード: {existing_sym} ({existing_dir}) と同方向 — リスク二重取り禁止"
                    )

        # 逆相関チェック（USD側の矛盾エントリー）
        for s1, s2 in INVERSE_PAIRS:
            if symbol == s1 and s2 in self._open:
                if direction == self._open[s2]:
                    return (
                        False,
                        f"逆相関ガード: {s2} ({self._open[s2]}) と矛盾方向 ({direction})"
                    )
            if symbol == s2 and s1 in self._open:
                if direction == self._open[s1]:
                    return (
                        False,
                        f"逆相関ガード: {s1} ({self._open[s1]}) と矛盾方向 ({direction})"
                    )

        return True, ""

    def check_and_register(self, symbol: str, direction: str) -> tuple[bool, str]:
        """is_allowed + register_open をアトミックに実行。許可された場合のみ登録する。"""
        with self._lock:
            allowed, reason = self._is_allowed_locked(symbol, direction)
            if allowed and symbol not in self._open:
                self._open[symbol] = direction
            return allowed, reason

    @property
    def open_positions(self) -> dict[str, str]:
        with self._lock:
            return dict(self._open)
