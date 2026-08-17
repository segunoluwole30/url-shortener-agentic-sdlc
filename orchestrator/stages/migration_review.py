"""migration_review stage handler.

Conditionally inserted into the graph by orchestrator/graph.py's plan_for()
when requirements signals a schema migration needs verifying (currently: the
TTL brownfield scenario) — design-log.md Section 2 addendum ("dynamic
re-planning", Core Requirement 4). Runs after `implementation`, in parallel
with test_planning/docs_drafting, verifying the REAL just-generated
service/app/db.py's migration path against a synthetic pre-migration
database — the same check done manually, out-of-band, earlier in this
project's history, now a governed pipeline stage instead.
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..retry import StageFailure
from ..state import RunState

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_DIR = REPO_ROOT / "service"


def _build_legacy_db(path: Path) -> None:
    """A synthetic pre-migration DB: links table with no expires_at column,
    one legacy row — mirrors the real shape a pre-TTL deployment would have."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE links (alias TEXT PRIMARY KEY, long_url TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, alias TEXT NOT NULL, "
            "timestamp TEXT NOT NULL, referrer TEXT, FOREIGN KEY (alias) REFERENCES links(alias))"
        )
        conn.execute(
            "INSERT INTO links (alias, long_url, created_at) VALUES (?, ?, ?)",
            ("legacy1", "https://example.com/legacy", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def handler(state: RunState) -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    legacy_db_path = Path(tmp.name)
    _build_legacy_db(legacy_db_path)

    prior_env = os.environ.get("SHORTENER_DB_PATH")
    os.environ["SHORTENER_DB_PATH"] = str(legacy_db_path)
    try:
        from service.app import db as service_db  # the REAL, just-generated module

        importlib.reload(service_db)  # ensure the on-disk version this run just wrote is used
        service_db.init_db()

        conn = sqlite3.connect(legacy_db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(links)")}
            row = conn.execute(
                "SELECT alias, long_url, expires_at FROM links WHERE alias = ?", ("legacy1",)
            ).fetchone()
        finally:
            conn.close()
    finally:
        if prior_env is None:
            os.environ.pop("SHORTENER_DB_PATH", None)
        else:
            os.environ["SHORTENER_DB_PATH"] = prior_env
        legacy_db_path.unlink(missing_ok=True)

    if "expires_at" not in columns:
        raise StageFailure("migration_review: expires_at column was not added via ALTER TABLE")
    if row is None or row[2] is not None:
        raise StageFailure("migration_review: legacy row did not survive migration with expires_at=NULL")

    report = (
        "# Migration Review\n\n"
        "Verified against the real generated `service/app/db.py`: a synthetic pre-TTL database "
        "(no `expires_at` column, one legacy row) was migrated via `init_db()`. Result:\n\n"
        "- `expires_at` column added: yes\n"
        f"- legacy row survived: yes (alias={row[0]!r}, long_url={row[1]!r})\n"
        f"- legacy row's expires_at: {row[2]!r} (None = never expires, correct default for "
        "pre-existing data)\n"
    )
    report_path = SERVICE_DIR / "docs" / "MIGRATION_REVIEW.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report)
    state.add_artifact("migration_review", "service/docs/MIGRATION_REVIEW.md")
    state.add_decision(
        stage="migration_review",
        decision="migration verified safe",
        rationale="pre-TTL DB migrated cleanly via the real generated db.py: expires_at column "
        "added, legacy row preserved with expires_at=NULL",
        actor="agent",
    )
