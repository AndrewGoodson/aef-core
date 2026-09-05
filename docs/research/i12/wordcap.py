"""A linear stand-in for the corpus's exponential word-cap regex, and the
proof that it is one.

`corpus/validation/sum-*.json` caps summary length with
`^(?:\\s*\\S+){1,N}\\s*$`. `\\s*\\S+` repeated is AMBIGUOUS — the engine can
split the same text between the repetitions in exponentially many ways — so a
subject that cannot match forces it through all of them. Measured: at N=35, a
35-word subject matches in 0.0000s and a 36-word subject had not finished
after 600s.

`^\\s*\\S+(?:\\s+\\S+){0,N-1}\\s*$` accepts exactly the same language and is
linear, because `\\S+` cannot contain whitespace and `\\s+` cannot contain
non-whitespace: the tokenisation is forced, so there is only ever one path.

This lives in the measurement rig, NOT in the repo. The defect is in
`corpus/` and in `aef/harness/checks.py` running an owner-supplied pattern
with no guard, and neither is this worker's file (ADR 0155).
"""

from __future__ import annotations

import dataclasses
import re

# The exact shape the corpus ships.
_EXPONENTIAL = re.compile(r"^\^\(\?:\\s\*\\S\+\)\{1,(\d+)\}\\s\*\$$")


def linear_equivalent(pattern: str) -> str | None:
    """The linear rewrite of `pattern`, or None if it is not the known shape.

    Deliberately an exact-shape match rather than a heuristic: rewriting a
    pattern this rig does not fully understand would change the metric it is
    supposed to be measuring.
    """
    m = _EXPONENTIAL.match(pattern)
    if m is None:
        return None
    cap = int(m.group(1))
    if cap < 1:
        return None
    return r"^\s*\S+(?:\s+\S+){0," + str(cap - 1) + r"}\s*$"


def delinearise_scenario(scenario):  # type: ignore[no-untyped-def]
    """A copy of `scenario` with every known-exponential check rewritten."""
    rewritten = []
    changed = False
    for check in scenario.checks:
        if check.op == "regex" and isinstance(check.value, str):
            replacement = linear_equivalent(check.value)
            if replacement is not None:
                rewritten.append(dataclasses.replace(check, value=replacement))
                changed = True
                continue
        rewritten.append(check)
    if not changed:
        return scenario
    return dataclasses.replace(scenario, checks=tuple(rewritten))


def _prove() -> None:
    """Agreement on every subject the original can decide, plus the timing."""
    import time

    failures = 0
    for cap in range(1, 21):
        original = re.compile(rf"^(?:\s*\S+){{1,{cap}}}\s*$")
        linear = re.compile(linear_equivalent(rf"^(?:\s*\S+){{1,{cap}}}\s*$") or "")
        subjects = [""] + [
            sep.join(f"w{i}" for i in range(n)) + trail
            for n in range(0, cap + 4)
            for sep in (" ", "  ", "\t")
            for trail in ("", " ", "\n")
        ]
        for subject in subjects:
            a = original.search(subject) is not None
            b = linear.search(subject) is not None
            if a != b:
                failures += 1
                print(f"DISAGREE cap={cap} subject={subject!r}: original={a} linear={b}")
    print(
        f"caps 1..20, every subject 0..cap+3 words x 3 separators x 3 trailers: "
        f"{failures} disagreements"
    )

    cap = 35
    original = re.compile(rf"^(?:\s*\S+){{1,{cap}}}\s*$")
    linear = re.compile(linear_equivalent(rf"^(?:\s*\S+){{1,{cap}}}\s*$") or "")
    for n in (35, 36, 60):
        subject = " ".join(f"w{i}" for i in range(n))
        t = time.time()
        b = linear.search(subject) is not None
        lin_dt = time.time() - t
        if n <= cap:
            t = time.time()
            a = original.search(subject) is not None
            orig_dt = time.time() - t
            print(f"n={n}: original={a} in {orig_dt:.4f}s | linear={b} in {lin_dt:.6f}s")
        else:
            print(f"n={n}: original=<did not terminate in 600s> | linear={b} in {lin_dt:.6f}s")


if __name__ == "__main__":
    _prove()
