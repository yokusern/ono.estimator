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
投資ストラテジストとして、以下の銘柄の1分足および1時間足のデータに基づき、
今後数分〜数十分の展開を200文字程度の日本語で具体的に分析・予測してください。
また、予測価格と確信度も算出してください。

【銘柄】: {symbol}
【1分足(短期)】: スコア={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}
【1時間足(長期)】: スコア={mtf.get('1h', {}).get('score')}, 状態={mtf.get('1h', {}).get('theme')}

以下のJSON形式で出力してください。
{{
  "ai_text": "分析内容（200文字程度の専門的な日本語）",
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
