"""Which scenario to move TRAIN -> VALIDATION so one gated turn fits the
wall-clock the harness allows, and what today's audit slice then draws.

This is a COST decision and it is disclosed as one: the night's first attempt
at 3 gated scenarios overran a 540 s alarm mid-gate. A turn costs
6 x (gated scenarios) live calls at ~27 s each plus seven workspace copies, so
2 gated scenarios is what fits. `audit_slice` is still a function of the
corpus and the date and nothing else — moving a scenario changes the POOL, not
the draw, and the table below is printed for every candidate move so the
choice is visible rather than fitted.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a1aa5766514609859")

from aef.harness.corpus import Split, load_corpus  # noqa: E402
from aef.harness.loop import audit_slice  # noqa: E402

SCORES = {
    "2b1b3501": ("src-02", 1.0),
    "48572a57": ("src-07", 1.0),
    "9305e905": ("src-06", 0.0),
    "a62dfb48": ("src-10", 0.3333),
    "a9c8ba03": ("src-05", 1.0),
}


class _S:
    def __init__(self, sid: str, split: Split) -> None:
        self.id, self.split = sid, split


class _C:
    def __init__(self, scenarios: list[_S]) -> None:
        self.scenarios = scenarios


def main() -> int:
    corpus = load_corpus(pathlib.Path(sys.argv[1]))
    ids = sorted(s.id for s in corpus.scenarios if s.split is Split.TRAIN)
    now = datetime.now(UTC)
    print(f"train today: {[i[:8] for i in ids]}   date {now:%Y-%m-%d}\n")
    print(f"{'moved to validation':22s} {'held back':22s} {'GATED (id, objective, score)'}")
    for moved in [None, *ids]:
        pool = [i for i in ids if i != moved]
        c = _C([_S(i, Split.TRAIN) for i in pool])
        sl = audit_slice(c, at=now, size=2)  # type: ignore[arg-type]
        gated = [i for i in pool if i not in sl.ids]
        g = ", ".join(f"{i[:8]} {SCORES[i[:8]][0]} {SCORES[i[:8]][1]:.2f}" for i in gated)
        print(f"{(moved[:8] if moved else '(none)'):22s} {str([i[:8] for i in sl.ids]):22s} {g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
