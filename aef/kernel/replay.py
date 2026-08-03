"""`ReplayEngine` — enforces constraint #1: nodes declaring
`deterministic=True` must reproduce an identical `StateDelta` and `Route`
when re-invoked with the same recorded `(state, context)`. Non-deterministic
(LLM) nodes are quarantined: their recorded output is trusted and replayed
verbatim, never re-executed and compared.

This is what makes the control plane's replayability an enforced property
rather than a hopeful convention.
"""

from __future__ import annotations

from collections.abc import Sequence

from aef.kernel.contracts import Services
from aef.kernel.executor import NodeExecutionRecord
from aef.kernel.graph import CompiledGraph
from aef.state import AEFState


class DeterminismViolationError(RuntimeError):
    pass


class ReplayEngine:
    def __init__(self, compiled: CompiledGraph, services: Services) -> None:
        self._graph = compiled.graph
        self._services = services

    def replay(self, trace: Sequence[NodeExecutionRecord]) -> AEFState:
        if not trace:
            raise ValueError("cannot replay an empty trace")

        state: AEFState | None = None
        for record in trace:
            node = self._graph.nodes.get(record.node_id)
            if node is None:
                raise DeterminismViolationError(
                    f"trace references node {record.node_id!r}, which is not in this graph"
                )
            if node.deterministic:
                replayed_delta, replayed_route = node.fn(
                    record.input_state, record.context, self._services
                )
                if replayed_delta != record.delta:
                    raise DeterminismViolationError(
                        f"node {node.id!r} is declared deterministic=True but produced a "
                        f"different StateDelta on replay.\nrecorded={record.delta!r}\n"
                        f"replayed={replayed_delta!r}"
                    )
                if replayed_route != record.route:
                    raise DeterminismViolationError(
                        f"node {node.id!r} is declared deterministic=True but produced a "
                        f"different Route on replay: recorded={record.route!r} "
                        f"replayed={replayed_route!r}"
                    )
            # Trust the recorded delta to reconstruct state — non-deterministic
            # (LLM) node output is replayed, not recomputed.
            state = record.delta.apply(record.input_state)

        assert state is not None  # non-empty trace guarantees at least one iteration
        return state
