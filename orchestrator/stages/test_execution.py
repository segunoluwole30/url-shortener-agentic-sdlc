"""test_execution stage handler — Step 3.

Depends on implementation only (sync point A, design-log.md Section 2).
Copies the real pytest suite template into service/tests/, then actually
runs it via subprocess against a temporary SQLite DB. Pass/fail is genuine,
not simulated — a real bug in the generated implementation makes this stage
fail for real and drives the orchestrator's retry/rollback path exactly as
it would for any other failure.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from ..audit import log_event
from ..retry import StageFailure
from ..state import RunState

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = Path(__file__).resolve().parent / "templates" / "service_tests" / "test_api.py"
TESTS_DIR = REPO_ROOT / "service" / "tests"


def handler(state: RunState) -> None:
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = TESTS_DIR / "test_api.py"
    shutil.copyfile(TEMPLATE, dest)
    state.add_artifact("test_execution", "service/tests/test_api.py")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(dest), "-v", "--tb=short"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    summary = _parse_summary(result.stdout)
    if result.returncode != 0:
        log_event(
            state,
            "test_execution",
            "test_failure_unresolved",
            detail=f"{summary}\n{result.stdout[-2000:]}",
        )
        raise StageFailure(f"pytest failed: {summary}")

    log_event(state, "test_execution", "tests_passed", detail=summary)


def _parse_summary(stdout: str) -> str:
    for line in reversed(stdout.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            return line.strip()
    return "no summary line found"
