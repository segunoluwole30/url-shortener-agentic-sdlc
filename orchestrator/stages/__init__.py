"""Real stage handlers (Step 3) — replaces orchestrator/demo_stages.py as
the graph runner's HANDLERS mapping."""
from __future__ import annotations

from . import (
    design,
    docs_drafting,
    docs_finalize,
    implementation,
    release_readiness,
    requirements,
    test_execution,
    test_planning,
)

HANDLERS = {
    "requirements": requirements.handler,
    "design": design.handler,
    "implementation": implementation.handler,
    "test_planning": test_planning.handler,
    "docs_drafting": docs_drafting.handler,
    "test_execution": test_execution.handler,
    "docs_finalize": docs_finalize.handler,
    "release_readiness": release_readiness.handler,
}
