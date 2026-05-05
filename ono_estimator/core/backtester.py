"""
Backtester — バックテスト自動化 (T-15強化版)
=============================================
改善点:
  - SL/TPのpips値での勝敗判定（方向だけでなくリスクリワードで評価）
  - 時間帯別勝率集計（東京/ロンドン/NY）
  - チャートパターン別勝率集計

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
  chart_pattern text,
  spread_pips float,
  pips_gain float,
  created_at timestamptz default now()
);
------------------------------------------------------------
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .session_filter import get_current_session

logger = logging.getLogger(__name__)

SPREAD_PIPS = {
    "USDJPY": 0.3, "EURUSD": 0.5, "GBPUSD": 0.7, "AUDUSD": 0.5,
    "EURJPY": 0.5, "GBPJPY": 0.8, "AUDJPY": 0.5,
    "GOLD": 3.0, "SILVER": 5.0, "BTC": 50.0, "ETH": 5.0,
    "JP225": 5.0, "US30": 5.0,
}

# 時間帯定義 (UTC時間)
SESSION_HOURS = {
    "Tokyo":   (0, 9),    # UTC 00:00-09:00
    "London":  (7, 16),   # UTC 07:00-16:00
    "NY":      (13, 22),  # UTC 13:00-22:00
}


def _get_spread(symbol: str) -> float:
    for key, val in SPREAD_PIPS.items():
        if key in symbol.upper():
            return val
    return 1.0


def _classify_session(dt: datetime) -> str:
    """時刻からセッション名を返す（重複あり→優先度: London/NY > Tokyo）"""
    h = dt.hour
    # ロンドン/NYオーバーラップ
    if 13 <= h < 16:
        return "London/NY"
    if 7 <= h < 13:
        return "London"
    if 13 <= h < 22:
        return "NY"
    if 0 <= h < 9:
        return "Tokyo"
    return "Off"


def _calc_pips(symbol: str, price_diff: float) -> float:
    """価格差をpipsに変換。"""
    sym = symbol.upper()
    if "JPY" in sym or "225" in sym:
        return price_diff * 100
    if "XAU" in sym or "GOLD" in sym or "GC" in sym:
        return price_diff * 10
    if "BTC" in sym:
        return price_diff
    return price_diff * 10000


def _determine_result(entry: float, current: float, tp: float, sl: float,
                      direction: str, symbol: str) -> tuple[str, float]:
    """
    SL/TP pips判定（T-15）。
    戻り値: (result, pips_gain)
    result: "WIN_TP" / "LOSS_SL" / "WIN_DIR" / "LOSS_DIR" / "PENDING"
    """
    if entry <= 0 or current <= 0:
        return "PENDING", 0.0

    is_buy  = "BUY" in direction.upper()
    is_sell = "SELL" in direction.upper()
    spread  = _get_spread(symbol)

    price_diff = current - entry

    # SL/TP が設定されている場合はリスクリワードで判定
    if tp > 0 and sl > 0:
        if is_buy:
            if current >= tp:
                pips = _calc_pips(symbol, tp - entry)
                return "WIN_TP", pips
            if current <= sl:
                pips = _calc_pips(symbol, entry - sl)
                return "LOSS_SL", -pips
        elif is_sell:
            if current <= tp:
                pips = _calc_pips(symbol, entry - tp)
                return "WIN_TP", pips
            if current >= sl:
                pips = _calc_pips(symbol, sl - entry)
                return "LOSS_SL", -pips

    # SL/TP なし → 方向判定（旧ロジック）
    is_correct = (is_buy and current > entry + spread * 0.01) or \
                 (is_sell and current < entry - spread * 0.01)
    pips = _calc_pips(symbol, abs(price_diff)) * (1 if is_correct else -1)
    return ("WIN_DIR" if is_correct else "LOSS_DIR"), pips


class Backtester:
    def __init__(self, db=None, price_cache: dict = None):
        self.db = db
        self.price_cache = price_cache or {}

    async def run(self):
        """過去 24〜72 時間の予測を採点する（T-15: SL/TP + セッション判定）"""
        if not self.db or not self.db.client:
            return

        try:
            pending = self.db.get_unscored_predictions()
            scored = 0
            for p in pending:
                sym     = p.get("symbol", "")
                current = self.price_cache.get(sym, 0)
                if current <= 0:
                    continue

                entry = p.get("current_price", 0)
                if entry <= 0:
                    continue

                status = p.get("status", "")
                tp     = float(p.get("tp1") or p.get("tp") or 0)
                sl     = float(p.get("sl") or 0)
                direction = "BUY" if "BUY" in status.upper() else "SELL" if "SELL" in status.upper() else "WAIT"

                result_str, pips_gain = _determine_result(
                    entry, current, tp, sl, direction, sym)
                is_win = result_str.startswith("WIN")

                self.db.update_prediction_result(p["id"], current, is_win)

                # created_at からセッション判定
                try:
                    created_raw = p.get("created_at", "")
                    created_dt  = datetime.fromisoformat(
                        created_raw.replace("Z", "+00:00")) if created_raw else datetime.now(tz=timezone.utc)
                    session = _classify_session(created_dt)
                except Exception:
                    session = get_current_session()

                # backtest_results に保存
                try:
                    self.db.client.table("backtest_results").insert({
                        "symbol":               sym,
                        "predicted_direction":  direction,
                        "predicted_score":      float(p.get("score", 0)),
                        "entry_price":          float(entry),
                        "tp":                   float(tp),
                        "sl":                   float(sl),
                        "actual_price_24h":     float(current),
                        "result":               result_str,
                        "rr_achieved":          round(pips_gain, 2),
                        "pips_gain":            round(pips_gain, 2),
                        "session":              session,
                        "spread_pips":          _get_spread(sym),
                        "chart_pattern":        p.get("chart_pattern", ""),
                        "created_at":           datetime.now(tz=timezone.utc).isoformat(),
                    }).execute()
                except Exception:
                    pass

                scored += 1
                logger.info(f"[Backtest] {sym}: {result_str} ({pips_gain:+.1f}pips) entry:{entry:.3f}→now:{current:.3f}")

            logger.info(f"[Backtest] Scored {scored} predictions")
        except Exception as e:
            logger.error(f"[Backtest] run error: {e}")

    def get_results(self, days: int = 30) -> dict:
        """直近 N 日の勝率統計 (T-15: セッション別 + パターン別追加)"""
        if not self.db or not self.db.client:
            return {"win_rate": 0, "total": 0, "wins": 0}

        try:
            since = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
            res = self.db.client.table("backtest_results")\
                .select("result, symbol, session, chart_pattern, pips_gain, spread_pips")\
                .gte("created_at", since)\
                .execute()
            data = res.data

            total = len(data)
            wins  = sum(1 for r in data if r.get("result", "").startswith("WIN"))
            win_rate = round(wins / total * 100, 1) if total > 0 else 0

            # 銘柄別勝率
            by_symbol: dict = {}
            for r in data:
                sym = r["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = {"wins": 0, "total": 0, "pips": 0.0}
                by_symbol[sym]["total"] += 1
                if r.get("result", "").startswith("WIN"):
                    by_symbol[sym]["wins"] += 1
                by_symbol[sym]["pips"] += float(r.get("pips_gain") or 0)

            by_symbol_stats = {
                sym: {
                    "win_rate": round(v["wins"] / v["total"] * 100, 1),
                    "total":    v["total"],
                    "pips":     round(v["pips"], 1),
                }
                for sym, v in by_symbol.items() if v["total"] > 0
            }

            # T-15: セッション別勝率
            by_session: dict = {}
            for r in data:
                sess = r.get("session") or "Unknown"
                if sess not in by_session:
                    by_session[sess] = {"wins": 0, "total": 0}
                by_session[sess]["total"] += 1
                if r.get("result", "").startswith("WIN"):
                    by_session[sess]["wins"] += 1

            by_session_rate = {
                sess: {
                    "win_rate": round(v["wins"] / v["total"] * 100, 1),
                    "total":    v["total"],
                }
                for sess, v in by_session.items() if v["total"] > 0
            }

            # T-15: パターン別勝率
            by_pattern: dict = {}
            for r in data:
                pat = r.get("chart_pattern") or "なし"
                if not pat or pat == "":
                    pat = "なし"
                if pat not in by_pattern:
                    by_pattern[pat] = {"wins": 0, "total": 0}
                by_pattern[pat]["total"] += 1
                if r.get("result", "").startswith("WIN"):
                    by_pattern[pat]["wins"] += 1

            by_pattern_rate = {
                pat: {
                    "win_rate": round(v["wins"] / v["total"] * 100, 1),
                    "total":    v["total"],
                }
                for pat, v in by_pattern.items() if v["total"] >= 3  # 3件以上のパターンのみ
            }

            return {
                "win_rate":      win_rate,
                "total":         total,
                "wins":          wins,
                "by_symbol":     by_symbol_stats,
                "by_session":    by_session_rate,
                "by_pattern":    by_pattern_rate,
                "days":          days,
            }
        except Exception as e:
            logger.error(f"[Backtest] get_results error: {e}")
            return {"win_rate": 0, "total": 0, "wins": 0}

    def export_csv(self, days: int = 30) -> str:
        """バックテスト結果を CSV 形式で返す"""
        if not self.db or not self.db.client:
            return "symbol,result,session,spread_pips,pips_gain,chart_pattern,created_at\n"

        try:
            since = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
            res = self.db.client.table("backtest_results")\
                .select("*")\
                .gte("created_at", since)\
                .order("created_at", desc=True)\
                .execute()
            data = res.data

            if not data:
                return "No data available\n"

            cols = ["symbol", "predicted_direction", "predicted_score", "entry_price",
                    "tp", "sl", "actual_price_24h", "result", "pips_gain",
                    "session", "chart_pattern", "spread_pips", "created_at"]
            lines = [",".join(cols)]
            for row in data:
                lines.append(",".join(str(row.get(c, "")) for c in cols))
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"[Backtest] export error: {e}")
            return f"Export error: {e}\n"

    def get_session_stats(self) -> dict:
        """時間帯別勝率のサマリーを返す（API用）"""
        return self.get_results(days=30).get("by_session", {})

    def get_pattern_stats(self) -> dict:
        """パターン別勝率のサマリーを返す（API用）"""
        return self.get_results(days=30).get("by_pattern", {})
