import os
import json
import re
import time
import traceback
import google.generativeai as genai

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

class GeminiAnalyzer:
    def __init__(self):
        self.api_keys = [
            k for k in [
                os.environ.get("GEMINI_API_KEY", ""),
                os.environ.get("GEMINI_API_KEY_2", ""),
                os.environ.get("GEMINI_API_KEY_3", ""),
            ] if k
        ]
        self.fallback_models = ["gemini-2.0-flash", "gemini-2.5-flash-preview"]
        self.model = None
        self.model_name = GEMINI_MODEL

        if not self.api_keys:
            print("[Gemini] No API keys found. AI analysis disabled.")
            return
        self._init_model(self.api_keys[0], GEMINI_MODEL)

    def _init_model(self, api_key: str, model_name: str):
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name)
            self.model_name = model_name
            print(f"[Gemini] Configured: {model_name}")
        except Exception as e:
            print(f"[Gemini] Init Error: {e}")
            self.model = None

    def _rotate_key(self) -> bool:
        for model in self.fallback_models:
            for key in self.api_keys:
                try:
                    genai.configure(api_key=key)
                    self.model = genai.GenerativeModel(model)
                    self.model_name = model
                    print(f"[Gemini] Rotated to model={model}")
                    return True
                except Exception:
                    continue
        self.model = None
        return False

    def analyze_single(
        self,
        symbol: str,
        data: dict,
        feedback: str = "",
        engine_signals: dict = None,
    ) -> dict:
        if not self.model:
            return None
        try:
            es = engine_signals or {}
            current_price = data.get("current_price", 0)

            env_trend    = es.get("env_trend", "N/A")
            dow_trend    = es.get("dow_trend", "N/A")
            sma200_pos   = es.get("sma200_pos", "N/A")
            bb_4h_dir    = es.get("bb_4h_dir", "N/A")
            bb_d1_dir    = es.get("bb_d1_dir", "N/A")
            macd_sync    = es.get("macd_sync", "N/A")
            hist_h1      = float(es.get("hist_h1", 0.0))
            hist_15m     = float(es.get("hist_15m", 0.0))
            bb_score     = int(es.get("bb_score", 0))
            bb_reasons   = ", ".join(es.get("bb_reasons", [])) or "なし"
            squeeze_rel  = es.get("squeeze_released", False)
            band_walk    = es.get("band_walk", False)
            rsi_15m      = float(es.get("rsi_15m", 0.0))
            rsi_1h       = float(es.get("rsi_1h", 0.0))
            rsi_state    = es.get("rsi_state", "NEUTRAL")
            atr_1h       = float(es.get("atr_1h", 0.0))
            vol_regime   = es.get("vol_regime", "NORMAL")
            vol_ratio    = float(es.get("vol_ratio", 1.0))
            pa_trigger   = es.get("pa_trigger", "None")
            iron_pats    = ", ".join(es.get("iron_patterns", [])) or "なし"
            key_levels   = es.get("key_levels", "N/A")
            funda_dir    = es.get("funda_dir", "NEUTRAL")
            funda_reason = es.get("funda_reason", "No data")
            fear_greed   = es.get("fear_greed", "Unknown")
            is_iron      = es.get("is_iron_clad", False)
            session      = es.get("session", "Unknown")
            fb           = feedback or "学習データ蓄積中。現在の市場データのみで判断すること。"

            lines = [
                "You are ONO Estimator — an elite FX/commodity quantitative analyst.",
                "Vague or hedging analysis is UNACCEPTABLE. Cite specific numbers.",
                "",
                f"SYMBOL: {symbol} | Price: {current_price} | Session: {session}",
                "",
                "=== TECHNICAL ENGINE OUTPUT ===",
                "",
                "[Environment — D1/4H]",
                f"- Trend: {env_trend} | Dow: {dow_trend} | 200SMA: {sma200_pos}",
                f"- 4H BB Dir: {bb_4h_dir} | D1 BB Dir: {bb_d1_dir}",
                "",
                "[Momentum — 1H/15m]",
                f"- MACD Sync: {macd_sync} | Hist H1={hist_h1:.5f} / 15m={hist_15m:.5f}",
                f"- BB Score: {bb_score}/83 | BB Details: {bb_reasons}",
                f"- Squeeze Released: {squeeze_rel} | Band Walk: {band_walk}",
                f"- RSI 15m={rsi_15m:.1f} / 1H={rsi_1h:.1f} | State: {rsi_state}",
                f"- ATR(1H,14): {atr_1h:.5f}",
                f"- Volatility Regime: {vol_regime} ({vol_ratio:.2f}x)",
                "",
                "[Trigger — 5m/15m]",
                f"- Price Action: {pa_trigger}",
                f"- Iron Patterns: {iron_pats}",
                f"- Key S/R Levels: {key_levels}",
                "",
                "[Fundamentals & Macro]",
                f"- Macro Direction: {funda_dir} | Reason: {funda_reason}",
                f"- Fear & Greed: {fear_greed}",
                "- Session: Tokyo=0-8UTC London=8-16UTC NY_Overlap=13-16UTC(最高ボラ) NY=16-21UTC",
                f"- Iron Clad: {is_iron}",
                "",
                "[Self-Learning]",
                fb,
                "",
                "=== ANALYSIS REQUIREMENTS（全て必須・日本語） ===",
                "",
                "【ファンダ分析】150-250字",
                "- マクロ環境・金利・ドル強弱・リスクオンオフを具体的に述べる",
                "- Fear&Greedの数値を引用してセンチメントを説明する",
                "- 方向感を断言すること",
                "",
                "【テクニカル分析】150-250字",
                f"- BB Score={bb_score}/83 の内訳と意味を必ず説明する",
                f"- RSI={rsi_15m:.1f}、MACD Hist={hist_15m:.5f} を具体的に引用する",
                "- 検知パターン・PAが何を示すか説明する",
                "- S/Rと現在価格の位置関係を述べる",
                "",
                "【総合判断】150-250字",
                "- BB/テクニカル/ファンダの3軸で評価してエントリー可否を断言する",
                "- AIが今が機会と判断した場合は should_notify=true にすること",
                "",
                "【戦略】",
                "- Entry/TP/SLは具体的な価格（付近は不可）",
                f"- ATR={atr_1h:.5f} を参考にSLを設定する",
                "- RR比を計算して示す",
                "",
                "=== OUTPUT: JSONのみ。マークダウン禁止 ===",
                '{',
                '  "ai_text": "【ファンダ分析】...\\n【テクニカル分析】...\\n【総合判断】...\\n【戦略】Entry:X/TP:X/SL:X/RR:X",',
                '  "predicted_price": 0.0,',
                '  "probability": 0,',
                '  "entry_price": 0.0,',
                '  "sl_price": 0.0,',
                '  "tp_price": 0.0,',
                '  "rr_ratio": 0.0,',
                '  "signal_quality": "HIGH or MEDIUM or LOW",',
                '  "should_notify": false',
                '}',
            ]
            prompt = "\n".join(lines)

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
            traceback.print_exc()
            return None

    def _call_api(self, prompt: str):
        if not self.model:
            return None
        for attempt in range(7):
            try:
                return self.model.generate_content(prompt)
            except Exception as e:
                err = str(e)
                if "404" in err:
                    print(f"[Gemini] 404 → rotating")
                    if not self._rotate_key():
                        print("[Gemini] ALL KEYS EXHAUSTED. Using cached data.")
                        return None
                elif "429" in err:
                    wait = min(2 ** attempt, 16)
                    print(f"[Gemini] 429 → wait {wait}s → rotating")
                    time.sleep(wait)
                    if not self._rotate_key():
                        print("[Gemini] ALL KEYS EXHAUSTED. Using cached data.")
                        return None
                else:
                    print(f"[Gemini] Error attempt {attempt+1}: {type(e).__name__}: {e}")
                    return None
        print("[Gemini] ALL KEYS EXHAUSTED after max attempts.")
        return None