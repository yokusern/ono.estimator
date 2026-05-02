import os
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from .models import PredictionResult

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.model = None
            return

        try:
            genai.configure(api_key=api_key)
            # モデル名を明示的なフルパスで指定
            model_name = 'models/gemini-1.5-flash-latest'
            print(f"[Gemini] Initializing with {model_name}")
            self.model = genai.GenerativeModel(model_name)
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def analyze(self, result: PredictionResult, symbol: str) -> str:
        if not self.model: return "AI Not Connected."
        
        prompt = f"""
あなたはFX/株/仮想通貨のプロトレーダー兼分析AI「ONO 3.0」です。
【銘柄】: {symbol}
【状況】: {result.status.value} (Score: {result.win_rate_score}%)
【根拠】: {result.rationale_a}, {result.rationale_b}
【注意】: {result.caution}

論理的かつ情熱的なプロの視点で分析を提示してください。
1. 結論（アクション）
2. テクニカル/ファンダメンタルズの融合分析
3. 具体的な資金管理（リスク/リワード）
4. 注意すべきシナリオ
"""
        try:
            return self._call_api(prompt)
        except Exception as e:
            return f"Analysis failed: {e}"
            
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=20))
    def _call_api(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text
