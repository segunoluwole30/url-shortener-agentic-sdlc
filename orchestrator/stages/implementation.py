"""implementation stage handler — Step 3.

Copies the real FastAPI service (orchestrator/stages/templates/service_app/)
into service/app/, then verifies every file actually compiles — this
handler's own py_compile pass fails fast with a clear StageFailure (driving
retry) rather than deferring the error to the exit gate, which independently
re-checks the same thing (gates.py._implementation_exit).
"""
from __future__ import annotations

import py_compile
import shutil
from pathlib import Path

from ..retry import StageFailure
from ..state import RunState

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "service_app"
APP_DIR = REPO_ROOT / "service" / "app"


def handler(state: RunState) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

    for template_path in sorted(TEMPLATES_DIR.glob("*.py")):
        dest = APP_DIR / template_path.name
        shutil.copyfile(template_path, dest)
        rel = str(dest.relative_to(REPO_ROOT))
        try:
            py_compile.compile(str(dest), doraise=True)
        except py_compile.PyCompileError as e:
            raise StageFailure(f"generated file {rel} failed to compile: {e}")
        state.add_artifact("implementation", rel)

    state.add_decision(
        stage="implementation",
        decision=f"wrote {len(state.artifacts.get('implementation', []))} module(s) implementing "
        "service/docs/DESIGN.md",
        rationale="SQLite-backed FastAPI implementation matching the approved design",
        actor="agent",
    )
