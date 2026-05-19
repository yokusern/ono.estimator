"""
Notifier — Discord専用通知モジュール（Gemini/LINE廃止版）
10分間の重複排除あり。
"""
import os
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SYMBOL_DISPLAY = {
    "USDJPY=X": "USDJPY", "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD",
    "AUDUSD=X": "AUDUSD", "USDCAD=X": "USDCAD", "USDCHF=X": "USDCHF",
    "NZDUSD=X": "NZDUSD", "EURJPY=X": "EURJPY", "GBPJPY=X": "GBPJPY",
    "AUDJPY=X": "AUDJPY", "CADJPY=X": "CADJPY", "CHFJPY=X": "CHFJPY",
    "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "OIL",
    "^N225": "JP225", "^DJI": "US30", "^GSPC": "SPX500", "^NDX": "NAS100",
    "BTC-USD": "BTC", "ETH-USD": "ETH",
}


class Notifier:
    def __init__(self, db=None):
        self.db = db
        self.webhook = (
            os.environ.get("DISCORD_WEBHOOK_AI") or
            os.environ.get("DISCORD_WEBHOOK_URL")
        )
        # チートシグナル専用 Discord webhook（新チャンネル）
        # .env に DISCORD_WEBHOOK_CHEAT_SIGNAL=https://discord.com/api/webhooks/... を設定
        self.cheat_webhook = os.environ.get("DISCORD_WEBHOOK_CHEAT_SIGNAL", "")
        self.session = requests.Session()
        self._sent: dict = {}     # {key: timestamp}
        self._throttle_sec = 600  # 10分重複排除

    def _sym(self, symbol: str) -> str:
        return SYMBOL_DISPLAY.get(symbol.upper(), symbol.upper())

    def _is_duplicate(self, key: str) -> bool:
        now = datetime.now().timestamp()
        if key in self._sent and now - self._sent[key] < self._throttle_sec:
            return True
        self._sent[key] = now
        return False

    def _post(self, payload: dict) -> bool:
        if not self.webhook:
            logger.debug("[Discord] webhook未設定 — 通知スキップ")
            return False
        try:
            r = self.session.post(self.webhook, json=payload, timeout=5)
            if r.status_code not in (200, 204):
                logger.error(f"[Discord] webhook失敗 status={r.status_code} body={r.text[:100]}")
                return False
            return True
        except Exception as e:
            logger.error(f"[Discord] 送信エラー: {e}")
            return False

    # ─── シグナル通知 ──────────────────────────────────────────
    def send_signal(self, symbol: str, direction: str, confidence: str,
                    entry: float, sl: float, tp: float,
                    reason: str = "", macro_summary: str = "") -> None:
        if direction == "WAIT":
            return
        key = f"{symbol}:{direction}"
        if self._is_duplicate(key):
            return

        conf_badge = {"HIGH": "🟢 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "⚪ LOW"}.get(confidence, "⚪")
        dir_icon   = "🟢🟢" if direction == "BUY" else "🔴🔴"
        sym        = self._sym(symbol)
        color      = 0x00C851 if direction == "BUY" else 0xFF4444
        macro_line = f"🌐 {macro_summary[:80]}\n" if macro_summary else ""

        desc = (
            f"```\n"
            f"{conf_badge} SIGNAL\n"
            f"{dir_icon} {direction} — {sym}\n"
            f"{'━' * 32}\n"
            f"💰 Entry : {entry:.5f}\n"
            f"🎯 TP    : {tp:.5f}\n"
            f"🛑 SL    : {sl:.5f}\n"
            f"{'━' * 32}\n"
            f"📋 {reason[:120]}\n"
            f"{macro_line}"
            f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"```"
        )
        self._post({
            "username": "ONO Estimator",
            "embeds": [{"description": desc, "color": color,
                        "footer": {"text": "ONO Estimator v7.1 — Technical + Funda"}}],
        })
        self._log(symbol, direction)

    # ─── デモ決済通知 ──────────────────────────────────────────
    def send_demo_result(self, pos: dict, close_price: float,
                         result: str, pips: float, win_rate=None) -> None:
        sym       = self._sym(pos.get("symbol", ""))
        direction = pos.get("direction", "")
        entry     = pos.get("entry_price", 0)
        reason    = pos.get("reason", "")
        icon      = "✅" if result == "WIN" else "❌"
        pips_sign = "+" if result == "WIN" else "-"
        wr_str    = f"{win_rate:.1f}%" if win_rate is not None else "---"
        color     = 0x00C851 if result == "WIN" else 0xFF4444

        desc = "\n".join([
            f"{icon} **DemoTrader {result}**",
            f"{sym} {direction}",
            f"Entry: {entry:.5f} → Close: {close_price:.5f}",
            f"{pips_sign}{abs(pips):.1f} pips | 通算勝率: {wr_str}",
            f"📋 {reason[:200]}" if reason else "",
            f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        ])
        self._post({
            "username": "ONO Estimator DemoTrader",
            "embeds": [{"description": desc[:2000], "color": color}],
        })

    # ─── 生テキスト送信（確率シグナル・ブリーフィング用） ─────────
    def send_raw(self, message: str) -> bool:
        """Discord に文字列をそのまま送信する（2000字超は分割）"""
        if not message:
            return False
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        ok = True
        for chunk in chunks:
            ok = self._post({"content": chunk}) and ok
        return ok

    # ─── システム警告 ──────────────────────────────────────────
    def send_alert(self, message: str) -> None:
        self._post({"content": f"⚠️ {message}"})

    # ─── チートシグナル通知 ────────────────────────────────────
    def send_cheat_signal(
        self,
        pair: str,
        interval: str,
        direction: str,           # "buy" | "sell"
        probability: float,       # 0-100
        ev: float,                # 期待値（pips or $）
        active_signals: list,     # [{"label": str, "wr": float}, ...]
        key_level: dict,          # get_key_level_summary() の戻り値
        price: float,
        pair_unit: str = "p",     # "p" or "$"
    ) -> bool:
        """
        チートシグナルチャンネルへエントリータイミング通知を送信。
        DISCORD_WEBHOOK_CHEAT_SIGNAL が未設定の場合はFalseを返す。
        """
        if not self.cheat_webhook:
            logger.debug("[CheatSignal] webhook未設定 — スキップ")
            return False

        key = f"cheat:{pair}:{interval}:{direction}"
        if self._is_duplicate(key):
            return False

        dir_ja   = "買い" if direction == "buy" else "売り"
        dir_icon = "🟢" if direction == "buy" else "🔴"
        color    = 0x00C851 if direction == "buy" else 0xFF4444

        # ── シグナル根拠行 ──────────────────────────────────────
        sig_lines = "\n".join(
            f"  ✅ {s['label']}（過去勝率 {s['wr']:.1f}%）"
            for s in active_signals[:6]
        ) or "  （シグナル詳細なし）"

        # ── キーレベル行 ─────────────────────────────────────────
        kl_lines = []
        if key_level.get("at_support"):
            kl_lines.append(f"  📍 サポート付近: {key_level['near_support']:.4f}"
                            f"（距離 {key_level['support_dist_pips']:.1f}{pair_unit}）")
        if key_level.get("at_resistance"):
            kl_lines.append(f"  🧱 レジスタンス付近: {key_level['near_resistance']:.4f}"
                            f"（距離 {key_level['resist_dist_pips']:.1f}{pair_unit}）")
        if key_level.get("breakout_up"):
            kl_lines.append(f"  🚀 キーレベル上方ブレイク: {key_level['nearest']:.4f}")
        if key_level.get("breakout_dn"):
            kl_lines.append(f"  📉 キーレベル下方ブレイク: {key_level['nearest']:.4f}")
        if not kl_lines:
            kl_lines.append("  （主要キーレベルから離れた位置）")
        kl_text = "\n".join(kl_lines)

        # ── エントリータイミング提案 ─────────────────────────────
        if interval in ("4h", "1d"):
            timing_hint = "15m足でハンマー/インサイドバーブレイクを確認してエントリー"
        elif interval in ("1h", "30m"):
            timing_hint = "5m足でピンバー or MACDヒストグラム転換を確認してエントリー"
        else:
            timing_hint = "現在足の確定後に成行エントリー（SLは直近安値/高値の外）"

        ev_str = f"{ev:+.0f}{pair_unit}"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        desc = (
            f"```\n"
            f"{dir_icon} {dir_ja}シグナル — {pair} {interval}\n"
            f"{'━' * 36}\n"
            f"💯 確率: {probability:.1f}%  |  EV: {ev_str}/トレード\n"
            f"💰 現在価格: {price}\n"
            f"{'━' * 36}\n"
            f"📋 根拠（アクティブシグナル）:\n"
            f"{sig_lines}\n"
            f"{'━' * 36}\n"
            f"📍 キーレベル状況:\n"
            f"{kl_text}\n"
            f"{'━' * 36}\n"
            f"⏰ エントリータイミング:\n"
            f"  → {timing_hint}\n"
            f"🛑 SL: {dir_ja}方向と逆のキーレベルの外側に設定\n"
            f"{'━' * 36}\n"
            f"🕐 {ts}\n"
            f"```"
        )

        payload = {
            "username": "チートシグナル by ONO",
            "embeds": [{
                "title": f"🎯 エントリー候補: {pair} {interval} {dir_ja}",
                "description": desc,
                "color": color,
                "footer": {"text": "FX辞典統計 × ONO Estimator"},
            }],
        }

        try:
            r = self.session.post(self.cheat_webhook, json=payload, timeout=5)
            ok = r.status_code in (200, 204)
            if not ok:
                logger.error(f"[CheatSignal] 失敗 status={r.status_code}")
            else:
                self._sent[key] = datetime.now().timestamp()
            return ok
        except Exception as e:
            logger.error(f"[CheatSignal] 送信エラー: {e}")
            return False

    def _log(self, symbol: str, direction: str) -> None:
        if not self.db or not self.db.client:
            return
        try:
            self.db.client.table("notification_logs").insert({
                "symbol": symbol,
                "direction": direction,
                "score": 0,
                "notified_at": datetime.now().isoformat(),
            }).execute()
        except Exception:
            pass
