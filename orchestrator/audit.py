"""Audit log writer + metrics tracker — design-log.md Section 7.

Every transition already lands in RunState.history via add_history(); this
module adds (a) an append-only audit.log file per run so the trail survives
even if state.json were ever corrupted/overwritten, and (b) recomputation of
the five tracked metrics from that same history, so metrics are always
derivable from the audit trail rather than an independent source of truth.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .state import RunState


def audit_log_path(state: RunState):
    return state.run_dir() / "audit.log"


def write_audit_line(state: RunState, stage: str, event: str, actor: str = "agent", detail: str = "") -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} | stage={stage} | event={event} | actor={actor} | {detail}"
    with open(audit_log_path(state), "a") as f:
        f.write(line + "\n")


def recompute_metrics(state: RunState) -> None:
    """Recomputes the five Section 7 metrics purely from state.history /
    retry_counts / stages — no metric is hand-set by a stage handler."""
    total_stages = len(state.stages)
    completed = [s for s in state.stages.values() if s.status == "complete"]
    failed_or_blocked = [s for s in state.stages.values() if s.status in ("failed", "blocked")]

    attempted = len(completed) + len(failed_or_blocked)
    state.metrics.success_rate = (len(completed) / attempted) if attempted else None

    total_retries = sum(state.retry_counts.values())
    state.metrics.retry_frequency = (total_retries / total_stages) if total_stages else None

    rollback_events = [h for h in state.history if h.event == "rollback"]
    state.metrics.rollback_frequency = (len(rollback_events) / total_stages) if total_stages else None

    # MTTR: mean time between a stage's first failure event and its next
    # completion event for that same stage (only over stages that actually
    # recovered from a failure).
    recovery_durations: list[float] = []
    by_stage: dict[str, list] = {}
    for h in state.history:
        by_stage.setdefault(h.stage, []).append(h)
    for stage, events in by_stage.items():
        events = sorted(events, key=lambda e: e.timestamp)
        failure_ts = None
        for e in events:
            if e.event in ("stage_failed", "retry"):
                if failure_ts is None:
                    failure_ts = e.timestamp
            elif e.event == "stage_complete" and failure_ts is not None:
                dt_fail = datetime.fromisoformat(failure_ts)
                dt_ok = datetime.fromisoformat(e.timestamp)
                recovery_durations.append((dt_ok - dt_fail).total_seconds())
                failure_ts = None
    state.metrics.mttr = (sum(recovery_durations) / len(recovery_durations)) if recovery_durations else None

    # End-to-end latency: run start (requirements started_at) to now/last event.
    started = state.stages["requirements"].started_at
    if started and state.history:
        dt_start = datetime.fromisoformat(started)
        dt_last = datetime.fromisoformat(state.history[-1].timestamp)
        state.metrics.end_to_end_latency = (dt_last - dt_start).total_seconds()
    else:
        state.metrics.end_to_end_latency = None


def log_event(state: RunState, stage: str, event: str, actor: str = "agent", detail: str = "") -> None:
    """The single entry point stages/runner should call: updates history,
    writes the audit line, recomputes metrics, and persists state."""
    state.add_history(stage=stage, event=event, detail=detail)
    write_audit_line(state, stage, event, actor=actor, detail=detail)
    recompute_metrics(state)
    state.save()
