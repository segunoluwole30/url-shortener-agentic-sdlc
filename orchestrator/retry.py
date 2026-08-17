"""Bounded retry / fallback / rollback policy — design-log.md Section 6.

Policy (confirmed with user before implementation):
- Retry: on handler exception or exit-gate failure, retry the *same* handler
  up to `max_retries` extra times (default 2 => 3 attempts total). No state
  is undone between retries.
- Fallback: once retries are exhausted, run one degraded/simplified handler
  if the stage registered one. Succeeds -> stage marked complete with a
  `fallback_used` audit note. At most one fallback attempt.
- Rollback: if fallback also fails (or none registered), restore the
  stage's pre-attempt snapshot (its own status/artifacts/retry_count only —
  not the whole run, so a failure in one parallel branch doesn't clobber
  sibling branches) and halt the run (`overall_status = "blocked"`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .state import RunState


class StageFailure(Exception):
    """Raised by a stage handler to signal a retryable failure."""


class GateFailure(Exception):
    """Raised internally when a stage's exit gate doesn't pass after the handler runs."""


class RunHalted(Exception):
    """Raised when retries + fallback are both exhausted and rollback has fired."""

    def __init__(self, stage: str, reason: str):
        self.stage = stage
        self.reason = reason
        super().__init__(f"run halted at stage {stage!r}: {reason}")


FallbackFn = Callable[[RunState], None]


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2
    fallback: FallbackFn | None = None


DEFAULT_POLICY = RetryPolicy()


def policy_for(stage: str, policies: dict[str, RetryPolicy]) -> RetryPolicy:
    return policies.get(stage, DEFAULT_POLICY)
