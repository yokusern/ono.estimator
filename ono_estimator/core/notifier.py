import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class Notifier:
    """DiscordおよびLINE Notifyへの通知クラス"""
    def __init__(self):
        self.webhooks = {
            "SV": os.environ.get("DISCORD_WEBHOOK_SV"),
            "LW": os.environ.get("DISCORD_WEBHOOK_LW"),
            "TKS": os.environ.get("DISCORD_WEBHOOK_TKS"),
            "AI": os.environ.get("DISCORD_WEBHOOK_AI")
        }
        self.default_webhook = os.environ.get("DISCORD_WEBHOOK_AI") or os.environ.get("DISCORD_WEBHOOK_URL")
        self.line_token = os.environ.get("LINE_NOTIFY_TOKEN")
        self.session = requests.Session() # 再利用で高速化

    def notify_if_needed(self, symbol: str, result, ai_data: dict, current_price: float):
        """通知が必要な場合にDiscord/LINEへ送信"""
        status_val = result.status.value if hasattr(result.status, "value") else str(result.status)
        systems = result.base_system.split(",") if hasattr(result, "base_system") else ["AI"]
        score = result.win_rate_score if hasattr(result, "win_rate_score") else 0
        ai_text = ai_data.get("ai_text", "")
        
        # 通知判定: 急変時（Start系）または優位性が極めて高い場合
        is_important = "Start" in status_val or score >= 80 or "🚨[急変]" in ai_text
        
        if not is_important:
            return

        # LINE Notify 送信
        if self.line_token:
            self._send_line(symbol, status_val, score, ai_data, current_price)

        # Discord 送信
        for system_name in systems:
            webhook_url = self.webhooks.get(system_name) or self.default_webhook
            if webhook_url:
                self._send_discord(webhook_url, symbol, system_name, status_val, score, ai_data, current_price)

    def _send_line(self, symbol: str, status: str, score: float, ai_data: dict, price: float):
        url = "https://notify-api.line.me/api/notify"
        headers = {"Authorization": f"Bearer {self.line_token}"}
        
        target_price = ai_data.get("predicted_price", "---")
        prob = ai_data.get("probability", "---")
        
        message = (
            f"\n【ONO Alert】{symbol}\n"
            f"状態: {status}\n"
            f"現在値: {price:.3f}\n"
            f"優位性: {score}%\n"
            f"予測価格: {target_price}\n"
            f"発生確率: {prob}%\n"
            f"--- 根拠 ---\n"
            f"{ai_data.get('ai_text', '')[:200]}..."
        )
        
        try:
            self.session.post(url, headers=headers, data={"message": message}, timeout=5)
        except Exception as e:
            logger.error(f"LINE Notify Error: {e}")

    def _send_discord(self, webhook_url: str, symbol: str, system: str, status: str, score: float, ai_data: dict, price: float):
        ai_text = ai_data.get("ai_text", "")
        is_iron_clad = "🌟[鉄板]" in ai_text or score >= 90
        mention = "@everyone" if is_iron_clad else ""
        
        display_status = status.replace(" ", "_")
        target_price = ai_data.get("predicted_price", "---")
        prob = ai_data.get("probability", "---")

        title = f"**{symbol} {system} {display_status} Now: {price:.3f} {mention}**"
        color = 0xF97316 if is_iron_clad else 0x10B981
        
        description = (
            f"**優位性スコア**: {score}%\n"
            f"**予測ターゲット**: {target_price}\n"
            f"**発生確率**: {prob}%\n\n"
            f"**AI分析・根拠**\n{ai_text[:1000]}"
        )
        
        payload = {
            "username": f"ONO Estimator ({system})",
            "embeds": [{
                "title": title,
                "description": description,
                "color": color,
                "footer": {"text": "ONO Estimator v4.2 | Rapid Monitoring AI"}
            }]
        }

        try:
            self.session.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Discord Error: {e}")
