"""docs_finalize stage handler — Step 3.

Depends on {test_execution, docs_drafting} (sync point B, design-log.md
Section 2). Folds the real test outcome into the drafted API doc.
"""
from __future__ import annotations

from pathlib import Path

from ..state import RunState

SERVICE_DIR = Path(__file__).resolve().parent.parent.parent / "service"


def handler(state: RunState) -> None:
    docs_path = SERVICE_DIR / "docs" / "API.md"
    draft = docs_path.read_text()

    passed_events = [h for h in state.history if h.stage == "test_execution" and h.event == "tests_passed"]
    verified_line = passed_events[-1].detail if passed_events else "test results unavailable"

    finalized = draft + f"\n---\n\n## Verified\n\n{verified_line} (service/tests/test_api.py)\n"
    docs_path.write_text(finalized)
    state.add_artifact("docs_finalize", "service/docs/API.md")
