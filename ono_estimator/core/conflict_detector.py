"""
ConflictDetector — 矛盾チェック (T-05)
=======================================
エントリーを見送るべき状況を明示的に定義する。
矛盾フラグが1つでもあればギャン理論ルール6により強制WAIT。
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import datetime

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

        # ── ルール2: 上位足RANGEでの方向性エントリー ──────────
        # ブレイクアウト未確認のRANGE×方向性エントリーはLS再ブレイク確認前に禁止
        if upper.trend == "RANGE" and trigger.direction in ("BUY", "SELL"):
            if not trigger.ls_confirmed:
                flags.append(f"上位足RANGE×{trigger.direction}（LSブレイク未確認）")

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

        # ── ルール9: 200MA（防衛線）による物理ブロック ───────
        if trigger.direction == "BUY" and upper.price_vs_ma200 == "BELOW":
            flags.append("1H 200MA下でのBUY（禁忌）")
        if trigger.direction == "SELL" and upper.price_vs_ma200 == "ABOVE":
            flags.append("1H 200MA上でのSELL（禁忌）")
        
        # ── ルール10: Liquidity Filter (究極の絞り込み) ───────
        if not trigger.ls_detected:
            flags.append("Liquidity Sweep未検出")

        # ── ルール11: Session Filter (JST 16:00~02:00 ロンドン+NY) ─────
        # ロンドン開場: JST 16:00 / NY開場: JST 22:00 / NY閉場: JST 翌07:00
        # 有効セッション: h ∈ {16,17,...,23, 0, 1} = 10時間
        jst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        h = jst_now.hour
        is_active_session = (h >= 16) or (h <= 1)
        if not is_active_session:
            flags.append("市場停滞時間帯（JST 16〜02時以外）")

        # ── ルール12: RR Strict (RR 1:2 未満を拒否) ────────────
        # abs()を使わず方向性を考慮。reward<=0はエントリー遅延（TPが後ろにある）を示す
        if trigger.direction != "WAIT" and trigger.price > 0:
            risk, reward = 0.0, 0.0
            if trigger.direction == "BUY" and mid.sr_nearest_support > 0 and mid.sr_nearest_resistance > 0:
                risk   = trigger.price - mid.sr_nearest_support
                reward = mid.sr_nearest_resistance - trigger.price
            elif trigger.direction == "SELL" and mid.sr_nearest_resistance > 0 and mid.sr_nearest_support > 0:
                risk   = mid.sr_nearest_resistance - trigger.price
                reward = trigger.price - mid.sr_nearest_support

            if risk > 0 and reward > 0 and (reward / risk) < 2.0:
                flags.append("RR期待値不足（1:2未満）")
            elif risk > 0 and reward <= 0:
                flags.append("エントリー遅延（抵抗帯超過でRR計算不能）")

        return flags
