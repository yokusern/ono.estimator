import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class Notifier:
    """システム別・銘柄固定のDiscord通知ルーティングクラス"""
    def __init__(self):
        # ユーザー要求に基づく個別Webhookの読み込み
        self.webhooks = {
            "SV": os.environ.get("DISCORD_WEBHOOK_SV"),
            "LW": os.environ.get("DISCORD_WEBHOOK_LW"),
            "TKS": os.environ.get("DISCORD_WEBHOOK_TKS"),
            "AI": os.environ.get("DISCORD_WEBHOOK_AI")
        }
        # フォールバック
        self.default_webhook = os.environ.get("DISCORD_WEBHOOK_AI") or os.environ.get("DISCORD_WEBHOOK_URL")

    def notify_if_needed(self, symbol: str, result, ai_text: str, current_price: float):
        """通知が必要な場合に適切なチャンネルへルーティングして送信"""
        status_val = result.status.value
        systems = result.base_system.split(",")
        
        # 通知すべき重要なステータス
        # Start系は常に通知、Standby系は優位性が高い場合のみ通知
        is_important = "Start" in status_val or (("Standby" in status_val) and result.win_rate_score >= 80)
        
        if not is_important:
            return

        # 各システムごとに通知を振り分け
        for system_name in systems:
            webhook_url = self.webhooks.get(system_name) or self.default_webhook
            if not webhook_url:
                continue

            self._send_discord(webhook_url, symbol, system_name, status_val, result.win_rate_score, ai_text, current_price)

    def _send_discord(self, webhook_url: str, symbol: str, system: str, status: str, score: float, ai_text: str, price: float):
        """実際のDiscord送信処理"""
        is_iron_clad = "🌟[鉄板]" in ai_text
        
        # フォーマット厳守: [Symbol] [Source] [Status] Now: [Price] @everyone
        # 例: USDJPY SV Sell_Standby Now: 157.112 @everyone
        mention = "@everyone" if (is_iron_clad or score >= 90) else ""
        
        # ステータス表示の調整 (Buy Start -> Buy_Start, etc. スペースをアンダースコアに)
        display_status = status.replace(" ", "_")
        title = f"**{symbol} {system} {display_status} Now: {price:.3f} {mention}**"
        
        color = 0xF97316 if is_iron_clad else 0x10B981 # Orange vs Emerald
        
        # 説明文の構築
        description = f"**優位性スコア**: {score}%\n\n"
        if system == "AI" or "Start" in status:
            description += f"**AI分析・根拠**\n{ai_text[:1000]}"
        
        payload = {
            "username": f"ONO Estimator ({system})",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/8644/8644145.png",
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                    "footer": {
                        "text": f"ONO Estimator v2.1 | Market Strategy AI"
                    },
                    "image": {
                        # チャート添付用のモック (将来的に動的生成画像URLに置換)
                        "url": f"https://s3.tradingview.com/snapshots/c/{symbol.lower()}.png" 
                    }
                }
            ]
        }

        try:
            response = requests.post(webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Notification sent to {system} channel for {symbol}")
        except Exception as e:
            logger.error(f"Failed to send notification to {system}: {e}")
