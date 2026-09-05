"""S1c's plumbing reproduction, run BEFORE any live quota was spent.

ADR 0155 spent 84 live calls comparing one configuration against itself and
found out afterwards. S1b added the check that catches it — hash every rendered
draft prompt under a stub provider that records instead of sending — and this
runs it over S1c's configuration, with the producer now wired into the scored
split. It produced:

    arm=a boost=0.0  hash=5956e7ffb9b0fcc9  entry_in_prompt= 0/17  (= S1b's (a))
    arm=b boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17  (= S1b's (b))
    arm=c boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17  <- IS arm (b)
    arm=c boost=3.0  hash=3868153f5bf8352e  entry_in_prompt=11/17

**Arms (a) and (b) reproduce S1b's live prompt hashes byte for byte**, which is
what makes the two nights' control arms the same experiment: ADR 0180's excerpt
removal changed a *knowledge entry's* text, and (a) and (b) never render one.

**Arm (d) is gone**, and with it the `--arm d` choice: S1b measured it sending
arm (c)'s prompts byte for byte on all 17 scenarios, so its 51 live calls
reached no prompt. Those calls are what bought this increment's repeats.

**One limit of this rig that S1b's did not have.** S1b could say its dry hashes
were a property of the live runs too, "because the rendered lessons are drawn
from records whose text does not depend on what the model answered". With the
producer on the scored split that is no longer true: whether a lesson is fresh
depends on whether a check failed, which depends on what the model said. The
stub answers a fixed 9-word string that never trips the word cap, so the
sequential trajectory here is NOT the live one — the dry (c) reproduces S1b's
staleness walk (rank 0 -> 39) precisely because the stub never re-triggers the
lesson. Use this to check plumbing and the first scenario's ranking; use
`boost_sweep.py` to choose the boost, and the live results for anything else.

Everything here is offline: the stub returns a fixed string and never reaches
`claude -p`.

Usage:
  <venv>/bin/python dry_identity.py [out-dir]
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
    ("c", "3.0"),
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
