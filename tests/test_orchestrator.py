"""Unit tests for the graph runner (Step 2): gate logic, retry bounds,
rollback restore, and genuine parallel fan-out — against synthetic graphs,
independent of any domain logic.
"""
from __future__ import annotations

import threading
import time

import pytest

from orchestrator.audit import log_event
from orchestrator.gates import entry_gate, exit_gate
from orchestrator.graph import StageDef
from orchestrator.retry import RetryPolicy, RunHalted, StageFailure
from orchestrator.runner import run
from orchestrator.state import RunState

# Synthetic 4-node graph reusing real stage names (so gates.py's Section-4
# exit-gate dispatch, which is keyed by name, applies without modification):
#   implementation, test_planning, docs_drafting  -- independent roots
#   test_execution -- depends on all three (sync point)
SYNTHETIC_GRAPH = (
    StageDef("implementation"),
    StageDef("test_planning"),
    StageDef("docs_drafting"),
    StageDef("test_execution", depends_on=("implementation", "test_planning", "docs_drafting")),
)


def make_state() -> RunState:
    return RunState.new(raw_requirement="test")


def artifact_handler(stage_name: str):
    """Generic passing handler for any stage EXCEPT "test_execution" — that
    one's real exit gate (gates.py._test_execution_exit) requires a
    "tests_passed" history event, not just an artifact, so it needs
    passing_test_execution below instead."""

    def handler(state: RunState) -> None:
        state.add_artifact(stage_name, f"demo://{stage_name}")

    return handler


def passing_test_execution(state: RunState) -> None:
    state.add_artifact("test_execution", "demo://test_execution")
    log_event(state, "test_execution", "tests_passed", detail="demo: N/N passed")


# --- gate logic --------------------------------------------------------


def test_entry_gate_blocks_until_all_deps_complete():
    state = make_state()
    assert entry_gate(state, "test_execution", graph=SYNTHETIC_GRAPH) is False
    state.stages["implementation"].status = "complete"
    state.stages["test_planning"].status = "complete"
    assert entry_gate(state, "test_execution", graph=SYNTHETIC_GRAPH) is False  # docs_drafting still pending
    state.stages["docs_drafting"].status = "complete"
    assert entry_gate(state, "test_execution", graph=SYNTHETIC_GRAPH) is True


def test_exit_gate_requires_artifact_presence():
    state = make_state()
    assert exit_gate(state, "implementation") is False
    state.add_artifact("implementation", "demo://x")
    assert exit_gate(state, "implementation") is True


# --- retry bounds --------------------------------------------------------


def test_retry_succeeds_within_budget():
    calls = {"n": 0}

    def flaky(state: RunState) -> None:
        calls["n"] += 1
        if calls["n"] < 3:  # fails twice, succeeds on 3rd attempt
            raise StageFailure("transient failure")
        state.add_artifact("implementation", "demo://implementation")

    handlers = {
        "implementation": flaky,
        "test_planning": artifact_handler("test_planning"),
        "docs_drafting": artifact_handler("docs_drafting"),
        "test_execution": passing_test_execution,
    }
    state = make_state()
    result = run(state, handlers=handlers, graph=SYNTHETIC_GRAPH)

    assert calls["n"] == 3
    assert result.stages["implementation"].status == "complete"
    assert result.retry_counts["implementation"] == 2
    assert result.overall_status == "complete"


def test_retry_exhausted_without_fallback_raises_and_blocks():
    def always_fails(state: RunState) -> None:
        raise StageFailure("permanent failure")

    handlers = {
        "implementation": always_fails,
        "test_planning": artifact_handler("test_planning"),
        "docs_drafting": artifact_handler("docs_drafting"),
        "test_execution": passing_test_execution,
    }
    state = make_state()

    with pytest.raises(RunHalted) as excinfo:
        run(state, handlers=handlers, graph=SYNTHETIC_GRAPH)

    assert excinfo.value.stage == "implementation"
    assert state.overall_status == "blocked"
    assert state.stages["implementation"].status == "blocked"


# --- fallback --------------------------------------------------------


def test_fallback_used_when_retries_exhausted():
    def always_fails(state: RunState) -> None:
        raise StageFailure("permanent failure")

    def degrade(state: RunState) -> None:
        state.add_artifact("implementation", "demo://implementation-degraded")

    policies = {"implementation": RetryPolicy(max_retries=1, fallback=degrade)}
    handlers = {
        "implementation": always_fails,
        "test_planning": artifact_handler("test_planning"),
        "docs_drafting": artifact_handler("docs_drafting"),
        "test_execution": passing_test_execution,
    }
    state = make_state()
    result = run(state, handlers=handlers, policies=policies, graph=SYNTHETIC_GRAPH)

    assert result.stages["implementation"].status == "complete"
    assert any(h.event == "fallback_used" for h in result.history if h.stage == "implementation")
    assert result.overall_status == "complete"


# --- rollback restores only the failing stage's own slice --------------


def test_rollback_restores_pre_attempt_snapshot_without_touching_siblings():
    def always_fails(state: RunState) -> None:
        # Pollute artifacts before failing, to prove rollback reverts this.
        state.add_artifact("implementation", "demo://partial-garbage")
        raise StageFailure("permanent failure")

    handlers = {
        "implementation": always_fails,
        "test_planning": artifact_handler("test_planning"),
        "docs_drafting": artifact_handler("docs_drafting"),
        "test_execution": passing_test_execution,
    }
    state = make_state()

    with pytest.raises(RunHalted):
        run(state, handlers=handlers, graph=SYNTHETIC_GRAPH)

    # implementation's own state reverted to pre-attempt (no artifacts, retry_count 0)
    assert state.artifacts.get("implementation", []) == []
    assert state.retry_counts["implementation"] == 0
    # audit trail is NOT erased by rollback
    assert any(h.event == "stage_failed" for h in state.history if h.stage == "implementation")
    # sibling stages that already completed are untouched by implementation's rollback
    assert state.stages["test_planning"].status == "complete"
    assert state.stages["docs_drafting"].status == "complete"


# --- genuine parallel fan-out -------------------------------------------


def test_independent_stages_run_concurrently_not_sequentially():
    """implementation/test_planning/docs_drafting have no dependency on each
    other in SYNTHETIC_GRAPH; if the runner executed them sequentially this
    would take >= 3 * SLEEP seconds. Real concurrency keeps it well under
    that, proving the fan-out is actual parallel execution."""
    SLEEP = 0.3
    start_times: dict[str, float] = {}
    lock = threading.Lock()

    def slow(stage_name: str):
        def handler(state: RunState) -> None:
            with lock:
                start_times[stage_name] = time.monotonic()
            time.sleep(SLEEP)
            state.add_artifact(stage_name, f"demo://{stage_name}")

        return handler

    handlers = {
        "implementation": slow("implementation"),
        "test_planning": slow("test_planning"),
        "docs_drafting": slow("docs_drafting"),
        "test_execution": passing_test_execution,
    }
    state = make_state()

    t0 = time.monotonic()
    run(state, handlers=handlers, graph=SYNTHETIC_GRAPH)
    elapsed = time.monotonic() - t0

    assert elapsed < 3 * SLEEP  # would be ~3*SLEEP+ if run sequentially
    spread = max(start_times.values()) - min(start_times.values())
    assert spread < SLEEP  # all three started within one sleep-window of each other
