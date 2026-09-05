"""Strip the recorded model_calls from the six summary validation scenarios.

Why: the incumbent prompt reproduces the recorded request byte-for-byte, so
`--cassette-miss live` HITS the cassette and makes zero live calls. A floor
measured that way is the replayed floor (spread 0.000000), not the live one.
Emptying the cassette forces every draft call to miss and go live — which is
exactly what the planted-regression arm experiences, so both arms are
symmetric and the only difference between them is the prompt.

The repo's own corpus/ is NEVER touched; this rewrites a scratch copy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TARGETS = [
    "sum-13-cider-press",
    "sum-14-quarry-lake",
    "sum-15-bookbinder",
    "sum-16-cliff-path",
    "sum-17-clockmaker",
    "sum-18-heron-rookery",
]


def main(corpus: Path) -> int:
    for name in TARGETS:
        path = corpus / "validation" / f"{name}.json"
        payload = json.loads(path.read_text())
        before = len(payload.get("model_calls", []))
        payload["model_calls"] = []
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"{name}: model_calls {before} -> 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
