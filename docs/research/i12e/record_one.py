"""P2 step 1 — record ONE new scenario per invocation, live.

One invocation, one scenario, one live model call, foreground — the loop's
rule, so a failure costs one call and not ten. The checks come from
`scenarios.py`, which was committed before the first of these ran; nothing on
this command line is authored after reading an answer.

`--model` never reaches the CLI: `aef.measurement.yaml` here carries
`model: ""` and `ClaudeCodeProvider` appends the flag only for a non-empty
string, so the session default answers (ADR 0171's config, one line changed).

Usage:
  PYTHONPATH=<worktree> <venv>/bin/python record_one.py sum-40-lyth-brook
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scenarios import BY_ID

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def argv_for(scenario_id: str) -> list[str]:
    scenario = BY_ID[scenario_id]
    argv = [
        "aef",
        "loop",
        "record",
        "agents.summary.graph",
        "--corpus",
        str(REPO / "corpus"),
        "--scenario-id",
        scenario.id,
        "--objective",
        scenario.objective,
        "--agent-id",
        "summary_agent",
        "--split",
        scenario.split,
        "--notes",
        scenario.notes,
        "--working-memory",
        json.dumps(scenario.working_memory),
        "--config",
        str(HERE / "aef.measurement.yaml"),
        "--budget-ms",
        "60000",
    ]
    for check in scenario.checks:
        argv += ["--check", json.dumps(check)]
    return argv


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: record_one.py <scenario-id>", file=sys.stderr)
        return 2
    argv = argv_for(sys.argv[1])
    print(" ".join(repr(a) for a in argv), flush=True)
    run = subprocess.run(argv, cwd=str(REPO), text=True)
    print(f"returncode {run.returncode}")
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
