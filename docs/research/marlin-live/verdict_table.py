"""The screen's R11 column, answer by answer: what the model ruled, and what
marlin's own rules force. This is the table an owner argues with."""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from objectives import OBJECTIVES  # noqa: E402
from screen import STATUS, Q, _expected_status, answers  # noqa: E402


def main(arm: str = "runs-armB") -> int:
    facts = {o["id"]: o for o in OBJECTIVES}
    print(f"arm: {arm}")
    print(f"{'objective':38s} {'model':>8s} {'forced':>8s}  agree")
    agree = 0
    for oid, a in answers(Q / arm):
        m = STATUS.search(a)
        got = m.group(1).lower() if m else "(none)"
        exp = _expected_status(facts[oid])
        agree += got == exp
        print(f"{oid:38s} {got:>8s} {exp:>8s}  {'yes' if got == exp else 'NO'}")
    print(f"\nagree on {agree} of 10")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
