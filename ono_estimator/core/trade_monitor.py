"""
Step B2: TP/SL 到達アラート
通知済みシグナルを管理し、TP/SL 到達時に Discord へ通知する。

Supabase テーブル作成 SQL（手動実行が必要）:
------------------------------------------------------------
create table if not exists active_signals (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  direction text,
  entry float,
  tp1 float,
  tp2 float,
  sl float,
  status text default 'ACTIVE',
  notified_at timestamptz,
  created_at timestamptz default now()
);
------------------------------------------------------------
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class TradeMonitor:
    def __init__(self, db=None, notifier=None):
        self.db = db
        self.notifier = notifier

    def register_signal(self, symbol: str, direction: str, entry: float,
                        tp1: float, tp2: float, sl: float):
        """新しいシグナルを登録する"""
        if not self.db or not self.db.client:
            return
        try:
            self.db.client.table("active_signals").insert({
                "symbol": symbol,
                "direction": direction,
                "entry": entry,
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "status": "ACTIVE",
                "notified_at": datetime.now().isoformat(),
                "created_at": datetime.now().isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"[TradeMonitor] Register failed: {e}")

    def check_signals(self, price_cache: dict):
        """5分ごとに現在価格と TP/SL を比較して通知する"""
        if not self.db or not self.db.client:
            return

        try:
            res = self.db.client.table("active_signals")\
                .select("*")\
                .eq("status", "ACTIVE")\
                .execute()
            signals = res.data

            for sig in signals:
                sym = sig["symbol"]
                current = price_cache.get(sym, 0)
                if current <= 0:
                    continue

                new_status = None
                msg = None

                if sig.get("tp2") and current >= sig["tp2"] and sig["direction"] == "BUY":
                    new_status = "TP2"
                    msg = f"🎯🎯 TP2 到達！ {sym} — 大成功\nEntry:{sig['entry']:.3f} → Now:{current:.3f}"
                elif sig.get("tp1") and current >= sig["tp1"] and sig["direction"] == "BUY":
                    new_status = "TP1"
                    msg = f"🎯 TP1 到達！ {sym} — 利益確定を推奨\nEntry:{sig['entry']:.3f} → Now:{current:.3f}"
                elif sig.get("sl") and current <= sig["sl"] and sig["direction"] == "BUY":
                    new_status = "SL"
                    msg = f"🛑 SL 到達 — {sym} 損切り\nEntry:{sig['entry']:.3f} → Now:{current:.3f}"
                elif sig.get("tp2") and current <= sig["tp2"] and sig["direction"] == "SELL":
                    new_status = "TP2"
                    msg = f"🎯🎯 TP2 到達！ {sym} — 大成功\nEntry:{sig['entry']:.3f} → Now:{current:.3f}"
                elif sig.get("tp1") and current <= sig["tp1"] and sig["direction"] == "SELL":
                    new_status = "TP1"
                    msg = f"🎯 TP1 到達！ {sym} — 利益確定を推奨"
                elif sig.get("sl") and current >= sig["sl"] and sig["direction"] == "SELL":
                    new_status = "SL"
                    msg = f"🛑 SL 到達 — {sym} 損切り"

                # 作成から48時間経過したら期限切れ
                created = datetime.fromisoformat(sig["created_at"].replace("Z", "+00:00"))
                if datetime.now().astimezone() - created > timedelta(hours=48):
                    new_status = "EXPIRED"

                if new_status:
                    try:
                        self.db.client.table("active_signals")\
                            .update({"status": new_status})\
                            .eq("id", sig["id"])\
                            .execute()
                    except Exception:
                        pass

                    if msg and self.notifier and new_status != "EXPIRED":
                        try:
                            webhook = self.notifier.default_webhook
                            if webhook:
                                requests.post(webhook, json={
                                    "content": msg,
                                    "username": "ONO Estimator — Trade Monitor",
                                }, timeout=5)
                        except Exception:
                            pass

                    logger.info(f"[TradeMonitor] {sym} → {new_status}")

        except Exception as e:
            logger.error(f"[TradeMonitor] check error: {e}")
