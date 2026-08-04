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

from aef.kernel.contracts import Services, _End
from aef.kernel.executor import NodeExecutionRecord
from aef.kernel.graph import CompiledGraph
from aef.state import AEFState


class DeterminismViolationError(RuntimeError):
    pass


class MalformedTraceError(RuntimeError):
    """A trace whose records don't form a legitimate chain — record N's
    route doesn't match record N+1's node_id, or a record routes to `END`
    with more records still to come. `GraphExecutor.run(record_trace=True)`
    can never produce a trace like this (routing is validated live), but
    `replay()` accepts any `Sequence[NodeExecutionRecord]`, and nothing
    stops a hand-assembled, reordered, or corrupted trace from being passed
    in — reproduced directly (see docs/adr/0023), not hypothetical."""


class ReplayEngine:
    def __init__(self, compiled: CompiledGraph, services: Services) -> None:
        self._graph = compiled.graph
        self._services = services

    def replay(self, trace: Sequence[NodeExecutionRecord]) -> AEFState:
        if not trace:
            raise ValueError("cannot replay an empty trace")
        self._validate_chain(trace)

        state: AEFState | None = None
        for record in trace:
            node = self._graph.nodes.get(record.node_id)
            if node is None:
                raise DeterminismViolationError(
                    f"trace references node {record.node_id!r}, which is not in this graph"
                )
            if node.deterministic and not record.is_fallback:
                # A fallback record (node raised, fell back — ADR 0036) is
                # trusted, not re-executed: re-running `fn` would raise the
                # original exception again. The recorded error-delta + fallback
                # route are replayed verbatim, exactly as a non-deterministic
                # node's output is (ADR 0039).
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

    def _validate_chain(self, trace: Sequence[NodeExecutionRecord]) -> None:
        """A legitimate trace's records form a path: record[i].route names
        record[i+1].node_id, for every record except the last. `END` (or a
        fan-out route — not supported by replay, same as the live executor
        per docs/adr/0007) may only appear on the final record."""
        last_index = len(trace) - 1
        for i, record in enumerate(trace):
            route = record.route
            is_last = i == last_index
            if isinstance(route, tuple):
                raise MalformedTraceError(
                    f"trace record {i} ({record.node_id!r}) has a fan-out route {route!r} — "
                    f"replay does not support fan-out traces (see docs/adr/0007)"
                )
            if isinstance(route, _End):
                if not is_last:
                    raise MalformedTraceError(
                        f"trace record {i} ({record.node_id!r}) routes to END, but the trace "
                        f"continues afterward with {trace[i + 1].node_id!r} — malformed trace"
                    )
                continue
            if is_last:
                continue  # a trailing non-END route is fine: this may be a
                # partial trace (e.g. captured up to a crash) rather than a
                # complete run — replay doesn't require every trace to reach END.
            next_node_id = trace[i + 1].node_id
            if route != next_node_id:
                raise MalformedTraceError(
                    f"trace record {i} ({record.node_id!r}) routes to {route!r}, but the next "
                    f"trace record is {next_node_id!r} — malformed or reordered trace"
                )
