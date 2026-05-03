"""
Step A1: バックテスト自動化
Supabase の predictions テーブルから過去の予測を取得し、
実際の価格変動と比較して勝敗を記録する。

Supabase テーブル作成 SQL（手動実行が必要）:
------------------------------------------------------------
create table if not exists backtest_results (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  predicted_direction text,
  predicted_score float,
  entry_price float,
  tp float,
  sl float,
  actual_price_24h float,
  actual_price_48h float,
  result text,        -- WIN / LOSS / PENDING
  rr_achieved float,
  session text,
  spread_pips float,
  created_at timestamptz default now()
);
------------------------------------------------------------
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from .session_filter import get_current_session

logger = logging.getLogger(__name__)

SPREAD_PIPS = {
    "USDJPY": 0.3, "EURUSD": 0.5, "GBPUSD": 0.7, "AUDUSD": 0.5,
    "EURJPY": 0.5, "GBPJPY": 0.8, "AUDJPY": 0.5,
    "GOLD": 3.0, "SILVER": 5.0, "BTC": 50.0, "ETH": 5.0,
    "JP225": 5.0, "US30": 5.0,
}


def _get_spread(symbol: str) -> float:
    for key, val in SPREAD_PIPS.items():
        if key in symbol.upper():
            return val
    return 1.0


class Backtester:
    def __init__(self, db=None, price_cache: dict = None):
        self.db = db
        self.price_cache = price_cache or {}

    async def run(self):
        """過去 24〜72 時間の予測を採点する"""
        if not self.db or not self.db.client:
            return

        try:
            pending = self.db.get_unscored_predictions()
            scored = 0
            for p in pending:
                sym = p.get("symbol", "")
                current = self.price_cache.get(sym, 0)
                if current <= 0:
                    continue

                entry = p.get("current_price", 0)
                if entry <= 0:
                    continue

                status = p.get("status", "")
                is_buy = "BUY" in status.upper()
                is_sell = "SELL" in status.upper()

                spread = _get_spread(sym)
                is_correct = (is_buy and current > entry + spread * 0.01) or \
                             (is_sell and current < entry - spread * 0.01)
                result_str = "WIN" if is_correct else "LOSS"

                self.db.update_prediction_result(p["id"], current, is_correct)

                # backtest_results に保存
                try:
                    self.db.client.table("backtest_results").insert({
                        "symbol": sym,
                        "predicted_direction": "BUY" if is_buy else "SELL" if is_sell else "WAIT",
                        "predicted_score": float(p.get("score", 0)),
                        "entry_price": float(entry),
                        "actual_price_24h": float(current),
                        "result": result_str,
                        "session": get_current_session(),
                        "spread_pips": spread,
                        "created_at": datetime.now().isoformat(),
                    }).execute()
                except Exception:
                    pass

                scored += 1
                logger.info(f"[Backtest] {sym}: {result_str} (entry:{entry:.3f} → now:{current:.3f})")

            logger.info(f"[Backtest] Scored {scored} predictions")
        except Exception as e:
            logger.error(f"[Backtest] run error: {e}")

    def get_results(self, days: int = 30) -> dict:
        """直近 N 日の勝率統計を返す"""
        if not self.db or not self.db.client:
            return {"win_rate": 0, "total": 0, "wins": 0}

        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            res = self.db.client.table("backtest_results")\
                .select("result, symbol, session, spread_pips")\
                .gte("created_at", since)\
                .execute()
            data = res.data

            total = len(data)
            wins = sum(1 for r in data if r.get("result") == "WIN")
            win_rate = round(wins / total * 100, 1) if total > 0 else 0

            # 銘柄別勝率
            by_symbol = {}
            for r in data:
                sym = r["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = {"wins": 0, "total": 0}
                by_symbol[sym]["total"] += 1
                if r.get("result") == "WIN":
                    by_symbol[sym]["wins"] += 1

            by_symbol_rate = {
                sym: round(v["wins"] / v["total"] * 100, 1)
                for sym, v in by_symbol.items() if v["total"] > 0
            }

            return {
                "win_rate": win_rate,
                "total": total,
                "wins": wins,
                "by_symbol": by_symbol_rate,
                "days": days,
            }
        except Exception as e:
            logger.error(f"[Backtest] get_results error: {e}")
            return {"win_rate": 0, "total": 0, "wins": 0}

    def export_csv(self, days: int = 30) -> str:
        """Step G3: バックテスト結果を CSV 形式で返す"""
        if not self.db or not self.db.client:
            return "symbol,result,session,spread_pips,created_at\n"

        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            res = self.db.client.table("backtest_results")\
                .select("*")\
                .gte("created_at", since)\
                .order("created_at", desc=True)\
                .execute()
            data = res.data

            if not data:
                return "No data available\n"

            cols = ["symbol", "predicted_direction", "predicted_score", "entry_price",
                    "actual_price_24h", "result", "session", "spread_pips", "created_at"]
            lines = [",".join(cols)]
            for row in data:
                lines.append(",".join(str(row.get(c, "")) for c in cols))
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"[Backtest] export error: {e}")
            return f"Export error: {e}\n"
