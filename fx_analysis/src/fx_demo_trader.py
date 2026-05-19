"""
FxDemoTrader — fx_analysis シグナルのデモトレード自動追跡
=====================================================
チートシグナルが発火 → デモポジション開設 → TP/SL到達で自動決済
→ 結果をSQLiteに蓄積し、シグナル別実績勝率を継続改善に活用する。

DB: fx_analysis/data/fx_demo.db
"""
from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fx_demo.db"


# ─── DB 初期化 ──────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fx_demo_positions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pair        TEXT NOT NULL,
            interval    TEXT NOT NULL,
            direction   TEXT NOT NULL,       -- 'buy' | 'sell'
            entry       REAL NOT NULL,
            sl          REAL NOT NULL,
            tp          REAL NOT NULL,
            probability REAL,                -- 発火時の推定確率(%)
            ev          REAL,                -- 発火時の期待値
            signals     TEXT,                -- JSON: アクティブシグナル名リスト
            key_level   REAL,                -- 直近キーレベル
            opened_at   TEXT NOT NULL,
            closed_at   TEXT,
            close_price REAL,
            result      TEXT,                -- 'WIN' | 'LOSS' | 'BE' | NULL(open)
            pips        REAL,
            status      TEXT DEFAULT 'OPEN'  -- 'OPEN' | 'CLOSED'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fx_demo_stats_cache (
            id            INTEGER PRIMARY KEY,
            last_updated  TEXT,
            total_trades  INTEGER,
            win_rate      REAL,
            avg_pips      REAL,
            profit_factor REAL
        )
    """)
    conn.commit()
    return conn


class FxDemoTrader:
    """
    fx_analysis チートシグナルのデモポジション管理クラス。
    cheat_signal_runner.py から呼び出す。
    """

    def __init__(self):
        self._open: dict[str, dict] = {}   # key: f"{pair}_{interval}_{direction}"
        self._load_open_from_db()

    # ─── ポジション開設 ──────────────────────────────────────────────
    def open_position(
        self,
        pair: str,
        interval: str,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        probability: float,
        ev: float,
        signals: list[str],
        key_level: float = 0.0,
    ) -> bool:
        """
        新規デモポジションを開く。
        同じ pair/interval/direction で既存ポジションがある場合はスキップ。
        """
        key = f"{pair}_{interval}_{direction}"
        if key in self._open:
            logger.debug(f"[FxDemo] {key} — 既存ポジションあり、スキップ")
            return False
        if not entry or not sl or not tp:
            return False

        import json
        pos = {
            "pair":        pair,
            "interval":    interval,
            "direction":   direction,
            "entry":       entry,
            "sl":          sl,
            "tp":          tp,
            "probability": probability,
            "ev":          ev,
            "signals":     json.dumps(signals[:5], ensure_ascii=False),
            "key_level":   key_level,
            "opened_at":   datetime.now().isoformat(),
            "status":      "OPEN",
        }
        conn = _get_conn()
        cur  = conn.execute("""
            INSERT INTO fx_demo_positions
            (pair, interval, direction, entry, sl, tp,
             probability, ev, signals, key_level, opened_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pair, interval, direction, entry, sl, tp,
              probability, ev, pos["signals"], key_level,
              pos["opened_at"], "OPEN"))
        pos["id"] = cur.lastrowid
        conn.commit()
        conn.close()

        self._open[key] = pos
        logger.info(
            f"[FxDemo] OPEN {pair} {interval} {direction.upper()} "
            f"entry={entry}  SL={sl}  TP={tp}  確率={probability:.1f}%"
        )
        return True

    # ─── 既存ポジション決済チェック ─────────────────────────────────
    def check_and_close(self, current_prices: dict[str, float]) -> list[dict]:
        """
        現在価格でTP/SLヒットを判定し、決済済みポジションのリストを返す。
        current_prices: {"XAUUSD": 3285.5, "USDJPY": 158.9, ...}
        """
        closed = []
        for key, pos in list(self._open.items()):
            pair  = pos["pair"]
            price = current_prices.get(pair, 0)
            if not price:
                continue

            entry = pos["entry"]
            sl    = pos["sl"]
            tp    = pos["tp"]
            direction = pos["direction"]

            result = None
            if direction == "buy":
                if price >= tp:   result = "WIN"
                elif price <= sl: result = "LOSS"
            else:
                if price <= tp:   result = "WIN"
                elif price >= sl: result = "LOSS"

            if result:
                pips = self._calc_pips(pair, entry, price, direction)
                self._close_db(pos["id"], price, result, pips)
                del self._open[key]
                pos.update({"close_price": price, "result": result, "pips": pips})
                closed.append(pos)
                logger.info(
                    f"[FxDemo] CLOSE {pair} {pos['interval']} {direction.upper()} "
                    f"{result}  pips={pips:+.1f}"
                )
        return closed

    # ─── 統計取得 ────────────────────────────────────────────────────
    def get_stats(self, pair: Optional[str] = None,
                  interval: Optional[str] = None) -> dict:
        """
        デモトレード実績統計を返す。
        pair/interval でフィルタ可能。全体統計の場合は None を指定。
        """
        conn = _get_conn()
        where = "WHERE status='CLOSED'"
        params: list = []
        if pair:
            where += " AND pair=?"; params.append(pair)
        if interval:
            where += " AND interval=?"; params.append(interval)

        rows = conn.execute(
            f"SELECT * FROM fx_demo_positions {where}", params
        ).fetchall()
        conn.close()

        if not rows:
            return {"total": 0, "win_rate": None, "avg_pips": None,
                    "profit_factor": None, "by_signal": {}}

        total = len(rows)
        wins  = [r for r in rows if r["result"] == "WIN"]
        losses = [r for r in rows if r["result"] == "LOSS"]
        win_rate = len(wins) / total * 100 if total else 0

        all_pips  = [r["pips"] for r in rows if r["pips"] is not None]
        avg_pips  = sum(all_pips) / len(all_pips) if all_pips else 0

        win_pips  = sum(r["pips"] for r in wins  if r["pips"])
        loss_pips = abs(sum(r["pips"] for r in losses if r["pips"]))
        pf = win_pips / loss_pips if loss_pips else float("inf")

        return {
            "total":         total,
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":      round(win_rate, 1),
            "avg_pips":      round(avg_pips, 1),
            "profit_factor": round(pf, 2),
        }

    def get_signal_stats(self) -> list[dict]:
        """シグナル別の実績勝率ランキングを返す（デモ結果から算出）"""
        import json
        conn = _get_conn()
        rows = conn.execute(
            "SELECT signals, result, pips, pair FROM fx_demo_positions "
            "WHERE status='CLOSED' AND signals IS NOT NULL"
        ).fetchall()
        conn.close()

        sig_map: dict[str, dict] = {}
        for r in rows:
            try:
                sigs = json.loads(r["signals"])
            except Exception:
                continue
            key = " + ".join(sorted(sigs[:2]))
            if key not in sig_map:
                sig_map[key] = {"label": key, "wins": 0, "total": 0, "pips": []}
            sig_map[key]["total"] += 1
            if r["result"] == "WIN":
                sig_map[key]["wins"] += 1
            if r["pips"]:
                sig_map[key]["pips"].append(r["pips"])

        result = []
        for v in sig_map.values():
            if v["total"] < 3:
                continue
            wr = v["wins"] / v["total"] * 100
            ap = sum(v["pips"]) / len(v["pips"]) if v["pips"] else 0
            result.append({
                "label":    v["label"],
                "total":    v["total"],
                "win_rate": round(wr, 1),
                "avg_pips": round(ap, 1),
            })
        result.sort(key=lambda x: -x["win_rate"])
        return result

    def get_open_positions(self) -> list[dict]:
        return list(self._open.values())

    # ─── 内部 ────────────────────────────────────────────────────────
    def _load_open_from_db(self) -> None:
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM fx_demo_positions WHERE status='OPEN'"
            ).fetchall()
            conn.close()
            for r in rows:
                key = f"{r['pair']}_{r['interval']}_{r['direction']}"
                self._open[key] = dict(r)
            if self._open:
                logger.info(f"[FxDemo] {len(self._open)}件のOPENポジションをDBから復元")
        except Exception as e:
            logger.warning(f"[FxDemo] DB復元エラー: {e}")

    def _close_db(self, pos_id: int, close_price: float,
                  result: str, pips: float) -> None:
        conn = _get_conn()
        conn.execute("""
            UPDATE fx_demo_positions
            SET closed_at=?, close_price=?, result=?, pips=?, status='CLOSED'
            WHERE id=?
        """, (datetime.now().isoformat(), close_price, result, pips, pos_id))
        conn.commit()
        conn.close()

    @staticmethod
    def _calc_pips(pair: str, entry: float, close: float, direction: str) -> float:
        pf = 0.01 if pair in ("USDJPY", "EURJPY") else (0.1 if pair == "XAUUSD" else 0.0001)
        diff = (close - entry) if direction == "buy" else (entry - close)
        return round(diff / pf, 1)
