"""Reproduce the ten-minute wall. Zero live calls.

The summary corpus's word-cap check is `^(?:\\s*\\S+){1,35}\\s*$`. A bounded
repetition of `\\s*\\S+` is ambiguous — every internal split of the same text
is a distinct path — so a subject that does NOT match forces the engine
through exponentially many of them. A summary within the cap matches and is
instant; a summary one word over hangs.

This is what a scenario run looks like when the model writes a long summary,
and it is a candidate explanation for the "three attempts past a ten-minute
wall" that ADR 0123 recorded as I13's unfinished live noise floor.
"""

from __future__ import annotations

import re
import time

PATTERN = r"^(?:\s*\S+){1,35}\s*$"


def main() -> None:
    compiled = re.compile(PATTERN)
    print(f"pattern: {PATTERN}\n")
    print(f"{'words':>6}  {'matches':>8}  {'seconds':>12}")
    for n in range(30, 48):
        subject = " ".join(f"word{i}" for i in range(n))
        t = time.time()
        matched = bool(compiled.match(subject))
        dt = time.time() - t
        print(f"{n:>6}  {str(matched):>8}  {dt:>12.4f}")
        if dt > 30:
            print("\nstopping: already past 30s on one check")
            break


if __name__ == "__main__":
    main()
