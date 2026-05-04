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
            # active_signals は廃止 → predictions テーブルを使用
            res = self.db.client.table("predictions")\
                .select("*")\
                .in_("direction", ["BUY", "SELL"])\
                .eq("is_scored", False)\
                .order("created_at", desc=True)\
                .limit(8)\
                .execute()
            signals = res.data or []

            for sig in signals:
                sym = sig.get("symbol", "")
                current = price_cache.get(sym, 0)
                if current <= 0:
                    continue

                direction = sig.get("direction", "")
                entry  = sig.get("entry_price") or sig.get("current_price") or 0
                tp1    = sig.get("take_profit") or 0
                tp2    = sig.get("take_profit_2") or 0
                sl     = sig.get("stop_loss") or 0

                msg = None

                if direction == "BUY":
                    if tp2 and current >= tp2:
                        msg = f"🎯🎯 TP2 到達！ {sym} — 大成功\nEntry:{entry:.3f} → Now:{current:.3f}"
                    elif tp1 and current >= tp1:
                        msg = f"🎯 TP1 到達！ {sym} — 利益確定を推奨\nEntry:{entry:.3f} → Now:{current:.3f}"
                    elif sl and current <= sl:
                        msg = f"🛑 SL 到達 — {sym} 損切り\nEntry:{entry:.3f} → Now:{current:.3f}"
                elif direction == "SELL":
                    if tp2 and current <= tp2:
                        msg = f"🎯🎯 TP2 到達！ {sym} — 大成功\nEntry:{entry:.3f} → Now:{current:.3f}"
                    elif tp1 and current <= tp1:
                        msg = f"🎯 TP1 到達！ {sym} — 利益確定を推奨\nEntry:{entry:.3f} → Now:{current:.3f}"
                    elif sl and current >= sl:
                        msg = f"🛑 SL 到達 — {sym} 損切り\nEntry:{entry:.3f} → Now:{current:.3f}"

                if msg and self.notifier:
                    try:
                        webhook = self.notifier.default_webhook
                        if webhook:
                            requests.post(webhook, json={
                                "content": msg,
                                "username": "ONO Estimator — Trade Monitor",
                            }, timeout=5)
                        logger.info(f"[TradeMonitor] {sym} → notified: {msg[:40]}")
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"[TradeMonitor] check error: {e}")
