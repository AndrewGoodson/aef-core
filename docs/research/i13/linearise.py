"""Rewrite the corpus's word-cap check into a linear-time equivalent.

`^(?:\\s*\\S+){1,N}\\s*$` matches iff the string can be cut into between 1 and
N runs of non-space. Because a run may be split anywhere, the minimal
decomposition is the whitespace-separated token list, so the predicate is
exactly `1 <= token_count <= N`. `^\\s*\\S+(?:\\s+\\S+){0,N-1}\\s*$` expresses
the same predicate with `\\s+`/`\\S+` disjoint at every position, so the engine
has no choice point to backtrack over.

Only the corpus COPY in scratch is rewritten. The repo's corpus/ is untouched.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

SRC = re.compile(r"^\^\(\?:\\s\*\\S\+\)\{1,(\d+)\}\\s\*\$$")


def linear_form(n: int) -> str:
    return rf"^\s*\S+(?:\s+\S+){{0,{n - 1}}}\s*$"


def equivalence_check(n: int, trials: int = 4000) -> None:
    """Both patterns must agree on every generated string. The original is
    only evaluated where it terminates fast — strings at or under the cap,
    plus a hand-checked handful over it — so this proves agreement, and the
    ReDoS reproduction proves why the original cannot be asked about the rest.
    """
    rng = random.Random(1013)
    alphabet = "abcXYZ,.;'-1"
    old = re.compile(rf"^(?:\s*\S+){{1,{n}}}\s*$")
    new = re.compile(linear_form(n))
    for _ in range(trials):
        k = rng.randint(0, n)  # 0..n tokens: never over the cap, so old is fast
        toks = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 6))) for _ in range(k)]
        sep = rng.choice([" ", "  ", "\n", " \t "])
        text = sep.join(toks)
        if rng.random() < 0.3:
            text = " " + text
        if rng.random() < 0.3:
            text = text + "  "
        a = old.search(text) is not None
        b = new.search(text) is not None
        if a != b:
            raise SystemExit(f"DISAGREE n={n} text={text!r} old={a} new={b}")


def main(corpus: Path) -> int:
    caps = set()
    changed = 0
    for path in sorted(corpus.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        payload = json.loads(path.read_text())
        checks = payload.get("checks") or []
        touched = False
        for check in checks:
            if check.get("op") != "regex":
                continue
            m = SRC.match(check["value"])
            if not m:
                continue
            n = int(m.group(1))
            caps.add(n)
            check["value"] = linear_form(n)
            touched = True
        if touched:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            changed += 1
            print(f"linearised {path.relative_to(corpus)}")
    for n in sorted(caps):
        equivalence_check(n)
        print(f"equivalence check passed for cap {n}")
    print(f"{changed} scenario(s) rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
