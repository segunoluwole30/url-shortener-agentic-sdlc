"""release_readiness stage handler — Step 3.

No artifact of its own (design-log.md Section 4): its only exit condition is
the human sign-off recorded by the approval checkpoint (design-log.md
Section 5), which the runner enforces via StageDef.requires_approval. This
handler just records whether everything upstream genuinely finished, so a
human reviewing the approval prompt sees an honest go/no-go summary.
"""
from __future__ import annotations

from ..state import RunState

UPSTREAM_STAGES = (
    "requirements",
    "design",
    "implementation",
    "test_planning",
    "docs_drafting",
    "test_execution",
    "docs_finalize",
)


def handler(state: RunState) -> None:
    all_prior_complete = all(state.stages[name].status == "complete" for name in UPSTREAM_STAGES)
    state.add_decision(
        stage="release_readiness",
        decision="ready for sign-off" if all_prior_complete else "NOT ready — upstream stage incomplete",
        rationale=(
            "all upstream stages report complete"
            if all_prior_complete
            else "at least one upstream stage is not complete"
        ),
        actor="agent",
    )
