"""Does ADR 0197's new `uuid` pattern refuse the very runs this pilot harvested?

A recorded run's id IS a UUID (`aef run --record-runs` names each file
`<uuid4>.json` and stamps `RecordedRun.run_id`), and `harvest` scans the
scenario it is about to write with the same policy. If that scan sees the id,
every harvested scenario becomes "a secret survived redaction" the moment ADR
0197 lands.

Two arms over the SAME five real runs, one variable — the pattern list.
Zero live model calls.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
sys.path.insert(0, str(W / "peptide"))

from agents.migrated.price_freshness_reviewer.graph import build_graph  # noqa: E402

from aef.harness.harvest import harvest  # noqa: E402
from aef.harness.redaction import DEFAULT_PATTERNS as BASE_PATTERNS  # noqa: E402
from aef.harness.redaction import RedactionPolicy  # noqa: E402

spec = importlib.util.spec_from_file_location("redaction_trunk", W / "redaction_main.py")
assert spec and spec.loader
trunk = importlib.util.module_from_spec(spec)
sys.modules["redaction_trunk"] = trunk
spec.loader.exec_module(trunk)

GRAPH = build_graph()
RUNS = W / "runs2"

for label, patterns in (
    ("BASE  (5 patterns, no uuid)", BASE_PATTERNS),
    ("TRUNK (10 patterns, ADR 0197's uuid included)", trunk.DEFAULT_PATTERNS),
):
    corpus = W / f"uuid-arm-{'base' if patterns is BASE_PATTERNS else 'trunk'}-corpus"
    if corpus.exists():
        shutil.rmtree(corpus)
    corpus.mkdir(parents=True)
    out = harvest(
        RUNS,
        corpus,
        GRAPH,
        now=datetime.now(UTC),
        include_successes=True,
        redaction=RedactionPolicy(patterns=patterns),
    )
    print(f"== {label}")
    for line in out.lines:
        print(f"   {line}")
    print(f"   redactions={out.redactions} "
          f"unredactable={len(out.rejected_unredactable)} "
          f"changed_behaviour={len(out.rejected_redaction_changed_behaviour)}")
    print()
