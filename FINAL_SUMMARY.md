# Final Engineering Summary

Interview assignment: build an agentic software engineering system (URL shortener).
This document is the assignment's Core Requirement #8 deliverable — plan/rationale,
artifacts, risks/trade-offs/validation, assumptions, and limitations. Full
decision-lineage detail (locked stage graph, state schema, gates, retry rules, and
per-scenario notes with orchestration/validation evidence) lives in
[`design-log.md`](design-log.md); setup/run instructions live in
[`README.md`](README.md). This document is the synthesis a reviewer can read
standalone.

---

## 1. Plan & Rationale

The assignment's explicit differentiator is the orchestration layer, not the
shortener itself ("Workflow Orchestration (Critical Differentiator)" — Core
Requirement 4). The plan followed from that directly: build a real, hand-rolled
state-machine/dependency-graph engine first (no LangGraph/Temporal/Airflow — every
gate check, retry decision, and approval block needed to be inspectable Python, not
framework magic, to be defensible in review), verify its mechanics in isolation
against synthetic graphs, *then* point it at a real domain (the URL shortener) and
have it build that domain stage by stage — so the shortener is evidence the
orchestrator works, not a separately-written thing the orchestrator merely
gestures at.

Work was staged in six explicit steps, each reviewed before the next began:

1. **Tech stack + layout.** Python (FastAPI + stdlib) for both the orchestrator and
   the service; a CLI-blocking (`input()`) mechanism for the human-approval
   checkpoint (unambiguous "halts execution until a human responds," no
   server/polling needed); JSON-file-per-run state persistence (human-readable,
   directly inspectable during review — the exact "audit-grade observability"
   goal).
2. **State schema + graph runner**, against a stub graph — no domain logic. The
   retry/fallback/rollback mechanics and genuine parallel fan-out (via
   `ThreadPoolExecutor`, not simulated ordering) were built and unit-tested here
   before any shortener code existed.
3. **Wiring the orchestrator to build the shortener for real** — the eight stage
   handlers produce real files (`service/app/*.py`, `service/tests/test_api.py`,
   `service/docs/*.md`) at run time; `test_execution` actually invokes `pytest` via
   subprocess rather than recording a simulated pass.
4. **Greenfield scenario** (custom aliases) — a genuinely new capability, run
   end-to-end through the pipeline.
5. **Brownfield scenario** (link expiration/TTL) — preceded by an explicit
   codebase-reasoning pass (which modules/files it touches, and why) before
   any code was written, per Core Requirement 3.
6. **Ambiguous scenario** ("make it more reliable") — disambiguated via explicit
   candidate analysis recorded as real decisions in the run's own decision log
   (`state.json`), not just narrated in this document or as source comments.

## 2. Architecture

**Orchestration engine** (`orchestrator/`): a locked 8-node dependency graph
(`requirements → design → {implementation, test_planning, docs_drafting} →
test_execution → docs_finalize → release_readiness`) walked by a thread-pool
scheduler that submits a stage the instant its entry gate (all dependencies
complete) passes — the three-way fan-out after `design` is genuine concurrent
execution, verified in `tests/test_orchestrator.py` by measured wall-clock
overlap, not asserted ordering. Every stage's exit gate is a real, checkable
predicate over state (design-log.md Section 4) — not a formality: `implementation`
only passes if its artifacts `py_compile` cleanly; `test_execution` only passes if
the *most recent* entry in that stage's logged history (state.json's `history`
list) is `tests_passed`, correctly
handling the retry-then-succeed case rather than a naive "no failure ever
happened" check that the append-only history would otherwise make impossible.

Two hard-blocking human approval checkpoints (`design`, `release_readiness`) —
deliberately not more; every other stage is governed mechanically by its exit
gate, since gating every stage on a human would make "controlled autonomy" into
"no autonomy" (design-log.md Section 5). Bounded retry (default 2 extra attempts)
→ one fallback attempt → stage-scoped rollback → run-level safe-stop
(`overall_status = "blocked"`) on exhaustion (design-log.md Section 6), verified
by dedicated unit tests including one that proves rollback reverts only the
failing stage's own state, not sibling stages that already completed in parallel.
Every transition is logged to both `state.json`'s `history` and a separate
append-only `audit.log`, and design-log.md Section 7's five metrics (success
rate, retry/rollback frequency, MTTR, end-to-end latency) are recomputed from
that same history on every write — never hand-set by a stage handler.

**Service** (`service/`): FastAPI + SQLite, built entirely by the orchestrator's
stage handlers via templates in `orchestrator/stages/templates/`. Three core
endpoints (create/redirect/stats) plus, by the end of the scenarios, optional
custom aliases, optional TTL expiration, and a `/healthz` readiness check.

## 3. Artifacts

- Working prototype: `orchestrator/` (engine) + `service/` (built by it) + `cli.py`
  (entrypoint) — runnable per [`README.md`](README.md).
- `design-log.md`: locked stage graph/schema/gates, retry rules, audit/metrics
  design, and full per-scenario notes (requirement text, codebase reasoning shown
  before coding for brownfield, key decisions, orchestration evidence with actual
  run IDs, and validation evidence for all three scenarios).
- Test suites: `tests/test_orchestrator.py` (7 tests, the engine in isolation) +
  `service/tests/test_api.py` (26 tests, written by the pipeline's own
  `test_execution` stage and run as subprocess `pytest` on every pipeline run —
  33 total, all passing as of the last run).
- `service/docs/DESIGN.md` + `service/docs/API.md`: written and finalized by the
  pipeline itself (`docs_drafting` → `docs_finalize`, folding in real test
  outcomes), not authored separately.
- `runs/<run_id>/{state.json,audit.log}`: a real run directory per scenario,
  inspectable directly — the literal audit trail, not a description of one.

## 4. Scenarios (summary — full detail in design-log.md Section 8)

- **Greenfield — custom aliases:** optional `custom_alias` on link creation.
  Collision on an existing alias returns 409 (not a silent substitute, unlike
  generated-alias collision handling); idempotency scoped to the exact
  `(alias, long_url)` pair so a custom-alias request can't be silently absorbed
  by the existing long_url-based idempotency check.
- **Brownfield — link expiration/TTL:** optional `ttl_seconds`; redirect
  returns 410 (expired) vs 404 (never existed) as distinct outcomes; analytics
  stay readable after expiry; existing pre-TTL databases migrate in place via
  `ALTER TABLE` (tested directly against a hand-built legacy DB file).
- **Ambiguous — "make it more reliable":** disambiguated into two selected
  improvements (bounded retry+backoff on SQLite write-lock contention; a
  DB-connectivity `/healthz` check) and two explicitly deferred candidates
  (structured logging, circuit breakers), each with a documented reason,
  recorded as four real decisions in the run's own `state.json` — the
  disambiguation reasoning is queryable data, not prose.

Each scenario ran through `python cli.py run --requirement "..."` end-to-end
(both approvals hit and approved, `overall_status: complete`) and was validated
with live `uvicorn`/`curl` smoke tests in addition to the automated suite — real
elapsed wall-clock time for the TTL expiry check, not a mocked clock.

## 5. Assumptions

From design-log.md Section 1 (baseline scope) — alias uniqueness is for the
system's lifetime; fixed 7-char base62 generated aliases for v1 (custom aliases
became the greenfield scenario); bounded generate-and-retry on collision;
analytics limited to click count/timestamp/referrer (no auth/per-user
dashboards); reliability defined concretely as idempotent creation + input
validation + graceful 404 rather than left vague; no expiration for v1 baseline
(reintroduced deliberately as the TTL brownfield scenario). Each scenario's own
assumptions are recorded in that scenario's `requirements.py` branch and surface
live in the run's `state.json` under `requirement.assumptions`.

## 6. Risks, Trade-offs, Limitations

Full list in [`design-log.md` Section 9`](design-log.md); summarized:

**Service:** no rate limiting (out of scope — the single brownfield scenario was
scoped to link expiration/TTL instead); orchestration-run state is in-memory/
single-process (won't scale across instances); SQLite's single-writer model
means bounded retry mitigates but doesn't eliminate write-lock contention under
sustained heavy load; expired links are never actively purged (no background
sweep); a small TOCTOU window exists on custom-alias creation (mitigated at the
DB-constraint level, not eliminated at the pre-check level); no auth/ownership;
the reserved-alias list is manually maintained per new route.

**Orchestration engine:** no resume-from-run-id (a blocked run must be fixed and
restarted fresh); CLI-blocking approval checkpoints work for this prototype's
single-interactive-session use case but wouldn't generalize to a team/async
approval workflow without a persisted pending-approval state a different
process could act on.

None of these were discovered after the fact — each was surfaced explicitly in
the design log at the point it became relevant.

## 7. Validation

Every scenario was verified at three levels, not just one:
1. **Automated tests**, written by the orchestrator's own `test_execution` stage
   and run as a real `pytest` subprocess on every pipeline run (33/33 passing).
2. **Direct inspection of generated state**, not just trusting the code — this is
   how a real bug was caught during the ambiguous scenario (malformed decision
   text from a data-structure mistake) and fixed before being called done.
3. **Live smoke tests** against a running `uvicorn` server via `curl`, including
   one case (TTL expiry) validated with real elapsed wall-clock time rather than
   a database row backdated to fake it.
