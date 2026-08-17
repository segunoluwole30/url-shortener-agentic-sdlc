# URL Shortener — Design

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

## Out of scope for v1 (design-log.md Section 1)

Auth/ownership — not yet addressed. (Custom aliases, link expiration/TTL, and
rate limiting moved from "out of scope" to implemented — see above.)
