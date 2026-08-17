"""Unit tests for dynamic re-planning — design-log.md Section 2 addendum
(Core Requirement 4). Covers orchestrator/graph.py's plan_for() directly,
independent of any real requirement text/keyword matching (that's covered by
orchestrator/stages/requirements.py's own logic, exercised live via cli.py).
"""
from __future__ import annotations

from orchestrator.graph import GRAPH, plan_for
from orchestrator.runner import run
from orchestrator.state import RunState


def make_state(requires_migration_review: bool = False) -> RunState:
    state = RunState.new(raw_requirement="test")
    state.requirement.normalized = "test"
    state.requirement.assumptions = ["test"]
    state.requirement.requires_migration_review = requires_migration_review
    return state


def test_plan_for_returns_graph_unchanged_when_signal_unset():
    state = make_state(requires_migration_review=False)
    result = plan_for(state)
    assert result is GRAPH
    assert "migration_review" not in state.stages


def test_plan_for_inserts_migration_review_when_signal_set():
    state = make_state(requires_migration_review=True)
    result = plan_for(state)

    names = {s.name for s in result}
    assert "migration_review" in names
    assert len(result) == len(GRAPH) + 1

    by_name = {s.name: s for s in result}
    assert by_name["migration_review"].depends_on == ("implementation",)
    assert by_name["test_execution"].depends_on == ("implementation", "migration_review")
    # Untouched stages carry over as-is.
    assert by_name["design"] is next(s for s in GRAPH if s.name == "design")


def test_plan_for_initializes_live_bookkeeping_for_new_stage():
    state = make_state(requires_migration_review=True)
    plan_for(state)
    assert "migration_review" in state.stages
    assert state.stages["migration_review"].status == "pending"
    assert state.retry_counts["migration_review"] == 0


def test_plan_for_logs_the_replan_decision():
    state = make_state(requires_migration_review=True)
    plan_for(state)
    replan_decisions = [
        d for d in state.decisions if d.stage == "requirements" and "re-planned" in d.decision
    ]
    assert len(replan_decisions) == 1
    assert replan_decisions[0].actor == "agent"


def test_plan_for_is_idempotent_on_state_mutation():
    """Calling plan_for twice on the same state (shouldn't happen in normal
    cli.py usage, but the bookkeeping-init guard should make it safe) must
    not double-initialize migration_review's stage slot."""
    state = make_state(requires_migration_review=True)
    plan_for(state)
    plan_for(state)
    assert state.retry_counts["migration_review"] == 0
    assert len([d for d in state.decisions if "re-planned" in d.decision]) == 2  # logs each call, that's fine


def test_run_with_finalize_false_does_not_set_overall_status():
    state = make_state()

    def noop(state):
        pass

    from orchestrator.graph import StageDef

    only_requirements = (StageDef("requirements"),)
    run(state, handlers={"requirements": noop}, graph=only_requirements, finalize=False)
    assert state.overall_status == "in_progress"
    assert state.stages["requirements"].status == "complete"


def test_run_with_finalize_true_default_still_sets_overall_status():
    state = make_state()

    def noop(state):
        pass

    from orchestrator.graph import StageDef

    only_requirements = (StageDef("requirements"),)
    run(state, handlers={"requirements": noop}, graph=only_requirements)
    assert state.overall_status == "complete"
