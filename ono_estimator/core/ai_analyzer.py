import os
import json
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import traceback

# 使用するモデル (起動時にネットワーク接続不要・オブジェクト作成のみ)
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
            # 起動時はオブジェクト作成のみ（ネットワーク呼び出しなし）
            # → サーバークラッシュを防ぐ
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            self.model_name = GEMINI_MODEL
            print(f"[Gemini] Engine Configured: {GEMINI_MODEL} (will verify on first use)")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def analyze_single(self, symbol: str, data: dict, feedback: str = "") -> dict:
        """単一銘柄に対して深い分析と自己学習を実行"""
        if not self.model:
            return None

        try:
            mtf = data.get("mtf", {})
            prompt = f"""
Return ONLY a raw JSON object. No markdown. No explanation outside JSON.
As an AI-driven quantitative strategist that EVOLVES from past results, analyze: {symbol}

[Market Data]
- Short (1m): Score={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}
- Long (1h): Score={mtf.get('1h', {}).get('score')}, Theme={mtf.get('1h', {}).get('theme')}

[Self-Learning Feedback (Your Past Performance)]
{feedback if feedback else "No historical data yet. Base analysis on market data only."}

[Requirement - Write in Japanese, ~200 chars per section]
1. 【論理解説】: Explain WHY using terms like Support-Resistance Flip, RSI divergence, Fakeout
2. 【過去類似局面】: Compare to a specific historical market period
3. 【戦略】: Entry / TP (Take Profit) / SL (Stop Loss) as specific numbers

JSON Format (return ONLY this, no other text):
{{
  "ai_text": "【論理解説】...\n【過去類似局面】...\n【戦略】Entry:XXX / TP:XXX / SL:XXX",
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
                # ai_text が空でないことを確認
                if result.get("ai_text"):
                    return result

            print(f"[Gemini] Parse failed for {symbol}. Raw: {text[:80]}")
            return None
        except Exception as e:
            print(f"[Gemini] Analysis failed for {symbol}: {type(e).__name__}: {e}")
            return None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=6),
        reraise=True
    )
    def _call_api(self, prompt: str):
        if not self.model:
            return None
        return self.model.generate_content(prompt)
