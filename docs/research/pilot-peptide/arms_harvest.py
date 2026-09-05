"""F-N7-1 isolated to ONE variable, offline, zero live model calls.

arm 0 — `aef loop harvest --include-successes` exactly as shipped.
arm 1 — the same, with the ONE input the re-check does not reproduce supplied:
        the durable memory as it stood BEFORE that run, which is what the
        run's `retrieve` node actually read. Patched in THIS process only;
        no file under aef/ is edited.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
sys.path.insert(0, str(W / "peptide"))

from agents.migrated.price_freshness_reviewer.graph import build_graph  # noqa: E402

from aef.harness import harvest as H  # noqa: E402
from aef.harness.harvest import harvest, load_runs  # noqa: E402
from aef.harness.memory_store import FileMemoryStore  # noqa: E402
from aef.services.memory.in_memory import InMemoryMemoryStore  # noqa: E402

GRAPH = build_graph()
RUNS = W / "runs"
MEM = W / "state" / "memory.jsonl"

runs_by_at = sorted(load_runs(RUNS), key=lambda r: r.at)
order = [r.run_id for r in runs_by_at]
all_records = list(FileMemoryStore(MEM)._load())
print(f"{len(runs_by_at)} run(s), {len(all_records)} durable memory record(s)")
print("run order by recorded time:", ", ".join(rid[:8] for rid in order))
print()

original = H._reexecution_services


def before_this_run(run_id: str) -> list:
    """The records written by every run that ran BEFORE this one."""
    cut = order.index(run_id)
    earlier = set(order[:cut])
    return [rec for rec in all_records if rec.run_id in earlier]


def patched(scenario, isolation=(), provider_name=""):  # type: ignore[no-untyped-def]
    services = original(scenario, isolation, provider_name)
    store = InMemoryMemoryStore()
    for rec in before_this_run(scenario.id):
        store.write(rec)
    return H.agent_services(
        clock=H._fixed_clock(scenario),
        memory=store,
        model_provider=services.model_provider,
    )


def arm(label: str, patch: bool) -> None:
    corpus = W / f"arm-{label}-corpus"
    state = W / f"arm-{label}-state"
    if patch:
        H._reexecution_services = patched  # type: ignore[assignment]
    try:
        corpus.mkdir(parents=True, exist_ok=True)
        state.mkdir(parents=True, exist_ok=True)
        out = harvest(
            RUNS, corpus, GRAPH, now=datetime.now(UTC), include_successes=True
        )
    finally:
        H._reexecution_services = original  # type: ignore[assignment]
    print(f"== arm {label}")
    print(f"   promoted {len(out.promoted)} run(s) to the train split")
    if out.rejected_nondeterministic:
        print(
            f"     {len(out.rejected_nondeterministic)} REJECTED, did not re-execute "
            f"deterministically: "
            + ", ".join(r[:8] for r in sorted(out.rejected_nondeterministic))
        )
    print(f"   redaction: {json.dumps(getattr(out, 'redaction_counts', {}), sort_keys=True)}")


arm("0-as-shipped", patch=False)
print()
arm("1-memory-the-run-saw", patch=True)
