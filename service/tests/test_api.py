"""Integration tests for the URL shortener API.

Written by orchestrator/stages/test_execution.py during the orchestration
engine's test_execution stage (design-log.md Section 2, sync point A — this
stage cannot start until implementation has produced real code to run
against). Cases follow service/tests/TEST_PLAN.md.
"""
from __future__ import annotations

import os
import tempfile

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
