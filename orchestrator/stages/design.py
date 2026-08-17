"""design stage handler — Step 3.

Writes service/docs/DESIGN.md summarizing the architecture the
implementation/test/docs stages will build against, then (per StageDef in
graph.py) the runner blocks for human approval before this stage's exit
gate can pass — design-log.md Section 5.
"""
from __future__ import annotations

from pathlib import Path

from ..state import RunState

SERVICE_DIR = Path(__file__).resolve().parent.parent.parent / "service"

DESIGN_DOC = """# URL Shortener — Design

Derived from design-log.md Sections 1-2 (normalized requirement + stage graph).

## Components

- **service/app/db.py** — SQLite persistence: `links(alias PK, long_url, created_at, expires_at)`,
  `clicks(id PK, alias FK, timestamp, referrer)`. `expires_at` is added via migration on startup for
  DBs created before TTL support existed.
- **service/app/shortener.py** — alias generation (7-char base62, `secrets`-backed),
  bounded collision retry (max 5 attempts), URL validation, idempotent creation
  (same `long_url` returns the existing alias rather than minting a new one).
- **service/app/analytics.py** — click recording + per-alias stats aggregation.
- **service/app/rate_limit.py** — in-memory fixed-window rate limiter, applied only to link creation.
- **service/app/main.py** — FastAPI app wiring the three endpoints below.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | /api/links | Create a short link. Accepts optional `custom_alias` and `ttl_seconds`. 201 with `{alias, short_url, long_url, created, expires_at}`. 422 on invalid URL/alias/ttl, 409 on custom-alias conflict, 429 on rate limit exceeded (with `Retry-After`). |
| GET | /{alias} | Redirect (302) to the original URL; records a click. 404 on unknown alias, 410 on expired alias. Not rate-limited. |
| GET | /api/links/{alias}/stats | Click count, timestamps, referrers, expires_at for a link. 404 on unknown alias (still readable after expiry). Not rate-limited. |
| GET | /healthz | Readiness check: verifies DB connectivity. 200 `{"status": "ok"}`, 503 if DB unreachable. Not rate-limited. |

## Reliability characteristics (design-log.md Section 1, ambiguity #5)

- Idempotent creation: re-submitting the same `long_url` (with no custom alias) returns the same alias.
- Input validation: URLs must start with `http://`/`https://`, rejected with 422 otherwise.
- Bounded alias-collision retry (max 5 attempts) before failing with 503 —
  mirrors the orchestration engine's own bounded-retry pattern
  (`orchestrator/retry.py`), applied at the domain level instead of the
  pipeline-stage level. Applies only to *generated* aliases.
- Graceful 404 on unknown/expired aliases rather than a 500.

## Custom aliases (design-log.md Section 8, greenfield scenario)

- Optional `custom_alias` field on `POST /api/links`: 3-32 chars, letters/digits/hyphen/underscore,
  a small reserved-word list (`api`) rejected with 422.
- Collision handling is deliberately different from generated aliases: an already-taken custom alias
  for a *different* URL returns 409 Conflict rather than silently substituting a different alias —
  the caller asked for something specific and gets that or a clear "no," never a silent swap.
- Idempotency is scoped to the exact (alias, long_url) pair for custom-alias requests, not to
  long_url alone, so requesting a custom alias for a URL that already has a different alias doesn't
  silently return the old one.

## Link expiration/TTL (design-log.md Section 8, brownfield scenario)

- Optional `ttl_seconds` field on `POST /api/links`; omitted means the link never expires.
- Enforced lazily at read-time in the redirect handler, not via a background sweep — no scheduler
  needed for a single-process prototype. Expired rows stay in the DB, just unreachable via redirect.
- Expired-but-present is a distinct outcome from never-existed: redirect returns 410 Gone for an
  expired alias vs 404 for an unknown one. Stats access is NOT gated by expiry — owners can still
  see final click counts for an expired link.
- Idempotent repeats never extend an existing link's expiry (idempotent = no-op, not "refresh TTL").
- Existing DBs created before this feature are migrated in place (`ALTER TABLE` on startup) rather
  than requiring a fresh table — genuinely brownfield: an existing data flow being extended.

## Rate limiting (design-log.md Section 8, brownfield scenario)

- Applies to `POST /api/links` only — creation is the resource-consuming, abuse-prone
  operation. Redirects and stats reads are deliberately NOT rate-limited; a public
  redirect service needs those to stay fast and always-available.
- Fixed-window counter keyed by client IP, default 10 requests / 60 seconds, configurable
  via `RATE_LIMIT_MAX_REQUESTS`/`RATE_LIMIT_WINDOW_SECONDS`.
- 429 with a `Retry-After` header on exceeded — a well-behaved client can back off
  correctly rather than guess.
- In-memory, single-process: does not survive a restart, not shared across multiple
  app instances — a real limitation for a production deployment, noted in Section 9
  rather than hidden.

## Reliability improvements (design-log.md Section 8, ambiguous scenario)

The raw requirement ("make it more reliable") named no concrete feature — disambiguated
via explicit candidate analysis recorded in the run's decision log (state.json), not just
here. Two candidates were selected, three deferred with reasons; see decisions for detail.

- **Write-lock retry**: `db.execute_with_retry()` wraps the two hot write paths (link
  creation, click recording) with bounded retry (3 attempts) + exponential backoff on
  SQLite's "database is locked" — a real risk under concurrent load with SQLite's
  single-writer model, previously unhandled anywhere in the codebase. Non-lock
  `OperationalError`s are NOT retried (retrying a genuine bug just delays the failure).
- **GET /healthz**: verifies DB connectivity (not just process liveness), not rate-limited,
  reserved in `RESERVED_ALIASES` so a custom alias can never shadow it.

## Out of scope for v1 (design-log.md Section 1)

Auth/ownership — not yet addressed. (Custom aliases, link expiration/TTL, rate
limiting, and the two reliability improvements above moved from "out of scope"
to implemented.)
"""


def handler(state: RunState) -> None:
    docs_dir = SERVICE_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "DESIGN.md").write_text(DESIGN_DOC)
    state.add_artifact("design", "service/docs/DESIGN.md")
    state.add_decision(
        stage="design",
        decision="proposed SQLite-backed FastAPI design with 3 endpoints (create/redirect/stats)",
        rationale="matches design-log.md Section 1 normalized requirement; SQLite is sufficient for a "
        "single-process prototype and keeps setup to zero external services",
        actor="agent",
    )
