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
            # モデル名をより一般的なものに変更
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            print("[Gemini] Engine Online (gemini-1.5-flash)")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            traceback.print_exc()
            self.model = None

    def batch_analyze(self, symbols_data: dict) -> dict:
        """MTF分析を強化"""
        if not self.model:
            return {sym: {"ai_text": "AI Analyzer Offline."} for sym in symbols_data.keys()}

        try:
            data_summary = ""
            for sym, d in symbols_data.items():
                mtf = d.get("mtf", {})
                data_summary += f"--- {sym} ---\n"
                data_summary += f"1m Momentum: RSI={mtf.get('1m', {}).get('rsi')}, Price={mtf.get('1m', {}).get('price')}\n"
                data_summary += f"1h Structure: Trend={mtf.get('1h', {}).get('theme')}, Score={mtf.get('1h', {}).get('score')}\n\n"

            prompt = f"""
投資ストラテジストとして、短期と長期のテクニカルから、次の一分の予測を出力してください。
JSON形式で、各銘柄ごとに 'ai_text', 'predicted_price', 'probability' を含めてください。
最後に全体のマーケット概況を 'market_intelligence' として記述してください。

【マーケットデータ】
{data_summary}
"""
            response = self._call_api(prompt)
            
            import re
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                return json.loads(match.group())
            
            print(f"[Gemini] Raw Response: {response.text}")
            return {sym: {"ai_text": "Parsing Error."} for sym in symbols_data.keys()}
        except Exception as e:
            print(f"[Gemini] Analysis failed: {e}")
            traceback.print_exc()
            return {sym: {"ai_text": f"Error: {str(e)}"} for sym in symbols_data.keys()}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=15))
    def _call_api(self, prompt: str):
        if not self.model: return None
        return self.model.generate_content(prompt)
