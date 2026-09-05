"""Reproduce the defect that stopped I11's three live attempts and this one.

The corpus's word-cap check is `^(?:\\s*\\S+){1,35}\\s*$` — a nested
quantifier over an ambiguous alternation. On a string that MATCHES it returns
at once. On a string that does NOT (one word too many) the engine must try
every way of splitting the text into <= 35 chunks before it can report
failure, which is exponential. `aef/harness/checks.py::_holds` calls
`re.search` with no timeout, so the scorer hangs, forever, on exactly the
input a live model produces when it overruns the cap.

Run: prints the recorded (passing) answer's time, then the live answer's.
"""

from __future__ import annotations

import multiprocessing as mp
import re
import time

PATTERN = r"^(?:\s*\S+){1,35}\s*$"
LINEAR = r"^\s*\S+(?:\s+\S+){0,34}\s*$"

RECORDED = (
    "The Dunmere cider press, an 1850s hand-turned oak screw press, has been rebuilt by "
    "volunteers with seasoned estate oak and will press apples again this autumn after "
    "forty years; bring surplus apples, take juice home."
)
LIVE = (
    "The 1850s Dunmere cider press, a hand-turned oak screw press, has been restored with "
    "seasoned oak and a hand-cut thread, and will press apples this autumn after forty "
    "years, with volunteers exchanging juice for surplus apples."
)


def _run(pattern: str, text: str, q: mp.Queue[object]) -> None:
    t0 = time.monotonic()
    hit = re.search(pattern, text) is not None
    q.put((hit, time.monotonic() - t0))


def timed(pattern: str, text: str, wall: float = 20.0) -> str:
    q: mp.Queue[object] = mp.Queue()
    p = mp.Process(target=_run, args=(pattern, text, q))
    p.start()
    p.join(wall)
    if p.is_alive():
        p.terminate()
        p.join()
        return f"DID NOT TERMINATE in {wall:.0f}s"
    hit, dt = q.get()  # type: ignore[misc]
    return f"match={hit} in {dt * 1000:.2f} ms"


if __name__ == "__main__":
    for label, text in (("recorded", RECORDED), ("live", LIVE)):
        words = len(text.split())
        print(f"--- {label}: {words} words")
        print(f"    corpus pattern  : {timed(PATTERN, text)}")
        print(f"    linear equivalent: {timed(LINEAR, text)}")
