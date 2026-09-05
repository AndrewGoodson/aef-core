"""The two blockers between `aef run --record-runs` and `aef loop harvest`,
each isolated to one variable. Offline, zero live calls, stub `command` provider.

  arm 0  as shipped                                 -> REJECTED (cassette miss)
  arm 1  + the cassette the recorder never wrote    -> REJECTED (containment)
  arm 2  + the provider the re-check never has      -> PROMOTED

Nothing under `aef/` is edited: arm 2 monkeypatches `_reexecution_services` in
this process only, to show what the missing piece is worth.
"""

from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a8eaa76f5710a8548")
PILOT = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/m6/pilot"
)
SCRATCH = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/m6"
)
sys.path.insert(0, str(PILOT))

import importlib  # noqa: E402

from aef.cli.run import build_run_config  # noqa: E402
from aef.harness import harvest as harvest_mod  # noqa: E402
from aef.harness.corpus import fixed_clock  # noqa: E402
from aef.harness.harvest import harvest  # noqa: E402
from aef.providers.cassette_provider import CassetteProvider  # noqa: E402
from aef.services.memory.in_memory import InMemoryMemoryStore  # noqa: E402
from aef.services.runtime import agent_services  # noqa: E402

GRAPH = importlib.import_module("agents.migrated.marlin_source.graph").build_graph()
CFG = build_run_config(str(PILOT / "aef.stub.yaml"))
CORPUS = SCRATCH / "reprocorpus"


def run_arm(label: str, runs_dir: Path) -> None:
    if CORPUS.exists():
        shutil.rmtree(CORPUS)
    CORPUS.mkdir(parents=True)
    out = harvest(runs_dir, CORPUS, GRAPH, now=datetime.now(UTC), include_successes=True)
    print(f"\n== {label}")
    for line in out.lines:
        print("  ", line)


run_arm("arm 0 — as shipped (`aef run --record-runs`)", SCRATCH / "stubruns")
run_arm("arm 1 — + the cassette the recorder never wrote", SCRATCH / "stubruns_fixed")

original = harvest_mod._reexecution_services


def with_provider(scenario):  # type: ignore[no-untyped-def]
    return agent_services(
        clock=fixed_clock(scenario),
        memory=InMemoryMemoryStore(),
        model_provider=CassetteProvider(CFG.model_provider, scenario.model_calls, on_miss="fail"),
    )


harvest_mod._reexecution_services = with_provider
try:
    run_arm(
        "arm 2 — + the provider the re-check never has (patched in THIS process)",
        SCRATCH / "stubruns_fixed",
    )
finally:
    harvest_mod._reexecution_services = original

print(
    "\ncorpus after arm 2:",
    sorted(p.relative_to(CORPUS).as_posix() for p in CORPUS.rglob("*.json")),
)
