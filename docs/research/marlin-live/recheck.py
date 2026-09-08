"""Re-run every edited measurement script from its COMMITTED copy and diff its
output against the artefact it produced (ADR 0192's rule: getting a committed
script through ruff is a code change, and a code change to a measurement script
must be shown not to change the measurement)."""

import pathlib
import subprocess
import sys

D = pathlib.Path(
    "/Users/raptor/aef-core/.claude/worktrees/agent-a1aa5766514609859/docs/research/marlin-live"
)
Q = pathlib.Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1"
)
PY = "/Users/raptor/aef-core/.venv/bin/python"
CLONE = Q / "marlin"

CASES = [
    ("screen.py", [], "05-screen.txt", None),
    ("verdict_table.py", [], "05b-verdict-tokens.txt", None),
    ("arms_preamble.py", [], "04-arms-preamble.txt", None),
    (
        "redaction_scan.py",
        ["--runs", str(Q / "runs"), "--repo", str(CLONE)],
        "10-redaction.txt",
        None,
    ),
    ("parse_run_commands.py", [], "02b-run-commands-parse.txt", CLONE),
    ("bytes_outside.py", [], "01b-bytes-outside-the-block.txt", None),
]

rc = 0
for script, args, artefact, cwd in CASES:
    out = subprocess.run(
        [PY, str(D / script), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env={
            "PATH": "/Users/raptor/aef-core/.venv/bin:/usr/bin:/bin",
            "PYTHONPATH": "/Users/raptor/aef-core/.claude/worktrees/"
            "agent-a1aa5766514609859:" + str(CLONE),
            "HOME": "/Users/raptor",
        },
    )
    produced = out.stdout
    on_disk = (D / "artefacts" / artefact).read_text()
    same = produced.strip() == on_disk.strip()
    print(f"{script:26s} -> {artefact:34s} {'IDENTICAL' if same else 'DIFFERS'}")
    if not same:
        rc = 1
        a = produced.strip().splitlines()
        b = on_disk.strip().splitlines()
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            if x != y:
                print(f"    first diff at line {i + 1}:")
                print(f"      now: {x[:120]}")
                print(f"      was: {y[:120]}")
                break
        if len(a) != len(b):
            print(f"    line counts: now {len(a)}, was {len(b)}")
        if out.stderr:
            print(f"    stderr: {out.stderr.strip()[:400]}")
sys.exit(rc)
