"""
Notifier — H-4: シグナルキーデバウンス（時間制限なし、同一シグナルのみ防止）
           H-9: AI主導通知バッジ（🟢HIGH / 🟡MEDIUM / 🔵AI JUDGMENT CALL）
"""
import os
import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, db=None):
        self.db = db
        self.webhooks = {
            "SV":  os.environ.get("DISCORD_WEBHOOK_SV"),
            "LW":  os.environ.get("DISCORD_WEBHOOK_LW"),
            "TKS": os.environ.get("DISCORD_WEBHOOK_TKS"),
            "AI":  os.environ.get("DISCORD_WEBHOOK_AI"),
        }
        self.default_webhook = (
            os.environ.get("DISCORD_WEBHOOK_AI") or
            os.environ.get("DISCORD_WEBHOOK_URL")
        )
        # Phase 1-1: LINE Messaging API (LINE Notify は2025年3月末廃止済み)
        self.line_channel_token = os.environ.get("LINE_CHANNEL_TOKEN")
        self.line_user_id       = os.environ.get("LINE_USER_ID")
        self.session = requests.Session()
        # Phase 4-4: Supabase ログ連続失敗カウンター
        self._notif_log_fail_count = 0
        # B-1: シグナルキー + タイムスタンプ管理（30分窓デバウンス）
        self._last_signal_key: dict = {}   # {sym: (key, timestamp)}

    # ─── H-4: シグナルキー生成 ─────────────────────────────────
    def _make_signal_key(self, symbol: str, direction: str, price: float) -> str:
        """銘柄の価格精度に合わせてキーを生成する。同一価格帯・方向の連続発火を防ぐ。"""
        rounding = {
            "USDJPY=X": 2, "AUDJPY=X": 2, "EURUSD=X": 4,
            "EURJPY=X": 2, "GC=F": 0, "SI=F": 2,
            "BTC-USD": -2, "^N225": 0
        }
        r = rounding.get(symbol, 2)
        return f"{symbol}_{direction}_{round(price, r)}"

    # ─── 通知判定 ─────────────────────────────────────────────
    def notify_if_needed(
        self,
        symbol: str,
        result,
        ai_data: dict,
        current_price: float,
        session: str = "off",
        event_risk: dict = None,
    ):
        """H-9: スコア閾値 or AI主導(should_notify=true)で通知"""
        direction      = ai_data.get("direction", "WAIT")
        probability    = ai_data.get("probability", 0)
        signal_quality = ai_data.get("signal_quality", ai_data.get("confidence", "LOW"))
        should_notify  = ai_data.get("should_notify", False)
        score = getattr(result, "win_rate_score", 0) if result else 0

        # WAIT かつ AI も通知不要なら終了
        if direction == "WAIT" and not should_notify:
            return

        # 重要指標2時間以内は抑制
        if event_risk and event_risk.get("critical"):
            logger.info(f"[Notifier] {symbol} suppressed: event within 2h")
            return

        # B-1: 同一シグナルキーかつ30分未満ならスキップ。方向反転は即時許可
        sig_key = self._make_signal_key(symbol, direction, current_price)
        import time as _time
        last_key, last_ts = self._last_signal_key.get(symbol, (None, 0))
        elapsed = _time.time() - last_ts
        if last_key == sig_key and elapsed < 1800:   # 30分以内の同一シグナルはスキップ
            return
        # 方向が反転した場合は時間に関わらず通知（旧方向のキーと比較）
        prev_dir = (last_key or "").split("_")[1] if last_key else ""
        if last_key != sig_key and prev_dir and prev_dir != direction and elapsed < 1800:
            pass  # 方向反転 → 即時通知
        self._last_signal_key[symbol] = (sig_key, _time.time())

        # H-9: バッジ選択
        if signal_quality == "HIGH" and probability >= 75:
            badge = "🟢 HIGH QUALITY SIGNAL"
        elif signal_quality == "MEDIUM" or probability >= 55:
            badge = "🟡 MEDIUM QUALITY SIGNAL"
        elif should_notify:
            badge = "🔵 AI JUDGMENT CALL"
        else:
            badge = "⚪ SIGNAL"

        ai_data_aug = {**ai_data, "_badge": badge}

        if self.line_channel_token and self.line_user_id:
            self._send_line(symbol, score, ai_data_aug, current_price, session)

        systems = result.base_system.split(",") if hasattr(result, "base_system") else ["AI"]
        for sys_name in systems:
            webhook = self.webhooks.get(sys_name) or self.default_webhook
            if webhook:
                self._send_discord(webhook, symbol, sys_name, score, ai_data_aug, current_price, session)

        self._log_notification(symbol, direction, score)

    def _log_notification(self, symbol: str, direction: str, score: float):
        if self.db and self.db.client:
            try:
                self.db.client.table("notification_logs").insert({
                    "symbol": symbol,
                    "direction": direction,
                    "score": score,
                    "notified_at": datetime.now().isoformat(),
                }).execute()
                self._notif_log_fail_count = 0
            except Exception as e:
                self._notif_log_fail_count += 1
                logger.warning(f"[DB] notification log failed ({self._notif_log_fail_count}回): {e}")
                if self._notif_log_fail_count >= 3:
                    webhook = self.default_webhook
                    if webhook:
                        try:
                            self.session.post(webhook, json={
                                "content": f"⚠️ Supabase 通知ログ書き込み失敗 {self._notif_log_fail_count}回連続 — DB接続を確認してください"
                            }, timeout=5)
                        except Exception:
                            pass
                    self._notif_log_fail_count = 0

    # ─── Discord 送信 ─────────────────────────────────────────
    def _send_discord(
        self,
        webhook_url: str,
        symbol: str,
        system: str,
        score: float,
        ai_data: dict,
        current_price: float,
        session: str = "off",
    ):
        direction      = ai_data.get("direction", "WAIT")
        probability    = ai_data.get("probability", 0)
        entry          = ai_data.get("entry") or ai_data.get("entry_price", "---")
        tp1            = ai_data.get("tp1") or ai_data.get("tp_price", "---")
        tp2            = ai_data.get("tp2", "---")
        sl             = ai_data.get("sl") or ai_data.get("sl_price", "---")
        rr             = ai_data.get("rr_ratio", "---")
        signal_quality = ai_data.get("signal_quality", ai_data.get("confidence", "LOW"))
        badge          = ai_data.get("_badge", "⚪ SIGNAL")
        cached         = ai_data.get("cached", False)
        basis          = ai_data.get("basis", "")
        if not basis:
            basis = ai_data.get("ai_text", "")[:80]

        dir_icon  = "🟢🟢" if direction == "BUY" else "🔴🔴" if direction == "SELL" else "⚪"
        sq_icon   = "⭐⭐⭐" if signal_quality == "HIGH" else "⭐⭐" if signal_quality == "MEDIUM" else "⭐"
        mention   = "@everyone" if probability >= 85 else ""

        try:
            from .session_filter import SESSION_LABELS
            session_label = SESSION_LABELS.get(session, session)
        except Exception:
            session_label = session
        multiplier = ai_data.get("session_multiplier", 1.0)

        rr_str = f"{rr:.2f}" if isinstance(rr, float) else str(rr)

        description = (
            f"```\n"
            f"{badge}\n"
            f"{dir_icon} {direction} — {symbol} {mention}\n"
            f"{'━' * 35}\n"
            f"📊 確率: {probability}% | {sq_icon} {signal_quality}\n"
            f"📐 Entry: {entry} | TP: {tp1} | TP2: {tp2} | SL: {sl} | RR: {rr_str}\n"
            f"🕘 {session_label}（×{multiplier}）\n"
            f"⚡ {basis[:80]}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M JST')}\n"
            f"{'━' * 35}\n"
            f"```"
        )
        if cached:
            description += "\n🕐 *キャッシュデータ使用中*"

        color = 0x00C851 if direction == "BUY" else 0xFF4444 if direction == "SELL" else 0x888888
        payload = {
            "username": f"ONO Estimator ({system})",
            "embeds": [{
                "description": description,
                "color": color,
                "footer": {"text": "ONO Estimator Ultra v6.2"},
            }],
        }
        try:
            self.session.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"[Discord] Error: {e}")

    # ─── H-20: AI熟練スキャルパー通知（スキャルピング特化フォーマット）──
    def notify_ai_judgment(self, symbol: str, ai_data: dict, base_system: str = "AI") -> None:
        """スキャルピング戦略特化の通知フォーマットで送信する。B-3: base_systemでwebhookを振り分け"""
        # B-3: システム名でwebhookを振り分け
        webhook = self.webhooks.get(base_system) or self.default_webhook
        if not webhook:
            return

        direction = ai_data.get("direction", "WAIT")
        if direction == "WAIT" and not ai_data.get("should_notify"):
            return

        # B-1: 30分窓デバウンス
        import time as _time
        entry_price = ai_data.get("entry_price") or ai_data.get("entry", 0) or 0
        sig_key = self._make_signal_key(symbol, direction, float(entry_price))
        last_key, last_ts = self._last_signal_key.get(symbol, (None, 0))
        if last_key == sig_key and _time.time() - last_ts < 1800:
            return
        self._last_signal_key[symbol] = (sig_key, _time.time())

        dir_icon   = "🟢" if direction == "BUY" else "🔴" if direction == "SELL" else "⚪"
        conf       = ai_data.get("confidence", ai_data.get("signal_quality", "LOW"))
        entry      = ai_data.get("entry_price") or ai_data.get("entry", 0)
        tp         = ai_data.get("tp_price")    or ai_data.get("tp1", 0)
        tp2        = ai_data.get("tp2", 0)
        sl         = ai_data.get("sl_price")    or ai_data.get("sl", 0)
        rr         = ai_data.get("rr_ratio", 0)
        prob       = ai_data.get("probability", 0)
        ai_text    = ai_data.get("ai_text", "")
        awareness  = ai_data.get("awareness_text", "")
        is_range   = ai_data.get("is_range", False)
        entry_type = ai_data.get("entry_type", "NONE")
        enter_demo = ai_data.get("should_enter_demo", False)
        entry_reason_short = ai_data.get("entry_reason_short", "")
        trade_style_data   = ai_data.get("trade_style", {}) or {}
        trade_style        = trade_style_data.get("main_style", "")
        hold_time          = trade_style_data.get("hold_time", "")
        style_emoji        = trade_style_data.get("emoji", "")
        entry_timing       = ai_data.get("entry_timing", {}) or {}
        timing             = entry_timing.get("timing", "")
        timing_reason      = entry_timing.get("reason", "")
        score              = ai_data.get("score", 0)

        def fmt(v, digits=3):
            if isinstance(v, (int, float)) and v:
                big = abs(v) > 100
                return f"{v:.{1 if big else digits}f}"
            return str(v) if v else "---"

        def pips(entry_v, target_v, sym):
            if not (entry_v and target_v): return "---"
            mult = 100 if "JPY" in sym or "GOLD" in sym or "JP225" in sym else 10000
            return f"{abs(target_v - entry_v) * mult:.1f}pips"

        rr_str = f"{rr:.2f}" if isinstance(rr, (int, float)) and rr else "---"
        sep = "━" * 20

        # E-1: スタイルラベル
        style_labels = {"scalping": "スキャルピング", "daytrading": "デイトレード", "swing": "スイング"}
        style_label  = style_labels.get(trade_style, trade_style) if trade_style else ""

        # タイミング表示
        timing_icons = {"NOW": "🟢 今すぐ", "WAIT": "🟡 待機", "LIMIT": "🔵 指値推奨"}
        timing_str   = timing_icons.get(timing, "") if timing else ""

        entry_badge = {
            "LIQUIDITY_SWEEP": "💦 Liquidity Sweep（最重要）",
            "BODY_BREAK":      "🔷 実体ブレイク",
            "WICK_DENIAL":     "⚡ ヒゲ否定",
            "HAS_SHOULDER":    "📐 三尊/逆三尊の右肩崩れ",
        }.get(entry_type, "")

        basis = entry_reason_short or (ai_text[:80] if ai_text else awareness[:80])

        msg_lines = [
            f"🎯 **【{symbol} {direction}】{style_emoji}{style_label}**",
            sep,
        ]

        if is_range:
            msg_lines.append("⏸ **レンジ中 — ブレイクアウト待機中**")
        else:
            if basis:
                msg_lines.append(f"📍 **根拠:** {basis}")
            if entry_badge:
                msg_lines.append(f"🔑 **パターン:** {entry_badge}")
            if timing_str:
                msg_lines.append(f"⏰ **タイミング:** {timing_str}{'  ' + timing_reason[:40] if timing_reason else ''}")
            msg_lines += [
                "",
                f"💰 **Entry:** {fmt(entry)}",
                f"🎯 **TP1:** {fmt(tp)} (+{pips(entry, tp, symbol)}){'  |  TP2: ' + fmt(tp2) + ' (+' + pips(entry, tp2, symbol) + ')' if tp2 else ''}",
                f"🛑 **SL:** {fmt(sl)} (-{pips(entry, sl, symbol)})",
                f"📊 **RR:** {rr_str} | Score: {score} | 確率: {prob}%",
                f"⏱ **想定保有:** {hold_time}" if hold_time else "",
            ]

        msg_lines = [l for l in msg_lines if l]  # remove empty
        msg_lines.append(sep)

        # AI text summary (key part only)
        if ai_text and not is_range:
            for section in ["【判断】", "【計画】"]:
                idx = ai_text.find(section)
                if idx >= 0:
                    excerpt = ai_text[idx:idx+150].replace("\n", " ")
                    msg_lines.append(f"🧠 {excerpt}")
                    break

        if enter_demo:
            msg_lines.append(f"🎮 **DemoTrader: {direction} エントリー実行**")
        msg_lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M JST')}")

        content = "\n".join(msg_lines)
        color = 0x00C851 if direction == "BUY" else 0xFF4444 if direction == "SELL" else 0x888888

        try:
            payload = {
                "username": "ONO Estimator AI Scalper",
                "embeds": [{
                    "description": content[:4000],
                    "color": color,
                    "footer": {"text": "ONO Estimator Ultra v6.2 — AI Scalper"},
                }],
            }
            self.session.post(webhook, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"[Notifier] notify_ai_judgment error: {e}")

        self._log_notification(symbol, direction, prob)

    # ─── H-20: デモ売買結果通知（AI教訓付き）────────────────────────
    def send_demo_result(self, pos: dict, close_price: float,
                         result: str, pips: float, win_rate=None,
                         ai_lesson: str = None) -> None:
        """決済結果通知。LOSSの場合はAI自己反省教訓も掲載する。"""
        webhook = self.default_webhook
        if not webhook:
            return
        sym       = pos.get("symbol", "")
        direction = pos.get("direction", "")
        entry     = pos.get("entry_price", 0)
        reason    = pos.get("reason", "")
        icon      = "✅" if result == "WIN" else "❌"
        pips_sign = "+" if result == "WIN" else "-"
        wr_str    = f"{win_rate:.1f}%" if win_rate is not None else "---"
        sep = "━" * 17

        msg_lines = [
            f"{icon} **DemoTrader {result}**",
            f"{sym} {direction}",
            f"Entry: {entry:.5f} → Close: {close_price:.5f}",
            f"{pips_sign}{abs(pips):.1f} pips",
            sep,
        ]
        if reason:
            msg_lines += [f"📋 **エントリー根拠:**", reason[:200]]
        msg_lines.append(f"📊 通算勝率: {wr_str}")

        if ai_lesson and result == "LOSS":
            msg_lines += [
                sep,
                f"🧠 **AI自己反省（次回への教訓）:**",
                ai_lesson[:300],
            ]

        msg_lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M JST')}")

        msg = "\n".join(msg_lines)
        color = 0x00C851 if result == "WIN" else 0xFF4444
        try:
            payload = {
                "username": "ONO Estimator DemoTrader",
                "embeds": [{"description": msg[:2000], "color": color}],
            }
            self.session.post(webhook, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"[Notifier] send_demo_result error: {e}")

    def send_now_auto_entry(self, sym: str, ai_data: dict, score: int, prob: int) -> None:
        """⚡ entry_timing==NOW 自動エントリー Discord通知"""
        webhook = self.default_webhook
        if not webhook:
            return
        direction = ai_data.get("direction", "WAIT")
        entry  = ai_data.get("entry") or ai_data.get("entry_price", 0)
        tp1    = ai_data.get("tp1") or ai_data.get("tp_price", 0)
        sl     = ai_data.get("sl") or ai_data.get("sl_price", 0)
        reason = ai_data.get("entry_reason_short", "")[:150]
        style  = (ai_data.get("trade_style") or {}).get("main_style", "")
        hold   = (ai_data.get("trade_style") or {}).get("hold_time", "")
        short_sym = sym.replace("_", "").replace("/", "")[:10]
        sep = "━" * 17
        dir_icon = "🟢" if "BUY" in direction else "🔴"
        msg = "\n".join([
            f"⚡ **NOW AUTO-ENTRY** {dir_icon}",
            f"**{short_sym}** {direction}",
            sep,
            f"📍 根拠: {reason}",
            f"💰 Entry: {entry} | TP: {tp1} | SL: {sl}",
            f"📊 Score: {score} | 確率: {prob}%",
            f"🎯 {style} | 保有: {hold}",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M JST')}",
        ])
        try:
            payload = {
                "username": "ONO Estimator ⚡NOW",
                "embeds": [{"description": msg[:2000], "color": 0xFFD700}],
            }
            self.session.post(webhook, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"[Notifier] send_now_auto_entry error: {e}")

    # ─── LINE 送信 (Phase 1-1: LINE Messaging API Push Message) ──
    # 通知送信ロジックは AI を呼ばない設計 — Gemini呼び出しはai_loopのみで行う
    def _send_line(self, symbol: str, score: float, ai_data: dict, price: float, session: str):
        prob   = ai_data.get("probability", "---")
        entry  = ai_data.get("entry") or ai_data.get("entry_price", "---")
        tp1    = ai_data.get("tp1") or ai_data.get("tp_price", "---")
        sl     = ai_data.get("sl") or ai_data.get("sl_price", "---")
        badge  = ai_data.get("_badge", "")
        basis  = ai_data.get("basis", ai_data.get("ai_text", ""))[:100]
        text = (
            f"{badge}\n【ONO Alert】{symbol}\n"
            f"方向: {ai_data.get('direction', 'WAIT')}\n"
            f"現在値: {price:.3f}\n"
            f"確率: {prob}%\n"
            f"Entry: {entry} TP: {tp1} SL: {sl}\n"
            f"{basis}"
        )
        try:
            self.session.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {self.line_channel_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": self.line_user_id,
                    "messages": [{"type": "text", "text": text[:5000]}],
                },
                timeout=5,
            )
        except Exception as e:
            logger.error(f"[LINE] Error: {e}")
