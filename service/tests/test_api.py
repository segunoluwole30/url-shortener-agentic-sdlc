"""Integration tests for the URL shortener API.

Written by orchestrator/stages/test_execution.py during the orchestration
engine's test_execution stage (design-log.md Section 2, sync point A — this
stage cannot start until implementation has produced real code to run
against). Cases follow service/tests/TEST_PLAN.md.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    os.environ["SHORTENER_DB_PATH"] = tmp_db.name
    from service.app.main import app  # imported after env var set

    with TestClient(app) as c:
        yield c

    del os.environ["SHORTENER_DB_PATH"]
    os.remove(tmp_db.name)


def test_create_link_returns_seven_char_alias(client):
    resp = client.post("/api/links", json={"long_url": "https://example.com/some/long/path"})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["alias"]) == 7
    assert body["created"] is True


def test_create_link_is_idempotent_for_same_url(client):
    r1 = client.post("/api/links", json={"long_url": "https://example.com/dup"})
    r2 = client.post("/api/links", json={"long_url": "https://example.com/dup"})
    assert r1.json()["alias"] == r2.json()["alias"]
    assert r2.json()["created"] is False


def test_create_link_rejects_invalid_url(client):
    resp = client.post("/api/links", json={"long_url": "not-a-url"})
    assert resp.status_code == 422


def test_redirect_follows_to_long_url(client):
    created = client.post("/api/links", json={"long_url": "https://example.com/redirect-me"}).json()
    resp = client.get(f"/{created['alias']}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/redirect-me"


def test_redirect_unknown_alias_returns_404(client):
    resp = client.get("/doesnotexist", follow_redirects=False)
    assert resp.status_code == 404


def test_stats_track_click_count_and_referrer(client):
    created = client.post("/api/links", json={"long_url": "https://example.com/stats-me"}).json()
    alias = created["alias"]
    client.get(f"/{alias}", follow_redirects=False, headers={"referer": "https://google.com"})
    client.get(f"/{alias}", follow_redirects=False)
    stats = client.get(f"/api/links/{alias}/stats").json()
    assert stats["click_count"] == 2
    assert stats["clicks"][0]["referrer"] == "https://google.com"


def test_stats_unknown_alias_returns_404(client):
    resp = client.get("/api/links/doesnotexist/stats")
    assert resp.status_code == 404


# --- custom aliases (design-log.md Section 8, greenfield scenario) ------


def test_create_link_with_custom_alias_uses_it(client):
    resp = client.post(
        "/api/links", json={"long_url": "https://example.com/custom", "custom_alias": "my-link"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["alias"] == "my-link"
    assert body["created"] is True


def test_create_link_custom_alias_repeat_is_idempotent(client):
    payload = {"long_url": "https://example.com/custom-dup", "custom_alias": "dup-alias"}
    r1 = client.post("/api/links", json=payload)
    r2 = client.post("/api/links", json=payload)
    assert r1.json()["alias"] == r2.json()["alias"] == "dup-alias"
    assert r2.json()["created"] is False


def test_create_link_custom_alias_conflict_returns_409(client):
    client.post("/api/links", json={"long_url": "https://example.com/first", "custom_alias": "taken"})
    resp = client.post("/api/links", json={"long_url": "https://example.com/second", "custom_alias": "taken"})
    assert resp.status_code == 409


def test_create_link_custom_alias_invalid_format_rejected(client):
    resp = client.post(
        "/api/links", json={"long_url": "https://example.com/x", "custom_alias": "a"}  # too short
    )
    assert resp.status_code == 422

    resp2 = client.post(
        "/api/links", json={"long_url": "https://example.com/y", "custom_alias": "not valid!"}
    )
    assert resp2.status_code == 422


def test_create_link_custom_alias_reserved_word_rejected(client):
    resp = client.post("/api/links", json={"long_url": "https://example.com/z", "custom_alias": "api"})
    assert resp.status_code == 422


def test_create_link_custom_alias_does_not_reuse_existing_alias_for_same_url(client):
    """Requesting a custom alias for a URL that already has a different
    alias must NOT silently return the old alias — that would defeat the
    point of asking for a specific one (design-log.md Section 8)."""
    first = client.post("/api/links", json={"long_url": "https://example.com/reused"}).json()
    second = client.post(
        "/api/links", json={"long_url": "https://example.com/reused", "custom_alias": "explicit-one"}
    ).json()
    assert second["alias"] == "explicit-one"
    assert second["alias"] != first["alias"]
    assert second["created"] is True


def test_redirect_follows_custom_alias(client):
    client.post("/api/links", json={"long_url": "https://example.com/via-custom", "custom_alias": "goto"})
    resp = client.get("/goto", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/via-custom"


# --- link expiration/TTL (design-log.md Section 8, brownfield scenario) ---


def _backdate_expiry(alias: str) -> None:
    """Directly rewrite an alias's expires_at into the past, so expiry tests
    are deterministic and don't need a real sleep."""
    from service.app import db

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE links SET expires_at = ? WHERE alias = ?", (past, alias))
        conn.commit()


def test_create_link_with_ttl_sets_expires_at(client):
    resp = client.post("/api/links", json={"long_url": "https://example.com/ttl", "ttl_seconds": 3600})
    assert resp.status_code == 201
    assert resp.json()["expires_at"] is not None


def test_create_link_without_ttl_has_null_expires_at(client):
    resp = client.post("/api/links", json={"long_url": "https://example.com/no-ttl"})
    assert resp.status_code == 201
    assert resp.json()["expires_at"] is None


def test_create_link_rejects_non_positive_ttl(client):
    resp = client.post("/api/links", json={"long_url": "https://example.com/bad-ttl", "ttl_seconds": 0})
    assert resp.status_code == 422

    resp2 = client.post("/api/links", json={"long_url": "https://example.com/bad-ttl2", "ttl_seconds": -5})
    assert resp2.status_code == 422


def test_redirect_before_expiry_still_works(client):
    created = client.post(
        "/api/links", json={"long_url": "https://example.com/not-yet-expired", "ttl_seconds": 3600}
    ).json()
    resp = client.get(f"/{created['alias']}", follow_redirects=False)
    assert resp.status_code == 302


def test_redirect_after_expiry_returns_410(client):
    created = client.post(
        "/api/links", json={"long_url": "https://example.com/will-expire", "ttl_seconds": 1}
    ).json()
    _backdate_expiry(created["alias"])
    resp = client.get(f"/{created['alias']}", follow_redirects=False)
    assert resp.status_code == 410


def test_stats_still_accessible_after_expiry(client):
    created = client.post(
        "/api/links", json={"long_url": "https://example.com/expired-stats", "ttl_seconds": 1}
    ).json()
    _backdate_expiry(created["alias"])
    resp = client.get(f"/api/links/{created['alias']}/stats")
    assert resp.status_code == 200


def test_create_link_idempotent_repeat_keeps_original_expiry(client):
    r1 = client.post(
        "/api/links", json={"long_url": "https://example.com/keep-expiry", "ttl_seconds": 100}
    ).json()
    r2 = client.post(
        "/api/links", json={"long_url": "https://example.com/keep-expiry", "ttl_seconds": 999999}
    ).json()
    assert r2["alias"] == r1["alias"]
    assert r2["expires_at"] == r1["expires_at"]  # not extended by the second request's ttl_seconds


# --- reliability improvements (design-log.md Section 8, ambiguous scenario) ---
# The two candidates selected during disambiguation: bounded write-lock retry
# and a DB-connectivity health check. See the run's decision log
# (state.json's `decisions`, stage="requirements") for why these two were
# picked and why structured logging / circuit breakers were deferred.


def test_execute_with_retry_recovers_from_transient_lock(monkeypatch):
    from service.app import db

    monkeypatch.setattr(db, "WRITE_RETRY_BASE_DELAY", 0.001)  # keep the test fast
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert db.execute_with_retry(flaky) == "ok"
    assert calls["n"] == 3


def test_execute_with_retry_raises_after_max_attempts(monkeypatch):
    from service.app import db

    monkeypatch.setattr(db, "WRITE_RETRY_BASE_DELAY", 0.001)

    def always_locked():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        db.execute_with_retry(always_locked)


def test_execute_with_retry_does_not_retry_non_lock_errors():
    from service.app import db

    calls = {"n": 0}

    def other_error():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: foo")

    with pytest.raises(sqlite3.OperationalError):
        db.execute_with_retry(other_error)
    assert calls["n"] == 1  # not retried


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_link_reserved_word_healthz_rejected(client):
    resp = client.post("/api/links", json={"long_url": "https://example.com/hz", "custom_alias": "healthz"})
    assert resp.status_code == 422
