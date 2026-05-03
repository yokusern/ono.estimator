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
            # モデル名をフルパスで指定して確実性を向上
            self.model = genai.GenerativeModel('models/gemini-1.5-flash')
            print("[Gemini] Engine Online (models/gemini-1.5-flash)")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            traceback.print_exc()
            self.model = None

    def batch_analyze(self, symbols_data: dict) -> dict:
        """MTF分析を強化し、解析エラーを極限まで減らす"""
        if not self.model:
            return {sym: {"ai_text": "AI Analyzer Offline. Please check GEMINI_API_KEY."} for sym in symbols_data.keys()}

        try:
            data_summary = ""
            for sym, d in symbols_data.items():
                mtf = d.get("mtf", {})
                data_summary += f"[{sym}]\n"
                data_summary += f"- 1m: Score={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}\n"
                data_summary += f"- 1h: Theme={mtf.get('1h', {}).get('theme')}, Score={mtf.get('1h', {}).get('score')}\n\n"

            prompt = f"""
Return ONLY a raw JSON object. NO markdown, NO code blocks.
Analyze these financial assets and provide strategy:
{data_summary}

Required JSON format:
{{
  "SYMBOL": {{
    "ai_text": "Japanese strategy description",
    "predicted_price": 123.45,
    "probability": 85
  }},
  "market_intelligence": "Overall market theme"
}}
"""
            response = self._call_api(prompt)
            text = response.text
            
            # JSON部分を抽出 (markdownの ```json ... ``` があっても対応)
            import re
            json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            
            print(f"[Gemini] Parsing Error. Raw output: {text[:200]}")
            return {sym: {"ai_text": "Analysis parsing failed."} for sym in symbols_data.keys()}
        except Exception as e:
            print(f"[Gemini] Analysis failed: {e}")
            traceback.print_exc()
            return {sym: {"ai_text": f"Error: {str(e)}"} for sym in symbols_data.keys()}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=15))
    def _call_api(self, prompt: str):
        if not self.model: return None
        return self.model.generate_content(prompt)
