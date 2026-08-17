"""The stage graph from design-log.md Section 2, as data (not code paths).

The runner walks this structure generically — it has no hardcoded knowledge
of "implementation" vs "docs_drafting"; it only knows about StageDef.depends_on.
That's what makes the fan-out/sync-point behavior real rather than simulated:
add/remove an edge here and the runner's scheduling changes with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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
