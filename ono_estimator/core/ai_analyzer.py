"""
GeminiAnalyzer v3 — クロスローテーション + H-6リッチプロンプト + should_notify
"""
import os, json, re, time, logging, traceback
from typing import Optional, List
import google.generativeai as genai

logger = logging.getLogger(__name__)

# H-1: 廃止モデル(gemini-1.5-flash v1beta)を除去し2モデルのみに絞る
MODEL_FALLBACK_ORDER = ["gemini-2.0-flash", "gemini-2.5-flash-preview"]

# 旧フォーマット互換用 E3 プロンプト末尾（gemini_prompt_override 経路のみ使用）
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
  "signal_quality": "HIGH" or "MEDIUM" or "LOW",
  "should_notify": true or false,
  "ai_text": "【論理解説】...\\n【過去類似局面】...\\n【戦略】Entry:XXX / TP:XXX / SL:XXX"
}"""


def _load_api_keys() -> List[str]:
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
        """次のキーへ切替。H-1: キー×モデルのクロスローテーション（最大 keys×2 = 6通り）"""
        self._log_health(self._key_idx, error_type)
        self._key_idx += 1
        if self._key_idx >= len(self._keys):
            self._key_idx = 0
            self._model_idx += 1
            if self._model_idx >= len(MODEL_FALLBACK_ORDER):
                self._model_idx = 0
                print("[Gemini] ALL KEYS EXHAUSTED. Using cached data.")
                self.model = None
                return
            print(f"[Gemini] All keys exhausted → fallback model: {MODEL_FALLBACK_ORDER[self._model_idx]}")
        self._init_model()

    def _log_health(self, key_idx: int, error_type: str):
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
        m = re.search(r'retry.?after[:\s]+(\d+)', err_str, re.IGNORECASE)
        return float(m.group(1)) if m else 0.0

    def _call_with_failover(self, prompt: str, max_attempts: int = 4):
        """H-1: 404→即フォールバック / 429→Retry-After待機+キーローテ / 500→指数バックオフ"""
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

                if "404" in err_str or "not found" in err_str:
                    print(f"[Gemini] 404 model error → fallback: {raw_err[:80]}")
                    self._rotate_key("ModelNotFound")
                    attempt += 1

                elif "resource_exhausted" in err_str or "429" in err_str or "quota" in err_str:
                    wait = self._extract_retry_after(raw_err) or (2 ** attempt)
                    wait = min(wait, 60)
                    print(f"[Gemini] 429 exhausted → wait {wait:.0f}s → rotating key")
                    time.sleep(wait)
                    self._rotate_key("ResourceExhausted")
                    if not self.model:
                        return None
                    attempt += 1

                elif "400" in err_str or "invalid_argument" in err_str:
                    logger.warning(f"[Gemini] 400 invalid (no retry): {raw_err[:80]}")
                    return None

                else:
                    network_retries += 1
                    if network_retries > 3:
                        logger.warning(f"[Gemini] Network error exceeded 3 retries: {raw_err[:80]}")
                        return None
                    wait = 2 ** (network_retries - 1)
                    logger.warning(f"[Gemini] Network error (retry {network_retries}/3) wait {wait}s: {raw_err[:80]}")
                    time.sleep(wait)
                    attempt += 1
        return None

    def _parse_e3(self, text: str) -> Optional[dict]:
        try:
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return None

    def _build_rich_prompt(self, symbol: str, es: dict, feedback: str, memory_context: str) -> str:
        """H-6: リッチプロンプト生成"""
        key_levels = es.get("key_levels", {})
        if isinstance(key_levels, dict):
            R = key_levels.get("R", [])
            S = key_levels.get("S", [])
            kl_str = f"R: {R} / S: {S}" if (R or S) else "N/A"
        else:
            kl_str = str(key_levels)

        bb_reasons = es.get("bb_reasons", [])
        iron_patterns = es.get("iron_patterns", [])

        return f"""You are ONO Estimator — an elite FX/commodity quantitative analyst.
Vague or hedging analysis is UNACCEPTABLE. Cite specific numbers. Call the trade or explain exactly why not.

━━━ SYMBOL: {symbol} | Price: {es.get('current_price', 0)} | Session: {es.get('session', 'Unknown')} ━━━

=== TECHNICAL ENGINE OUTPUT ===

[Environment — D1/4H]
- Trend: {es.get('env_trend', 'N/A')} | Dow Theory: {es.get('dow_trend', 'N/A')} | 200SMA: {es.get('sma200_pos', 'N/A')}
- 4H BB Dir: {es.get('bb_4h_dir', 'N/A')} | D1 BB Dir: {es.get('bb_d1_dir', 'N/A')}

[Momentum — 1H/15m]
- MACD Sync: {es.get('macd_sync', 'N/A')} | Hist H1={es.get('hist_h1', 0):.5f} / 15m={es.get('hist_15m', 0):.5f}
- BB Score: {es.get('bb_score', 0)}/83 | BB Details: {bb_reasons}
- Squeeze Released: {es.get('squeeze_released', False)} | Band Walk: {es.get('band_walk', False)}
- RSI 15m={es.get('rsi_15m', 50):.1f} / 1H={es.get('rsi_1h', 50):.1f} | State: {es.get('rsi_state', 'NEUTRAL')}
- ATR(1H,14): {es.get('atr_1h', 0):.5f}
- Volatility Regime: {es.get('vol_regime', 'NORMAL')} ({es.get('vol_ratio', 1.0):.2f}x)

[Trigger — 5m/15m]
- Price Action: {es.get('pa_trigger', 'None')}
- Iron Patterns: {iron_patterns}
- Key S/R Levels: {kl_str}

[Fundamentals & Macro]
- Macro Direction: {es.get('funda_dir', 'NEUTRAL')} | Reason: {es.get('funda_reason', 'N/A')}
- Fear & Greed: {es.get('fear_greed', 'Unknown')}
- Session: Tokyo=0-8UTC(低ボラ) London=8-16UTC NY_Overlap=13-16UTC(最高ボラ) NY=16-21UTC
- Iron Clad (Tech+Funda一致): {es.get('is_iron_clad', False)}

[Self-Learning]
{feedback or "学習データ蓄積中。現在の市場データのみで判断すること。"}
{("\\n【AI学習メモ】\\n" + memory_context) if memory_context else ""}

=== ANALYSIS REQUIREMENTS（全て必須・日本語） ===

【ファンダ分析】(150-250字)
- 現在のマクロ環境、金利・ドル強弱・リスクオンオフを具体的に述べる
- Fear&Greedの数値を引用し、市場センチメントを説明する
- "データなし"は不可。通貨ペアの特性から推測して方向感を断言する

【テクニカル分析】(150-250字)
- BB Score={es.get('bb_score', 0)}/83 の内訳と意味を必ず説明する
- RSI={es.get('rsi_15m', 50):.1f}、MACD Hist={es.get('hist_15m', 0):.5f} を具体的に引用する
- 検知されたパターン・PAが何を示しているか説明する
- S/Rレベルと現在価格の位置関係を述べる

【総合判断】(150-250字)
- BB/テクニカルコンフルエンス/ファンダの3軸で評価し、エントリー可否を断言する
- 「様子見」の場合も「何が揃えばエントリーできるか」を具体的に述べる
- AIが「ここだ」と判断した場合は should_notify=true を設定する
  スコアが低くても、局面の質が高いと判断したら迷わず true にすること

【戦略】
- Entry/TP/SL は具体的な価格を記載（"〜付近"は不可）
- ATR={es.get('atr_1h', 0):.5f} を参考にSLを設定する
- RR比を計算して示す

=== OUTPUT: JSONのみ。マークダウン・コードブロック禁止 ===
{{
  "direction": "BUY or SELL or WAIT",
  "probability": 0,
  "ai_text": "【ファンダ分析】...\\n【テクニカル分析】...\\n【総合判断】...\\n【戦略】Entry:X / TP:X / SL:X / RR:X",
  "entry_price": 0.0,
  "sl_price": 0.0,
  "tp_price": 0.0,
  "rr_ratio": 0.0,
  "signal_quality": "HIGH or MEDIUM or LOW",
  "should_notify": true or false
}}"""

    def analyze_single(self, symbol: str, data: dict, feedback: str = "",
                       gemini_prompt_override: str = None,
                       engine_signals: dict = None) -> dict:
        if not self.model:
            cached = self._load_cache(symbol)
            return {**(cached or {}), **self._fallback(), "cached": bool(cached)}

        try:
            memory_context = self._get_ai_memory(symbol)
            es = engine_signals or {}

            if gemini_prompt_override:
                prompt = gemini_prompt_override
                if memory_context:
                    prompt += f"\n\n【過去の学習内容】\n{memory_context}"
                prompt += E3_SUFFIX
            elif engine_signals:
                prompt = self._build_rich_prompt(symbol, es, feedback, memory_context)
            else:
                # レガシーフォールバックプロンプト
                mtf    = data.get("mtf", {})
                price  = data.get("price", 0)
                atr    = data.get("atr", 0)
                layers = data.get("layers", {})
                prompt = f"""ONO Estimator — {symbol} 分析リクエスト
現在価格: {price}
ATR: {atr}
5-Layerスコア: {json.dumps(layers, ensure_ascii=False)}
MTF: {json.dumps(mtf, ensure_ascii=False, indent=2)[:500]}
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
                result = self._normalize_result(parsed, raw_text)
                self._save_cache(symbol, result)
                return result
            else:
                return {**self._fallback(), "ai_text": raw_text[:500], "cached": False}

        except Exception as e:
            logger.error(f"[Gemini] analyze_single error: {e}")
            cached = self._load_cache(symbol)
            return {**(cached or {}), **self._fallback(), "cached": True}

    def _normalize_result(self, parsed: dict, raw_text: str) -> dict:
        """新旧両フォーマットを統一されたresultに変換"""
        # エントリー/SL/TPの正規化（新旧両フォーマット対応）
        entry = parsed.get("entry_price") or parsed.get("entry")
        sl    = parsed.get("sl_price") or parsed.get("sl")
        tp1   = parsed.get("tp_price") or parsed.get("tp1")
        tp2   = parsed.get("tp2")
        signal_quality = parsed.get("signal_quality", parsed.get("confidence", "LOW"))
        return {
            "direction":          parsed.get("direction", "WAIT"),
            "probability":        int(parsed.get("probability", 0)),
            "expected_move_pips": parsed.get("expected_move_pips"),
            "time_window":        parsed.get("time_window", {}),
            "hold_time_minutes":  parsed.get("hold_time_minutes"),
            "entry":              entry,
            "tp1":                tp1,
            "tp2":                tp2,
            "sl":                 sl,
            "rr_ratio":           parsed.get("rr_ratio"),
            "basis":              parsed.get("basis", ""),
            "confidence":         signal_quality,
            "signal_quality":     signal_quality,
            "should_notify":      bool(parsed.get("should_notify", False)),
            "ai_text":            parsed.get("ai_text", raw_text[:500]),
            "cached":             False,
            "raw":                raw_text[:200],
        }

    def _get_ai_memory(self, symbol: str) -> str:
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
            "signal_quality": "LOW", "should_notify": False,
            "ai_text": "-- AI分析待機中 --", "cached": False,
        }
