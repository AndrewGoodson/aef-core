"""P2 step 1b — the plumbing reproduction, the (c)≡(b) question, and the
choice of arm (d)'s boost, all before any quota.

ADR 0193 established two things this rig inherits: hash every rendered draft
prompt under a stub provider that records instead of sending (S1b's check,
which catches the 84 calls ADR 0155 spent comparing one configuration against
itself), and choose the boost from the WORST case rather than the best.

What is new is the question. On a store holding ONE entry, `(c)@0.0` sent
`(b)`'s prompts byte for byte, so ADR 0193 did not run (c) at all and said so.
The store now holds THREE, ranked against each other and against twenty-odd
raw records, and whether the identity survives is not something to assume:
`entry_in_prompt` below counts, per arm, how many of the twenty-one validation
prompts carried each lesson inside `render_retrieved_context`'s five bullets.

**This is the WORST case**, by construction. The stub answers a fixed 9-word
string that trips no check, so no scored run refreshes any lesson and ADR
0116's staleness demotion walks all three down monotonically. The live
trajectory can only be better. Arm (d)'s boost is chosen here for exactly that
reason: the smallest value on the grid that keeps **every** lesson inside the
five bullets on **every** scenario even when nothing refreshes them.

Everything here is offline: the stub returns a fixed string and never reaches
`claude -p`.

Usage:
  PYTHONPATH=<worktree>:<here> <venv>/bin/python dry_identity.py [out-dir]
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

# A 1.0 grid, so "the smallest value that engages every lesson everywhere" is
# a value this sweep can actually name rather than the nearest one it tried.
CONFIGS = [("a", "0.0"), ("b", "0.0"), ("c", "0.0")] + [("d", f"{b}.0") for b in range(1, 19)]


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
        rendered = d["lessons_rendered"]
        n = len(rendered)
        counts = {
            name: sum(1 for v in rendered.values() if name in v)
            for name in ("cap", "ruleA", "both")
        }
        all_three = sum(1 for v in rendered.values() if len(v) == 3)
        print(
            f"arm={arm} boost={boost:>5} calls={d['calls']} "
            f"hash={d['draft_prompt_sha256'][:16]} "
            f"cap={counts['cap']:2d}/{n} ruleA={counts['ruleA']:2d}/{n} "
            f"both={counts['both']:2d}/{n} all_three={all_three:2d}/{n}"
        )


if __name__ == "__main__":
    main()
