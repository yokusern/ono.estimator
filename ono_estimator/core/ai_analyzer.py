"""
GeminiAnalyzer — E3構造化出力 + 14RPMレートリミット + Supabaseキャッシュ
"""
import os, json, re, time, logging, traceback
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

E3_SUFFIX = """\n\n必ずこのJSONのみで返答（余分なテキスト禁止）:
{
  "direction": "BUY" or "SELL" or "WAIT",
  "probability": <0-100>,
  "expected_move_pips": <数値 or null>,
  "time_window": {"start": "<JST HH:MM>", "end": "<JST HH:MM>"},
  "hold_time_minutes": <数値 or null>,
  "entry": <価格 or null>,
  "tp1": <価格 or null>,
  "tp2": <価格 or null>,
  "sl": <価格 or null>,
  "basis": "<根拠100字以内>",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "ai_text": "【論理解説】...\\n【過去類似局面】...\\n【戦略】Entry:XXX / TP:XXX / SL:XXX"
}"""


class GeminiAnalyzer:
    _call_times: list = []
    RPM_LIMIT = 14
    MIN_INTERVAL = 60.0 / RPM_LIMIT

    def __init__(self, db=None):
        self.db = db
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[Gemini] GEMINI_API_KEY not set. AI disabled.")
            self.model = None
            return
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(GEMINI_MODEL)
            print(f"[Gemini] Configured: {GEMINI_MODEL}")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def _rate_limit(self):
        now = time.time()
        GeminiAnalyzer._call_times = [t for t in GeminiAnalyzer._call_times if now - t < 60]
        if len(GeminiAnalyzer._call_times) >= self.RPM_LIMIT:
            sleep_sec = 60 - (now - GeminiAnalyzer._call_times[0]) + 0.5
            if sleep_sec > 0:
                print(f"[Gemini] Rate limit: sleeping {sleep_sec:.1f}s")
                time.sleep(sleep_sec)
        if GeminiAnalyzer._call_times:
            elapsed = time.time() - GeminiAnalyzer._call_times[-1]
            if elapsed < self.MIN_INTERVAL:
                time.sleep(self.MIN_INTERVAL - elapsed)
        GeminiAnalyzer._call_times.append(time.time())

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=False,
    )
    def _call_api(self, prompt: str):
        self._rate_limit()
        return self.model.generate_content(prompt)

    def analyze_single(self, symbol: str, data: dict, feedback: str = "",
                       gemini_prompt_override: str = None) -> dict | None:
        if not self.model:
            return self._load_cache(symbol) or self._fallback()

        try:
            if gemini_prompt_override:
                prompt = gemini_prompt_override + E3_SUFFIX
            else:
                mtf = data.get("mtf", {})
                h1 = mtf.get("1h", {})
                m1 = mtf.get("1m", {})
                prompt = f"""Return ONLY JSON. Analyze {symbol} as a quantitative FX strategist.
[Data] 1m:Score={m1.get('score')} RSI={m1.get('rsi')} | 1h:Score={h1.get('score')} Layers={h1.get('aligned',0)}/5
[Engine] {h1.get('status','?')} {h1.get('emoji','⚪')} | TP1={h1.get('tp1',0)} TP2={h1.get('tp2',0)} SL={h1.get('sl',0)}
[History] {feedback or 'No data'}
{E3_SUFFIX}"""

            resp = self._call_api(prompt)
            if not resp:
                raise RuntimeError("API returned None")

            result = self._parse(resp.text)
            if result:
                self._save_cache(symbol, result)
                return result

            print(f"[Gemini] Parse failed {symbol}: {resp.text[:100]}")
            return self._load_cache(symbol) or self._fallback()

        except Exception as e:
            print(f"[Gemini] Error {symbol}: {e}")
            return self._load_cache(symbol) or self._fallback()

    def _parse(self, text: str) -> dict | None:
        try:
            text = re.sub(r"```json?\s*", "", text).replace("```", "")
            m = re.search(r"\{[\s\S]*\}", text)
            if not m:
                return None
            d = json.loads(m.group())
            if "direction" not in d:
                return None
            if not d.get("ai_text") and d.get("basis"):
                d["ai_text"] = (f"【論理解説】{d['basis']}\n"
                                f"【戦略】Entry:{d.get('entry','N/A')} / TP:{d.get('tp2','N/A')} / SL:{d.get('sl','N/A')}")
            return d
        except Exception:
            return None

    def _save_cache(self, symbol: str, result: dict):
        if not self.db:
            return
        try:
            self.db.client.table("analysis_cache").insert({"symbol": symbol, "result": result}).execute()
        except Exception:
            pass

    def _load_cache(self, symbol: str) -> dict | None:
        if not self.db:
            return None
        try:
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            res = (self.db.client.table("analysis_cache").select("result")
                   .eq("symbol", symbol).gte("created_at", cutoff)
                   .order("created_at", desc=True).limit(1).execute())
            if res.data:
                r = res.data[0]["result"]
                r["cached"] = True
                return r
        except Exception:
            pass
        return None

    def _fallback(self) -> dict:
        return {"direction": "WAIT", "probability": 0,
                "ai_text": "-- AI分析待機中 --", "basis": "", "cached": False}
