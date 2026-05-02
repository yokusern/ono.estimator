import os
import json
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

class FundaAnalyzer:
    """7つの外部指標を統合し、Gemini 1.5 Pro で多角的な分析を行うクラス"""
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def analyze(self, symbol: str, yf_news: list, market_context: dict) -> dict:
        """
        全ソース（yfinance, Alpha Vantage, FRED, News API, CoinGecko等）を統合分析する
        """
        if not self.model:
            return {"theme": "NONE", "direction": "NEUTRAL", "reason": "Gemini APIキー未設定"}

        # コンテキスト情報の整形
        context_str = json.dumps(market_context, indent=2, ensure_ascii=False)
        news_summary = "\n".join([f"- {n.get('title', '')}" for n in yf_news[:3]])
        
        prompt = f"""
あなたはFX・ゴールド・暗号資産のチーフ・ストラテジストです。
以下の「7層のデータソース」を統合分析し、現在の相場テーマと、対象銘柄に対する最も合理的な方向感を判定してください。

【対象銘柄】: {symbol}

【外部指標データ (Technical/Macro/Sentiment)】:
{context_str}

【主要ニュース要約】:
{news_summary}

【分析ミッション】
1. マクロ環境（金利・景気）とセンチメント（恐怖指数等）から、現在が「リスクオン」か「リスクオフ」かを特定せよ。
2. 対象銘柄のテクニカル指標（Alpha Vantage提供）との整合性を確認せよ。
3. 総合的な「優位性のある方向（UP/DOWN/NEUTRAL）」と、その「確固たる根拠」を導き出せ。

【出力要件】
以下のキーを持つ厳密なJSON形式で出力すること。
- "theme": 相場の支配的テーマ（15文字以内）
- "direction": 推奨される方向（"UP", "DOWN", "NEUTRAL"）
- "reason": マクロとテクニカルを統合した論理的な根拠（100文字程度）
"""
        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
                
            result = json.loads(text)
            return result
        except Exception as e:
            print(f"Funda Analysis Error: {e}")
            return {"theme": "ERROR", "direction": "NEUTRAL", "reason": f"AI分析失敗: {str(e)}"}
