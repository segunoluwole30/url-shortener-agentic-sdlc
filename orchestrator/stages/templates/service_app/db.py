"""SQLite persistence for links and click analytics."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "shortener.db"


def db_path() -> Path:
    """Resolved dynamically (not cached) so tests can override
    SHORTENER_DB_PATH before the app's lifespan calls init_db()."""
    override = os.environ.get("SHORTENER_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


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
