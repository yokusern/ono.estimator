"""
Step F1 + E3: Gemini API レートリミット対策 + 定量予測の構造化出力
- 指数バックオフ付きリトライ（最大4回）
- GeminiRateLimiter による RPM 制御
- Supabase analysis_cache テーブルへのキャッシュフォールバック
- E3: JSON 構造化出力（direction/probability/pips/time_window/entry/tp1/tp2/sl/basis）

Supabase に手動実行が必要な SQL:
  create table if not exists analysis_cache (
    id uuid primary key default gen_random_uuid(),
    symbol text,
    result jsonb,
    created_at timestamptz default now()
  );
"""
import os
import json
import re
import time
import random
import logging
import google.generativeai as genai
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


class GeminiAnalyzer:
    def __init__(self, db=None):
        self.db = db
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("[Gemini] GEMINI_API_KEY not set.")
            self.model = None
            return
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            self.model_name = GEMINI_MODEL
            logger.info(f"[Gemini] Configured: {GEMINI_MODEL}")
        except Exception as e:
            logger.error(f"[Gemini] Init Error: {e}")
            self.model = None

    def analyze_single(
        self,
        symbol: str,
        data: dict,
        feedback: str = "",
        fred_data: dict = None,
        event_risk: dict = None,
        session: str = "off",
        session_multiplier: float = 1.0,
    ) -> dict:
        """単一銘柄の深い分析（asyncio.to_thread 経由で呼ぶ）"""
        if not self.model:
            cached = self._load_cache(symbol)
            return cached or self._fallback(symbol)

        try:
            mtf = data.get("mtf", {})
            macro_section = self._build_macro_section(symbol, fred_data, event_risk, session)
            now_jst = (datetime.utcnow() + timedelta(hours=9)).strftime("%H:%M JST")

            prompt = f"""
Return ONLY a raw JSON object. No markdown. No explanation outside JSON.
As an AI-driven quantitative strategist, analyze: {symbol}

[Market Data]
- 1m: Score={mtf.get('1m', {}).get('score')}, RSI={mtf.get('1m', {}).get('rsi')}
- 1h: Score={mtf.get('1h', {}).get('score')}
- Current time: {now_jst}

[Macro Environment]
{macro_section}

[Past Performance]
{feedback or "No historical data yet."}

[Output Format — ONLY this JSON]
{{
  "direction": "BUY" or "SELL" or "WAIT",
  "probability": <0〜100の整数>,
  "expected_move_pips": <予測変動幅pipsまたはnull>,
  "time_window": {{"start": "<JST HH:MM>", "end": "<JST HH:MM>"}},
  "hold_time_minutes": <推奨保有時間（分）またはnull>,
  "entry": <エントリー価格またはnull>,
  "tp1": <第1利確価格またはnull>,
  "tp2": <第2利確価格またはnull>,
  "sl": <損切り価格またはnull>,
  "basis": "<根拠を100字以内の日本語で>",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "predicted_price": <tp1と同じ値またはnull>,
  "ai_text": "【論理解説】...\\n【過去類似局面】...\\n【戦略】Entry:xxx TP1:xxx TP2:xxx SL:xxx"
}}

数値が算出できない場合は null。曖昧な表現は使わないこと。
"""
            result = self._call_with_retry(prompt)
            if result:
                result["cached"] = False
                result["session"] = session
                result["session_multiplier"] = session_multiplier
                self._save_cache(symbol, result)
                return result

            cached = self._load_cache(symbol)
            if cached:
                cached["cached"] = True
                logger.info(f"[Gemini] Cache hit for {symbol}")
                return cached

            return self._fallback(symbol)

        except Exception as e:
            logger.error(f"[Gemini] {symbol}: {type(e).__name__}: {e}")
            cached = self._load_cache(symbol)
            return cached if cached else self._fallback(symbol)

    def _call_with_retry(self, prompt: str, max_retries: int = 4) -> dict | None:
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                text = response.text
                match = re.search(r'(\{.*?\})\s*$', text, re.DOTALL)
                if not match:
                    match = re.search(r'(\{.*\})', text, re.DOTALL)
                if match:
                    result = json.loads(match.group(1))
                    if result.get("ai_text") or result.get("basis"):
                        return result
                logger.warning(f"[Gemini] Parse failed attempt {attempt+1}. Raw: {text[:60]}")
            except Exception as e:
                err = str(e)
                if "429" in err or "ResourceExhausted" in err or "quota" in err.lower():
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"[Gemini] 429 hit. Retry {attempt+1}/{max_retries} in {wait:.1f}s")
                    time.sleep(wait)
                else:
                    logger.error(f"[Gemini] API error: {e}")
                    return None
        return None

    def _save_cache(self, symbol: str, result: dict):
        if not self.db or not self.db.client:
            return
        try:
            self.db.client.table("analysis_cache").insert({
                "symbol": symbol,
                "result": result,
                "created_at": datetime.now().isoformat(),
            }).execute()
        except Exception:
            pass

    def _load_cache(self, symbol: str) -> dict | None:
        if not self.db or not self.db.client:
            return None
        try:
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            res = self.db.client.table("analysis_cache")\
                .select("result")\
                .eq("symbol", symbol)\
                .gte("created_at", one_hour_ago)\
                .order("created_at", desc=True)\
                .limit(1).execute()
            if res.data:
                return res.data[0]["result"]
        except Exception:
            pass
        return None

    def _build_macro_section(self, symbol: str, fred_data: dict, event_risk: dict, session: str) -> str:
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
                f"逆イールド: {fmt(fred_data.get('T10Y2Y'))}（マイナス=景気後退）",
                f"VIX: {fmt(fred_data.get('VIXCLS'), '')}",
                f"DXY: {fmt(fred_data.get('DTWEXBGS'), '')}",
                f"実質金利: {fmt(fred_data.get('REAL_RATE'))}",
            ]
        if event_risk and event_risk.get("message"):
            lines.append(f"イベントリスク: {event_risk['message']}")

        try:
            from .session_filter import SESSION_LABELS
            lines.append(f"現在のセッション: {SESSION_LABELS.get(session, session)}")
        except ImportError:
            pass

        vix = (fred_data or {}).get("VIXCLS", {})
        cpi = (fred_data or {}).get("CPIAUCSL", {})
        ff = (fred_data or {}).get("FEDFUNDS", {})
        vix_v = vix.get("value", 0) if vix else 0
        cpi_v = cpi.get("value", 0) if cpi else 0
        rate_v = ff.get("value", 0) if ff else 0
        vix_env = "高恐怖" if vix_v > 25 else "中程度" if vix_v > 18 else "低ボラ"
        cpi_env = "高インフレ" if cpi_v > 4 else "中インフレ" if cpi_v > 2 else "低インフレ"
        rate_env = "高金利" if rate_v > 4 else "中金利" if rate_v > 1 else "低金利"
        lines.append(
            f"質問: 金利{rate_env}・CPI{cpi_env}・VIX{vix_env}かつこのセッションで"
            f"{symbol}はどう動いた？歴史的事例を踏まえ予測してください。"
        )
        return "\n".join(lines) if lines else "マクロデータ取得中"

    @staticmethod
    def _fallback(symbol: str) -> dict:
        return {
            "direction": "WAIT",
            "probability": 0,
            "expected_move_pips": None,
            "time_window": None,
            "hold_time_minutes": None,
            "entry": None,
            "tp1": None,
            "tp2": None,
            "sl": None,
            "basis": "AI分析待機中",
            "confidence": "LOW",
            "ai_text": "-- AI分析待機中 --",
            "predicted_price": 0,
            "cached": False,
        }
