"""Blocking human-approval checkpoint — design-log.md Section 5.

Hard-blocks the run on stdin. This is deliberately not async/polling: when
the runner reaches an approval-gated stage, the process itself stops and
waits for a human to type approve/reject, which is the most literal,
unambiguous way to satisfy "halts execution until I respond."
"""
from __future__ import annotations

from .state import RunState, now_iso


class ApprovalRejected(Exception):
    def __init__(self, checkpoint: str, rationale: str):
        self.checkpoint = checkpoint
        self.rationale = rationale
        super().__init__(f"approval checkpoint {checkpoint!r} rejected: {rationale}")


def request_approval(state: RunState, checkpoint: str, summary: str, input_fn=input) -> None:
    """Blocks the calling thread until the human types approve/reject.

    Records the outcome in both `approvals` (Section 3 schema) and
    `decisions` (actor="human"), so the same event is visible from both the
    gate-checkable field and the decision-lineage log.
    """
    print(f"\n--- HUMAN APPROVAL REQUIRED: {checkpoint} ---")
    print(summary)
    while True:
        raw = input_fn(f"[{checkpoint}] approve / reject (with reason)? > ").strip()
        if raw.lower() in ("approve", "approved", "y", "yes"):
            decision, rationale = "approved", "approved via CLI checkpoint"
            break
        if raw.lower().startswith(("reject", "n", "no")):
            decision = "rejected"
            rationale = raw.partition(" ")[2] or "rejected via CLI checkpoint (no reason given)"
            break
        print("Please type 'approve' or 'reject <reason>'.")

    from .state import Approval

    state.approvals[checkpoint] = Approval(
        approved_by="human",
        approved_at=now_iso(),
        decision=decision,
    )
    state.add_decision(stage=checkpoint, decision=decision, rationale=rationale, actor="human")
    state.add_history(stage=checkpoint, event=f"approval_{decision}", detail=rationale)
    state.save()

    if decision == "rejected":
        raise ApprovalRejected(checkpoint, rationale)
