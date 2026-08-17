"""FastAPI app: create / redirect / analytics APIs for the URL shortener.

Written by orchestrator/stages/implementation.py during the orchestration
engine's implementation stage — see design-log.md Section 1 for the
normalized requirement + assumptions this implements, and
service/docs/DESIGN.md for the architecture.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import analytics, db, shortener
from .models import CreateLinkResponse, CreateLinkRequest, LinkStats


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="URL Shortener", version="1.0.0", lifespan=lifespan)


@app.post("/api/links", response_model=CreateLinkResponse, status_code=201)
def create_link(payload: CreateLinkRequest) -> CreateLinkResponse:
    try:
        alias, created, expires_at = shortener.create_link(
            payload.long_url, custom_alias=payload.custom_alias, ttl_seconds=payload.ttl_seconds
        )
    except shortener.InvalidURLError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except shortener.InvalidAliasError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except shortener.InvalidTTLError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except shortener.AliasConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except shortener.AliasGenerationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return CreateLinkResponse(
        alias=alias, short_url=f"/{alias}", long_url=payload.long_url, created=created, expires_at=expires_at
    )


@app.get("/api/links/{alias}/stats", response_model=LinkStats)
def link_stats(alias: str) -> LinkStats:
    stats = analytics.get_stats(alias)
    if stats is None:
        raise HTTPException(status_code=404, detail="unknown alias")
    return LinkStats(**stats)


@app.get("/healthz")
def health_check():
    """Readiness check (design-log.md Section 8, ambiguous scenario — see
    the run's decision log for why this was selected). Verifies DB
    connectivity, not just process liveness: a process that's up but can't
    reach its only dependency isn't actually healthy for this service.
    Registered ahead of GET /{alias} and reserved in shortener.py's
    RESERVED_ALIASES so a custom alias can never shadow it."""
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="database unreachable")
    return {"status": "ok"}


@app.get("/{alias}")
def redirect(alias: str, request: Request):
    try:
        long_url = shortener.get_long_url(alias)
    except shortener.LinkExpiredError as e:
        raise HTTPException(status_code=410, detail=str(e))
    if long_url is None:
        raise HTTPException(status_code=404, detail="unknown alias")
    analytics.record_click(alias, request.headers.get("referer"))
    return RedirectResponse(url=long_url, status_code=302)
