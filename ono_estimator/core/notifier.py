"""
Step B1: Discord 通知の完全自動化
- Step 8 の強化トリガー条件（スコア±35以上 & 利確率80%以上 & MTF 2/3以上 & 4時間制限 & イベント抑制）
- Step 8 の Discord メッセージフォーマット（Entry/TP1/TP2/SL/セッション表示）
- 通知履歴を Supabase で管理し、同銘柄4時間以内の連投を防止

Supabase に手動実行が必要な SQL:
  create table if not exists notification_logs (
    id uuid primary key default gen_random_uuid(),
    symbol text,
    direction text,
    score float,
    notified_at timestamptz default now()
  );
"""
import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, db=None):
        self.db = db
        self.webhooks = {
            "SV":  os.environ.get("DISCORD_WEBHOOK_SV"),
            "LW":  os.environ.get("DISCORD_WEBHOOK_LW"),
            "TKS": os.environ.get("DISCORD_WEBHOOK_TKS"),
            "AI":  os.environ.get("DISCORD_WEBHOOK_AI"),
        }
        self.default_webhook = (
            os.environ.get("DISCORD_WEBHOOK_AI") or
            os.environ.get("DISCORD_WEBHOOK_URL")
        )
        self.line_token = os.environ.get("LINE_NOTIFY_TOKEN")
        self.session = requests.Session()
        self._local_log: dict = {}  # DB 不使用時のローカル4時間制限

    # ─── 通知判定 ─────────────────────────────────────────────
    def notify_if_needed(
        self,
        symbol: str,
        result,
        ai_data: dict,
        current_price: float,
        session: str = "off",
        event_risk: dict = None,
    ):
        """Step 8 の AND 条件で通知判定"""
        score = getattr(result, "win_rate_score", 0) if result else ai_data.get("probability", 0)
        direction = ai_data.get("direction", "WAIT")
        probability = ai_data.get("probability", 0)

        # 条件1: スコア or 利確率
        if abs(score) < 35 and probability < 80:
            return

        # 条件2: 利確率 80%以上
        if probability < 80:
            return

        # 条件3: 重要指標 2時間以内は通知抑制
        if event_risk and event_risk.get("critical"):
            logger.info(f"[Notifier] {symbol} suppressed: event within 2h")
            return

        # 条件4: 4時間以内の連投防止
        if self._notified_recently(symbol):
            return

        # 通知実行
        if self.line_token:
            self._send_line(symbol, score, ai_data, current_price, session)

        systems = result.base_system.split(",") if hasattr(result, "base_system") else ["AI"]
        for sys_name in systems:
            webhook = self.webhooks.get(sys_name) or self.default_webhook
            if webhook:
                self._send_discord(webhook, symbol, sys_name, score, ai_data, current_price, session)

        self._log_notification(symbol, direction, score)

    def _notified_recently(self, symbol: str) -> bool:
        """4時間以内に同銘柄への通知があれば True"""
        cutoff = datetime.now() - timedelta(hours=4)

        # Supabase から確認
        if self.db and self.db.client:
            try:
                res = self.db.client.table("notification_logs")\
                    .select("notified_at")\
                    .eq("symbol", symbol)\
                    .gte("notified_at", cutoff.isoformat())\
                    .limit(1).execute()
                return len(res.data) > 0
            except Exception:
                pass

        # ローカルフォールバック
        last = self._local_log.get(symbol)
        return bool(last and (datetime.now() - last) < timedelta(hours=4))

    def _log_notification(self, symbol: str, direction: str, score: float):
        self._local_log[symbol] = datetime.now()
        if self.db and self.db.client:
            try:
                self.db.client.table("notification_logs").insert({
                    "symbol": symbol,
                    "direction": direction,
                    "score": score,
                    "notified_at": datetime.now().isoformat(),
                }).execute()
            except Exception:
                pass

    # ─── Discord 送信 ─────────────────────────────────────────
    def _send_discord(
        self,
        webhook_url: str,
        symbol: str,
        system: str,
        score: float,
        ai_data: dict,
        current_price: float,
        session: str = "off",
    ):
        direction = ai_data.get("direction", "WAIT")
        probability = ai_data.get("probability", 0)
        entry = ai_data.get("entry") or ai_data.get("predicted_price", "---")
        tp1 = ai_data.get("tp1", "---")
        tp2 = ai_data.get("tp2", "---")
        sl = ai_data.get("sl", "---")
        hold_min = ai_data.get("hold_time_minutes", "---")
        basis = ai_data.get("basis", ai_data.get("ai_text", "")[:80])
        confidence = ai_data.get("confidence", "LOW")
        cached = ai_data.get("cached", False)
        event_msg = ai_data.get("event_message", "なし")

        dir_icon = "🟢🟢" if direction == "BUY" else "🔴🔴" if direction == "SELL" else "⚪"
        conf_icon = "⭐⭐⭐" if confidence == "HIGH" else "⭐⭐" if confidence == "MEDIUM" else "⭐"
        mention = "@everyone" if score >= 90 else ""

        from .session_filter import SESSION_LABELS
        session_label = SESSION_LABELS.get(session, session)
        multiplier = ai_data.get("session_multiplier", 1.0)

        hold_label = f"約{hold_min}分" if isinstance(hold_min, int) else "---"

        description = (
            f"```\n"
            f"{dir_icon} {direction} — {symbol} {mention}\n"
            f"{'━' * 35}\n"
            f"📊 スコア: {score} | 利確率: {probability}% | {conf_icon}\n"
            f"📐 Entry: {entry} | TP1: {tp1} | TP2: {tp2} | SL: {sl}\n"
            f"⏱ 推奨保有時間: {hold_label}\n"
            f"🕘 {session_label}（補正倍率 ×{multiplier}）\n"
            f"⚡ 根拠: {basis[:80]}\n"
            f"⚠️ イベントリスク: {event_msg}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M JST')}\n"
            f"{'━' * 35}\n"
            f"```"
        )

        if cached:
            description += "\n🕐 *キャッシュデータ使用中*"

        color = 0x00C851 if direction == "BUY" else 0xFF4444 if direction == "SELL" else 0x888888
        payload = {
            "username": f"ONO Estimator ({system})",
            "embeds": [{
                "description": description,
                "color": color,
                "footer": {"text": "ONO Estimator Ultra v6.0"},
            }],
        }
        try:
            self.session.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"[Discord] Error: {e}")

    # ─── LINE 送信 ────────────────────────────────────────────
    def _send_line(self, symbol: str, score: float, ai_data: dict, price: float, session: str):
        prob = ai_data.get("probability", "---")
        entry = ai_data.get("entry", "---")
        tp1 = ai_data.get("tp1", "---")
        sl = ai_data.get("sl", "---")
        message = (
            f"\n【ONO Alert】{symbol}\n"
            f"方向: {ai_data.get('direction', 'WAIT')}\n"
            f"現在値: {price:.3f}\n"
            f"スコア: {score} / 利確率: {prob}%\n"
            f"Entry: {entry} TP1: {tp1} SL: {sl}\n"
            f"{ai_data.get('basis', '')[:100]}"
        )
        try:
            self.session.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {self.line_token}"},
                data={"message": message},
                timeout=5,
            )
        except Exception as e:
            logger.error(f"[LINE] Error: {e}")
