import os
import json
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import traceback

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

class GeminiAnalyzer:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[Gemini] GEMINI_API_KEY not set. AI analysis disabled.")
            self.model = None
            return
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            self.model_name = GEMINI_MODEL
            print(f"[Gemini] Engine Configured: {GEMINI_MODEL} (will verify on first use)")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def analyze_single(
        self,
        symbol: str,
        data: dict,
        feedback: str = "",
        fred_data: dict = None,
        event_risk: dict = None,
    ) -> dict:
        """単一銘柄に対して深い分析と自己学習を実行"""
        if not self.model:
            return None

        try:
            mtf = data.get("mtf", {})

            # ─── マクロ環境セクション ────────────────────────────
            macro_section = self._build_macro_section(symbol, fred_data, event_risk)

            prompt = f"""
Return ONLY a raw JSON object. No markdown. No explanation outside JSON.
As an AI-driven quantitative strategist that EVOLVES from past results, analyze: {symbol}

[Market Data]
- Short (1m): Score={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}
- Long (1h): Score={mtf.get('1h', {}).get('score')}, Theme={mtf.get('1h', {}).get('theme')}

[Macro Environment - Current]
{macro_section}

[Self-Learning Feedback (Your Past Performance)]
{feedback if feedback else "No historical data yet. Base analysis on market data only."}

[Requirement - Write in Japanese, ~200 chars per section]
1. 【論理解説】: Explain WHY using terms like Support-Resistance Flip, RSI divergence, Fakeout
2. 【過去類似局面】: Compare to a specific historical market period. 現在のマクロ環境（金利・CPI・VIX水準）に最も類似した過去の局面を挙げ、その時{symbol}がどう動いたか説明してください。
3. 【戦略】: Entry / TP (Take Profit) / SL (Stop Loss) as specific numbers

JSON Format (return ONLY this, no other text):
{{
  "ai_text": "【論理解説】...\\n【過去類似局面】...\\n【戦略】Entry:XXX / TP:XXX / SL:XXX",
  "predicted_price": 0.0,
  "probability": 0
}}
"""
            response = self._call_api(prompt)
            if not response:
                return None
            text = response.text

            json_match = re.search(r'(\{.*?\})\s*$', text, re.DOTALL)
            if not json_match:
                json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
                if result.get("ai_text"):
                    return result

            print(f"[Gemini] Parse failed for {symbol}. Raw: {text[:80]}")
            return None
        except Exception as e:
            print(f"[Gemini] Analysis failed for {symbol}: {type(e).__name__}: {e}")
            return None

    def _build_macro_section(self, symbol: str, fred_data: dict, event_risk: dict) -> str:
        """FREDデータとイベントリスクをプロンプト用テキストに変換"""
        lines = []

        if fred_data:
            def fmt(d, unit="%"):
                if not d:
                    return "N/A"
                sign = "+" if d.get("diff", 0) >= 0 else ""
                return f"{d['value']}{unit}（前回比 {sign}{d['diff']}{unit} {d.get('direction', '')}）"

            lines += [
                f"FF金利: {fmt(fred_data.get('FEDFUNDS'))}",
                f"米CPI: {fmt(fred_data.get('CPIAUCSL'))}",
                f"米失業率: {fmt(fred_data.get('UNRATE'))}",
                f"逆イールド(10Y-2Y): {fmt(fred_data.get('T10Y2Y'))}（マイナスは景気後退シグナル）",
                f"VIX: {fmt(fred_data.get('VIXCLS'), '')}（20以上でリスクオフ）",
                f"実効DXY: {fmt(fred_data.get('DTWEXBGS'), '')}（ドル強弱）",
                f"実質金利: {fmt(fred_data.get('REAL_RATE'))}（名目金利 - 期待インフレ）",
            ]

        if event_risk and event_risk.get("message"):
            lines.append(f"\nイベントリスク: {event_risk['message']}")

        if not lines:
            lines.append("マクロデータ取得中（FRED_API_KEY未設定または取得失敗）")

        # シンボル別の環境コンテキスト
        vix = (fred_data or {}).get("VIXCLS", {})
        cpi = (fred_data or {}).get("CPIAUCSL", {})
        ff = (fred_data or {}).get("FEDFUNDS", {})
        vix_val = vix.get("value", 0) if vix else 0
        cpi_val = cpi.get("value", 0) if cpi else 0
        rate_val = ff.get("value", 0) if ff else 0

        vix_env = "高恐怖" if vix_val > 25 else "中程度" if vix_val > 18 else "低ボラ"
        cpi_env = "高インフレ" if cpi_val > 4 else "中インフレ" if cpi_val > 2 else "低インフレ"
        rate_env = "高金利" if rate_val > 4 else "中金利" if rate_val > 1 else "低金利"

        lines.append(
            f"\n過去の類似局面質問: 金利{rate_env}・CPI{cpi_env}・VIX{vix_env}の環境で"
            f"{symbol}はどう動いた？歴史的事例を踏まえて予測してください。"
        )

        return "\n".join(lines)

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=6),
        reraise=True
    )
    def _call_api(self, prompt: str):
        if not self.model:
            return None
        return self.model.generate_content(prompt)
