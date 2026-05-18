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

    # ─── システム警告 ──────────────────────────────────────────
    def send_alert(self, message: str) -> None:
        self._post({"content": f"⚠️ {message}"})

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
