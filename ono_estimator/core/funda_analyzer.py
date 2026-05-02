import os
import google.generativeai as genai
from .market_context import MarketContextFetcher

class FundaAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # モデル名の自動解決
                available_models = [m.name for m in genai.list_models()]
                target_model = 'models/gemini-1.5-flash-latest'
                if target_model not in available_models:
                    fallback = next((m for m in available_models if 'gemini-1.5-flash' in m), None)
                    target_model = fallback if fallback else 'gemini-1.5-flash'
                
                self.model = genai.GenerativeModel(target_model)
            except Exception as e:
                print(f"FundaAnalyzer Init Error: {e}")
                self.model = None
        else:
            self.model = None

    def analyze(self, symbol, news_list, context):
        if not self.model:
            return {"theme": "Technical Analysis Only", "direction": "NEUTRAL", "rationale": "AI Not Initialized"}

        news_text = "\n".join([f"- {n['title']}" for n in news_list[:5]])
        
        prompt = f"""
市場分析エキスパートとして、{symbol}のファンダメンタルズを15文字以内の「テーマ」と「方向性」で判定してください。
【ニュース】: {news_text}
【市場状況】: {context}

出力形式(JSON):
{{"theme": "〇〇相場", "direction": "BUY/SELL/NEUTRAL", "rationale": "理由"}}
"""
        try:
            response = self.model.generate_content(prompt)
            # 簡易パース
            text = response.text
            import json
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"theme": "Analyzing...", "direction": "NEUTRAL", "rationale": text}
        except Exception as e:
            print(f"Funda Analysis Error for {symbol}: {e}")
            return {"theme": "Error/Rate Limit", "direction": "NEUTRAL", "rationale": str(e)}
