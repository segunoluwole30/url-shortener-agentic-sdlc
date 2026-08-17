"""test_planning stage handler — Step 3.

Runs in parallel with implementation/docs_drafting (all three depend only on
design). Writes the test plan that test_execution's real pytest suite
implements once the code exists.
"""
from __future__ import annotations

from pathlib import Path

from ..state import RunState

SERVICE_DIR = Path(__file__).resolve().parent.parent.parent / "service"

TEST_PLAN = """# URL Shortener — Test Plan

Derived from design-log.md Section 1 assumptions + service/docs/DESIGN.md.

| # | Case | Expected |
|---|---|---|
| 1 | POST /api/links with a valid URL | 201, 7-char alias, created=true |
| 2 | POST /api/links twice with the same long_url | second call returns same alias, created=false |
| 3 | POST /api/links with a non-http(s) URL | 422 |
| 4 | GET /{alias} for a known alias | 302 redirect to the original long_url |
| 5 | GET /{alias} for an unknown alias | 404 |
| 6 | GET /api/links/{alias}/stats after N redirects | click_count == N, referrers recorded |
| 7 | GET /api/links/{alias}/stats for an unknown alias | 404 |
| 8 | POST /api/links with a valid custom_alias | 201, alias == requested custom_alias, created=true |
| 9 | POST /api/links twice with the same (long_url, custom_alias) | second call is idempotent, created=false |
| 10 | POST /api/links with custom_alias already used by a different long_url | 409 |
| 11 | POST /api/links with a malformed custom_alias (too short / bad chars) | 422 |
| 12 | POST /api/links with custom_alias == a reserved word (e.g. "api") | 422 |
| 13 | POST /api/links with custom_alias for a URL that already has a different alias | new alias used, NOT the old one |
| 14 | GET /{custom_alias} for a link created via custom_alias | 302 redirect to the original long_url |

Implemented as `service/tests/test_api.py` by the test_execution stage, run against
a temporary SQLite DB (via SHORTENER_DB_PATH override) so pipeline runs never
pollute each other's data.
"""


def handler(state: RunState) -> None:
    tests_dir = SERVICE_DIR / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "TEST_PLAN.md").write_text(TEST_PLAN)
    state.add_artifact("test_planning", "service/tests/TEST_PLAN.md")
