"""FastAPI app: create / redirect / analytics APIs for the URL shortener.

Written by orchestrator/stages/implementation.py during the orchestration
engine's implementation stage — see design-log.md Section 1 for the
normalized requirement + assumptions this implements, and
service/docs/DESIGN.md for the architecture.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import analytics, db, rate_limit, shortener
from .models import CreateLinkResponse, CreateLinkRequest, LinkStats


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="URL Shortener", version="1.0.0", lifespan=lifespan)


def enforce_rate_limit(request: Request) -> None:
    """Dependency applied only to link creation — see rate_limit.py for why
    redirects are deliberately excluded."""
    client_key = request.client.host if request.client else "unknown"
    try:
        rate_limit.check(client_key)
    except rate_limit.RateLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=str(e),
            headers={"Retry-After": str(int(e.retry_after) + 1)},
        )


@app.post("/api/links", response_model=CreateLinkResponse, status_code=201)
def create_link(payload: CreateLinkRequest, _: None = Depends(enforce_rate_limit)) -> CreateLinkResponse:
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
