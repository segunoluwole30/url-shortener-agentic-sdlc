"""Section 3 schema (design-log.md) as dataclasses, with JSON persistence.

One RunState instance == one run == one runs/<run_id>/state.json file on disk.
Every field here maps 1:1 to a field in the locked schema so the JSON on disk
can be read directly against design-log.md Section 3 during review.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageState:
    status: str = "pending"  # pending | in_progress | complete | failed | blocked
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class Requirement:
    raw: str = ""
    normalized: str = ""
    assumptions: list[str] = field(default_factory=list)
    # Typed control signal (not string-sniffed from `assumptions`) that
    # orchestrator/graph.py's plan_for() reads to decide whether to
    # conditionally insert the migration_review stage — design-log.md
    # Section 2 addendum, "dynamic re-planning".
    requires_migration_review: bool = False


@dataclass
class Decision:
    stage: str
    decision: str
    rationale: str
    timestamp: str
    actor: str  # "agent" | "human"


@dataclass
class HistoryEvent:
    stage: str
    event: str
    timestamp: str
    detail: str = ""


@dataclass
class Approval:
    approved_by: str = ""
    approved_at: str = ""
    decision: str = ""  # "approved" | "rejected"


@dataclass
class Metrics:
    success_rate: float | None = None
    retry_frequency: float | None = None
    rollback_frequency: float | None = None
    mttr: float | None = None
    end_to_end_latency: float | None = None


STAGE_NAMES = [
    "requirements",
    "design",
    "implementation",
    "test_planning",
    "docs_drafting",
    "test_execution",
    "docs_finalize",
    "release_readiness",
]


@dataclass
class RunState:
    run_id: str
    overall_status: str = "pending"  # pending|in_progress|blocked|failed|complete
    stages: dict[str, StageState] = field(
        default_factory=lambda: {name: StageState() for name in STAGE_NAMES}
    )
    requirement: Requirement = field(default_factory=Requirement)
    decisions: list[Decision] = field(default_factory=list)
    artifacts: dict[str, list[str]] = field(default_factory=dict)
    history: list[HistoryEvent] = field(default_factory=list)
    retry_counts: dict[str, int] = field(default_factory=lambda: {n: 0 for n in STAGE_NAMES})
    approvals: dict[str, Approval] = field(default_factory=dict)
    metrics: Metrics = field(default_factory=Metrics)

    # --- lifecycle helpers -------------------------------------------------

    @classmethod
    def new(cls, raw_requirement: str = "") -> "RunState":
        run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        state = cls(run_id=run_id)
        state.requirement.raw = raw_requirement
        return state

    def run_dir(self) -> Path:
        d = RUNS_DIR / self.run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "artifacts").mkdir(exist_ok=True)
        return d

    def path(self) -> Path:
        return self.run_dir() / "state.json"

    # --- serialization -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self) -> None:
        """Atomic write so state.json is never observed half-written."""
        path = self.path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        tmp.replace(path)

    @classmethod
    def load(cls, run_id: str) -> "RunState":
        path = RUNS_DIR / run_id / "state.json"
        raw = json.loads(path.read_text())
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunState":
        state = cls(run_id=raw["run_id"])
        state.overall_status = raw.get("overall_status", "pending")
        state.stages = {k: StageState(**v) for k, v in raw.get("stages", {}).items()}
        req = raw.get("requirement", {})
        state.requirement = Requirement(
            raw=req.get("raw", ""),
            normalized=req.get("normalized", ""),
            assumptions=req.get("assumptions", []),
            requires_migration_review=req.get("requires_migration_review", False),
        )
        state.decisions = [Decision(**d) for d in raw.get("decisions", [])]
        state.artifacts = raw.get("artifacts", {})
        state.history = [HistoryEvent(**h) for h in raw.get("history", [])]
        state.retry_counts = raw.get("retry_counts", {n: 0 for n in STAGE_NAMES})
        state.approvals = {k: Approval(**v) for k, v in raw.get("approvals", {}).items()}
        state.metrics = Metrics(**raw.get("metrics", {}))
        return state

    # --- mutation helpers used by the runner/gates/audit modules -------

    def add_history(self, stage: str, event: str, detail: str = "") -> None:
        self.history.append(HistoryEvent(stage=stage, event=event, timestamp=now_iso(), detail=detail))

    def add_decision(self, stage: str, decision: str, rationale: str, actor: str) -> None:
        self.decisions.append(
            Decision(stage=stage, decision=decision, rationale=rationale, timestamp=now_iso(), actor=actor)
        )

    def add_artifact(self, stage: str, path: str) -> None:
        self.artifacts.setdefault(stage, []).append(path)

    def snapshot_stage(self, stage: str) -> dict[str, Any]:
        """Deep-ish snapshot of everything a rollback for this stage must restore."""
        return {
            "stage_state": StageState(**asdict(self.stages[stage])),
            "artifacts": list(self.artifacts.get(stage, [])),
            "retry_count": self.retry_counts.get(stage, 0),
        }

    def restore_stage(self, stage: str, snapshot: dict[str, Any]) -> None:
        self.stages[stage] = snapshot["stage_state"]
        self.artifacts[stage] = snapshot["artifacts"]
        self.retry_counts[stage] = snapshot["retry_count"]
