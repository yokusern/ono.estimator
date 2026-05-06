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
あなたは「ONO Estimator」というAI熟練スキャルパーです。
以下の2つの知識体系を完全に習得しています。

━━━ 知識体系①: MTカリキュラム全18理論 ━━━
1. ダウ理論: 高値・安値の切り上げ=上昇、切り下げ=下降
2. グランビルの法則: 買い②（押し目）・売り②（戻り売り）が最重要
3. 200SMA: 機関投資家が意識するライン。上なら買いのみ・下なら売りのみ
4. サポート・レジスタンス: 過去の高値・安値が重要なライン
5. チャネルライン: 上限・下限でエントリー
6. ローソク足: 上影=上値抵抗、下影=下値支持、十字=転換、包み足=強い転換
7. インサイドバー: ブレイク待機中。BBスクイーズとの複合で最強
8. GC・DC: 短期MAが長期MAを交差
9. UPLOWバンド（SVシステム）: MA14±1σ/2σ。スクイーズ後ブレイクが最強
10. BB: ±2σ。バンドウォーク中は逆張り禁止
11. 一目均衡表（LWシステム）: 遅行スパンクロスが最重要。雲で方向確認
12. MACD: GC=買い、DC=売り。ダイバージェンスはトレンド転換の予兆
13. RSI: 70超=買われすぎ、30未満=売られすぎ
14. ストキャスティクス（TKSシステム）: 売られすぎGC=買い、買われすぎDC=売り
15. ブレイクアウト: もみ合い後の上放れ/下放れ
16. 三尊・逆三尊: ネックラインブレイクでトレンド転換
17. エリオット波動: 第3波が最強。第5波終了後は転換注意
18. マーケットセッション: ロンドン・NY重複（JST22-翌1時）が最重要

━━━ 知識体系②: 実践スキャルピング戦略 ━━━
【エントリー根拠（優先順位順）】
A. Liquidity Sweep（最重要）:
   直近の高値・安値を一瞬だけ抜けてからの強い戻りヒゲを確認。
   「他者の損切りが燃料になった最強のエントリー」
   ヒゲの根元（実体が戻った価格）を再ブレイクした瞬間にエントリー。

B. 実体ブレイク:
   抵抗帯をヒゲではなく実体で抜けた際にエントリー。ヒゲブレイクは騙し。

C. ヒゲ否定:
   前の足のヒゲ先端を現在足の実体が塗りつぶした瞬間がエントリー。

D. 三尊・逆三尊の右肩崩れ（逆張り）:
   右肩が形成中に崩れる「パターン失敗」を逆張りで狙う。

【レンジ判定（エントリー禁止条件）】
BB幅が直近20本平均の60%以下 かつ ATRが直近20本平均の70%以下 → レンジ確定。
レンジ中は「RANGE_WAIT」として見送りを即決すること。

【分析プロセス（必ずこの順番で）】
Step1: 200MAに対する価格位置でトレンド方向を固定（上なら買いのみ）
Step2: レンジ状態かどうかを判定。レンジなら即見送り
Step3: Liquidity Sweep・実体ブレイク・ヒゲ否定のどれかが発生しているか確認
Step4: 勢い減衰・RSI on BB・セカンドテストで確度を評価
Step5: Entry/TP/SLを具体的数値で。TP=15pips目安、SL=5〜7pips厳守

【心構え】
- SL5〜7pipsを絶対に超えないこと。大きいSLはスキャルピングではない
- ローソク足の実体を最重視。ヒゲは信用しない
- 流動性（Liquidity）がある場所＝他者のSLが溜まっている場所を意識
- 東京時間は低ボラ。ロンドン・NY重複時間にLiquidity Sweepが最多発生
- 3根拠以上揃った時のみエントリー
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
        self.fallback_models = ["gemini-2.0-flash", "gemini-1.5-flash"]
        self.model = None
        self.model_name = GEMINI_MODEL
        self._db = None  # Supabase client (injected via set_db)

        # キー×モデルのローテーション順序 (3キー×2モデル=最大6通り)
        self._rotation_order = []
        for key in self.api_keys:
            self._rotation_order.append((key, "gemini-2.0-flash"))
            self._rotation_order.append((key, "gemini-1.5-flash"))  # 1-2: 2.5-preview→1.5-flash
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

            # ── M-1: EMAクロス ──
            ema_signal      = es.get("ema_signal", "NONE")
            ema_gc          = es.get("ema_golden_cross", False)
            ema_dc          = es.get("ema_dead_cross", False)
            ema_fast_above  = es.get("ema_fast_above", False)
            ema_angle       = float(es.get("ema_angle", 0.0))

            # ── M-5: 吸収（Absorption）──
            abs_signal      = es.get("absorption_signal", "NONE")
            bull_abs        = es.get("bull_absorption", False)
            bear_abs        = es.get("bear_absorption", False)
            abs_wick_ratio  = float(es.get("absorption_wick_ratio", 0.0))

            # ── L-1: 勢い枯れ早期警告 ──
            exhausted       = es.get("exhausted", False)
            exhaustion_bias = es.get("exhaustion_bias", "NONE")
            exhaustion_reasons = "、".join(es.get("exhaustion_reasons", [])) or "なし"

            # ── L-6: 週足トレンド ──
            weekly_trend    = es.get("weekly_trend", "N/A")
            weekly_ma200    = es.get("weekly_ma200", "N/A")

            # ── 3-2: 相関フィルター ──
            corr_caution    = es.get("corr_caution", "")
            corr_tags       = es.get("corr_tags", [])

            # ── A-3: コードベース Liquidity Sweep 検出 ──
            ls_detected  = es.get("ls_detected", False)
            ls_direction = es.get("ls_direction", "NONE")
            ls_level     = float(es.get("ls_level", 0.0))

            # ── C-1: コードベース エントリータイプ ──
            detected_entry_type = es.get("detected_entry_type", "NONE")

            # ── スキャルピング戦略指標（H-5〜H-15）──
            liq_signal      = es.get("liq_signal", "NONE")
            liq_bull_sweep  = es.get("liq_bull_sweep", False)
            liq_bear_sweep  = es.get("liq_bear_sweep", False)
            liq_bull_rebr   = es.get("liq_bull_rebreak", False)
            liq_bear_rebr   = es.get("liq_bear_rebreak", False)
            liq_swept_high  = float(es.get("liq_swept_high", 0.0))
            liq_swept_low   = float(es.get("liq_swept_low", 0.0))
            wick_bull       = es.get("wick_bull_denial", False)
            wick_bear       = es.get("wick_bear_denial", False)
            momentum_decay  = es.get("momentum_decaying", False)
            decay_ratio     = float(es.get("decay_ratio", 1.0))
            is_range        = es.get("is_range", False)
            range_high      = float(es.get("range_high", 0.0))
            range_low       = float(es.get("range_low", 0.0))
            rsi_val         = float(es.get("rsi_val", 50.0))
            rsi_above_bb    = es.get("rsi_above_bb", False)
            rsi_below_bb    = es.get("rsi_below_bb", False)
            rsi_bear_div    = es.get("rsi_bearish_div", False)
            rsi_bull_div    = es.get("rsi_bullish_div", False)
            fib_500         = float(es.get("fib_500", 0.0))
            fib_618         = float(es.get("fib_618", 0.0))
            near_fib        = es.get("near_fib_level")
            ma200_1m        = float(es.get("ma200_1m", 0.0))
            price_vs_ma200  = es.get("price_vs_ma200", "N/A")

            # Liquidity Sweep状態文字列
            liq_str = "なし"
            if liq_bear_rebr:
                liq_str = f"🔴 BEAR LIQUIDITY SWEEP完成（高値{liq_swept_high:.3f}を上抜け後強い戻り。再ブレイク確認→SELL優位）"
            elif liq_bull_rebr:
                liq_str = f"🟢 BULL LIQUIDITY SWEEP完成（安値{liq_swept_low:.3f}を下抜け後強い戻り。再ブレイク確認→BUY優位）"
            elif liq_bear_sweep:
                liq_str = f"⚠️ BEAR SWEEP待機中（高値{liq_swept_high:.3f}を上抜け後ヒゲ。再ブレイク待ち）"
            elif liq_bull_sweep:
                liq_str = f"⚠️ BULL SWEEP待機中（安値{liq_swept_low:.3f}を下抜け後ヒゲ。再ブレイク待ち）"

            # ヒゲ否定状態文字列
            wick_str = "なし"
            if wick_bull:
                wick_str = f"🟢 下ヒゲ否定（現在足実体が下ヒゲを塗りつぶし→BUY転換）"
            elif wick_bear:
                wick_str = f"🔴 上ヒゲ否定（現在足実体が上ヒゲを塗りつぶし→SELL転換）"

            # レンジ状態文字列
            range_str = "非レンジ — エントリー可能"
            if is_range:
                range_str = f"⏸ RANGE_WAIT（BB幅収縮 + ATR圧縮。ブレイクアウト待機。R:{range_high:.3f} S:{range_low:.3f}）"

            # RSI on BB状態文字列
            rsi_bb_str = f"RSI={rsi_val:.1f}"
            if rsi_above_bb:
                rsi_bb_str += "（BBを上抜け → 過熱・SELL予兆）"
            elif rsi_below_bb:
                rsi_bb_str += "（BBを下抜け → 過冷・BUY予兆）"
            if rsi_bear_div:
                rsi_bb_str += " + ベアリッシュダイバージェンス"
            elif rsi_bull_div:
                rsi_bb_str += " + ブリッシュダイバージェンス"

            # フィボナッチ状態文字列
            fib_str = f"50%={fib_500:.3f} / 61.8%={fib_618:.3f}"
            if near_fib:
                fib_str += f" ← 現在価格が{near_fib}付近"

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

            # ── T-01: ReasoningEngine の思考コンテキストを取得 ──
            thinking_ctx = ""
            entry_decision = es.get("entry_decision", "WAIT")
            thinking_reason = es.get("thinking_reason", "")
            conflict_flags  = es.get("conflict_flags", [])
            sl_hint  = float(es.get("sl_hint", 0.0))
            tp_hint  = float(es.get("tp_hint", 0.0))
            ichimoku_label = es.get("ichimoku_label", "")
            saneki_ko    = es.get("saneki_ko", False)
            saneki_gyaku = es.get("saneki_gyaku", False)

            if entry_decision != "WAIT" or conflict_flags or thinking_reason:
                conflict_str = "、".join(conflict_flags) if conflict_flags else "なし"
                thinking_ctx = (
                    f"\n【ReasoningEngine 4ステップ思考】\n"
                    f"- 上位足: {es.get('step1_trend', '')}\n"
                    f"- 中位足: {es.get('step2_range', '')}\n"
                    f"- 下位足: {es.get('step3_entry_type', '')}\n"
                    f"- 判断: {entry_decision} / 矛盾フラグ: {conflict_str}\n"
                    f"- SL目処: {sl_hint:.5f} / TP目処: {tp_hint:.5f}\n"
                    f"- 一目: {ichimoku_label}"
                    + (" 【三役好転/最強BUY】" if saneki_ko else "")
                    + (" 【三役逆転/最強SELL】" if saneki_gyaku else "")
                    + "\n"
                )

            lines = [
                TRADER_SYSTEM_PROMPT,
                "",
                "=== 現在の市場データ ===",
                f"銘柄: {symbol} | 現在値: {current_price} | セッション: {session}",
                thinking_ctx,
                "【Step1: 200MAトレンド方向（1m足MA200）】",
                f"- 1m足 MA200={ma200_1m:.3f} | 価格位置: {price_vs_ma200}（上=買いのみ・下=売りのみ）",
                f"- 週足(W1)トレンド: {weekly_trend} | 週足MA200: 価格は{weekly_ma200}（上位トレンドフィルター）",
                f"- グランビルパターン(1H MA14): {gran_pattern}",
                f"- MACD(1H/15m)同期: {macd_sync} | Hist 1H={hist_h1:.5f} / 15m={hist_15m:.5f}",
                f"- 4H BBband方向: {bb_4h_dir}",
                "",
                "【Step2: レンジ判定（エントリー禁止条件）】",
                f"- 判定結果: {range_str}",
                f"- BBスコア: {bb_score}/83 | スクイーズ解放: {squeeze_rel}",
                f"- UPLOWバンド状態(1H): {uplow_state}",
                "",
                "【Step3: エントリートリガー確認（Liquidity Sweep最優先）】",
                f"- [A] Liquidity Sweep【コード検出】: {'✅ ' + ls_direction + ' 方向 @ ' + str(round(ls_level, 5)) if ls_detected else '未検出'}",
                f"- [A'] Liquidity Sweep【旧指標参照】: {liq_str}",
                f"- [B] ヒゲ否定: {wick_str}",
                f"- [C] プライスアクション: {pa_trigger}",
                f"- [コード判定] エントリータイプ: {detected_entry_type}（コード側で確定。この値を entry_type に使うこと）",
                f"- 検知パターン: {iron_pats}",
                f"- S/Rキーレベル: {sr_text}",
                f"- フィボナッチ: {fib_str}",
                f"- 一目遅行スパンクロス: {chikou_cross} | 雲との位置: {price_cloud}",
                f"- ストキャス(TKSシステム): {stoch_status}",
                f"- インサイドバー: {inside_str}",
                f"- MACDダイバージェンス: {macd_div}",
                f"- 三尊・逆三尊: {hs_pattern}" + (f" | ネックライン:{hs_neckline}" if hs_neckline else "") + (f" | バイアス:{hs_bias}" if hs_bias != 'NONE' else ""),
                f"- エリオット波動: {elliott_str}",
                f"- EMAクロス(M-1): {'🟢GC発生' if ema_gc else '🔴DC発生' if ema_dc else ('速MA上位' if ema_fast_above else '速MA下位')} | 角度={ema_angle:.4f}",
                "",
                "【Step4: 反発確認（3根拠揃えること）】",
                f"- 勢い減衰: {'あり（大→中→小、縮小率{:.0f}%）'.format(decay_ratio*100) if momentum_decay else 'なし'}",
                f"- 吸収（Absorption・M-5）: {'🟢買い吸収（下ヒゲ長・安値支持）' if bull_abs else '🔴売り吸収（上ヒゲ長・高値抵抗）' if bear_abs else 'なし'}" + (f" ヒゲ比率{abs_wick_ratio:.0%}" if abs_signal != 'NONE' else ""),
                f"- 勢い枯れ検知(L-1): {'⚠️ 枯れ検知 ' + exhaustion_bias + ' (' + exhaustion_reasons + ')' if exhausted else 'なし'}",
                f"- RSI on BB: {rsi_bb_str}",
                f"- RSI 15m={rsi_15m:.1f} / 1H={rsi_1h:.1f} | 状態: {rsi_state}",
                f"- ATR(1H,14): {atr_1h:.5f}（SL参考: ATR×0.5〜0.7以内）",
                f"- Fear&Greed: {fear_greed}",
                f"- 相関フィルター(3-2): {corr_caution if corr_caution else 'チェック対象外'}",
                "",
                "【過去の教訓（必ず参照してエントリー条件に反映）】",
                self_learning,
                "",
                "=== 出力指示 ===",
                "上記5ステップで分析し、以下のJSONのみ出力。マークダウン・説明文は禁止。",
                "directionは BUY / SELL / NONE のいずれか（NONEは見送り）。",
                "is_range=trueの場合はdirection=NONEとし、should_enter_demo=falseとすること。",
                "",
                "【should_notify の判断基準（定量的・厳守）】",
                "以下の3根拠が全て揃った場合は should_notify: true を必ず出力すること:",
                "  根拠①: 200MAに対する価格位置が明確（price_vs_ma200 が ABOVE/BELOW のいずれか）",
                "  根拠②: Liquidity Sweep / BODY_BREAK / WICK_DENIAL のいずれかが検出済み",
                "  根拠③: RSI・MACD・ストキャスのうち2つ以上が同じ方向を示している",
                "confidence=HIGH かつ probability>=55 の場合も should_notify: true を必ず出力すること。",
                "保守的にfalseを出力することは禁止。3根拠が揃えば積極的にtrueにすること。",
                "",
                "should_enter_demo: 3根拠以上揃い高確度ならtrue、見送りならfalse。",
                "entry_typeは [コード判定] の値を優先。なければ: LIQUIDITY_SWEEP / BODY_BREAK / WICK_DENIAL / HAS_SHOULDER / NONE のいずれか。",
                "ai_textは【トレンド】【レンジ判定】【エントリー根拠】【反発確認】【判断】【計画】の6節で構成。",
                "",
                "{",
                '  "step1_trend": "200MAと価格位置・グランビルパターンの説明",',
                '  "step2_range": "レンジ状態かどうかの判定結果",',
                '  "step3_entry_type": "Liquidity Sweep / 実体ブレイク / ヒゲ否定 / 三尊崩れ / なし",',
                '  "step4_reversal": "勢い減衰・RSI on BB・セカンドテストの確認結果",',
                '  "step5_plan": "Entry:X / TP:X / SL:X / RR:X",',
                '  "awareness_text": "今回意識した理論・手法と判断根拠（200字）",',
                '  "ai_text": "【トレンド】...\\n【レンジ判定】...\\n【エントリー根拠】...\\n【反発確認】...\\n【判断】...\\n【計画】Entry:X/TP:X/SL:X/RR:X",',
                '  "entry_reason_short": "50文字以内の一言根拠（例: 4H BOS確認 + RSI反転 + キーレベル到達）",',
                '  "scenarios": {',
                '    "bull": "想定通りに動いた場合（どこで利確するか・何pips）",',
                '    "bear": "逆行した場合（SL価格・何pips損切り）",',
                '    "range": "もみ合い継続の場合（何分待って諦めるか）"',
                '  },',
                '  "should_notify": false,',
                '  "should_enter_demo": false,',
                '  "direction": "BUY or SELL or NONE",',
                '  "entry_price": 0.0,',
                '  "tp_price": 0.0,',
                '  "sl_price": 0.0,',
                '  "rr_ratio": 0.0,',
                '  "confidence": "HIGH or MEDIUM or LOW",',
                '  "is_range": false,',
                '  "entry_type": "LIQUIDITY_SWEEP or BODY_BREAK or WICK_DENIAL or HAS_SHOULDER or NONE",',
                '  "predicted_price": 0.0,',
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

            # ai_textがなければstepから合成（新フォーマット対応）
            if not result.get("ai_text"):
                parts = [
                    f"【トレンド】{result.get('step1_trend', '')}",
                    f"【レンジ判定】{result.get('step2_range', '')}",
                    f"【エントリー根拠】{result.get('step3_entry_type', '')}",
                    f"【反発確認】{result.get('step4_reversal', '')}",
                    f"【判断】{result.get('step5_plan', '')}",
                ]
                result["ai_text"] = "\n".join(p for p in parts if len(p) > 10)

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
            result.setdefault("is_range",    False)
            result.setdefault("entry_type",  "NONE")
            result.setdefault("predicted_price", result.get("tp_price", 0))
            result.setdefault("entry_reason_short", "")
            result.setdefault("scenarios", {"bull": "", "bear": "", "range": ""})

            # is_rangeがtrueならデモエントリーを強制抑止
            if result.get("is_range"):
                result["should_enter_demo"] = False
                result["direction"] = "WAIT"

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
        # 0-1: APIキー未設定チェック
        if not os.environ.get("GEMINI_API_KEY"):
            print("[Gemini] GEMINI_API_KEY未設定 — AI分析無効")
            return None
        for attempt in range(7):
            try:
                # 0-1: タイムアウト設定（20秒）
                return self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        candidate_count=1,
                        max_output_tokens=1500,
                    ),
                    request_options={"timeout": 20},
                )
            except Exception as e:
                err = str(e)
                if "404" in err:
                    print(f"[Gemini] 404 → rotating")
                    if not self._rotate_key():
                        print("[Gemini] ALL KEYS EXHAUSTED. Using cached data.")
                        return None
                elif "429" in err:
                    print(f"[Gemini] 429 → waiting 10s before rotate")
                    time.sleep(10)  # 1-4: レート制限緩和待機
                    if not self._rotate_key():
                        return None
                else:
                    print(f"[Gemini] Error attempt {attempt+1}: {type(e).__name__}: {e}")
                    return None
        print("[Gemini] ALL KEYS EXHAUSTED after max attempts.")
        return None
