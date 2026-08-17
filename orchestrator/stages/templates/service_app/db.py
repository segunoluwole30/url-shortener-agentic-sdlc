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
        conn.commit()
