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
        else:
            genai.configure(api_key=api_key)
            # 安定した動作のため最新のgemini-1.5-proなどを指定
            self.model = genai.GenerativeModel('models/gemini-1.5-flash')

    def analyze(self, result: PredictionResult, symbol: str) -> str:
        if result.status.value not in ["Standby", "Start"]:
            return "分析対象外のステータスです。"
            
        if not self.model:
            return "【モックAI出力】\n- 優位性: {}\n- 環境: {}\n- 勢い: {}\n- 注意: {}\n- タグ: {}".format(
                result.win_rate_score, result.rationale_a, result.rationale_b, result.caution, ", ".join(result.tags)
            )

        prompt = f"""
あなたは月1000万を安定して稼ぐプロトレーダー兼「ONO estimator」の分析AIです。
以下の判定エンジンの出力を元に、トレーダーに提示する「AIアナリティクス」を作成してください。

【対象銘柄】: {symbol}
【現在のステータス】: {result.status.value} (発火したシステム: {result.base_system})
【基本優位性スコア】: {result.win_rate_score}%

【エンジンの根拠データ】
- 環境認識: {result.rationale_a}
- 勢い分析: {result.rationale_b}
- 注意点フラグ: {result.caution}
- 検出されたタグ: {", ".join(result.tags)}

【出力要件】
以下の5項目を必ず含め、論理的で簡潔なマークダウン形式で出力してください。
1. **結論**: 総合的な優位性%と、現在取るべきアクション。優位性が低い場合（60%未満など）や、テクニカルとファンダメンタルズが相反している場合は、**「今は待て (No Trade)」**と明確に警告してください。また、Buy/Sell Startの場合は、現在のボラティリティに基づき**「目安の待機時間」**および**「利確/損切りまでの目安時間（例: 2〜4時間程度）」**を推測して記載してください。
2. **根拠A**: テクニカルとファンダメンタルズの環境認識について。
3. **根拠B**: 勢いやトリガーについて。
4. **資金管理**: 勝率（優位性スコア）に基づいて厳密な資金管理を提示してください。
5. **注意点・リスク**: 指標発表やボラティリティへの警告など、最悪のシナリオを絶対に隠さずに提示すること。
"""
        try:
            return self._call_api(prompt)
        except Exception as e:
            return f"Gemini API エラー (リトライ失敗): {e}"
            
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call_api(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text
