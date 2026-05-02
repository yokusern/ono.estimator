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
            # v1バージョンを明示的に使用し、安定性を確保
            self.model = genai.GenerativeModel(
                'models/gemini-1.5-flash-latest'
            )
            print("[Gemini] Batch Strategist Initialized (v1 mode)")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def batch_analyze(self, symbols_data: dict) -> dict:
        """全銘柄のデータを一括で分析し、相関を含めた戦略を生成"""
        if not self.model:
            return {sym: "AI Analysis Offline." for sym in symbols_data.keys()}

        # 8銘柄のサマリーを一つの文字列に統合
        data_summary = ""
        for sym, d in symbols_data.items():
            data_summary += f"--- {sym} ---\n"
            data_summary += f"Status: {d.get('status')}, Score: {d.get('score')}%\n"
            data_summary += f"Indicators: RSI={d.get('rsi')}, MACD={d.get('macd')}\n"
            data_summary += f"Context: {d.get('theme')}\n\n"

        prompt = f"""
あなたは伝説的なマルチアセット・ストラテジスト「ONO AI」です。
以下の8銘柄のテクニカルおよびファンダメンタルズデータを分析し、各銘柄の具体的なトレード戦略を生成してください。
リクエスト回数を節約するため、全ての回答を一つの有効なJSONオブジェクトとして返してください。

【マーケットデータ】
{data_summary}

【出力要件】
1. 各銘柄の「ai_text」を、プロの視点で論理的に記述（アクション、根拠、リスク）。
2. 銘柄間の相関（例: ドル高がゴールドや日経に与える影響）を考慮した全体戦略を「market_intelligence」に記述。

【出力形式】
{{
  "USDJPY": {{"ai_text": "..."}},
  "GOLD": {{"ai_text": "..."}},
  ...
  "market_intelligence": "現在の市場全体のテーマと相関分析の結果..."
}}
JSON以外のテキストは一切含めないでください。
"""
        try:
            response = self._call_api(prompt)
            # JSON部分を抽出
            import re
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {sym: "JSON Parsing Error." for sym in symbols_data.keys()}
        except Exception as e:
            print(f"[Gemini] Batch Analysis Error: {e}")
            return {sym: f"Analysis failed: {e}" for sym in symbols_data.keys()}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=15))
    def _call_api(self, prompt: str):
        return self.model.generate_content(prompt)
