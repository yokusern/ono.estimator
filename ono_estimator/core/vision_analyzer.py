"""
Step 7: チャート画像の Gemini Vision 分析
SMC（スマートマネーコンセプト）視点での分析を返す。
"""
import os
import json
import re
import base64
import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


class VisionAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.model = None
            return
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(GEMINI_MODEL)
        except Exception as e:
            logger.error(f"[Vision] Init failed: {e}")
            self.model = None

    async def analyze_chart_image(self, symbol: str, image_base64: str) -> dict:
        """
        Gemini 2.0 Flash にチャート画像を送り、SMC 視点での分析を返す。
        戻り値: { "smc_bias": "BUY|SELL|NEUTRAL", "key_levels": [...], "summary": str }
        """
        if not self.model:
            return {"smc_bias": "NEUTRAL", "key_levels": [], "summary": "Vision AI 未設定"}

        try:
            image_data = base64.b64decode(image_base64)
            prompt = f"""
あなたはSMC（スマートマネーコンセプト）の専門トレーダーです。
{symbol} のチャート画像を分析してください。

以下の JSON のみを返してください（マークダウン禁止）:
{{
  "smc_bias": "BUY" or "SELL" or "NEUTRAL",
  "key_levels": [
    {{"type": "resistance|support|order_block|fvg", "price": 数値, "strength": "strong|medium|weak"}}
  ],
  "bos": "直近のブレイク・オブ・ストラクチャーの説明（日本語50字以内）",
  "liquidity": "流動性プール・スイープの有無（日本語50字以内）",
  "summary": "総合判断（日本語100字以内）",
  "confidence": "HIGH" or "MEDIUM" or "LOW"
}}
"""
            import PIL.Image
            import io
            img = PIL.Image.open(io.BytesIO(image_data))
            response = self.model.generate_content([prompt, img])
            text = response.text

            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                result = json.loads(match.group())
                return result

            return {"smc_bias": "NEUTRAL", "key_levels": [], "summary": text[:100]}
        except Exception as e:
            logger.error(f"[Vision] Analysis failed: {e}")
            return {"smc_bias": "NEUTRAL", "key_levels": [], "summary": f"解析エラー: {str(e)[:50]}"}
