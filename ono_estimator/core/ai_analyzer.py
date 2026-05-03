import os
import json
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
import traceback

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.model = None
            return

        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('models/gemini-1.5-flash')
            print("[Gemini] Engine Online (Raw Intelligence Mode)")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            traceback.print_exc()
            self.model = None

    def analyze_single(self, symbol: str, data: dict) -> dict:
        """単一銘柄に対して深い分析を実行"""
        if not self.model:
            return None

        try:
            mtf = data.get("mtf", {})
            prompt = f"""
Return ONLY a raw JSON object.
As a professional investment strategist, analyze this asset: {symbol}

[Market Data]
- Short-term (1m): Score={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}
- Long-term (1h): Score={mtf.get('1h', {}).get('score')}, Theme={mtf.get('1h', {}).get('theme')}

[Requirement]
In the "ai_text" field, write a professional strategy (approx. 200 Japanese characters) covering:
1. Current price trend analysis
2. Technical indicators' rationale (RSI, MTF context)
3. Specific future forecast for the next few minutes.

JSON Format:
{{
  "ai_text": "分析内容（専門的な日本語200文字程度）",
  "predicted_price": 0.0,
  "probability": 0
}}
"""
            response = self._call_api(prompt)
            text = response.text
            
            import re
            json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            
            print(f"[Gemini] Parse failed for {symbol}. Output: {text[:100]}")
            return None
        except Exception as e:
            print(f"[Gemini] Analysis failed for {symbol}: {e}")
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
    def _call_api(self, prompt: str):
        if not self.model: return None
        return self.model.generate_content(prompt)
