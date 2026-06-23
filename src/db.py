from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .dates import now_text


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT,
    is_st INTEGER NOT NULL DEFAULT 0,
    is_star INTEGER NOT NULL DEFAULT 0,
    is_chinext INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    two_limit_date TEXT NOT NULL,
    pool_date TEXT NOT NULL,
    monitor_until TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(code, two_limit_date),
    FOREIGN KEY(code) REFERENCES stocks(code)
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    volume_ratio REAL,
    turnover_amount REAL,
    is_limit_up INTEGER NOT NULL DEFAULT 0,
    is_one_word_board INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(code, trade_date, captured_at),
    FOREIGN KEY(code) REFERENCES stocks(code)
);

CREATE TABLE IF NOT EXISTS fund_flow_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    main_net_inflow REAL,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(code, trade_date),
    FOREIGN KEY(code) REFERENCES stocks(code)
);

CREATE TABLE IF NOT EXISTS strategy_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    candidate_pool_id INTEGER,
    volume_ratio_ok INTEGER NOT NULL,
    turnover_amount_ok INTEGER NOT NULL,
    fund_flow_3d REAL,
    fund_flow_ok INTEGER NOT NULL,
    final_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(code, trade_date, candidate_pool_id),
    FOREIGN KEY(code) REFERENCES stocks(code),
    FOREIGN KEY(candidate_pool_id) REFERENCES candidate_pool(id)
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    run_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    message TEXT,
    rows_processed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS email_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    email_type TEXT NOT NULL,
    recipient TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    UNIQUE(code, trade_date, email_type, recipient)
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def init(self) -> None:
        self.db.init()

    def upsert_stock(self, stock: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO stocks (code, name, market, is_st, is_star, is_chinext, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name,
                    market=excluded.market,
                    is_st=excluded.is_st,
                    is_star=excluded.is_star,
                    is_chinext=excluded.is_chinext,
                    updated_at=excluded.updated_at
                """,
                (
                    stock["code"],
                    stock["name"],
                    stock.get("market"),
                    int(bool(stock.get("is_st"))),
                    int(bool(stock.get("is_star"))),
                    int(bool(stock.get("is_chinext"))),
                    now_text(),
                ),
            )

    def add_candidate(self, stock: dict[str, Any], two_limit_date: str, monitor_until: str) -> bool:
        self.upsert_stock(stock)
        with self.db.connect() as conn:
            existing = conn.execute(
                """
                SELECT 1
                FROM candidate_pool
                WHERE code = ? AND two_limit_date = ?
                """,
                (stock["code"], two_limit_date),
            ).fetchone()
            if existing is not None:
                return False

            conn.execute(
                """
                UPDATE candidate_pool
                SET status = 'replaced', updated_at = ?
                WHERE code = ? AND status = 'active'
                """,
                (now_text(), stock["code"]),
            )
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO candidate_pool
                    (code, two_limit_date, pool_date, monitor_until, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (stock["code"], two_limit_date, two_limit_date, monitor_until, now_text(), now_text()),
            )
            return conn.total_changes > before

    def active_candidates(self, trade_date: str) -> list[sqlite3.Row]:
        with self.db.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT cp.*, s.name, s.market, s.is_st, s.is_star, s.is_chinext
                    FROM candidate_pool cp
                    JOIN stocks s ON s.code = cp.code
                    WHERE cp.status = 'active' AND cp.monitor_until >= ?
                    ORDER BY cp.pool_date DESC, cp.code
                    """,
                    (trade_date,),
                )
            )

    def expire_candidates(self, trade_date: str) -> int:
        with self.db.connect() as conn:
            before = conn.total_changes
            conn.execute(
                """
                UPDATE candidate_pool
                SET status = 'expired', updated_at = ?
                WHERE status = 'active' AND monitor_until < ?
                """,
                (now_text(), trade_date),
            )
            return conn.total_changes - before

    def insert_daily_snapshot(self, row: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_snapshots
                    (code, trade_date, captured_at, volume_ratio, turnover_amount,
                     is_limit_up, is_one_word_board, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["code"],
                    row["trade_date"],
                    row["captured_at"],
                    row.get("volume_ratio"),
                    row.get("turnover_amount"),
                    int(bool(row.get("is_limit_up"))),
                    int(bool(row.get("is_one_word_board"))),
                    row.get("raw_json"),
                    now_text(),
                ),
            )

    def insert_fund_flow(self, row: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fund_flow_snapshots
                    (code, trade_date, main_net_inflow, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row["code"], row["trade_date"], row.get("main_net_inflow"), row.get("raw_json"), now_text()),
            )

    def recent_fund_sum(self, code: str, end_date: str, limit: int = 3) -> float:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT main_net_inflow
                FROM fund_flow_snapshots
                WHERE code = ? AND trade_date <= ? AND main_net_inflow IS NOT NULL
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (code, end_date, limit),
            ).fetchall()
            return float(sum(row["main_net_inflow"] or 0 for row in rows))

    def upsert_strategy_result(self, result: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_results
                    (code, trade_date, candidate_pool_id, volume_ratio_ok, turnover_amount_ok,
                     fund_flow_3d, fund_flow_ok, final_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, trade_date, candidate_pool_id) DO UPDATE SET
                    volume_ratio_ok=excluded.volume_ratio_ok,
                    turnover_amount_ok=excluded.turnover_amount_ok,
                    fund_flow_3d=excluded.fund_flow_3d,
                    fund_flow_ok=excluded.fund_flow_ok,
                    final_status=excluded.final_status,
                    created_at=excluded.created_at
                """,
                (
                    result["code"],
                    result["trade_date"],
                    result.get("candidate_pool_id"),
                    int(bool(result["volume_ratio_ok"])),
                    int(bool(result["turnover_amount_ok"])),
                    result.get("fund_flow_3d"),
                    int(bool(result["fund_flow_ok"])),
                    result["final_status"],
                    now_text(),
                ),
            )

    def mark_candidate_passed(self, candidate_pool_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE candidate_pool SET status = 'passed', updated_at = ? WHERE id = ?",
                (now_text(), candidate_pool_id),
            )

    def start_job(self, job_name: str, run_date: str) -> int:
        self.mark_stale_jobs()
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_runs (job_name, run_date, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (job_name, run_date, now_text()),
            )
            return int(cursor.lastrowid)

    def mark_stale_jobs(self, max_age_minutes: int = 120) -> int:
        with self.db.connect() as conn:
            before = conn.total_changes
            conn.execute(
                """
                UPDATE job_runs
                SET finished_at = ?, status = 'failed', message = COALESCE(message, '') || ?
                WHERE status = 'running'
                  AND datetime(started_at) <= datetime('now', 'localtime', ?)
                """,
                (now_text(), f"\nMarked stale after {max_age_minutes} minutes.", f"-{max_age_minutes} minutes"),
            )
            return conn.total_changes - before

    def finish_job(self, job_id: int, status: str, message: str = "", rows_processed: int = 0) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE job_runs
                SET finished_at = ?, status = ?, message = ?, rows_processed = ?
                WHERE id = ?
                """,
                (now_text(), status, message, rows_processed, job_id),
            )

    def email_already_sent(self, code: str, trade_date: str, email_type: str, recipient: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM email_logs
                WHERE code = ? AND trade_date = ? AND email_type = ? AND recipient = ?
                """,
                (code, trade_date, email_type, recipient),
            ).fetchone()
            return row is not None

    def log_email(self, code: str, trade_date: str, email_type: str, recipient: str, subject: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO email_logs
                    (code, trade_date, email_type, recipient, sent_at, subject)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (code, trade_date, email_type, recipient, now_text(), subject),
            )

    def get_api_cache(self, cache_key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM api_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            return str(row["payload"]) if row is not None else None

    def set_api_cache(self, cache_key: str, payload: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO api_cache (cache_key, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (cache_key, payload, now_text()),
            )
