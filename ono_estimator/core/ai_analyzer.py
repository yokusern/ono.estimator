import os
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from .models import PredictionResult

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("WARNING: GEMINI_API_KEY is not set. AI Analysis will be mocked.")
            self.model = None
            return

        try:
            genai.configure(api_key=api_key)
            
            # 利用可能なモデルをリストアップしてデバッグ出力
            print("--- Gemini Model Diagnostics ---")
            available_models = [m.name for m in genai.list_models()]
            print(f"Available models: {available_models}")
            
            # 正確なモデル名の特定
            # 'models/gemini-1.5-flash-latest' または 'models/gemini-1.5-flash' が一般的
            target_model = 'models/gemini-1.5-flash-latest'
            if target_model not in available_models:
                # 代替案を検索
                fallback = next((m for m in available_models if 'gemini-1.5-flash' in m), None)
                if fallback:
                    target_model = fallback
                else:
                    target_model = available_models[0] if available_models else 'gemini-1.5-flash'

            print(f"Selected Gemini Model: {target_model}")
            self.model = genai.GenerativeModel(target_model)
        except Exception as e:
            print(f"CRITICAL: Failed to initialize Gemini: {e}")
            self.model = None

    def analyze(self, result: PredictionResult, symbol: str) -> str:
        if result.status.value not in ["Standby", "Start"]:
            return "分析対象外のステータスです。"
            
        if not self.model:
            return "【モックAI出力】\n- 優位性: {}\n- 環境: {}\n- 勢い: {}\n- 注意: {}".format(
                result.win_rate_score, result.rationale_a, result.rationale_b, result.caution
            )

        prompt = f"""
あなたはプロトレーダー兼分析AIです。以下のデータを元に、論理的で簡潔なアドバイスを作成してください。

【対象】: {symbol} / {result.status.value}
【スコア】: {result.win_rate_score}%
【根拠】: {result.rationale_a}, {result.rationale_b}
【リスク】: {result.caution}

出力項目:
1. 結論（アクションと理由）
2. 資金管理アドバイス
3. リスク警告
"""
        try:
            return self._call_api(prompt)
        except Exception as e:
            print(f"Gemini Analysis Error for {symbol}: {e}")
            return f"分析エラー: 現在リクエストが集中しています。時間をおいて確認してください。({e})"
            
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call_api(self, prompt: str) -> str:
        if not self.model: return "Model not initialized."
        response = self.model.generate_content(prompt)
        return response.text
