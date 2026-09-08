"""Prove `aef adopt` appended and changed nothing.

The bytes of AGENTS.md and the ignore file OUTSIDE the aef marker block,
hashed against what was there before adopt ran.
"""

import hashlib
import pathlib

Q = pathlib.Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1"
)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


CASES = (
    ("AGENTS.md", "<!-- aef:begin", "<!-- aef:end -->", "AGENTS.md.before"),
    ("." + "gitignore", "# aef:begin", "# aef:end", "ignore.before"),
)

ok = True
for name, begin, end, before_name in CASES:
    before = (Q / "art" / before_name).read_bytes()
    after = (Q / "marlin" / name).read_bytes()
    lines = after.decode().split("\n")
    b = next(i for i, ln in enumerate(lines) if ln.startswith(begin))
    e = next(i for i, ln in enumerate(lines) if ln.strip() == end.strip())
    start = b - 1 if b > 0 and lines[b - 1] == "" else b
    outside = "\n".join(lines[:start] + lines[e + 1 :]).encode()
    same = sha(before) == sha(outside)
    ok = ok and same
    print(f"== {name}")
    print(f"   aef block   : lines {b + 1}..{e + 1}; blank separator at {start + 1}")
    print(f"   before      : sha256 {sha(before)}  {len(before)} bytes")
    print(f"   outside now : sha256 {sha(outside)}  {len(outside)} bytes")
    print(f"   IDENTICAL   : {same}")
print(f"\nall pre-existing bytes survived verbatim: {ok}")
