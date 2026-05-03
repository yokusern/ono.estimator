"""
GeminiAnalyzer v2 — マルチキーローテーション + モデルフォールバック + E3構造化出力
"""
import os, json, re, time, logging, traceback
from typing import Optional, List
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# ─── モデル優先順位 ───────────────────────────────────────────
MODEL_FALLBACK_ORDER = [
    os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

# ─── E3出力フォーマット ───────────────────────────────────────
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


def _load_api_keys() -> List[str]:
    """環境変数から複数Gemini APIキーを取得"""
    keys = []
    for i in range(1, 10):
        k = os.environ.get(f"GEMINI_API_KEY_{i}")
        if k:
            keys.append(k)
    single = os.environ.get("GEMINI_API_KEY")
    if single and single not in keys:
        keys.append(single)
    return keys


class GeminiAnalyzer:
    _call_times: list = []
    RPM_LIMIT = 14
    MIN_INTERVAL = 60.0 / RPM_LIMIT

    def __init__(self, db=None):
        self.db = db
        self._keys = _load_api_keys()
        self._key_idx = 0
        self._model_idx = 0
        self.model = None
        self._init_model()

    def _init_model(self):
        """現在のキーとモデルでGenAI初期化"""
        if not self._keys:
            print("[Gemini] No API keys found. AI disabled.")
            self.model = None
            return
        key = self._keys[self._key_idx % len(self._keys)]
        model_name = MODEL_FALLBACK_ORDER[self._model_idx % len(MODEL_FALLBACK_ORDER)]
        try:
            genai.configure(api_key=key)
            self.model = genai.GenerativeModel(model_name)
            print(f"[Gemini] key#{self._key_idx+1}/{len(self._keys)} model={model_name}")
        except Exception as e:
            print(f"[Gemini] Init error: {e}")
            self.model = None

    def _rotate_key(self, error_type: str = "EXHAUSTED"):
        """次のAPIキーへ切り替え。全キー枯渇時はモデルをフォールバック"""
        self._log_health(self._key_idx, error_type)
        self._key_idx += 1
        if self._key_idx >= len(self._keys):
            self._key_idx = 0
            self._model_idx += 1
            if self._model_idx >= len(MODEL_FALLBACK_ORDER):
                self._model_idx = 0
                print("[Gemini] All keys & models exhausted. Using cache.")
                self.model = None
                return
            print(f"[Gemini] All keys exhausted → fallback model: {MODEL_FALLBACK_ORDER[self._model_idx]}")
        self._init_model()

    def _log_health(self, key_idx: int, error_type: str):
        """system_healthテーブルへ記録"""
        if not self.db or not self.db.client:
            return
        try:
            model_name = MODEL_FALLBACK_ORDER[self._model_idx % len(MODEL_FALLBACK_ORDER)]
            self.db.client.table("system_health").insert({
                "api_key_index": key_idx,
                "status": "EXHAUSTED" if "exhaust" in error_type.lower() else "ERROR",
                "error_type": error_type[:200],
                "model_fallback": model_name,
            }).execute()
        except Exception:
            pass

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

    def _call_api_inner(self, prompt: str):
        self._rate_limit()
        return self.model.generate_content(prompt)

    def _extract_retry_after(self, err_str: str) -> float:
        """Retry-Afterヘッダーから待機秒数を抽出"""
        import re as _re
        m = _re.search(r'retry.?after[:\s]+(\d+)', err_str, _re.IGNORECASE)
        return float(m.group(1)) if m else 0.0

    def _call_with_failover(self, prompt: str, max_attempts: int = 4):
        """エラー種別ごとのリトライ戦略:
        - 404/モデル不存在 → 即次モデルへフォールバック (リトライなし)
        - 429/ResourceExhausted → Retry-After待機後、次のAPIキーへ
        - 500系/ネットワーク → 指数バックオフ最大3回
        """
        network_retries = 0
        attempt = 0
        while attempt < max_attempts:
            if not self.model:
                return None
            try:
                return self._call_api_inner(prompt)
            except Exception as e:
                err_str = str(e).lower()
                raw_err = str(e)

                # ── 404: モデル不存在 → 即フォールバック (リトライ不要) ──
                if "404" in err_str or "not found" in err_str or "model" in err_str and "not" in err_str:
                    print(f"[Gemini] 404 model error → fallback model: {raw_err[:80]}")
                    self._rotate_key("ModelNotFound")
                    attempt += 1
                    continue

                # ── 429: レート制限 → Retry-After待機 → キーローテーション ──
                elif "resource_exhausted" in err_str or "429" in err_str or "quota" in err_str:
                    wait = self._extract_retry_after(raw_err) or (2 ** attempt)
                    wait = min(wait, 60)
                    print(f"[Gemini] 429 exhausted → wait {wait:.0f}s → rotating key")
                    time.sleep(wait)
                    self._rotate_key("ResourceExhausted")
                    if not self.model:
                        return None
                    attempt += 1

                # ── 400: 不正リクエスト → リトライ不要 ──
                elif "400" in err_str or "invalid_argument" in err_str:
                    logger.warning(f"[Gemini] 400 invalid request (no retry): {raw_err[:80]}")
                    return None

                # ── 500系/ネットワーク → 指数バックオフ 最大3回 ──
                else:
                    network_retries += 1
                    if network_retries > 3:
                        logger.warning(f"[Gemini] Network error exceeded 3 retries: {raw_err[:80]}")
                        return None
                    wait = 2 ** (network_retries - 1)  # 1s, 2s, 4s
                    logger.warning(f"[Gemini] Network error (retry {network_retries}/3) wait {wait}s: {raw_err[:80]}")
                    time.sleep(wait)
                    attempt += 1

        return None

    def _parse_e3(self, text: str) -> Optional[dict]:
        """E3 JSON抽出"""
        try:
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return None

    def analyze_single(self, symbol: str, data: dict, feedback: str = "",
                       gemini_prompt_override: str = None) -> dict:
        if not self.model:
            cached = self._load_cache(symbol)
            return {**(cached or {}), **self._fallback(), "cached": bool(cached)}

        try:
            # AI memoryから学習内容を取得
            memory_context = self._get_ai_memory(symbol)

            if gemini_prompt_override:
                prompt = gemini_prompt_override
                if memory_context:
                    prompt += f"\n\n【過去の学習内容】\n{memory_context}"
                prompt += E3_SUFFIX
            else:
                mtf = data.get("mtf", {})
                layers = data.get("layers", {})
                price = data.get("price", 0)
                atr = data.get("atr", 0)

                prompt = f"""ONO Estimator — {symbol} 分析リクエスト

現在価格: {price:.5f}
ATR: {atr:.5f}

5-Layerスコア:
- SMC: {layers.get('smc', 0):.1f}
- Technical: {layers.get('technical', 0):.1f}
- Fundamental: {layers.get('fundamental', 0):.1f}
- Momentum: {layers.get('momentum', 0):.1f}
- Correlation: {layers.get('correlation', 0):.1f}

MTF整合:
{json.dumps(mtf, ensure_ascii=False, indent=2)}

{feedback}
"""
                if memory_context:
                    prompt += f"\n【AI学習メモ】\n{memory_context}\n"
                prompt += E3_SUFFIX

            response = self._call_with_failover(prompt)
            if not response:
                cached = self._load_cache(symbol)
                return {**(cached or {}), **self._fallback(), "cached": bool(cached)}

            raw_text = response.text
            parsed = self._parse_e3(raw_text)

            if parsed:
                result = {
                    "direction":          parsed.get("direction", "WAIT"),
                    "probability":        int(parsed.get("probability", 0)),
                    "expected_move_pips": parsed.get("expected_move_pips"),
                    "time_window":        parsed.get("time_window", {}),
                    "hold_time_minutes":  parsed.get("hold_time_minutes"),
                    "entry":              parsed.get("entry"),
                    "tp1":                parsed.get("tp1"),
                    "tp2":                parsed.get("tp2"),
                    "sl":                 parsed.get("sl"),
                    "basis":              parsed.get("basis", ""),
                    "confidence":         parsed.get("confidence", "LOW"),
                    "ai_text":            parsed.get("ai_text", raw_text[:500]),
                    "cached":             False,
                    "raw":                raw_text[:200],
                }
                self._save_cache(symbol, result)
                return result
            else:
                return {"ai_text": raw_text[:500], "direction": "WAIT",
                        "probability": 0, "cached": False}

        except Exception as e:
            logger.error(f"[Gemini] analyze_single error: {e}")
            cached = self._load_cache(symbol)
            return {**(cached or {}), **self._fallback(), "cached": True}

    def _get_ai_memory(self, symbol: str) -> str:
        """ai_memoryテーブルから最新の学習内容を取得"""
        if not self.db or not self.db.client:
            return ""
        try:
            res = self.db.client.table("ai_memory")\
                .select("lesson")\
                .eq("is_active", True)\
                .in_("symbol", [symbol, "ALL"])\
                .order("applied_at", desc=True)\
                .limit(3).execute()
            lessons = [r["lesson"] for r in (res.data or []) if r.get("lesson")]
            return "\n".join(lessons)
        except Exception:
            return ""

    def save_ai_lesson(self, symbol: str, lesson: str, win_rate: float):
        """AI反省をai_memoryに保存"""
        if not self.db or not self.db.client:
            return
        try:
            self.db.client.table("ai_memory").insert({
                "symbol": symbol,
                "lesson": lesson[:500],
                "win_rate_at_time": win_rate,
                "is_active": True,
            }).execute()
        except Exception as e:
            logger.warning(f"[AI Memory] Save error: {e}")

    def generate_self_reflection(self, symbol: str, losses: list) -> Optional[str]:
        """敗北シグナルを分析してAIが自己反省を生成"""
        if not self.model or not losses:
            return None
        try:
            loss_summary = "\n".join([
                f"- {l.get('direction','?')} @ {l.get('entry_price','?')} → {l.get('outcome','?')} ({l.get('pips_result',0):.1f} pips)"
                for l in losses[:5]
            ])
            prompt = f"""{symbol} の直近の負けトレードを分析し、なぜ外れたかを日本語100字以内で反省してください。
負けトレード:
{loss_summary}

出力: 反省文のみ（JSON不要、100字以内）"""
            resp = self._call_with_failover(prompt)
            if resp:
                return resp.text[:200]
        except Exception as e:
            logger.warning(f"[AI Reflection] Error: {e}")
        return None

    def _save_cache(self, symbol: str, result: dict):
        if not self.db or not self.db.client:
            return
        try:
            self.db.client.table("predictions").upsert({
                "symbol": symbol,
                "timeframe": "CACHE",
                "direction": result.get("direction", "WAIT"),
                "confidence": result.get("probability", 0),
                "ai_reasoning": result.get("ai_text", ""),
                "layer_scores": result,
            }, on_conflict="symbol,timeframe").execute()
        except Exception:
            pass

    def _load_cache(self, symbol: str) -> Optional[dict]:
        if not self.db or not self.db.client:
            return None
        try:
            res = self.db.client.table("predictions")\
                .select("*")\
                .eq("symbol", symbol)\
                .eq("timeframe", "CACHE")\
                .order("created_at", desc=True)\
                .limit(1).execute()
            if res.data:
                row = res.data[0]
                scores = row.get("layer_scores") or {}
                if isinstance(scores, str):
                    scores = json.loads(scores)
                return {**scores, "cached": True}
        except Exception:
            pass
        return None

    def _fallback(self) -> dict:
        return {
            "direction": "WAIT", "probability": 0, "confidence": "LOW",
            "ai_text": "-- AI分析待機中 --", "cached": False,
        }
