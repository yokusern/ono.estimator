import os
import json
import re
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

import google.generativeai as genai

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

TRADER_SYSTEM_PROMPT = """\
あなたは「ONO Estimator」というAI熟練トレーダーです。
株式会社advanceのMTカリキュラム全理論を習得しています。

【習得済み理論・全18項目】
1. ダウ理論: 高値・安値の切り上げ=上昇、切り下げ=下降、それ以外=レンジ
2. グランビルの法則: 移動平均線と価格の8パターン
   - 買い②（MA上向き・価格がMAに接近して反発）が最重要＝押し目買い
   - 売り②（MA下向き・価格がMAに接近して反落）が最重要＝戻り売り
3. 200SMA: 機関投資家が意識するライン。価格が上なら上昇相場、下なら下降相場
4. サポート・レジスタンス: 過去の高値・安値が重要なライン
5. チャネルライン: トレンドの上限・下限でエントリー
6. ローソク足: 上影=上値抵抗、下影=下値支持、十字=転換予兆、包み足=強い転換
7. インサイドバー: ブレイク待機中。BBスクイーズとの複合で最強
8. ゴールデンクロス・デッドクロス: 短期MAが長期MAを交差
9. UPLOWバンド（SVシステム）: MA14 ± 1σ/2σ/3σ
   - バンド外への乖離=逆張り候補、スクイーズ後のブレイク=最強シグナル
10. ボリンジャーバンド: ±2σで95.4%の価格が収まる
    - トレンド中のバンドウォークは追わない（逆張り禁止）
    - BBスクイーズ→ブレイクが最高確度
11. 一目均衡表（LWシステム）: 遅行スパンクロスが最重要
    - 遅行スパンが現在ローソクを上抜け=買い転換、雲の上=上昇相場
12. MACD: GC=買い、DC=売り。ダイバージェンスはトレンド転換の予兆
13. RSI: 70超=買われすぎ、30未満=売られすぎ。方向フィルター必須
14. ストキャスティクス（TKSシステム）:
    - 売られすぎ(20以下)でGC=買い、買われすぎ(80以上)でDC=売り
    - 上位足のトレンドと同方向のみ有効
15. ブレイクアウト: もみ合い後の上放れ=上昇、下放れ=下降
16. 三尊・逆三尊: ネックラインブレイクでトレンド転換
17. エリオット波動: 第3波が最長・最強。第5波終了後は転換注意
18. マーケットセッション: ロンドン・NY重複（JST22-翌1時）が最重要・最高ボラ

【分析プロセス（必ずこの順番で）】
Step1【上位足トレンド】D1/4HのダウとグランビルでTRENDを確認。200SMAの上下も。
Step2【ゾーン特定】1HのBBとUPLOWバンドで現在地を判定。スクイーズ中か、バンドウォーク中か。
Step3【トリガー確認】15m/5mでストキャスGC/DC、ローソク足、遅行スパンクロスを確認。
Step4【ファンダ確認】金利・ドル強弱・Fear&Greedで方向の裏付けを確認。
Step5【総合判断】BUY/SELL/見送り を断言。Entry/TP/SL/RRを具体的数値で。

【心構え】
- 揃っていない時は見送りが重要な判断。無理にエントリーしない
- 東京時間はボラが低い。ロンドン・NY重複時間を最重視
- 上位足と下位足が逆方向なら必ず見送り
- 3つ以上の根拠が揃った時だけエントリー判断する
- SLはATR×1.5以内、RR最低1.5以上
"""


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
        self._db = None  # Supabase client (injected via set_db)

        # キー×モデルのローテーション順序 (3キー×2モデル=最大6通り)
        self._rotation_order = []
        for key in self.api_keys:
            self._rotation_order.append((key, "gemini-2.0-flash"))
            self._rotation_order.append((key, "gemini-2.5-flash-preview"))
        self._rotation_index = 0

        if not self.api_keys:
            print("[Gemini] No API keys found. AI analysis disabled.")
            return
        self._init_model(self.api_keys[0], "gemini-2.0-flash")

    def set_db(self, db) -> None:
        """自己学習用にSupabaseクライアントを注入する"""
        self._db = db

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
        self._rotation_index += 1
        if self._rotation_index >= len(self._rotation_order):
            print("[Gemini] ALL KEYS EXHAUSTED. Using cached data.")
            self._rotation_index = 0
            return False
        key, model = self._rotation_order[self._rotation_index]
        print(f"[Gemini] Rotating → key#{self._rotation_index} model={model}")
        self._init_model(key, model)
        return True

    # ── 自己学習 ──────────────────────────────────────────────────

    def _get_ai_memory(self, symbol: str) -> str:
        """ai_memoryテーブルから過去の教訓を取得してプロンプト用文字列に変換"""
        if not self._db:
            return ""
        try:
            client = getattr(self._db, "client", None)
            if not client:
                return ""
            res = (
                client.table("ai_memory")
                .select("lesson, win_rate_at_time, applied_at")
                .in_("symbol", [symbol, "ALL"])
                .eq("is_active", True)
                .order("applied_at", desc=True)
                .limit(5)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return ""
            lines = ["【AIメモリ — 過去の教訓】"]
            for r in rows:
                wr = r.get("win_rate_at_time", 0)
                lesson = (r.get("lesson") or "")[:120]
                lines.append(f"- {lesson}（当時勝率{wr:.1f}%）")
            return "\n".join(lines)
        except Exception:
            return ""

    def generate_self_reflection(self, symbol: str, losses: list) -> Optional[str]:
        """直近の負けトレードを受け取り、AI自己反省文（日本語100字以内）を生成する"""
        if not self.model or not losses:
            return None
        try:
            loss_lines = []
            for loss in losses[:5]:
                loss_lines.append(
                    f"  - {loss.get('symbol','?')} {loss.get('direction','?')}"
                    f" entry={loss.get('entry_price', 0):.5f}"
                    f" exit={loss.get('exit_price', 0):.5f}"
                    f" pips={loss.get('pips_result', 0):.1f}"
                )
            prompt = (
                f"You are ONO Estimator AI. Analyze these recent losing trades for {symbol}:\n"
                + "\n".join(loss_lines)
                + "\n\n"
                "Write ONE concise Japanese lesson (max 120 chars) for future entry improvement.\n"
                "Focus on: what signal conditions to avoid, or what confirmation was missing.\n"
                "Output the lesson sentence ONLY. No JSON, no markdown, no numbering."
            )
            resp = self._call_api(prompt)
            if resp:
                lesson = resp.text.strip()[:200]
                if lesson:
                    return lesson
        except Exception as e:
            print(f"[Gemini] Reflection error for {symbol}: {e}")
        return None

    def save_ai_lesson(self, symbol: str, lesson: str, win_rate: float) -> bool:
        """生成した教訓をai_memoryテーブルに保存する"""
        if not self._db:
            return False
        try:
            client = getattr(self._db, "client", None)
            if not client:
                return False
            client.table("ai_memory").insert({
                "symbol": symbol,
                "lesson": lesson,
                "win_rate_at_time": win_rate,
                "is_active": True,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            print(f"[AIMemory] Saved lesson for {symbol}: {lesson[:60]}...")
            return True
        except Exception as e:
            print(f"[AIMemory] Save error: {e}")
            return False

    # ── 主分析 ────────────────────────────────────────────────────

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
            current_price = data.get("current_price", es.get("current_price", 0))

            # ── 基本シグナル ──
            session      = es.get("session", "Tokyo")
            macd_sync    = es.get("macd_sync", "N/A")
            hist_h1      = float(es.get("hist_h1", 0.0))
            hist_15m     = float(es.get("hist_15m", 0.0))
            bb_score     = int(es.get("bb_score", 0))
            bb_reasons   = "、".join(es.get("bb_reasons", [])) or "なし"
            squeeze_rel  = es.get("squeeze_released", False)
            band_walk    = es.get("band_walk", False)
            rsi_15m      = float(es.get("rsi_15m", 50.0))
            rsi_1h       = float(es.get("rsi_1h",  50.0))
            rsi_state    = es.get("rsi_state", "NEUTRAL")
            atr_1h       = float(es.get("atr_1h", 0.0))
            vol_regime   = es.get("vol_regime", "NORMAL")
            pa_trigger   = es.get("pa_trigger", "None")
            iron_pats    = "、".join(str(x) for x in es.get("iron_patterns", [])) or "なし"
            key_levels   = es.get("key_levels", {})
            fear_greed   = es.get("fear_greed", "不明")
            bb_4h_dir    = es.get("bb_4h_dir", "N/A")
            bb_15m_dir   = es.get("bb_15m_dir", "N/A")

            # ── 新指標（H-4〜H-7） ──
            gran_pattern  = es.get("granville_pattern", "なし")
            stoch_k       = float(es.get("stoch_k", 50.0))
            stoch_d       = float(es.get("stoch_d", 50.0))
            stoch_gc      = es.get("stoch_gc", False)
            stoch_dc      = es.get("stoch_dc", False)
            chikou_cross  = es.get("chikou_cross", "NONE")
            price_cloud   = es.get("price_vs_cloud", "N/A")
            uplow_state   = es.get("uplow_state", "INSIDE")

            # ── MEDIUM指標（M-1/M-2/M-4/M-5）──
            inside_bar      = es.get("inside_bar", False)
            inside_squeeze  = es.get("inside_bar_squeeze", False)
            macd_div        = es.get("macd_divergence", "None")
            hs_pattern      = es.get("hs_pattern", "なし")
            hs_neckline     = es.get("hs_neckline", 0.0)
            hs_bias         = es.get("hs_bias", "NONE")
            elliott_wave    = es.get("elliott_wave", "不明")
            elliott_wave3   = es.get("elliott_wave3", False)

            # インサイドバー状態文字列
            inside_str = "なし"
            if inside_bar and inside_squeeze:
                inside_str = "インサイドバー+BBスクイーズ（ブレイク待ち・最強）"
            elif inside_bar:
                inside_str = "インサイドバー（ブレイク待ち）"

            # エリオット波動状態文字列
            elliott_str = f"{elliott_wave}"
            if elliott_wave3:
                elliott_str += "（第3波検出 → 最強の推進波）"

            # サポレジ文字列
            sr_text = "N/A"
            if isinstance(key_levels, dict):
                r_list = key_levels.get("R", [])
                s_list = key_levels.get("S", [])
                sr_text = f"R: {r_list} / S: {s_list}" if (r_list or s_list) else "N/A"

            # ストキャス状態文字列
            stoch_status = "中立"
            if stoch_gc:   stoch_status = "GC（買いサイン）"
            elif stoch_dc: stoch_status = "DC（売りサイン）"
            elif stoch_k > 80: stoch_status = f"買われすぎ K={stoch_k:.1f}"
            elif stoch_k < 20: stoch_status = f"売られすぎ K={stoch_k:.1f}"
            else:          stoch_status = f"中立 K={stoch_k:.1f}"

            # 自己学習コンテキスト
            ai_memory_text = self._get_ai_memory(symbol)
            if ai_memory_text and feedback:
                self_learning = f"{ai_memory_text}\n\n【直近実績】\n{feedback}"
            elif ai_memory_text:
                self_learning = ai_memory_text
            elif feedback:
                self_learning = f"【直近実績】\n{feedback}"
            else:
                self_learning = "学習データ蓄積中。現在の市場データのみで判断。"

            lines = [
                TRADER_SYSTEM_PROMPT,
                "",
                "=== 現在の市場データ ===",
                f"銘柄: {symbol} | 現在値: {current_price} | セッション: {session}",
                "",
                "【Step1 上位足トレンド判定に使うデータ】",
                f"- MACD(1H/15m)同期方向: {macd_sync}",
                f"- MACD Hist 1H={hist_h1:.5f} / 15m={hist_15m:.5f}",
                f"- グランビルパターン(1H MA14): {gran_pattern}",
                f"- 4H BBband方向: {bb_4h_dir}",
                "",
                "【Step2 ゾーン判定に使うデータ】",
                f"- BBスコア: {bb_score}/83 | 詳細: {bb_reasons}",
                f"- スクイーズ解放: {squeeze_rel} | バンドウォーク: {band_walk}",
                f"- UPLOWバンド状態(1H MA14±σ): {uplow_state}",
                f"- ボラティリティレジーム: {vol_regime}",
                "",
                "【Step3 エントリートリガーに使うデータ】",
                f"- ストキャス(TKSシステム): {stoch_status}",
                f"- 一目遅行スパンクロス: {chikou_cross} | 雲との位置: {price_cloud}",
                f"- RSI 15m={rsi_15m:.1f} / 1H={rsi_1h:.1f} | 状態: {rsi_state}",
                f"- プライスアクション: {pa_trigger}",
                f"- 検知パターン: {iron_pats}",
                f"- S/Rキーレベル: {sr_text}",
                f"- インサイドバー(M-1): {inside_str}",
                f"- MACDダイバージェンス(M-2): {macd_div}",
                f"- 三尊・逆三尊(M-4): {hs_pattern}" + (f" | ネックライン:{hs_neckline}" if hs_neckline else "") + (f" | バイアス:{hs_bias}" if hs_bias != 'NONE' else ""),
                f"- エリオット波動(M-5): {elliott_str}",
                "",
                "【Step4 ファンダメンタル】",
                f"- Fear&Greed指標: {fear_greed}",
                f"- ATR(1H,14): {atr_1h:.5f}（SLの参考値、ATR×1.5以内）",
                "",
                "【過去の教訓（必ず参照）】",
                self_learning,
                "",
                "=== 出力指示 ===",
                "上記5ステップで分析し、以下のJSONのみ出力。マークダウン・説明文は禁止。",
                "directionは BUY / SELL / NONE のいずれか（NONEは見送り）。",
                "should_enter_demo: 3根拠以上揃い高確度ならtrue、見送りならfalse。",
                "ai_textは【トレンド】【ゾーン】【トリガー】【ファンダ】【判断】【計画】の6節で構成。",
                "",
                "{",
                '  "step1_trend": "ダウとグランビルによるトレンド判定",',
                '  "step2_zone": "BBとUPLOWバンドによるゾーン評価",',
                '  "step3_trigger": "ストキャス・一目・ローソク足のトリガー確認",',
                '  "step4_funda": "ファンダメンタルとテクニカルの一致度",',
                '  "step5_judgment": "BUY/SELL/見送りと根拠3点以上",',
                '  "awareness_text": "今回意識した理論と判断根拠を200字で日本語記述",',
                '  "ai_text": "【トレンド】...\\n【ゾーン】...\\n【トリガー】...\\n【ファンダ】...\\n【判断】...\\n【計画】Entry:X / TP:X / SL:X / RR:X",',
                '  "should_notify": false,',
                '  "should_enter_demo": false,',
                '  "direction": "BUY or SELL or NONE",',
                '  "entry_price": 0.0,',
                '  "tp_price": 0.0,',
                '  "sl_price": 0.0,',
                '  "rr_ratio": 0.0,',
                '  "confidence": "HIGH or MEDIUM or LOW",',
                '  "probability": 0',
                "}",
            ]
            prompt = "\n".join(lines)

            response = self._call_api(prompt)
            if not response:
                return None

            text = response.text
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if not json_match:
                print(f"[Gemini] Parse failed for {symbol}. Raw: {text[:100]}")
                return None

            result = json.loads(json_match.group(0))

            # ai_textがなければstepから合成
            if not result.get("ai_text"):
                parts = [
                    f"【トレンド】{result.get('step1_trend', '')}",
                    f"【ゾーン】{result.get('step2_zone', '')}",
                    f"【トリガー】{result.get('step3_trigger', '')}",
                    f"【ファンダ】{result.get('step4_funda', '')}",
                    f"【判断】{result.get('step5_judgment', '')}",
                ]
                result["ai_text"] = "\n".join(p for p in parts if p != "【トレンド】")

            # 後方互換正規化
            direction = result.get("direction", "NONE")
            if direction == "NONE":
                direction = "WAIT"
            result["direction"] = direction
            result.setdefault("signal_quality", result.get("confidence", "LOW"))
            result.setdefault("entry",  result.get("entry_price", 0))
            result.setdefault("sl",     result.get("sl_price", 0))
            result.setdefault("tp1",    result.get("tp_price", 0))
            result.setdefault("should_notify",     False)
            result.setdefault("should_enter_demo", False)

            if not result.get("ai_text") and not result.get("awareness_text"):
                print(f"[Gemini] Empty result for {symbol}")
                return None

            return result

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
                    print(f"[Gemini] 429 → rotating immediately (no wait)")
                    if not self._rotate_key():
                        return None
                else:
                    print(f"[Gemini] Error attempt {attempt+1}: {type(e).__name__}: {e}")
                    return None
        print("[Gemini] ALL KEYS EXHAUSTED after max attempts.")
        return None
