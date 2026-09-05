"""S1b's reproduction, run BEFORE any live quota was spent.

ADR 0155 spent 84 live calls comparing one configuration against itself, and it
found out afterwards. The check it added — hash every rendered draft prompt
under a provider that records instead of sending — is run here first, over the
configuration S1b actually intends, and it changed the plan:

    arm=a boost=0.0  hash=5956e7ff…  entry_in_prompt= 0/17
    arm=b boost=0.0  hash=c6873a50…  entry_in_prompt= 0/17
    arm=c boost=0.0  hash=c6873a50…  entry_in_prompt= 0/17   <- identical to (b)
    arm=c boost=0.5  hash=c6873a50…  entry_in_prompt= 0/17   <- identical to (b)
    arm=c boost=1.0  hash=c6873a50…  entry_in_prompt= 0/17   <- identical to (b)
    arm=c boost=3.0  hash=77db3dc3…  entry_in_prompt=10/17
    arm=d boost=3.0  hash=77db3dc3…  entry_in_prompt=10/17

At the shipped `knowledge_boost` default the knowledge layer's only entry never
enters `render_retrieved_context`'s five bullets, so arm (c) sends arm (b)'s
prompts byte for byte. Running (c) at 0.0 would have been ADR 0155's mistake a
second time — with a knowledge entry present this time, which would have made
the null look like a result. Hence `--boost 3.0` for the live (c) and (d).

Everything here is offline: the stub provider returns a fixed string and never
reaches `claude -p`.

Usage:
  <venv>/bin/python dry_identity.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PY = sys.executable

CONFIGS = [
    ("a", "0.0"),
    ("b", "0.0"),
    ("c", "0.0"),
    ("c", "0.5"),
    ("c", "1.0"),
    ("c", "3.0"),
    ("d", "3.0"),
]


def main() -> None:
    env = dict(os.environ, PYTHONPATH=f"{REPO}:{HERE}")
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    out_dir.mkdir(parents=True, exist_ok=True)
    for arm, boost in CONFIGS:
        out = out_dir / f"dry_{arm}_{boost}.json"
        run = subprocess.run(
            [
                PY,
                str(HERE / "arms.py"),
                "--arm",
                arm,
                "--repeat",
                "0",
                "--boost",
                boost,
                "--dry-run",
                "--out",
                str(out),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if run.returncode != 0:
            print(f"arm={arm} boost={boost} FAILED\n{run.stdout[-2000:]}\n{run.stderr[-3000:]}")
            raise SystemExit(1)
        d = json.loads(out.read_text())
        ranks = sorted({str(v) for v in d["entry_rank"].values()})
        shown = sum(1 for v in d["entry_in_prompt"].values() if v)
        print(
            f"arm={arm} boost={boost} calls={d['calls']} "
            f"hash={d['draft_prompt_sha256'][:16]} "
            f"entry_in_prompt={shown}/{len(d['entry_in_prompt'])} ranks={ranks}"
        )


if __name__ == "__main__":
    main()
