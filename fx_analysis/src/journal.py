import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "journal.db"

_CREATE = """
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pair          TEXT    NOT NULL,
    timeframe     TEXT,
    direction     TEXT    NOT NULL,
    entry_time    TEXT    NOT NULL,
    entry_price   REAL    NOT NULL,
    exit_time     TEXT,
    exit_price    REAL,
    lot           REAL,

    sig_bb        INTEGER DEFAULT 0,
    sig_macd      INTEGER DEFAULT 0,
    sig_rsi       INTEGER DEFAULT 0,
    sig_stoch     INTEGER DEFAULT 0,
    sig_ma        INTEGER DEFAULT 0,
    sig_divergence INTEGER DEFAULT 0,

    confidence    INTEGER,
    notes         TEXT,
    created_at    TEXT    DEFAULT CURRENT_TIMESTAMP
)
"""

_WIN_EXPR = """
    CASE
        WHEN direction='buy'  AND exit_price > entry_price THEN 1
        WHEN direction='sell' AND exit_price < entry_price THEN 1
        ELSE 0
    END
"""

_SIG_COUNT = "(sig_bb + sig_macd + sig_rsi + sig_stoch + sig_ma + sig_divergence)"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE)
    conn.commit()
    return conn


def add_trade(data: dict) -> int:
    with _conn() as conn:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        cur = conn.execute(
            f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        return cur.lastrowid


def close_trade(trade_id: int, exit_time: str, exit_price: float):
    with _conn() as conn:
        conn.execute(
            "UPDATE trades SET exit_time=?, exit_price=? WHERE id=?",
            (exit_time, exit_price, trade_id),
        )


def list_trades(limit: int = 20) -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def signal_analysis() -> dict:
    """確認シグナル数・種類・確信度ごとの勝率を返す（決済済みトレードのみ）。"""
    with _conn() as conn:
        by_count = conn.execute(f"""
            SELECT {_SIG_COUNT} AS sig_count,
                   COUNT(*) AS total,
                   SUM({_WIN_EXPR}) AS wins
            FROM trades
            WHERE exit_price IS NOT NULL
            GROUP BY sig_count
            ORDER BY sig_count
        """).fetchall()

        by_signal = []
        for col in ["sig_bb", "sig_macd", "sig_rsi", "sig_stoch", "sig_ma", "sig_divergence"]:
            row = conn.execute(f"""
                SELECT COUNT(*) AS total,
                       SUM({_WIN_EXPR}) AS wins
                FROM trades
                WHERE exit_price IS NOT NULL AND {col} = 1
            """).fetchone()
            if row and row["total"] >= 3:
                by_signal.append({
                    "signal": col.replace("sig_", ""),
                    "total": row["total"],
                    "wins": row["wins"] or 0,
                })

        by_conf = conn.execute(f"""
            SELECT confidence,
                   COUNT(*) AS total,
                   SUM({_WIN_EXPR}) AS wins
            FROM trades
            WHERE exit_price IS NOT NULL AND confidence IS NOT NULL
            GROUP BY confidence
            ORDER BY confidence DESC
        """).fetchall()

    return {
        "by_count":      [dict(r) for r in by_count],
        "by_signal":     by_signal,
        "by_confidence": [dict(r) for r in by_conf],
    }
