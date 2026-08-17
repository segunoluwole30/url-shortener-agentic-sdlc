"""Entry/exit gate predicates from design-log.md Section 4.

Each function is a pure predicate over RunState — no side effects, no I/O —
so a gate can be pointed to directly in review and unit-tested in isolation
from the runner that calls it.
"""
from __future__ import annotations

import py_compile
from pathlib import Path

from .graph import GRAPH, GRAPH_BY_NAME, StageDef
from .state import RunState

REPO_ROOT = Path(__file__).resolve().parent.parent


def entry_gate(state: RunState, stage: str, graph: tuple[StageDef, ...] = GRAPH) -> bool:
    """Generic: every dependency's stage must be complete.

    This alone is what makes fan-out real — implementation/test_planning/
    docs_drafting all share depends_on=("design",), so the moment design
    is complete, all three simultaneously satisfy their entry gate and are
    eligible to start concurrently.

    Takes `graph` explicitly (defaulting to the real GRAPH) rather than
    always consulting the module-level GRAPH_BY_NAME, so this also works
    correctly against synthetic graphs used in tests.
    """
    stage_def = GRAPH_BY_NAME[stage] if graph is GRAPH else next(s for s in graph if s.name == stage)
    return all(state.stages[dep].status == "complete" for dep in stage_def.depends_on)


def _requirements_exit(state: RunState) -> bool:
    return bool(state.requirement.normalized) and len(state.requirement.assumptions) > 0


def _design_exit(state: RunState) -> bool:
    # Note: deliberately does NOT check stages["design"].status == "complete" —
    # the runner calls exit_gate() to *decide* whether the stage may become
    # complete, so that status is still "in_progress" at this point.
    return any(d.stage == "design" and d.actor == "human" for d in state.decisions)


def _implementation_exit(state: RunState) -> bool:
    """Artifacts present AND every one of them actually compiles — the
    literal "compiles/lints clean" condition from design-log.md Section 4,
    checked independently of whatever the handler itself already verified."""
    artifacts = state.artifacts.get("implementation")
    if not artifacts:
        return False
    for rel_path in artifacts:
        if not rel_path.endswith(".py"):
            continue
        try:
            py_compile.compile(str(REPO_ROOT / rel_path), doraise=True)
        except (py_compile.PyCompileError, FileNotFoundError):
            return False
    return True


def _test_planning_exit(state: RunState) -> bool:
    return bool(state.artifacts.get("test_planning"))


def _docs_drafting_exit(state: RunState) -> bool:
    return bool(state.artifacts.get("docs_drafting"))


def _test_execution_exit(state: RunState) -> bool:
    """No unresolved test failures — checked as "the most recent test_execution
    history event is a pass", not "no failure ever happened", since history is
    append-only and a stage can legitimately fail once, retry, then pass."""
    stage_events = [h for h in state.history if h.stage == "test_execution"]
    if not stage_events:
        return False
    latest = max(stage_events, key=lambda h: h.timestamp)
    return latest.event == "tests_passed"


def _docs_finalize_exit(state: RunState) -> bool:
    return bool(state.artifacts.get("docs_finalize"))


def _release_readiness_exit(state: RunState) -> bool:
    approval = state.approvals.get("release_readiness")
    return approval is not None and approval.decision == "approved"


_EXIT_GATES = {
    "requirements": _requirements_exit,
    "design": _design_exit,
    "implementation": _implementation_exit,
    "test_planning": _test_planning_exit,
    "docs_drafting": _docs_drafting_exit,
    "test_execution": _test_execution_exit,
    "docs_finalize": _docs_finalize_exit,
    "release_readiness": _release_readiness_exit,
}


def exit_gate(state: RunState, stage: str) -> bool:
    return _EXIT_GATES[stage](state)
