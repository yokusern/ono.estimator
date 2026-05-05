"""
ConflictDetector — 矛盾チェック (T-05)
=======================================
エントリーを見送るべき状況を明示的に定義する。
矛盾フラグが1つでもあればギャン理論ルール6により強制WAIT。
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ono_estimator.core.reasoning_engine import UpperContext, ZoneContext, TriggerContext


class ConflictDetector:

    def detect(self, upper: "UpperContext", mid: "ZoneContext",
               trigger: "TriggerContext") -> list[str]:
        """矛盾フラグのリストを返す。空なら矛盾なし。"""
        flags = []

        # ── ルール1: 上位足と下位足の方向が逆 ─────────────────
        if upper.trend == "UP" and trigger.direction == "SELL":
            flags.append("上位足UP×下位足SELL")
        if upper.trend == "DOWN" and trigger.direction == "BUY":
            flags.append("上位足DOWN×下位足BUY")

        # ── ルール2: レンジ相場の中央付近でのエントリー ────────
        if upper.trend == "RANGE" and mid.zone == "MIDDLE":
            flags.append("レンジ中央付近エントリー禁止")

        # ── ルール3: 大循環ステージ2,3,5,6（もみ合い）────────
        if upper.stage in (2, 3, 5, 6) and trigger.direction != "WAIT":
            flags.append(f"大循環ステージ{upper.stage}（もみ合い）")

        # ── ルール4: RSI過熱 + 逆方向エントリー ───────────────
        rsi_sig = trigger.rsi_signal.lower()
        if "overbought" in rsi_sig and trigger.direction == "BUY":
            flags.append("RSI買われすぎ×BUY")
        if "oversold" in rsi_sig and trigger.direction == "SELL":
            flags.append("RSI売られすぎ×SELL")

        # ── ルール5: バンドウォーク中の逆張り ─────────────────
        if trigger.is_band_walk and trigger.is_counter_trend:
            flags.append("バンドウォーク中逆張り禁止")

        # ── ルール6: レジスタンス付近のBUY（騙し上げ注意）────
        if mid.zone == "RESISTANCE" and trigger.direction == "BUY" and not mid.reji_support_flip:
            flags.append("レジスタンス付近BUY")

        # ── ルール7: サポート付近のSELL（騙し下げ注意）────────
        if mid.zone == "SUPPORT" and trigger.direction == "SELL" and not mid.reji_support_flip:
            flags.append("サポート付近SELL")

        # ── ルール8: BBエクスパンション中の逆張り ──────────────
        if mid.bb_state == "EXPANSION" and trigger.is_counter_trend:
            flags.append("BBエクスパンション中逆張り禁止")

        return flags
