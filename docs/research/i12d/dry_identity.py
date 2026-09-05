"""N2 step 1b — the plumbing reproduction and the knob's A/B, before any quota.

ADR 0155 spent 84 live calls comparing one configuration against itself and
found out afterwards. S1b added the check that catches it — hash every rendered
draft prompt under a stub provider that records instead of sending — and this
runs it over N2's configuration on the one-model corpus. It produced:

    arm=a boost=0.0  hash=5956e7ffb9b0fcc9  entry_in_prompt= 0/17
    arm=b boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17
    arm=c boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17  <- IS arm (b)
    arm=c boost=3.0  hash=a7427ac0524ae6e0  entry_in_prompt= 4/17
    arm=c boost=4.0  hash=bd92e98d844f2781  entry_in_prompt= 8/17
    arm=c boost=5.0  hash=...               entry_in_prompt=10/17
    arm=c boost=6.0  hash=01b9836e72df8c14  entry_in_prompt=13/17
    arm=c boost=7.0  hash=914814cfd2e35044  entry_in_prompt=16/17
    arm=c boost=8.0  hash=...               entry_in_prompt=17/17

**Two findings, both at zero cost.**

1. **The knob's A/B at the shipped default needs no quota.** `(c)` at 0.0
   sends `(b)`'s prompts BYTE FOR BYTE on all seventeen scenarios — one hash,
   not a similar one. ADR 0184 reported the same identity on the pre-0186
   corpus and it survives the re-recording. So the arm that isolates
   `knowledge_boost` at its default is not a third measurement; it is arm (b)
   under another name, and running it live would spend 51 calls to reproduce a
   hash.
2. **Arms (a) and (b) reproduce S1b's and S1c's live prompt hashes byte for
   byte** (`5956e7ff…`, `c6873a50…`) even though ADR 0186 re-recorded eighteen
   scenarios underneath them. That is the cross-check that three nights'
   control arms are the same experiment: the re-recording changed what the
   MODEL ANSWERED, and neither control arm renders anything derived from an
   answer into the top five bullets.

**This is the WORST case for arm (c), by construction.** The stub answers a
fixed 9-word string that never trips the word cap, so no scored run ever
refreshes the lesson and ADR 0116's staleness demotion walks it down
monotonically. The live trajectory can only be better (S1c: 11/17 dry, 15/17
live). The boost arm (c) runs at is chosen HERE rather than from the static
sweep for exactly that reason: 8.0 is the smallest value on a 1.0 grid that
keeps the lesson inside `render_retrieved_context`'s five bullets in all
seventeen scenarios even when nothing refreshes it.

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
    ("c", "4.0"),
    ("c", "5.0"),
    ("c", "6.0"),
    ("c", "7.0"),
    ("c", "8.0"),
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
