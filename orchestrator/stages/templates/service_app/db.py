"""SQLite persistence for links and click analytics."""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypeVar

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "shortener.db"

# Bounded retry for SQLite write-lock contention (design-log.md Section 8,
# ambiguous scenario — see the run's decision log for the disambiguation
# that led here). Mirrors the same bounded-retry pattern already used for
# alias-generation collisions (shortener.py) and the orchestration engine
# itself (orchestrator/retry.py) — same philosophy, applied here to a
# different transient-failure class.
WRITE_RETRY_MAX_ATTEMPTS = 3
WRITE_RETRY_BASE_DELAY = 0.05  # seconds; doubles each attempt

T = TypeVar("T")


def db_path() -> Path:
    """Resolved dynamically (not cached) so tests can override
    SHORTENER_DB_PATH before the app's lifespan calls init_db()."""
    override = os.environ.get("SHORTENER_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def execute_with_retry(fn: Callable[[], T]) -> T:
    """Runs fn() (expected to perform one or more writes via get_conn())
    with bounded retry + exponential backoff, but ONLY for SQLite's
    "database is locked" — a transient failure from write contention under
    concurrent load, not a bug. Any other OperationalError (e.g. a genuine
    schema problem) is NOT retried, since retrying a non-transient error
    just delays the same failure."""
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(WRITE_RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
            last_error = e
            if attempt < WRITE_RETRY_MAX_ATTEMPTS - 1:
                time.sleep(WRITE_RETRY_BASE_DELAY * (2**attempt))
    assert last_error is not None
    raise last_error


@contextmanager
def get_conn():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Brownfield migration: an existing DB file created before TTL support
    (design-log.md Section 8) already has a `links` table without
    `expires_at`. CREATE TABLE IF NOT EXISTS alone would leave that column
    missing forever, so check for it explicitly and ALTER TABLE if absent."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db() -> None:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS links ("
            "alias TEXT PRIMARY KEY, "
            "long_url TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS clicks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "alias TEXT NOT NULL, "
            "timestamp TEXT NOT NULL, "
            "referrer TEXT, "
            "FOREIGN KEY (alias) REFERENCES links(alias))"
        )
        _add_column_if_missing(conn, "links", "expires_at", "TEXT")  # NULL = never expires
        conn.commit()
