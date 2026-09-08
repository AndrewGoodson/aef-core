"""The owner's checks, written once and applied to every harvested scenario.

Three rules, all chosen ON THE SCREEN'S EVIDENCE (`screen.py`, run before
these scenarios were recorded) and all disclosed as chosen because this agent
fails them:

  C1  the output contract's `status: pass|fail|blocked` line exists  (10%)
  C2  the verdict token marlin's own rules force, per scenario       (20%)
  C3  AGENTS.md's two-manual-runs rule, stated in words              (30%)

C2's value is COMPUTED, per scenario, by `screen._expected_status` from that
scenario's own stated facts and the persona's own precedence — never typed
per answer. C1 and C3 are one constant regex each, identical on every
scenario.

All three use `op: regex` on `working_memory.prompt_agent`, so a failure of
any of them keys to the same signature `check:working_memory.prompt_agent:
regex` (ADR 0174 keys a check without its value). That is what makes ADR
0110's two-distinct-runs threshold reachable across scenarios failing
different rules.

Run with --dry to print what would be written and change nothing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from objectives import OBJECTIVES  # noqa: E402
from screen import _expected_status  # noqa: E402

PATH = "working_memory.prompt_agent"

C1 = r"(?mi)^\s*(?:[*_`#>\s-]*)status(?:\*\*)?\s*[:=]\s*(?:pass|fail|blocked)\b"
C3 = r"(?i)two manual|second manual|2 manual"


def c2(expected: str) -> str:
    return rf"(?mi)^\s*(?:[*_`#>\s-]*)status(?:\*\*)?\s*[:=]\s*{expected}\b"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    by_text = {o["text"]: o for o in OBJECTIVES}
    root = pathlib.Path(args.corpus)
    n = 0
    for p in sorted(root.rglob("*.json")):
        if p.name == "manifest.json":
            continue
        d = json.loads(p.read_text())
        obj = d["initial_state"]["objective"]
        o = next((v for k, v in by_text.items() if k in obj), None)
        assert o is not None, f"{p.name}: objective not in objectives.py"
        exp = _expected_status(o)
        checks = [
            {"path": PATH, "op": "regex", "value": C1},
            {"path": PATH, "op": "regex", "value": c2(exp)},
            {"path": PATH, "op": "regex", "value": C3},
        ]
        answer = d["trace"][1]["delta"]["working_memory"].get("prompt_agent", "")
        got = [bool(re.search(c["value"], answer)) for c in checks]
        print(f"{p.parent.name}/{p.name[:8]}  {o['id']:38s} forced={exp:8s} passes={got}")
        if not args.dry:
            d["checks"] = checks
            p.write_text(json.dumps(d, indent=1))
            assert json.loads(p.read_text())["checks"] == checks, "patch did not take"
        n += 1
    print(f"\n{n} scenario(s) {'inspected' if args.dry else 'given 3 owner checks each'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
