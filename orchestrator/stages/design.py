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

- **service/app/db.py** — SQLite persistence: `links(alias PK, long_url, created_at)`,
  `clicks(id PK, alias FK, timestamp, referrer)`.
- **service/app/shortener.py** — alias generation (7-char base62, `secrets`-backed),
  bounded collision retry (max 5 attempts), URL validation, idempotent creation
  (same `long_url` returns the existing alias rather than minting a new one).
- **service/app/analytics.py** — click recording + per-alias stats aggregation.
- **service/app/main.py** — FastAPI app wiring the three endpoints below.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | /api/links | Create a short link. Accepts an optional `custom_alias`. 201 with `{alias, short_url, long_url, created}`. 422 on invalid URL/alias, 409 on custom-alias conflict. |
| GET | /{alias} | Redirect (302) to the original URL; records a click. 404 on unknown alias. |
| GET | /api/links/{alias}/stats | Click count, timestamps, referrers for a link. 404 on unknown alias. |

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

## Out of scope for v1 (design-log.md Section 1)

Link expiration/TTL, auth/ownership — reintroduced deliberately by later
scenarios rather than baked into the baseline. (Custom aliases moved from
"out of scope" to implemented — see above.)
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
