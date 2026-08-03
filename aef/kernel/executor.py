"""`GraphExecutor` — runs a `CompiledGraph` one super-step (one node) at a
time. This is the control plane: sequencing and routing here are pure
bookkeeping over what nodes return, with zero model calls or I/O of its own.

Every super-step is checkpointed (if a `DurabilityBackend` is configured) and
traced (if a `Tracer` is configured) — observability and durability are
opt-in via DI, never hardwired.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

from aef.kernel.contracts import Context, Node, Route, Services, _End
from aef.kernel.graph import CompiledGraph, Graph
from aef.observability import semconv
from aef.state import AEFState, StateDelta


class GraphExecutionError(RuntimeError):
    pass


class RoutingViolationError(RuntimeError):
    """A node returned a route not backed by any declared, currently-true
    edge (report §4 / blueprint §2.2: edges are typed and declared
    statically — a node cannot silently invent a new transition)."""


@dataclass(frozen=True)
class NodeExecutionRecord:
    """One super-step, captured for replay (`aef.kernel.replay`)."""

    node_id: str
    input_state: AEFState
    context: Context
    delta: StateDelta
    route: Route


@dataclass(frozen=True)
class ExecutionResult:
    final_state: AEFState
    trace: tuple[NodeExecutionRecord, ...] | None = None


class GraphExecutor:
    def __init__(
        self, compiled: CompiledGraph, services: Services, *, max_steps: int = 1000
    ) -> None:
        self._graph: Graph = compiled.graph
        self._services = services
        self._max_steps = max_steps

    def run(self, initial_state: AEFState, *, record_trace: bool = False) -> ExecutionResult:
        state = initial_state
        current: str | _End = self._graph.entry_node
        trace: list[NodeExecutionRecord] = []

        for _ in range(self._max_steps):
            if isinstance(current, _End):
                return ExecutionResult(
                    final_state=state, trace=tuple(trace) if record_trace else None
                )

            node = self._graph.nodes.get(current)
            if node is None:
                raise GraphExecutionError(f"no such node {current!r}")

            ctx = Context(
                run_id=state.run_id,
                graph_version=self._graph.version,
                trace_id=state.provenance[-1].trace_id if state.provenance else state.run_id,
                node_id=node.id,
                now=self._services.clock(),
            )

            delta, route = self._execute_node(node, state, ctx)
            new_state = delta.apply(state)
            if record_trace:
                trace.append(
                    NodeExecutionRecord(
                        node_id=node.id, input_state=state, context=ctx, delta=delta, route=route
                    )
                )
            state = new_state
            if self._services.durability is not None:
                self._services.durability.save_checkpoint(state)
            current = self._resolve_route(node, route, state)

        raise GraphExecutionError(f"exceeded max_steps={self._max_steps} without reaching END")

    def _execute_node(self, node: Node, state: AEFState, ctx: Context) -> tuple[StateDelta, Route]:
        tracer = self._services.tracer
        span_cm = (
            tracer.span(
                f"aef.node.{node.id}",
                {
                    semconv.AEF_RUN_ID: ctx.run_id,
                    semconv.AEF_NODE_ID: node.id,
                    semconv.AEF_GRAPH_VERSION: ctx.graph_version,
                    semconv.AEF_NODE_DETERMINISTIC: node.deterministic,
                    semconv.AEF_NODE_SIDE_EFFECTS: node.side_effects.value,
                    semconv.AEF_CHECKPOINT_SEQ: state.checkpoint_seq,
                },
            )
            if tracer is not None
            else nullcontext(None)
        )
        with span_cm as span:
            try:
                delta, route = node.fn(state, ctx, self._services)
            except Exception as exc:
                if node.fallback_node_id is not None:
                    if span is not None:
                        span.record_exception(exc)
                    error_delta = StateDelta(
                        errors=[
                            {
                                "node_id": node.id,
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                            }
                        ]
                    )
                    return error_delta, node.fallback_node_id
                raise
            if span is not None and delta.provenance:
                total_tokens = sum(p.token_cost for p in delta.provenance)
                span.set_attribute(semconv.GEN_AI_USAGE_OUTPUT_TOKENS, total_tokens)
                last_model = delta.provenance[-1].model
                if last_model is not None:
                    span.set_attribute(semconv.GEN_AI_RESPONSE_MODEL, last_model)
            return delta, route

    def _resolve_route(self, node: Node, route: Route, state: AEFState) -> str | _End:
        if isinstance(route, _End):
            return route
        if isinstance(route, tuple):
            raise NotImplementedError(
                "fan-out routes are part of the Edge/Route contract but are not yet "
                "executed — BSP-style parallel super-steps are deferred to a Phase 2 "
                "executor; see docs/adr/0004"
            )
        candidates = self._graph.edges_from(node.id)
        for edge in candidates:
            if route in edge.targets and edge.condition(state):
                return route
        raise RoutingViolationError(
            f"node {node.id!r} routed to {route!r}, but no declared edge from {node.id!r} "
            f"to {route!r} currently has a true condition"
        )
