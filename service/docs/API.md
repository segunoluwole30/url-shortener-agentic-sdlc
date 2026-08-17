# URL Shortener API (draft)

> Draft — written from the design before implementation/tests exist.
> Finalized by the docs_finalize stage once test_execution has run.

## POST /api/links
Create a short link. `custom_alias` is optional — omit it for a system-generated
7-char alias, or supply one to claim a specific alias (3-32 chars, letters/digits/
hyphen/underscore, not a reserved word). `ttl_seconds` is optional — omit it for a
link that never expires.

Request: `{"long_url": "https://example.com/very/long/path", "custom_alias": null, "ttl_seconds": null}`
Response (201): `{"alias": "aZ3kq9x", "short_url": "/aZ3kq9x", "long_url": "...", "created": true, "expires_at": null}`

Errors:
- 422 if long_url doesn't start with http:// or https://
- 422 if custom_alias fails format validation or is a reserved word
- 422 if ttl_seconds is present but not a positive integer
- 409 if custom_alias is already in use by a different long_url

## GET /{alias}
Redirect to the original URL. 302 on success, 404 if the alias is unknown,
410 if the alias existed but its TTL has elapsed.

## GET /api/links/{alias}/stats
Return click analytics for a link. 404 if the alias is unknown. Still returns
200 for an expired alias — expiry only blocks the redirect, not analytics access.

Response: `{"alias": "...", "long_url": "...", "created_at": "...", "expires_at": null, "click_count": N,
"clicks": [{"timestamp": "...", "referrer": "..."}]}`

## GET /healthz
Readiness check for monitoring/load-balancer probes. Verifies DB connectivity, not just
process liveness.

Response (200): `{"status": "ok"}`
Response (503): DB unreachable.

Writes on link creation and click recording retry automatically (bounded, with backoff)
on transient SQLite write-lock contention — no client-visible change, just fewer spurious
failures under concurrent load.

---

## Verified

======================== 26 passed, 1 warning in 0.38s ========================= (service/tests/test_api.py)
