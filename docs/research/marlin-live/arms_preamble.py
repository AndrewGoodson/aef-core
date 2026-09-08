"""F-Q1-1, isolated to one variable: the sentence that says there are no tools.

Arm A — the ten objectives exactly as `objectives.py` states them.
Arm B — the same ten, with `objectives.NO_TOOLS_PREAMBLE` prepended and
        nothing else changed. Fresh memory store per arm, so the retrieved
        lesson block is not a second variable.

The measure is not a score. It is whether the completion is an ANSWER or a
description of work the model believes it did: `aef migrate` puts each persona
in the system role of one `--tools "" --max-turns 1` completion, and marlin's
personas tell their reader to inspect the repository.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

Q = pathlib.Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1"
)

# The model writing tool-call syntax, or narrating a tool result, in prose.
TOOL_SHAPE = re.compile(
    r"<invoke name=|<parameter name=|\{\"name\":\"Bash\"|"
    r"I'll (check|inspect|ground|look|read|verify)\b|"
    r"The working directory is empty|No files found",
    re.I,
)
STATUS_LINE = re.compile(r"(?mi)^\s*(?:[*_`#>\s-]*)status(?:\*\*)?\s*[:=]\s*(pass|fail|blocked)\b")


def answers(runs: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(runs.glob("*.json")):
        d = json.loads(p.read_text())
        pa = next(t for t in d["trace"] if t["node_id"] == "prompt_agent")
        out[d["run_id"]] = pa["delta"]["working_memory"].get("prompt_agent", "")
    return out


def main() -> int:
    rows = []
    for arm, runs in (("A  no preamble", Q / "runs-armA"), ("B  + preamble", Q / "runs-armB")):
        a = answers(runs)
        short = sum(1 for t in a.values() if len(t) < 1000)
        tooly = sum(1 for t in a.values() if TOOL_SHAPE.search(t[:400]))
        status = sum(1 for t in a.values() if STATUS_LINE.search(t))
        words = sorted(len(t.split()) for t in a.values())
        rows.append((arm, len(a), short, tooly, status, words))
    print(f"{'arm':16s} {'n':>3s} {'<1000 chars':>12s} {'tool-shaped':>12s} {'status: line':>13s}")
    for arm, n, short, tooly, status, _ in rows:
        print(f"{arm:16s} {n:3d} {short:12d} {tooly:12d} {status:13d}")
    print()
    for arm, _, _, _, _, words in rows:
        print(f"{arm:16s} word counts: {words}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
