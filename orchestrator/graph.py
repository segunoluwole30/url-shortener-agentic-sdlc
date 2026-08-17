"""The stage graph from design-log.md Section 2, as data (not code paths).

The runner walks this structure generically — it has no hardcoded knowledge
of "implementation" vs "docs_drafting"; it only knows about StageDef.depends_on.
That's what makes the fan-out/sync-point behavior real rather than simulated:
add/remove an edge here and the runner's scheduling changes with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .state import RunState, StageState


@dataclass(frozen=True)
class StageDef:
    name: str
    depends_on: tuple[str, ...] = ()
    requires_approval: bool = False
    max_retries: int = 2


# Mirrors design-log.md Section 2 exactly:
#   requirements -> design -> {implementation, test_planning, docs_drafting}
#   implementation -> test_execution                        (sync point A)
#   {test_execution, docs_drafting} -> docs_finalize          (sync point B, loose)
#   {test_execution, docs_finalize} -> release_readiness      (final sync point)
GRAPH: tuple[StageDef, ...] = (
    StageDef("requirements"),
    StageDef("design", depends_on=("requirements",), requires_approval=True),
    StageDef("implementation", depends_on=("design",)),
    StageDef("test_planning", depends_on=("design",)),
    StageDef("docs_drafting", depends_on=("design",)),
    StageDef("test_execution", depends_on=("implementation",)),
    StageDef("docs_finalize", depends_on=("test_execution", "docs_drafting")),
    StageDef("release_readiness", depends_on=("test_execution", "docs_finalize"), requires_approval=True),
)

GRAPH_BY_NAME: dict[str, StageDef] = {s.name: s for s in GRAPH}


def plan_for(state: RunState) -> tuple[StageDef, ...]:
    """Decide the stage graph for this run from requirements' output —
    design-log.md Section 2 addendum, "dynamic re-planning" (Core
    Requirement 4). Called once, right after the `requirements` stage
    completes and before the rest of the graph is scheduled — this is a
    genuine plan change driven by upstream output (different requirement
    text produces a structurally different graph), not a cosmetic branch.

    Returns GRAPH unchanged for every requirement except ones that signal a
    schema migration needs verifying (state.requirement.requires_migration_review),
    in which case `migration_review` is spliced in after `implementation`
    and `test_execution` is rewired to wait on it too — so the pipeline
    verifies the real generated migration path before tests run against it,
    instead of that being a manual, out-of-band check.
    """
    if not state.requirement.requires_migration_review:
        return GRAPH

    migration_review = StageDef("migration_review", depends_on=("implementation",))
    new_test_execution = StageDef("test_execution", depends_on=("implementation", "migration_review"))

    augmented = tuple(new_test_execution if s.name == "test_execution" else s for s in GRAPH) + (
        migration_review,
    )
    validate_graph(augmented)

    # GRAPH's default stage/retry_count bookkeeping (state.py's STAGE_NAMES)
    # doesn't know about migration_review — give it a live slot before the
    # scheduler ever looks it up.
    if "migration_review" not in state.stages:
        state.stages["migration_review"] = StageState()
        state.retry_counts["migration_review"] = 0

    # Governance requirement, not optional: the re-plan itself must be
    # audit-trail-visible, not a silent branch.
    state.add_decision(
        stage="requirements",
        decision="graph re-planned: inserted migration_review stage",
        rationale="requirement.requires_migration_review is set — the schema migration this "
        "requirement needs (design-log.md Section 8, TTL brownfield scenario) gets verified "
        "against the real generated db.py as a governed pipeline stage, not a manual check.",
        actor="agent",
    )

    return augmented


def dependents_of(stage_name: str, graph: tuple[StageDef, ...] = GRAPH) -> list[str]:
    """Stages that list `stage_name` as a dependency — used to know what to
    (re)check once a stage completes."""
    return [s.name for s in graph if stage_name in s.depends_on]


def validate_graph(graph: tuple[StageDef, ...] = GRAPH) -> None:
    """Fails fast on a malformed graph: unknown dep name or a cycle."""
    names = {s.name for s in graph}
    for s in graph:
        for dep in s.depends_on:
            if dep not in names:
                raise ValueError(f"stage {s.name!r} depends on unknown stage {dep!r}")

    # Cycle check via DFS.
    WHITE, GREY, BLACK = 0, 1, 2
    color = {s.name: WHITE for s in graph}
    by_name = {s.name: s for s in graph}

    def visit(name: str, path: list[str]) -> None:
        color[name] = GREY
        for dep in by_name[name].depends_on:
            if color[dep] == GREY:
                raise ValueError(f"cycle detected: {' -> '.join(path + [dep])}")
            if color[dep] == WHITE:
                visit(dep, path + [dep])
        color[name] = BLACK

    for s in graph:
        if color[s.name] == WHITE:
            visit(s.name, [s.name])


validate_graph()
