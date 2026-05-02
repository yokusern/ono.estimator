import os
import json
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.model = None
            return

        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
            print("[Gemini] MTF Strategist Initialized")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def batch_analyze(self, symbols_data: dict) -> dict:
        """MTFデータを統合して分析"""
        if not self.model:
            return {sym: {"ai_text": "AI Analysis Offline."} for sym in symbols_data.keys()}

        data_summary = ""
        for sym, d in symbols_data.items():
            mtf = d.get("mtf", {})
            data_summary += f"--- {sym} ---\n"
            # 現在の選択TF
            data_summary += f"Current TF: {d.get('timeframe')}\n"
            data_summary += f"1m Momentum: RSI={mtf.get('1m', {}).get('rsi')}, Price={mtf.get('1m', {}).get('price')}\n"
            data_summary += f"1h Structure: RSI={mtf.get('1h', {}).get('rsi')}, Trend={mtf.get('1h', {}).get('theme')}\n"
            data_summary += f"Score: {d.get('score')}%\n\n"

        prompt = f"""
あなたは伝説的なマルチアセット・ストラテジスト「ONO AI」です。
短期（1分足）のモメンタムと長期（1時間足）の構造的トレンドを組み合わせ、精度の高い戦略を生成してください。

【マーケットデータ】
{data_summary}

【出力要件】
1. 「ai_text」: 短期と長期のコンフルエンス（一致）に基づいた論理的根拠。短期の過熱感と長期のトレンド転換の乖離なども指摘してください。
2. 「predicted_price」: 数値。ターゲット価格。
3. 「probability」: 0-100。短期・長期が一致している場合は高めに、乖離している場合は低めに設定。
4. 全体戦略を「market_intelligence」に記述。

【出力形式】
{{
  "USDJPY": {{
    "ai_text": "1分足では買われすぎだが、1時間足の強力な上昇トレンドラインに支えられており...",
    "predicted_price": 157.80,
    "probability": 82
  }},
  ...
  "market_intelligence": "ドル高傾向が1時間足レベルで定着しており..."
}}
JSON以外のテキストは一切含めないでください。
"""
        try:
            response = self._call_api(prompt)
            import re
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {sym: {"ai_text": "JSON Parsing Error."} for sym in symbols_data.keys()}
        except Exception as e:
            print(f"[Gemini] MTF Analysis Error: {e}")
            return {sym: {"ai_text": f"Analysis failed: {e}"} for sym in symbols_data.keys()}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=15))
    def _call_api(self, prompt: str):
        return self.model.generate_content(prompt)
