"""Step 2 demo/stub handlers — exercise the graph runner end-to-end with no
domain logic. These are throwaway: Step 3 replaces them with the real
handlers in orchestrator/stages/*.py that actually build the shortener.

Each handler does the minimum needed to satisfy its stage's exit gate
(gates.py), so a real run through this demo graph proves the gates are
actually being enforced, not just decorative.
"""
from __future__ import annotations

from .state import RunState


def requirements(state: RunState) -> None:
    state.requirement.normalized = f"Normalized: {state.requirement.raw or 'unspecified requirement'}"
    state.requirement.assumptions = ["demo assumption: no domain logic yet (Step 2 stub run)"]
    state.add_decision(
        stage="requirements",
        decision="normalized requirement accepted",
        rationale="Step 2 demo stub — real normalization arrives in Step 3",
        actor="agent",
    )


def design(state: RunState) -> None:
    state.add_artifact("design", "demo://design/notes.md")
    state.add_decision(
        stage="design",
        decision="stub design proposed",
        rationale="Step 2 demo stub",
        actor="agent",
    )


def implementation(state: RunState) -> None:
    state.add_artifact("implementation", "demo://service/app/main.py (stub)")


def test_planning(state: RunState) -> None:
    state.add_artifact("test_planning", "demo://service/tests/plan.md (stub)")


def docs_drafting(state: RunState) -> None:
    state.add_artifact("docs_drafting", "demo://service/docs/API.md (draft, stub)")


def test_execution(state: RunState) -> None:
    state.add_artifact("test_execution", "demo://service/tests/results.txt (stub, all-pass)")


def docs_finalize(state: RunState) -> None:
    state.add_artifact("docs_finalize", "demo://service/docs/API.md (final, stub)")


def release_readiness(state: RunState) -> None:
    state.add_decision(
        stage="release_readiness",
        decision="ready for sign-off",
        rationale="all upstream stages complete (Step 2 demo stub)",
        actor="agent",
    )


HANDLERS = {
    "requirements": requirements,
    "design": design,
    "implementation": implementation,
    "test_planning": test_planning,
    "docs_drafting": docs_drafting,
    "test_execution": test_execution,
    "docs_finalize": docs_finalize,
    "release_readiness": release_readiness,
}
