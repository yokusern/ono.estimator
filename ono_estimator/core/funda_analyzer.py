import os
import google.generativeai as genai

class FundaAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # モデル名を明示的なフルパスで指定
                self.model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
            except Exception as e:
                print(f"[Funda] Init Error: {e}")
                self.model = None
        else:
            self.model = None

    def analyze(self, symbol, news_list, context):
        if not self.model: return {"theme": "Neutral", "direction": "NEUTRAL"}
        
        prompt = f"Analyze {symbol} fundamentals based on news and global context: {context}. Return JSON: {{'theme': '...', 'direction': 'BUY/SELL/NEUTRAL'}}"
        try:
            response = self.model.generate_content(prompt)
            # 簡易的な抽出（本番はjson.loads等を使用）
            import json
            import re
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match: return json.loads(match.group())
            return {"theme": "Syncing", "direction": "NEUTRAL"}
        except:
            return {"theme": "Market Stability", "direction": "NEUTRAL"}
