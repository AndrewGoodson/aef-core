import pytest

from aef.kernel import (
    END,
    Edge,
    ExecutionResult,
    Graph,
    GraphExecutionError,
    GraphExecutor,
    HumanApprovalRequiredError,
    InMemoryDurabilityBackend,
    Node,
    RoutingViolationError,
    ServiceNotConfiguredError,
    Services,
    hitl_approval_key,
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


def test_telemetry_tags_land_on_the_span() -> None:
    node = Node(
        id="tagged",
        version="1.0.0",
        fn=_finish_fn,
        deterministic=True,
        telemetry_tags=("azure_sec", "read_only"),
    )
    graph = Graph(id="g", version="1.0.0", nodes={"tagged": node}, edges=[], entry_node="tagged")
    tracer = InMemoryTracer()
    executor = GraphExecutor(graph.compile(), Services(tracer=tracer))
    executor.run(_make_state())
    assert tracer.spans[0].attributes["aef.node.telemetry_tags"] == ("azure_sec", "read_only")


def test_no_telemetry_tags_attribute_when_node_declares_none() -> None:
    node = Node(id="untagged", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g", version="1.0.0", nodes={"untagged": node}, edges=[], entry_node="untagged"
    )
    tracer = InMemoryTracer()
    executor = GraphExecutor(graph.compile(), Services(tracer=tracer))
    executor.run(_make_state())
    assert "aef.node.telemetry_tags" not in tracer.spans[0].attributes


def test_emergent_routing_edge_emits_a_marker_span() -> None:
    def _router_fn(state, ctx, services):
        return StateDelta(), "finish"

    a = Node(id="a", version="1.0.0", fn=_router_fn, deterministic=True)
    finish = Node(id="finish", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "finish": finish},
        edges=[Edge(from_node="a", to_node="finish", requires_deterministic_fallback=True)],
        entry_node="a",
    )
    tracer = InMemoryTracer()
    executor = GraphExecutor(graph.compile(), Services(tracer=tracer))
    executor.run(_make_state())

    marker_spans = [s for s in tracer.spans if s.name == "aef.edge.emergent_routing"]
    assert len(marker_spans) == 1
    assert marker_spans[0].attributes["aef.edge.requires_deterministic_fallback"] is True
    assert marker_spans[0].attributes["aef.edge.to_node"] == "finish"


def test_normal_edge_emits_no_marker_span() -> None:
    tracer = InMemoryTracer()
    executor = GraphExecutor(_two_node_graph().compile(), Services(tracer=tracer))
    executor.run(_make_state())
    assert not [s for s in tracer.spans if s.name == "aef.edge.emergent_routing"]


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


def test_fallback_fires_even_with_no_declared_edge_to_it() -> None:
    """Review/round-1 High finding (docs/adr/0036): a fallback is an error
    handler — it must fire on exception regardless of edge conditions. Before
    the fix, the fallback route was resolved through _resolve_route, which
    required a declared true-condition edge; with none, the original error
    was masked by a misleading RoutingViolationError and the handler never
    ran. The fallback now bypasses edge resolution."""

    def _boom_fn(state, ctx, services):
        raise ValueError("ORIGINAL boom")

    boom = Node(
        id="boom", version="1.0.0", fn=_boom_fn, deterministic=True, fallback_node_id="safe"
    )
    safe = Node(id="safe", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(  # NO edge from boom to safe
        id="g", version="1.0.0", nodes={"boom": boom, "safe": safe}, edges=[], entry_node="boom"
    )
    result = GraphExecutor(graph.compile(), Services()).run(_make_state())
    assert result.final_state.working_memory == {"visited_finish": True}
    assert result.final_state.errors[0]["error"] == "ORIGINAL boom"


def test_fallback_fires_even_when_the_edge_condition_is_false() -> None:
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
        edges=[Edge(from_node="boom", to_node="safe", condition=lambda state: False)],
        entry_node="boom",
    )
    result = GraphExecutor(graph.compile(), Services()).run(_make_state())
    assert result.final_state.working_memory == {"visited_finish": True}


def test_node_exception_is_recorded_on_its_span_before_falling_back() -> None:
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
    tracer = InMemoryTracer()
    executor = GraphExecutor(graph.compile(), Services(tracer=tracer))
    executor.run(_make_state())

    boom_span = next(s for s in tracer.spans if s.name == "aef.node.boom")
    assert len(boom_span.exceptions) == 1
    assert isinstance(boom_span.exceptions[0], ValueError)
    assert str(boom_span.exceptions[0]) == "boom"


def test_node_exception_without_fallback_propagates() -> None:
    def _boom_fn(state, ctx, services):
        raise ValueError("boom")

    boom = Node(id="boom", version="1.0.0", fn=_boom_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"boom": boom}, edges=[], entry_node="boom")
    executor = GraphExecutor(graph.compile(), Services())
    with pytest.raises(ValueError, match="boom"):
        executor.run(_make_state())


def test_context_idempotency_key_is_none_for_pure_node() -> None:
    seen: dict[str, object] = {}

    def _fn(state, ctx, services):
        seen["key"] = ctx.idempotency_key
        return StateDelta(), END

    node = Node(id="pure", version="1.0.0", fn=_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"pure": node}, edges=[], entry_node="pure")
    GraphExecutor(graph.compile(), Services()).run(_make_state())
    assert seen["key"] is None


def _two_node_hitl_graph() -> Graph:
    def _router_fn(state, ctx, services):
        return StateDelta(), "finish"

    a = Node(id="a", version="1.0.0", fn=_router_fn, deterministic=True)
    finish = Node(id="finish", version="1.0.0", fn=_finish_fn, deterministic=True)
    return Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "finish": finish},
        edges=[Edge(from_node="a", to_node="finish", requires_human_approval=True)],
        entry_node="a",
    )


def test_hitl_edge_blocked_without_approval() -> None:
    executor = GraphExecutor(_two_node_hitl_graph().compile(), Services())
    with pytest.raises(HumanApprovalRequiredError):
        executor.run(_make_state())


def test_hitl_edge_proceeds_with_approval() -> None:
    approvals = frozenset({hitl_approval_key("a", "finish")})
    executor = GraphExecutor(_two_node_hitl_graph().compile(), Services(hitl_approvals=approvals))
    result = executor.run(_make_state())
    assert result.final_state.working_memory == {"visited_finish": True}


def test_hitl_approval_is_specific_to_the_edge_not_global() -> None:
    wrong_approval = frozenset({hitl_approval_key("a", "somewhere_else")})
    executor = GraphExecutor(
        _two_node_hitl_graph().compile(), Services(hitl_approvals=wrong_approval)
    )
    with pytest.raises(HumanApprovalRequiredError):
        executor.run(_make_state())


def test_non_hitl_edges_unaffected_by_missing_approvals() -> None:
    # _two_node_graph()'s single edge has no requires_human_approval, so an
    # empty Services() (the default, no approvals at all) must still work.
    executor = GraphExecutor(_two_node_graph().compile(), Services())
    result = executor.run(_make_state())
    assert result.final_state.working_memory == {"visited_start": True, "visited_finish": True}


def test_context_idempotency_key_is_computed_from_node_fn() -> None:
    from aef.kernel import SideEffect

    seen: dict[str, object] = {}

    def _fn(state, ctx, services):
        seen["key"] = ctx.idempotency_key
        return StateDelta(), END

    node = Node(
        id="io",
        version="1.0.0",
        fn=_fn,
        deterministic=False,
        side_effects=SideEffect.EXTERNAL_CALL,
        idempotency_key_fn=lambda state: f"key-for-{state.run_id}",
    )
    graph = Graph(id="g", version="1.0.0", nodes={"io": node}, edges=[], entry_node="io")
    GraphExecutor(graph.compile(), Services()).run(_make_state("run-xyz"))
    assert seen["key"] == "key-for-run-xyz"


def _three_node_graph() -> Graph:
    def _mk(name: str, next_node):
        def _fn(state, ctx, services):
            visited = [*state.working_memory.get("visited", []), name]
            return StateDelta(working_memory={"visited": visited}), next_node

        return Node(id=name, version="1.0.0", fn=_fn, deterministic=True)

    a, b, c = _mk("a", "b"), _mk("b", "c"), _mk("c", END)
    return Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "b": b, "c": c},
        edges=[Edge(from_node="a", to_node="b"), Edge(from_node="b", to_node="c")],
        entry_node="a",
    )


def test_run_does_not_resume_it_restarts_and_duplicates_side_effects() -> None:
    """Documents the gap resume() exists to fix: calling run() again with a
    loaded checkpoint's state restarts at entry_node and re-executes nodes
    that already ran, duplicating their effects. This is not desired
    behavior — it's the reason resume() exists — but pinning it down in a
    test means a future change to run()'s semantics is a deliberate,
    reviewed decision, not an accidental regression discovered in prod."""
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(
        _three_node_graph().compile(), Services(durability=durability), max_steps=2
    )
    with pytest.raises(GraphExecutionError):
        executor.run(_make_state("resume-run"))

    partial = durability.load_latest("resume-run")
    assert partial is not None
    assert partial.working_memory["visited"] == ["a", "b"]

    executor2 = GraphExecutor(_three_node_graph().compile(), Services(durability=durability))
    result = executor2.run(partial)
    assert result.final_state.working_memory["visited"] == ["a", "b", "a", "b", "c"]


def test_resume_continues_from_the_saved_cursor_without_duplicating_nodes() -> None:
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(
        _three_node_graph().compile(), Services(durability=durability), max_steps=2
    )
    with pytest.raises(GraphExecutionError):
        executor.run(_make_state("resume-2"))

    assert durability.load_cursor("resume-2") == "c"

    executor2 = GraphExecutor(_three_node_graph().compile(), Services(durability=durability))
    result = executor2.resume("resume-2")
    assert result.final_state.working_memory["visited"] == ["a", "b", "c"]


def test_resume_on_completed_run_is_idempotent_noop() -> None:
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(_three_node_graph().compile(), Services(durability=durability))
    executor.run(_make_state("resume-3"))
    assert durability.load_cursor("resume-3") is None

    result = executor.resume("resume-3")
    assert result.final_state.working_memory["visited"] == ["a", "b", "c"]


def test_resume_unknown_run_id_raises_clearly() -> None:
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(_three_node_graph().compile(), Services(durability=durability))
    with pytest.raises(GraphExecutionError, match="no checkpoints found"):
        executor.resume("never-existed")


def test_resume_without_durability_configured_raises() -> None:
    executor = GraphExecutor(_three_node_graph().compile(), Services())
    with pytest.raises(ServiceNotConfiguredError):
        executor.resume("whatever")


def test_resume_records_trace_when_requested() -> None:
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(
        _three_node_graph().compile(), Services(durability=durability), max_steps=1
    )
    with pytest.raises(GraphExecutionError):
        executor.run(_make_state("resume-4"))

    executor2 = GraphExecutor(_three_node_graph().compile(), Services(durability=durability))
    result = executor2.resume("resume-4", record_trace=True)
    assert result.trace is not None
    assert [r.node_id for r in result.trace] == ["b", "c"]


def test_hitl_block_on_the_entry_node_is_still_resumable() -> None:
    """Review Finding 2, Reproduction A (docs/adr/0032): when the HITL gate
    is on the entry node's outgoing edge, the block used to happen before
    any checkpoint was ever written, so resume() raised 'nothing to
    resume' — the paused run was unrecoverable. After the fix, a checkpoint
    + cursor is persisted at the block, so resume() with approval
    completes."""
    durability = InMemoryDurabilityBackend()
    executor = GraphExecutor(_two_node_hitl_graph().compile(), Services(durability=durability))
    with pytest.raises(HumanApprovalRequiredError):
        executor.run(_make_state("hitl-entry"))

    # A checkpoint and a cursor now exist despite blocking on the entry node.
    assert durability.load_latest("hitl-entry") is not None
    assert durability.load_cursor("hitl-entry") == "a"

    approvals = frozenset({hitl_approval_key("a", "finish")})
    resumed = GraphExecutor(
        _two_node_hitl_graph().compile(), Services(durability=durability, hitl_approvals=approvals)
    ).resume("hitl-entry")
    assert resumed.final_state.working_memory == {"visited_finish": True}


def test_hitl_block_resume_reexecutes_the_gated_node_at_least_once() -> None:
    """Review Finding 2, Reproduction B (docs/adr/0032): the node whose
    outgoing edge is gated has already run by the time approval is checked,
    and resume re-executes it. This is at-least-once semantics (matching
    LangGraph interrupt() / Temporal activities), mitigated by the node's
    idempotency_key — the kernel does NOT dedupe (ADR 0010). This test pins
    the accepted behavior: resume completes, and the gated node ran twice."""
    calls = {"b": 0}

    def _a_fn(state, ctx, services):
        return StateDelta(working_memory={"a": True}), "b"

    def _b_fn(state, ctx, services):
        calls["b"] += 1
        return StateDelta(working_memory={"b": calls["b"]}), "c"

    def _c_fn(state, ctx, services):
        return StateDelta(working_memory={"c": True}), END

    from aef.kernel import SideEffect

    def _graph() -> Graph:
        a = Node(id="a", version="1.0.0", fn=_a_fn, deterministic=True)
        b = Node(
            id="b",
            version="1.0.0",
            fn=_b_fn,
            deterministic=False,
            side_effects=SideEffect.EXTERNAL_CALL,
            idempotency_key_fn=lambda s: "b-key",
        )
        c = Node(id="c", version="1.0.0", fn=_c_fn, deterministic=False)
        return Graph(
            id="g",
            version="1.0.0",
            nodes={"a": a, "b": b, "c": c},
            edges=[
                Edge(from_node="a", to_node="b"),
                Edge(from_node="b", to_node="c", requires_human_approval=True),
            ],
            entry_node="a",
        )

    durability = InMemoryDurabilityBackend()
    with pytest.raises(HumanApprovalRequiredError):
        GraphExecutor(_graph().compile(), Services(durability=durability)).run(
            _make_state("hitl-b")
        )
    assert calls["b"] == 1  # ran once before the gate

    approvals = frozenset({hitl_approval_key("b", "c")})
    resumed = GraphExecutor(
        _graph().compile(), Services(durability=durability, hitl_approvals=approvals)
    ).resume("hitl-b")
    assert resumed.final_state.working_memory["c"] is True
    assert calls["b"] == 2  # re-executed on resume (at-least-once, idempotency-key mitigated)
