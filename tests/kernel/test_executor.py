import pytest

from aef.kernel import (
    END,
    Edge,
    ExecutionResult,
    Graph,
    GraphExecutionError,
    GraphExecutor,
    InMemoryDurabilityBackend,
    Node,
    RoutingViolationError,
    Services,
)
from aef.observability.in_memory import InMemoryTracer
from aef.state import AEFState, Message, Provenance, StateDelta


def _make_state(run_id: str = "run-1") -> AEFState:
    return AEFState(run_id=run_id, agent_id="agent-1", objective="test objective")


def _start_fn(state, ctx, services):
    delta = StateDelta(working_memory={"visited_start": True})
    return delta, "finish"


def _finish_fn(state, ctx, services):
    return StateDelta(working_memory={"visited_finish": True}), END


def _two_node_graph() -> Graph:
    start = Node(id="start", version="1.0.0", fn=_start_fn, deterministic=True)
    finish = Node(id="finish", version="1.0.0", fn=_finish_fn, deterministic=True)
    return Graph(
        id="g",
        version="1.0.0",
        nodes={"start": start, "finish": finish},
        edges=[Edge(from_node="start", to_node="finish")],
        entry_node="start",
    )


def test_run_executes_to_completion() -> None:
    compiled = _two_node_graph().compile()
    executor = GraphExecutor(compiled, Services())
    result = executor.run(_make_state())
    assert isinstance(result, ExecutionResult)
    assert result.final_state.working_memory == {"visited_start": True, "visited_finish": True}
    assert result.final_state.checkpoint_seq == 2


def test_run_records_trace_when_requested() -> None:
    compiled = _two_node_graph().compile()
    executor = GraphExecutor(compiled, Services())
    result = executor.run(_make_state(), record_trace=True)
    assert result.trace is not None
    assert [r.node_id for r in result.trace] == ["start", "finish"]


def test_routing_to_undeclared_edge_raises() -> None:
    def _bad_fn(state, ctx, services):
        return StateDelta(), "nowhere"

    bad = Node(id="start", version="1.0.0", fn=_bad_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"start": bad}, edges=[], entry_node="start")
    executor = GraphExecutor(graph.compile(), Services())
    with pytest.raises(RoutingViolationError):
        executor.run(_make_state())


def test_edge_condition_gates_routing() -> None:
    def _router_fn(state, ctx, services):
        return StateDelta(), "b"

    a = Node(id="a", version="1.0.0", fn=_router_fn, deterministic=True)
    b = Node(id="b", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "b": b},
        edges=[Edge(from_node="a", to_node="b", condition=lambda state: False)],
        entry_node="a",
    )
    executor = GraphExecutor(graph.compile(), Services())
    with pytest.raises(RoutingViolationError):
        executor.run(_make_state())


def test_fanout_route_not_implemented() -> None:
    def _fanout_fn(state, ctx, services):
        return StateDelta(), ("b", "c")

    a = Node(id="a", version="1.0.0", fn=_fanout_fn, deterministic=True)
    b = Node(id="b", version="1.0.0", fn=_finish_fn, deterministic=True)
    c = Node(id="c", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "b": b, "c": c},
        edges=[Edge(from_node="a", to_node=("b", "c"))],
        entry_node="a",
    )
    executor = GraphExecutor(graph.compile(), Services())
    with pytest.raises(NotImplementedError):
        executor.run(_make_state())


def test_max_steps_exceeded_raises() -> None:
    def _self_loop_fn(state, ctx, services):
        return StateDelta(), "a"

    a = Node(id="a", version="1.0.0", fn=_self_loop_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a},
        edges=[Edge(from_node="a", to_node="a")],
        entry_node="a",
    )
    executor = GraphExecutor(graph.compile(), Services(), max_steps=5)
    with pytest.raises(GraphExecutionError):
        executor.run(_make_state())


def test_checkpointing_saves_every_superstep() -> None:
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(_two_node_graph().compile(), Services(durability=durability))
    result = executor.run(_make_state())
    assert durability.list_checkpoints(result.final_state.run_id) == [1, 2]
    latest = durability.load_latest(result.final_state.run_id)
    assert latest == result.final_state


def test_tracer_receives_one_span_per_node() -> None:
    tracer = InMemoryTracer()
    executor = GraphExecutor(_two_node_graph().compile(), Services(tracer=tracer))
    executor.run(_make_state())
    assert [s.name for s in tracer.spans] == ["aef.node.start", "aef.node.finish"]
    assert all(s.ended for s in tracer.spans)


def test_tracer_records_token_usage_from_provenance() -> None:
    def _llm_fn(state, ctx, services):
        prov = Provenance(
            node_id=ctx.node_id,
            graph_version=ctx.graph_version,
            ts=ctx.now,
            trace_id=ctx.trace_id,
            model="claude-x",
            token_cost=42,
        )
        delta = StateDelta(
            messages=[Message(role="assistant", content="hi", prov=prov)],
            provenance=[prov],
        )
        return delta, END

    node = Node(id="llm", version="1.0.0", fn=_llm_fn, deterministic=False)
    graph = Graph(id="g", version="1.0.0", nodes={"llm": node}, edges=[], entry_node="llm")
    tracer = InMemoryTracer()
    executor = GraphExecutor(graph.compile(), Services(tracer=tracer))
    executor.run(_make_state())
    span = tracer.spans[0]
    assert span.attributes["gen_ai.usage.output_tokens"] == 42
    assert span.attributes["gen_ai.response.model"] == "claude-x"


def test_node_exception_routes_to_fallback_and_records_error() -> None:
    def _boom_fn(state, ctx, services):
        raise ValueError("boom")

    boom = Node(
        id="boom", version="1.0.0", fn=_boom_fn, deterministic=True, fallback_node_id="safe"
    )
    safe = Node(id="safe", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"boom": boom, "safe": safe},
        edges=[Edge(from_node="boom", to_node="safe")],
        entry_node="boom",
    )
    executor = GraphExecutor(graph.compile(), Services())
    result = executor.run(_make_state())
    assert result.final_state.errors[0]["error"] == "boom"
    assert result.final_state.working_memory == {"visited_finish": True}


def test_node_exception_without_fallback_propagates() -> None:
    def _boom_fn(state, ctx, services):
        raise ValueError("boom")

    boom = Node(id="boom", version="1.0.0", fn=_boom_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"boom": boom}, edges=[], entry_node="boom")
    executor = GraphExecutor(graph.compile(), Services())
    with pytest.raises(ValueError, match="boom"):
        executor.run(_make_state())
