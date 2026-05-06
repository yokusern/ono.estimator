"""
SupabaseClient v2 — 新スキーマ対応 + パフォーマンス追跡 + AI Memory
"""
import os, json, logging, traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)


class SupabaseClient:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            self.client = None
            print("[Supabase] No credentials. Running without DB.")
            return
        try:
            self.client = create_client(url, key)
            print("[Supabase] Connected ✅")
        except Exception as e:
            print(f"[Supabase] Connection failed: {e}")
            self.client = None

    # ─── predictions ──────────────────────────────────────────
    def save_prediction(self, data: Dict[str, Any]) -> Optional[str]:
        if not self.client:
            return None
        try:
            row = {
                "symbol":        str(data.get("symbol", "UNKNOWN")),
                "timeframe":     str(data.get("timeframe", "1h")),
                "direction":     str(data.get("status", data.get("direction", "WAIT"))).upper(),
                "confidence":    float(data.get("probability", 0)),
                "entry_price":   _f(data.get("entry") or data.get("predicted_price")),
                "current_price": _f(data.get("current_price")),
                "stop_loss":     _f(data.get("sl")),
                "take_profit":   _f(data.get("tp1") or data.get("tp")),
                "take_profit_2": _f(data.get("tp2")),
                "ai_reasoning":  str(data.get("ai_text", ""))[:2000],
                "layer_scores":  data.get("layers") or {},
                "score":         float(data.get("score", 0)),
                "probability":   float(data.get("probability", 0)),
                "aligned":       int(data.get("aligned", 0)),
                "session":       str(data.get("session", "off")),
                "is_scored":     False,
            }
            # directionをBUY/SELL/WAITに正規化
            d = row["direction"]
            if "BUY" in d:
                row["direction"] = "BUY"
            elif "SELL" in d:
                row["direction"] = "SELL"
            else:
                row["direction"] = "WAIT"

            res = self.client.table("predictions").insert(row).execute()
            if res.data:
                return res.data[0].get("id")
        except Exception as e:
            logger.warning(f"[Supabase] save_prediction error: {e}")
        return None

    def get_predictions(self, symbol: str = None, limit: int = 50,
                        direction: str = None, timeframe: str = None) -> List[Dict]:
        if not self.client:
            return []
        try:
            q = self.client.table("predictions").select("*")
            if symbol:
                q = q.eq("symbol", symbol)
            if direction:
                q = q.eq("direction", direction)
            if timeframe:
                q = q.eq("timeframe", timeframe)
            res = q.order("created_at", desc=True).limit(limit).execute()
            return res.data or []
        except Exception as e:
            logger.warning(f"[Supabase] get_predictions error: {e}")
            return []

    def get_unscored_predictions(self) -> List[Dict]:
        if not self.client:
            return []
        one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        try:
            res = self.client.table("predictions")\
                .select("*")\
                .eq("is_scored", False)\
                .neq("direction", "WAIT")\
                .lt("created_at", one_hour_ago)\
                .limit(20).execute()
            return res.data or []
        except Exception:
            return []

    def update_prediction_result(self, row_id: str, actual_price: float, is_correct: bool,
                                  outcome: str = None):
        if not self.client:
            return
        try:
            update_data = {
                "actual_price": actual_price,
                "is_correct": is_correct,
                "is_scored": True,
            }
            self.client.table("predictions").update(update_data).eq("id", row_id).execute()
            # performance_logに記録
            if outcome:
                self.client.table("performance_log").insert({
                    "prediction_id": row_id,
                    "symbol": "UNKNOWN",
                    "direction": "WAIT",
                    "exit_price": actual_price,
                    "outcome": outcome,
                    "closed_at": datetime.utcnow().isoformat(),
                }).execute()
        except Exception as e:
            logger.warning(f"[Supabase] update_prediction_result error: {e}")

    # ─── performance_log ──────────────────────────────────────
    def save_performance(self, prediction_id: str, symbol: str, direction: str,
                         entry_price: float, exit_price: float, outcome: str,
                         pips_result: float, hold_minutes: int = None):
        if not self.client:
            return
        try:
            rr = abs(pips_result) / max(abs(entry_price - exit_price) * 0.5, 0.0001) if entry_price and exit_price else None
            self.client.table("performance_log").insert({
                "prediction_id": prediction_id,
                "symbol": symbol,
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "outcome": outcome,
                "pips_result": pips_result,
                "rr_achieved": rr,
                "hold_minutes": hold_minutes,
                "closed_at": datetime.utcnow().isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_performance error: {e}")

    def get_performance_summary(self) -> Dict:
        if not self.client:
            return _empty_perf()
        try:
            res = self.client.table("performance_log")\
                .select("outcome,pips_result,symbol,direction,rr_achieved")\
                .neq("outcome", "PENDING")\
                .order("closed_at", desc=True)\
                .limit(200).execute()
            rows = res.data or []
            if not rows:
                return _empty_perf()
            total = len(rows)
            wins = sum(1 for r in rows if r.get("outcome") == "WIN")
            losses = sum(1 for r in rows if r.get("outcome") == "LOSS")
            pips = [r.get("pips_result", 0) or 0 for r in rows]
            win_pips = sum(p for p in pips if p > 0)
            loss_pips = abs(sum(p for p in pips if p < 0))
            win_rate = wins / total * 100 if total else 0
            pf = win_pips / loss_pips if loss_pips > 0 else 0
            rrs = [r.get("rr_achieved") for r in rows if r.get("rr_achieved")]
            avg_rr = sum(rrs) / len(rrs) if rrs else 0
            # 銘柄別集計
            by_symbol: Dict = {}
            for r in rows:
                sym = r.get("symbol", "?")
                if sym not in by_symbol:
                    by_symbol[sym] = {"total": 0, "wins": 0, "win_rate": 0}
                by_symbol[sym]["total"] += 1
                if r.get("outcome") == "WIN":
                    by_symbol[sym]["wins"] += 1
            for sym in by_symbol:
                t = by_symbol[sym]["total"]
                w = by_symbol[sym]["wins"]
                by_symbol[sym]["win_rate"] = round(w / t * 100, 1) if t else 0
            return {
                "win_rate": round(win_rate, 1),
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "profit_factor": round(pf, 2),
                "avg_rr": round(avg_rr, 2),
                "total_pips": round(sum(pips), 1),
                "by_symbol": by_symbol,
                "logs": [
                    {
                        "symbol": r.get("symbol"),
                        "direction": r.get("direction"),
                        "entry": r.get("entry_price"),
                        "exit": r.get("exit_price"),
                        "outcome": r.get("outcome"),
                        "pips": r.get("pips_result"),
                        "rr": r.get("rr_achieved"),
                    }
                    for r in rows[:30]
                ],
            }
        except Exception as e:
            logger.warning(f"[Supabase] get_performance_summary error: {e}")
            return _empty_perf()

    # ─── market_snapshots (キャッシュ) ────────────────────────
    def save_snapshot(self, symbol: str, timeframe: str, ohlcv: list, indicators: dict):
        if not self.client:
            return
        try:
            self.client.table("market_snapshots").insert({
                "symbol": symbol,
                "timeframe": timeframe,
                "ohlcv": ohlcv[-200:] if ohlcv else [],
                "indicators": indicators or {},
            }).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_snapshot error: {e}")

    def get_latest_snapshot(self, symbol: str, timeframe: str) -> Optional[Dict]:
        if not self.client:
            return None
        try:
            res = self.client.table("market_snapshots")\
                .select("*")\
                .eq("symbol", symbol)\
                .eq("timeframe", timeframe)\
                .order("fetched_at", desc=True)\
                .limit(1).execute()
            if res.data:
                return res.data[0]
        except Exception:
            pass
        return None

    # ─── notification_logs ────────────────────────────────────
    def check_notified_recently(self, symbol: str, hours: int = 4) -> bool:
        """指定時間内に同銘柄へ通知済みか確認"""
        if not self.client:
            return False
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        try:
            res = self.client.table("notification_logs")\
                .select("id")\
                .eq("symbol", symbol)\
                .gt("notified_at", cutoff)\
                .limit(1).execute()
            return len(res.data or []) > 0
        except Exception:
            return False

    def save_notification(self, symbol: str, direction: str, score: float, prob: float):
        if not self.client:
            return
        try:
            self.client.table("notification_logs").insert({
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "probability": prob,
            }).execute()
        except Exception as e:
            logger.warning(f"[Supabase] save_notification error: {e}")

    # ─── demo_positions (H-11) ────────────────────────────────
    def save_demo_position(self, pos: dict) -> Optional[str]:
        if not self.client:
            return None
        try:
            row = {
                "symbol":      str(pos.get("symbol", "")),
                "direction":   str(pos.get("direction", "")),
                "entry_price": _f(pos.get("entry_price")),
                "tp_price":    _f(pos.get("tp_price")),
                "sl_price":    _f(pos.get("sl_price")),
                "reason":      str(pos.get("reason", ""))[:500],
                "status":      "OPEN",
                "opened_at":   pos.get("opened_at") or datetime.utcnow().isoformat(),
            }
            res = self.client.table("demo_positions").insert(row).execute()
            if res.data:
                return res.data[0].get("id")
        except Exception as e:
            logger.warning(f"[Supabase] save_demo_position error: {e}")
        return None

    def close_demo_position(self, symbol: str, close_price: float,
                             result: str, pips: float) -> Optional[float]:
        """ポジションを決済し、最新の勝率を返す"""
        if not self.client:
            return None
        try:
            self.client.table("demo_positions").update({
                "close_price": close_price,
                "result":      result,
                "pips":        round(pips, 1),
                "status":      "CLOSED",
                "closed_at":   datetime.utcnow().isoformat(),
            }).eq("symbol", symbol).eq("status", "OPEN").execute()
            return self.get_demo_win_rate()
        except Exception as e:
            logger.warning(f"[Supabase] close_demo_position error: {e}")
        return None

    def get_demo_win_rate(self) -> Optional[float]:
        if not self.client:
            return None
        try:
            res = self.client.table("demo_positions")\
                .select("result")\
                .eq("status", "CLOSED")\
                .execute()
            rows = res.data or []
            if not rows:
                return None
            wins  = sum(1 for r in rows if r.get("result") == "WIN")
            total = len(rows)
            return round(wins / total * 100, 1) if total else None
        except Exception as e:
            logger.warning(f"[Supabase] get_demo_win_rate error: {e}")
        return None

    def get_demo_positions(self, limit: int = 20) -> list:
        if not self.client:
            return []
        try:
            res = self.client.table("demo_positions")\
                .select("*")\
                .order("opened_at", desc=True)\
                .limit(limit)\
                .execute()
            return res.data or []
        except Exception as e:
            logger.warning(f"[Supabase] get_demo_positions error: {e}")
        return []

    # ─── legacy ───────────────────────────────────────────────
    def get_performance_by_symbol(self, limit: int = 500) -> List[Dict]:
        """D-3: 銘柄別パフォーマンス（総シグナル数・勝率・平均スコア・セッション別）"""
        if not self.client:
            return []
        try:
            res = self.client.table("predictions")\
                .select("symbol,score,is_scored,is_correct,session")\
                .order("created_at", desc=True)\
                .limit(limit).execute()
            rows = res.data or []
            agg: Dict[str, Dict] = {}
            for r in rows:
                sym = r.get("symbol", "?")
                sess = r.get("session") or "off"
                if sym not in agg:
                    agg[sym] = {
                        "symbol": sym, "total": 0, "scored": 0, "wins": 0, "score_sum": 0.0,
                        "by_session": {},
                    }
                agg[sym]["total"] += 1
                agg[sym]["score_sum"] += float(r.get("score") or 0)
                if r.get("is_scored"):
                    agg[sym]["scored"] += 1
                    if r.get("is_correct"):
                        agg[sym]["wins"] += 1
                # D-3: セッション別集計
                sd = agg[sym]["by_session"]
                if sess not in sd:
                    sd[sess] = {"total": 0, "wins": 0}
                sd[sess]["total"] += 1
                if r.get("is_correct"):
                    sd[sess]["wins"] += 1
            result = []
            for sym, d in agg.items():
                t, s, w = d["total"], d["scored"], d["wins"]
                by_sess = {}
                for sess, sd in d["by_session"].items():
                    st, sw = sd["total"], sd["wins"]
                    by_sess[sess] = {
                        "total": st,
                        "wins":  sw,
                        "win_rate": round(sw / st * 100, 1) if st > 0 else None,
                    }
                result.append({
                    "symbol":      sym,
                    "total":       t,
                    "scored":      s,
                    "wins":        w,
                    "win_rate":    round(w / s * 100, 1) if s > 0 else None,
                    "avg_score":   round(d["score_sum"] / t, 1) if t > 0 else 0.0,
                    "by_session":  by_sess,
                })
            result.sort(key=lambda x: x["total"], reverse=True)
            return result
        except Exception as e:
            logger.warning(f"[Supabase] get_performance_by_symbol error: {e}")
            return []

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self.get_predictions(limit=limit)

    def get_performance_text(self) -> str:
        summary = self.get_performance_summary()
        wr = summary.get("win_rate", 0)
        total = summary.get("total_trades", 0)
        if total == 0:
            return "学習データ蓄積中..."
        return f"直近{total}件の勝率: {wr:.1f}%"

    # ─── B-2: 見送りシグナル ──────────────────────────────────
    def save_missed_signal(self, data: Dict[str, Any]) -> Optional[str]:
        if not self.client:
            return None
        try:
            row = {
                "symbol":         str(data.get("symbol", "")),
                "direction":      str(data.get("direction", "WAIT")),
                "score":          _f(data.get("score")),
                "probability":    _f(data.get("probability")),
                "entry_price":    _f(data.get("entry") or data.get("entry_price")),
                "tp1":            _f(data.get("tp1") or data.get("tp_price")),
                "tp2":            _f(data.get("tp2")),
                "sl":             _f(data.get("sl") or data.get("sl_price")),
                "reason_skipped": str(data.get("skip_reason", ""))[:200],
                "trade_style":    str(data.get("trade_style", "")),
            }
            res = self.client.table("missed_signals").insert(row).execute()
            if res.data:
                return res.data[0].get("id")
        except Exception as e:
            logger.warning(f"[Supabase] save_missed_signal error: {e}")
        return None

    def get_missed_signals(self, limit: int = 20) -> List[Dict]:
        if not self.client:
            return []
        try:
            res = self.client.table("missed_signals")\
                .select("*")\
                .order("timestamp", desc=True)\
                .limit(limit).execute()
            return res.data or []
        except Exception as e:
            logger.warning(f"[Supabase] get_missed_signals error: {e}")
            return []


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _empty_perf() -> Dict:
    return {
        "win_rate": 0, "total_trades": 0, "wins": 0, "losses": 0,
        "profit_factor": 0, "avg_rr": 0, "total_pips": 0,
        "by_symbol": {}, "logs": [],
    }
