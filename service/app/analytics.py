"""Click recording + per-link analytics (design-log.md Section 1, ambiguity #4)."""
from __future__ import annotations

from datetime import datetime, timezone

from . import db


def record_click(alias: str, referrer: str | None) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO clicks (alias, timestamp, referrer) VALUES (?, ?, ?)",
            (alias, datetime.now(timezone.utc).isoformat(), referrer),
        )
        conn.commit()


def get_stats(alias: str) -> dict | None:
    with db.get_conn() as conn:
        link = conn.execute(
            "SELECT alias, long_url, created_at FROM links WHERE alias = ?", (alias,)
        ).fetchone()
        if not link:
            return None
        clicks = conn.execute(
            "SELECT timestamp, referrer FROM clicks WHERE alias = ? ORDER BY timestamp", (alias,)
        ).fetchall()
        return {
            "alias": link["alias"],
            "long_url": link["long_url"],
            "created_at": link["created_at"],
            "click_count": len(clicks),
            "clicks": [{"timestamp": c["timestamp"], "referrer": c["referrer"]} for c in clicks],
        }
