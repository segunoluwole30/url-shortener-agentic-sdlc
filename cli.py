"""Entrypoint: `python cli.py run [--requirement "..."]`.

Step 3: runs the real stage handlers (orchestrator/stages/) that build the
URL shortener into service/ — requirements -> design -> {implementation,
test_planning, docs_drafting} -> test_execution -> docs_finalize ->
release_readiness. orchestrator/demo_stages.py (Step 2's no-op stubs) is no
longer used by this entrypoint but is left in place for reference.

Runs `requirements` on its own first, then decides the rest of the graph via
orchestrator/graph.py's plan_for() — design-log.md Section 2 addendum
("dynamic re-planning", Core Requirement 4): some requirements (currently,
ones needing a schema migration) get an extra migration_review stage spliced
in, decided from requirements' own output, not a fixed graph every run.
"""
from __future__ import annotations

import argparse
import json
import sys

from orchestrator.graph import GRAPH_BY_NAME, plan_for
from orchestrator.retry import RunHalted
from orchestrator.runner import run
from orchestrator.stages import HANDLERS
from orchestrator.state import RunState


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SDLC orchestration engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Start a new orchestration run.")
    run_parser.add_argument("--requirement", default="", help="Raw requirement text for this run.")

    args = parser.parse_args()

    if args.command == "run":
        state = RunState.new(raw_requirement=args.requirement)
        print(f"Starting run {state.run_id}")
        try:
            run(state, handlers=HANDLERS, graph=(GRAPH_BY_NAME["requirements"],), finalize=False)
            graph = plan_for(state)
            run(state, handlers=HANDLERS, graph=graph)
        except RunHalted as e:
            print(f"\nRun halted: {e}")
            print(f"State: {state.path()}")
            return 1

        print(f"\nRun complete. overall_status={state.overall_status}")
        print(f"State file: {state.path()}")
        print(json.dumps(state.metrics.__dict__, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
