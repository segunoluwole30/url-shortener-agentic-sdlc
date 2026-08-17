"""Alias generation + collision handling.

Collision handling assumption (design-log.md Section 1, ambiguity #3):
regenerate and retry on collision, bounded to MAX_ALIAS_ATTEMPTS before
failing the request — mirrors the orchestration engine's own bounded-retry
pattern (orchestrator/retry.py), applied at the domain level instead of the
pipeline-stage level. This ONLY applies to system-generated aliases.

Custom aliases (design-log.md Section 8, greenfield scenario) deliberately
do NOT use this retry-and-substitute behavior: a collision there is reported
as 409 Conflict so the caller can pick a different alias themselves, since
silently handing back a different alias than the one explicitly requested
would defeat the point of asking for a specific one.

TTL / expiration (design-log.md Section 8, brownfield scenario): expiration
is checked lazily at read-time (get_long_url), not via a background sweep —
simplest reliable approach for a single-process prototype, no scheduler
needed. Expired rows are never actively purged, just made unreachable
through this function; see design-log.md Section 9 for that tradeoff.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone

from . import db

ALPHABET = string.digits + string.ascii_letters  # base62
ALIAS_LENGTH = 7
MAX_ALIAS_ATTEMPTS = 5

CUSTOM_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
# "api" avoids confusion with the /api/* route prefix; "healthz" avoids a
# custom alias shadowing the health-check route added in the ambiguous
# scenario (design-log.md Section 8) — both are exact-match single-segment
# routes registered ahead of the GET /{alias} catch-all.
RESERVED_ALIASES = {"api", "healthz"}


class AliasGenerationError(Exception):
    """Raised when MAX_ALIAS_ATTEMPTS collisions occur in a row (generated aliases only)."""


class InvalidURLError(Exception):
    pass


class InvalidAliasError(Exception):
    """Raised when a requested custom alias fails format/reserved-word validation."""


class AliasConflictError(Exception):
    """Raised when a requested custom alias is already taken by a different URL."""


class InvalidTTLError(Exception):
    """Raised when ttl_seconds is present but not a positive integer."""


class LinkExpiredError(Exception):
    """Raised by get_long_url when the alias exists but its TTL has elapsed —
    distinct from "never existed" so callers can return 410 Gone instead of
    404 Not Found (design-log.md Section 8)."""


def _generate_alias() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(ALIAS_LENGTH))


def _validate_url(long_url: str) -> None:
    if not (long_url.startswith("http://") or long_url.startswith("https://")):
        raise InvalidURLError("URL must start with http:// or https://")
    if len(long_url) > 2048:
        raise InvalidURLError("URL too long (max 2048 chars)")


def _validate_custom_alias(alias: str) -> None:
    if not CUSTOM_ALIAS_PATTERN.match(alias):
        raise InvalidAliasError(
            "custom alias must be 3-32 characters: letters, digits, hyphen, or underscore only"
        )
    if alias.lower() in RESERVED_ALIASES:
        raise InvalidAliasError(f"alias {alias!r} is reserved")


def _compute_expires_at(ttl_seconds: int | None) -> str | None:
    if ttl_seconds is None:
        return None
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise InvalidTTLError("ttl_seconds must be a positive integer")
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _find_existing_alias(long_url: str) -> str | None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT alias FROM links WHERE long_url = ?", (long_url,)).fetchone()
        return row["alias"] if row else None


def _find_link(alias: str) -> sqlite3.Row | None:
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT alias, long_url, expires_at FROM links WHERE alias = ?", (alias,)
        ).fetchone()


def _insert_link(alias: str, long_url: str, expires_at: str | None) -> None:
    def _do_insert() -> None:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO links (alias, long_url, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (alias, long_url, datetime.now(timezone.utc).isoformat(), expires_at),
            )
            conn.commit()

    # Bounded retry for "database is locked" (design-log.md Section 8,
    # ambiguous scenario). sqlite3.IntegrityError (alias collision) is a
    # different exception type and is NOT retried here — it propagates
    # immediately to the collision-handling logic in create_link().
    db.execute_with_retry(_do_insert)


def create_link(
    long_url: str, custom_alias: str | None = None, ttl_seconds: int | None = None
) -> tuple[str, bool, str | None]:
    """Returns (alias, created, expires_at).

    custom_alias given: explicit intent to claim that specific alias, so the
    long_url-based idempotency lookup below is skipped entirely (design-log.md
    Section 8, greenfield scenario) — a caller asking for a specific alias
    gets that alias or a clear 409 conflict, never a silent substitution of
    an unrelated existing alias for the same URL. Idempotency here is scoped
    to the exact (alias, long_url) pair: repeating the same request is a
    no-op success (the ORIGINAL expires_at is returned, not a new one derived
    from this call's ttl_seconds — idempotent means "no-op", not "extend").

    custom_alias omitted: existing design-log.md Section 1 behavior —
    idempotent by long_url (same no-extend rule applies), then bounded
    generate-and-retry on collision.
    """
    _validate_url(long_url)
    expires_at = _compute_expires_at(ttl_seconds)

    if custom_alias is not None:
        _validate_custom_alias(custom_alias)
        existing = _find_link(custom_alias)
        if existing is not None:
            if existing["long_url"] == long_url:
                return custom_alias, False, existing["expires_at"]  # idempotent repeat
            raise AliasConflictError(f"alias {custom_alias!r} is already in use")
        try:
            _insert_link(custom_alias, long_url, expires_at)
        except sqlite3.IntegrityError:
            # Lost a race against a concurrent request for the same alias.
            raise AliasConflictError(f"alias {custom_alias!r} is already in use")
        return custom_alias, True, expires_at

    existing_alias = _find_existing_alias(long_url)
    if existing_alias:
        existing_row = _find_link(existing_alias)
        return existing_alias, False, existing_row["expires_at"] if existing_row else None

    for _ in range(MAX_ALIAS_ATTEMPTS):
        alias = _generate_alias()
        try:
            _insert_link(alias, long_url, expires_at)
            return alias, True, expires_at
        except sqlite3.IntegrityError:
            continue  # alias collision — regenerate and retry

    raise AliasGenerationError(f"failed to generate a unique alias after {MAX_ALIAS_ATTEMPTS} attempts")


def get_long_url(alias: str) -> str | None:
    """Returns the long URL, or None if the alias never existed.
    Raises LinkExpiredError if the alias exists but its TTL has elapsed."""
    link = _find_link(alias)
    if link is None:
        return None
    if link["expires_at"] is not None:
        expires_at = datetime.fromisoformat(link["expires_at"])
        if datetime.now(timezone.utc) >= expires_at:
            raise LinkExpiredError(f"alias {alias!r} expired at {link['expires_at']}")
    return link["long_url"]
