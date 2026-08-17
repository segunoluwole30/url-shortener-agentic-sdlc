"""The orchestration engine: topological/parallel execution over graph.GRAPH,
enforcing gates.py, retry/fallback/rollback per retry.py, blocking on
approval.py at approval-gated stages, and logging every transition via
audit.py.

Scheduling model: a stage becomes eligible the instant its entry gate passes
(all deps complete). Because implementation/test_planning/docs_drafting all
depend only on design, they become eligible simultaneously and are submitted
to a thread pool together — genuine concurrent execution, not a simulated
ordering, which is what design-log.md Section 2 calls for.
"""
from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable

from .approval import ApprovalRejected, request_approval
from .audit import log_event
from .gates import entry_gate, exit_gate
from .graph import GRAPH, StageDef
from .retry import DEFAULT_POLICY, GateFailure, RetryPolicy, RunHalted, StageFailure, policy_for
from .state import RunState, now_iso

StageHandler = Callable[[RunState], None]


def _run_stage(
    state: RunState,
    name: str,
    stage_def: StageDef,
    handlers: dict[str, StageHandler],
    fallback_handlers: dict[str, StageHandler],
    policies: dict[str, RetryPolicy],
    lock: threading.Lock,
) -> None:
    policy = policy_for(name, policies)

    with lock:
        snapshot = state.snapshot_stage(name)
        state.stages[name].status = "in_progress"
        state.stages[name].started_at = now_iso()
        log_event(state, name, "stage_started")

    attempt = 0
    while True:
        try:
            handler = handlers.get(name)
            if handler is not None:
                handler(state)

            if stage_def.requires_approval:
                # Flush state.json BEFORE blocking on the prompt, not after — otherwise
                # a human reviewing the run mid-pause (a second terminal, say) would see
                # state through the end of the *previous* stage only, since
                # approval.request_approval() doesn't save until input() returns.
                # design/release_readiness never run concurrently with sibling stages,
                # so this save can't race another stage's in-flight handler.
                with lock:
                    state.save()
                request_approval(state, name, summary=f"Review stage {name!r} before proceeding.")

            with lock:
                if not exit_gate(state, name):
                    raise GateFailure(f"exit gate failed for stage {name!r}")
                state.stages[name].status = "complete"
                state.stages[name].completed_at = now_iso()
                log_event(state, name, "stage_complete")
            return

        except ApprovalRejected as e:
            with lock:
                state.restore_stage(name, snapshot)
                state.stages[name].status = "blocked"
                log_event(state, name, "rollback", detail=f"approval rejected: {e.rationale}")
            raise RunHalted(name, f"approval rejected: {e.rationale}")

        except (StageFailure, GateFailure) as e:
            with lock:
                state.retry_counts[name] = state.retry_counts.get(name, 0) + 1
                log_event(state, name, "stage_failed", detail=str(e))
            attempt += 1
            if attempt <= policy.max_retries:
                with lock:
                    log_event(state, name, "retry", detail=f"attempt {attempt} of {policy.max_retries}")
                continue

            fallback = fallback_handlers.get(name) or policy.fallback
            if fallback is not None:
                try:
                    fallback(state)
                    with lock:
                        state.stages[name].status = "complete"
                        state.stages[name].completed_at = now_iso()
                        log_event(state, name, "fallback_used")
                    return
                except Exception as fe:  # fallback itself failed -> fall through to rollback
                    with lock:
                        log_event(state, name, "fallback_failed", detail=str(fe))

            with lock:
                state.restore_stage(name, snapshot)
                state.stages[name].status = "blocked"
                log_event(state, name, "rollback", detail="retries and fallback exhausted")
            raise RunHalted(name, "retries and fallback exhausted")


def run(
    state: RunState,
    handlers: dict[str, StageHandler] | None = None,
    fallback_handlers: dict[str, StageHandler] | None = None,
    policies: dict[str, RetryPolicy] | None = None,
    graph=GRAPH,
    max_workers: int = 8,
    finalize: bool = True,
) -> RunState:
    """finalize=False skips the trailing overall_status write — for callers
    that run a subgraph and intend to call run() again over the rest of the
    graph before the run is actually done (cli.py's requirements-then-
    plan_for()-then-rest split, design-log.md Section 2 addendum). Default
    True keeps every existing caller's behavior unchanged."""
    handlers = handlers or {}
    fallback_handlers = fallback_handlers or {}
    policies = policies or {}
    lock = threading.Lock()

    state.overall_status = "in_progress"
    state.save()

    scheduled: set[str] = set()
    futures: dict = {}
    by_name = {s.name: s for s in graph}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            with lock:
                ready = [
                    s.name
                    for s in graph
                    if state.stages[s.name].status not in ("complete", "blocked", "failed")
                    and s.name not in scheduled
                    and entry_gate(state, s.name, graph=graph)
                ]
                for name in ready:
                    scheduled.add(name)
                    fut = executor.submit(
                        _run_stage, state, name, by_name[name], handlers, fallback_handlers, policies, lock
                    )
                    futures[fut] = name

            if not futures:
                break  # nothing running, nothing newly eligible -> done or stuck

            done, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
            halted: RunHalted | None = None
            for fut in done:
                name = futures.pop(fut)
                scheduled.discard(name)
                try:
                    fut.result()
                except RunHalted as e:
                    halted = e

            if halted is not None:
                for pending_fut in list(futures.keys()):
                    pending_fut.cancel()
                with lock:
                    state.overall_status = "blocked"
                    state.save()
                raise halted

    if finalize:
        with lock:
            # Only the stages that were actually part of this run's graph matter —
            # state.stages carries all 8 real stage slots regardless of which
            # (sub)graph was executed, e.g. in synthetic-graph tests.
            all_complete = all(state.stages[s.name].status == "complete" for s in graph)
            state.overall_status = "complete" if all_complete else "failed"
            state.save()

    return state
