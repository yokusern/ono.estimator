import os
import json
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import traceback

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[Gemini] GEMINI_API_KEY not set. AI analysis disabled.")
            self.model = None
            return
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            self.model_name = GEMINI_MODEL
            print(f"[Gemini] Engine Configured: {GEMINI_MODEL}")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def analyze_single(
        self,
        symbol: str,
        data: dict,
        feedback: str = "",
        gemini_prompt_override: str = None,
    ) -> dict:
        """
        単一銘柄分析。
        gemini_prompt_override が渡された場合はv6エンジンのプロンプトを使用。
        それ以外は従来のシンプルプロンプトを使用。
        """
        if not self.model:
            return None

        try:
            if gemini_prompt_override:
                # v6エンジン生成の高品質プロンプトを使用
                prompt = gemini_prompt_override + """

## 追加指示
以下のJSON形式のみで回答してください（日本語）:
{
  "ai_text": "【論理解説】...(100字)\\n【過去類似局面】...(80字)\\n【戦略】Entry:XXX / TP:XXX / SL:XXX",
  "predicted_price": 0.0,
  "probability": 0
}
"""
            else:
                # 従来プロンプト（過去フィードバック付き）
                mtf = data.get("mtf", {})
                prompt = f"""
Return ONLY a raw JSON object. No markdown. No explanation outside JSON.
As an AI-driven quantitative strategist that EVOLVES from past results, analyze: {symbol}

[Market Data]
- Short (1m): Score={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}
- Mid (30m):  Score={mtf.get('30m', {}).get('score')}, RSI={mtf.get('30m', {}).get('rsi')}
- Long (1h):  Score={mtf.get('1h', {}).get('score')}

[Self-Learning Feedback (Your Past Performance)]
{feedback if feedback else "No historical data yet. Base analysis on market data only."}

[Requirement - Write in Japanese, ~200 chars per section]
1. 【論理解説】: Explain WHY using terms like Support-Resistance Flip, RSI divergence, Fakeout
2. 【過去類似局面】: Compare to a specific historical market period
3. 【戦略】: Entry / TP / SL as specific numbers

JSON Format (return ONLY this, no other text):
{{
  "ai_text": "【論理解説】...\\n【過去類似局面】...\\n【戦略】Entry:XXX / TP:XXX / SL:XXX",
  "predicted_price": 0.0,
  "probability": 0
}}
"""

            response = self._call_api(prompt)
            if not response:
                return None
            text = response.text

            json_match = re.search(r'(\{.*?\})\s*$', text, re.DOTALL)
            if not json_match:
                json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
                if result.get("ai_text"):
                    return result

            print(f"[Gemini] Parse failed for {symbol}. Raw: {text[:200]}")
            return None

        except Exception as e:
            print(f"[Gemini] analyze_single error for {symbol}: {e}")
            traceback.print_exc()
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def _call_api(self, prompt: str):
        try:
            return self.model.generate_content(prompt)
        except Exception as e:
            print(f"[Gemini] API call error: {e}")
            raise
