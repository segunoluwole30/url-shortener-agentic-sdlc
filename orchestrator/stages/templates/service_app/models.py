"""Pydantic request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateLinkRequest(BaseModel):
    long_url: str = Field(..., description="The URL to shorten; must start with http:// or https://")
    custom_alias: str | None = Field(
        default=None,
        description="Optional user-chosen alias (3-32 chars: letters, digits, hyphen, underscore). "
        "If omitted, a 7-character alias is generated.",
    )
    ttl_seconds: int | None = Field(
        default=None,
        description="Optional time-to-live in seconds. If omitted, the link never expires.",
    )


class CreateLinkResponse(BaseModel):
    alias: str
    short_url: str
    long_url: str
    created: bool
    expires_at: str | None = None


class ClickRecord(BaseModel):
    timestamp: str
    referrer: str | None = None


class LinkStats(BaseModel):
    alias: str
    long_url: str
    created_at: str
    expires_at: str | None = None
    click_count: int
    clicks: list[ClickRecord]
