"""SQLite access helpers.

Each operation opens a short-lived connection (cheap for SQLite) so request
threads and scheduler threads never share a connection. ``transaction()`` uses
``BEGIN IMMEDIATE`` so read-modify-write sequences are atomic and writers are
serialised instead of failing with "database is locked".
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger("pe3k.db")

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_lock = threading.Lock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    # -- connections -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Autocommit connection for reads and single-statement writes."""
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic unit of work: commits on success, rolls back on any error."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - already rolled back
                pass
            raise
        finally:
            conn.close()

    # -- schema --------------------------------------------------------------
    def init_schema(self) -> None:
        with self._init_lock:
            conn = self.connect()
            try:
                if self.path != ":memory:":
                    conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                _migrate(conn)
            finally:
                conn.close()
        log.info("database ready", extra={"event": "db_ready", "path": self.path})

    def reset(self) -> None:
        """Drop every Pe3k table (used by the ``reset-db`` CLI command and tests)."""
        with self.transaction() as conn:
            for table in ("monitor_logs", "alerts", "bandwidth_logs", "scan_logs", "settings", "devices"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")  # fixed identifiers, not user input
        self.init_schema()


# Columns added after v1.0.0: (table, column, definition). Applied once to older databases.
MIGRATIONS = [
    ("scan_logs", "cached_found", "INTEGER NOT NULL DEFAULT 0"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, definition in MIGRATIONS:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}  # fixed identifiers
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            log.info("database migrated", extra={"event": "db_migrate", "table": table, "column": column})


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def row_to_dict(row) -> dict | None:
    return dict(row) if row is not None else None
