"""Run every objective in `objectives.py` through `aef run --record-runs`.

One invocation of the real CLI per objective — the same command an adopter
would put in a deployment — so each is one live `claude_code` call and each
writes one `RecordedRun` the harvest leg can be pointed at.

`--memory` is passed or not, by flag, because that is the variable ADR 0192's
F-N7-1 is about: the determinism re-check inside `aef loop harvest` rebuilds
its services with an EMPTY memory store, and every generated prompt-agent
graph is wired `retrieve -> prompt_agent`, so a run that read a non-empty
store cannot re-execute to the same bytes. Both arms are run here on marlin.

Usage:
    run_objectives.py --repo <clone> --runs <dir> [--memory <file>] [--only ids]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from objectives import NO_TOOLS_PREAMBLE, OBJECTIVES  # noqa: E402

MODULE = "agents.migrated.marlin_source.graph"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--memory", default=None)
    ap.add_argument("--observations", default=None)
    ap.add_argument("--only", default="", help="comma-separated objective ids")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument(
        "--preamble",
        action="store_true",
        help="arm B: prepend objectives.NO_TOOLS_PREAMBLE to every objective",
    )
    args = ap.parse_args()

    only = {s for s in args.only.split(",") if s}
    todo = [o for o in OBJECTIVES if not only or o["id"] in only]
    print(f"{len(todo)} objective(s); runs -> {args.runs}; memory -> {args.memory}")

    calls = 0
    for o in todo:
        argv = [
            args.python,
            "-m",
            "aef.cli.main",
            "run",
            MODULE,
            "--objective",
            (NO_TOOLS_PREAMBLE + o["text"]) if args.preamble else o["text"],
            "--config",
            "aef.yaml",
            "--record-runs",
            args.runs,
        ]
        if args.memory:
            argv += ["--memory", args.memory]
        if args.observations:
            argv += ["--observations", args.observations]
        t0 = time.time()
        r = subprocess.run(argv, cwd=args.repo, capture_output=True, text=True)
        calls += 1
        head = (r.stdout or r.stderr).strip().splitlines()
        print(f"[{o['id']}] exit={r.returncode} {time.time() - t0:.1f}s")
        for line in head[:3]:
            print(f"    {line}")
        if r.returncode != 0:
            print(f"    STDERR: {r.stderr.strip()[:800]}")
    print(f"\nlive model calls spent by this script: {calls}")

    runs = sorted(pathlib.Path(args.runs).glob("*.json"))
    print(f"recorded run files now in {args.runs}: {len(runs)}")
    for p in runs:
        d = json.loads(p.read_text())
        calls_n = len(d.get("model_calls", []))
        print(f"  {p.name}  graph_id={d.get('graph_id')}  model_calls={calls_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
