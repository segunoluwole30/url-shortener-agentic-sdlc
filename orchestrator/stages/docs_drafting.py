"""docs_drafting stage handler — Step 3.

Runs in parallel with implementation/test_planning. Drafts the API doc from
the design alone; docs_finalize folds in real test outcomes once they exist.
"""
from __future__ import annotations

from pathlib import Path

from ..state import RunState

SERVICE_DIR = Path(__file__).resolve().parent.parent.parent / "service"

API_DOC_DRAFT = """# URL Shortener API (draft)

> Draft — written from the design before implementation/tests exist.
> Finalized by the docs_finalize stage once test_execution has run.

## POST /api/links
Create a short link. `custom_alias` is optional — omit it for a system-generated
7-char alias, or supply one to claim a specific alias (3-32 chars, letters/digits/
hyphen/underscore, not a reserved word).

Request: `{"long_url": "https://example.com/very/long/path", "custom_alias": null}`
Response (201): `{"alias": "aZ3kq9x", "short_url": "/aZ3kq9x", "long_url": "...", "created": true}`
Errors:
- 422 if long_url doesn't start with http:// or https://
- 422 if custom_alias fails format validation or is a reserved word
- 409 if custom_alias is already in use by a different long_url

## GET /{alias}
Redirect to the original URL. 302 on success, 404 if the alias is unknown.

## GET /api/links/{alias}/stats
Return click analytics for a link. 404 if the alias is unknown.

Response: `{"alias": "...", "long_url": "...", "created_at": "...", "click_count": N,
"clicks": [{"timestamp": "...", "referrer": "..."}]}`
"""


def handler(state: RunState) -> None:
    docs_dir = SERVICE_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "API.md").write_text(API_DOC_DRAFT)
    state.add_artifact("docs_drafting", "service/docs/API.md")
