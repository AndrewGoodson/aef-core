"""Exactly which byte of the request changed between recording and re-execution."""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
sys.path.insert(0, str(W / "peptide"))

from agents.migrated.price_freshness_reviewer.graph import build_graph  # noqa: E402

from aef.harness import harvest as H  # noqa: E402
from aef.harness.harvest import load_runs  # noqa: E402
from aef.kernel import GraphExecutor  # noqa: E402
from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider  # noqa: E402

GRAPH = build_graph()
runs = {r.run_id[:8]: r for r in load_runs(W / "runs")}
run = runs["1ddcad17"]  # O2, one of the four REJECTED


class Capturing(ModelProvider):
    """Answers nothing; records the request the re-execution would have sent."""

    name = "capture"

    def __init__(self, isolation: tuple[str, ...]) -> None:
        self._iso = frozenset(isolation)
        self.seen: list[CompletionRequest] = []

    @property
    def isolation(self) -> frozenset[str]:
        return self._iso

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.seen.append(request)
        raise SystemExit("captured")


scenario = H.Scenario(
    id=run.run_id,
    split=H.Split.TRAIN,
    graph_id=run.graph_id,
    graph_version=run.graph_version,
    initial_state=run.initial_state,
    trace=run.trace,
    recorded_at=run.at,
    model_calls=run.model_calls,
)
services = H._reexecution_services(scenario, run.provider_isolation, run.provider_name)
cap = Capturing(run.provider_isolation)
services = H.agent_services(
    clock=H._fixed_clock(scenario), memory=H.InMemoryMemoryStore(), model_provider=cap
)
try:
    GraphExecutor(GRAPH.compile(), services).run(run.initial_state, record_trace=True)
except SystemExit:
    pass

recorded = run.model_calls[0].request
sent = cap.seen[0]


def msgs(r) -> list[tuple[str, str]]:
    if isinstance(r, dict):
        return [(m["role"], m["content"]) for m in r["messages"]]
    return [(m.role, m.content) for m in r.messages]


rec, new = msgs(recorded), msgs(sent)
print(f"recorded messages: {[(r, len(c)) for r, c in rec]}")
print(f"re-executed     : {[(r, len(c)) for r, c in new]}")
print()
for (ra, ca), (_rb, cb) in zip(rec, new, strict=False):
    if ca != cb:
        print(f"--- role {ra}: DIFFERS ({len(ca)} -> {len(cb)} chars)")
        for line in difflib.unified_diff(
            ca.splitlines(), cb.splitlines(), "recorded", "re-executed", lineterm="", n=1
        ):
            print("   " + line[:200])
    else:
        print(f"--- role {ra}: identical ({len(ca)} chars)")
