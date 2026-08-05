from datetime import UTC, datetime

import pytest

from aef.kernel import END, Context, Edge, Graph, GraphExecutor, Node, ReplayEngine, Route, Services
from aef.kernel.executor import NodeExecutionRecord
from aef.kernel.replay import DeterminismViolationError, MalformedTraceError
from aef.state import AEFState, StateDelta


def _make_state(run_id: str = "run-1") -> AEFState:
    return AEFState(run_id=run_id, agent_id="agent-1", objective="test objective")


def _pure_increment_fn(state, ctx, services):
    count = state.working_memory.get("count", 0)
    return StateDelta(working_memory={"count": count + 1}), "finish"


def _finish_fn(state, ctx, services):
    return StateDelta(working_memory={"done": True}), END


def test_replay_reconstructs_a_deterministic_node_fallback_trace() -> None:
    """Regression for a seam ADR 0036 exposed (fixed in ADR 0039): a
    deterministic=True node that raises and falls back records a legitimate
    trace, but replay used to re-execute that node's fn to verify
    determinism — which raised the original exception again, with no guard,
    so a valid trace was unreplayable. A fallback record must be trusted
    (like a non-deterministic node's output), not re-executed."""

    def _boom(state, ctx, services):
        raise ValueError("boom detonated")

    boom = Node(id="boom", version="1.0.0", fn=_boom, deterministic=True, fallback_node_id="safe")
    safe = Node(id="safe", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g", version="1.0.0", nodes={"boom": boom, "safe": safe}, edges=[], entry_node="boom"
    ).compile()
    result = GraphExecutor(graph, Services()).run(_make_state(), record_trace=True)
    assert result.trace is not None

    replayed = ReplayEngine(graph, Services()).replay(result.trace)
    assert replayed == result.final_state
    assert replayed.working_memory == {"done": True}
    assert replayed.errors[0]["error"] == "boom detonated"


def test_replay_matches_for_genuinely_deterministic_node() -> None:
    start = Node(id="start", version="1.0.0", fn=_pure_increment_fn, deterministic=True)
    finish = Node(id="finish", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"start": start, "finish": finish},
        edges=[Edge(from_node="start", to_node="finish")],
        entry_node="start",
    )
    compiled = graph.compile()
    executor = GraphExecutor(compiled, Services())
    result = executor.run(_make_state(), record_trace=True)
    assert result.trace is not None

    replayed_final = ReplayEngine(compiled, Services()).replay(result.trace)
    assert replayed_final == result.final_state


def test_replay_trusts_recorded_output_for_nondeterministic_node() -> None:
    calls = {"n": 0}

    def _flaky_fn(state, ctx, services):
        calls["n"] += 1
        return StateDelta(working_memory={"call_number": calls["n"]}), END

    node = Node(id="flaky", version="1.0.0", fn=_flaky_fn, deterministic=False)
    graph = Graph(id="g", version="1.0.0", nodes={"flaky": node}, edges=[], entry_node="flaky")
    compiled = graph.compile()
    executor = GraphExecutor(compiled, Services())
    result = executor.run(_make_state(), record_trace=True)
    assert result.trace is not None

    # Replay would compute call_number=2 internally, but because the node is
    # declared non-deterministic, the engine must trust the recorded delta
    # (call_number=1) rather than raising or substituting the new value.
    replayed_final = ReplayEngine(compiled, Services()).replay(result.trace)
    assert replayed_final.working_memory["call_number"] == 1
    assert replayed_final == result.final_state


def test_replay_catches_a_node_that_lies_about_being_deterministic() -> None:
    calls = {"n": 0}

    def _lying_fn(state, ctx, services):
        calls["n"] += 1
        return StateDelta(working_memory={"call_number": calls["n"]}), END

    # Declared deterministic=True even though it isn't — this is exactly the
    # bug the replay engine exists to catch.
    node = Node(id="liar", version="1.0.0", fn=_lying_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"liar": node}, edges=[], entry_node="liar")
    compiled = graph.compile()
    executor = GraphExecutor(compiled, Services())
    result = executor.run(_make_state(), record_trace=True)
    assert result.trace is not None

    try:
        ReplayEngine(compiled, Services()).replay(result.trace)
        raised = False
    except DeterminismViolationError:
        raised = True
    assert raised, "replay must catch a deterministic=True node whose output actually varies"


def test_replay_rejects_empty_trace() -> None:
    start = Node(id="start", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"start": start}, edges=[], entry_node="start")
    compiled = graph.compile()
    engine = ReplayEngine(compiled, Services())
    try:
        engine.replay([])
        raised = False
    except ValueError:
        raised = True
    assert raised


def _record(
    node_id: str, state: AEFState, route, delta: StateDelta | None = None
) -> NodeExecutionRecord:
    ctx = Context(
        run_id=state.run_id,
        graph_version="1.0.0",
        trace_id="t",
        node_id=node_id,
        now=datetime.now(UTC),
    )
    return NodeExecutionRecord(
        node_id=node_id, input_state=state, context=ctx, delta=delta or StateDelta(), route=route
    )


def test_replay_rejects_a_trace_referencing_a_node_not_in_the_graph() -> None:
    start = Node(id="start", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"start": start}, edges=[], entry_node="start")
    compiled = graph.compile()
    state = _make_state()
    trace = [_record("nonexistent", state, END)]

    try:
        ReplayEngine(compiled, Services()).replay(trace)
        raised = False
    except DeterminismViolationError:
        raised = True
    assert raised


def test_replay_rejects_a_reordered_or_corrupted_trace() -> None:
    """Reproduces a real, confirmed bug: before this fix, replay() never
    checked that record[i].route matched record[i+1].node_id — a
    hand-assembled, reordered, or corrupted trace was silently accepted
    and replayed into a nonsensical result with no error at all. See
    docs/adr/0023."""
    a = Node(id="a", version="1.0.0", fn=_finish_fn, deterministic=True)
    b = Node(id="b", version="1.0.0", fn=_finish_fn, deterministic=True)
    c = Node(id="c", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "b": b, "c": c},
        edges=[Edge(from_node="a", to_node="b"), Edge(from_node="a", to_node="c")],
        entry_node="a",
    )
    compiled = graph.compile()
    state = _make_state()

    record_a = _record("a", state, route="b")  # says "go to b"...
    record_c = _record("c", state, route=END)  # ...but the next record is "c"

    try:
        ReplayEngine(compiled, Services()).replay([record_a, record_c])
        raised = False
    except MalformedTraceError:
        raised = True
    assert raised


def test_replay_rejects_end_appearing_before_the_last_record() -> None:
    a = Node(id="a", version="1.0.0", fn=_finish_fn, deterministic=True)
    b = Node(id="b", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "b": b},
        edges=[Edge(from_node="a", to_node="b")],
        entry_node="a",
    )
    compiled = graph.compile()
    state = _make_state()

    record_a = _record("a", state, route=END)  # claims termination...
    record_b = _record("b", state, route=END)  # ...but the trace keeps going

    try:
        ReplayEngine(compiled, Services()).replay([record_a, record_b])
        raised = False
    except MalformedTraceError:
        raised = True
    assert raised


def test_replay_rejects_fanout_route_in_a_trace_record() -> None:
    a = Node(id="a", version="1.0.0", fn=_finish_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"a": a}, edges=[], entry_node="a")
    compiled = graph.compile()
    state = _make_state()
    trace = [_record("a", state, route=("b", "c"))]

    try:
        ReplayEngine(compiled, Services()).replay(trace)
        raised = False
    except MalformedTraceError:
        raised = True
    assert raised


def test_replay_allows_a_partial_trace_not_ending_in_end() -> None:
    """A trace captured up to a crash (or otherwise stopped early) is a
    legitimate thing to replay — the last record's route doesn't have to be
    END, only records BEFORE the last one need to chain correctly. The last
    node is declared non-deterministic so its recorded (trusted, not
    re-executed) route is what's under test, not a coincidental match with
    what `_finish_fn` would itself return."""

    def _route_to_b_fn(state, ctx, services):
        return StateDelta(working_memory={"stage": "a"}), "b"

    a = Node(id="a", version="1.0.0", fn=_route_to_b_fn, deterministic=True)
    b = Node(id="b", version="1.0.0", fn=_finish_fn, deterministic=False)
    graph = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": a, "b": b},
        edges=[Edge(from_node="a", to_node="b")],
        entry_node="a",
    )
    compiled = graph.compile()
    state = _make_state()

    delta_a = StateDelta(working_memory={"stage": "a"})
    record_a = _record("a", state, route="b", delta=delta_a)
    # b's input is a's OUTPUT. A trace is a chain, and replay now verifies
    # that — a hand-built trace where both records share the initial state
    # describes a run that never happened (ADR 0087). The point under test is
    # the unresolvable final route, not a broken chain.
    record_b = _record(
        "b", delta_a.apply(state), route="c"
    )  # "c" doesn't even exist — but this is the LAST record

    result = ReplayEngine(compiled, Services()).replay([record_a, record_b])
    assert result is not None


# --------------------------------------------------------------------------
# ADR 0068 — a fallback record's ROUTE is verified, not only its delta
# --------------------------------------------------------------------------


def _fallback_graph(fallback_to: str) -> Graph:
    """A deterministic node that always raises, plus two possible handlers."""

    def boom(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        raise RuntimeError("node exploded")

    def safe(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        return StateDelta(working_memory={"handled_by": "SAFE"}), END

    def risky(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        return (
            StateDelta(
                working_memory={"handled_by": "RISKY"},
                errors=[{"error": "suppressed by the risky handler"}],
            ),
            END,
        )

    return Graph(
        id="fb",
        version="1",
        nodes={
            "work": Node(
                id="work", version="1", fn=boom, deterministic=True, fallback_node_id=fallback_to
            ),
            "safe": Node(id="safe", version="1", fn=safe, deterministic=True),
            "risky": Node(id="risky", version="1", fn=risky, deterministic=True),
        },
        edges=[],
        entry_node="work",
    )


def test_replay_detects_a_retargeted_fallback() -> None:
    """A fallback record is trusted rather than re-executed (ADR 0039),
    because re-running the fn would raise the original exception again. That
    is sound for the DELTA and was silently extended to the ROUTE: replaying
    an old trace against a graph whose fallback now points at a different
    existing handler PASSED, while a live run of that graph produced
    materially different behaviour (SAFE/1 error vs RISKY/2 errors).
    """
    recorded = GraphExecutor(_fallback_graph("safe").compile(), Services()).run(
        AEFState(run_id="r1", agent_id="a", objective="o"), record_trace=True
    )
    assert recorded.trace is not None

    retargeted = _fallback_graph("risky").compile()
    with pytest.raises(DeterminismViolationError, match="fallback"):
        ReplayEngine(retargeted, Services()).replay(recorded.trace)


def test_replay_accepts_an_unchanged_fallback() -> None:
    recorded = GraphExecutor(_fallback_graph("safe").compile(), Services()).run(
        AEFState(run_id="r1", agent_id="a", objective="o"), record_trace=True
    )
    assert recorded.trace is not None

    ReplayEngine(_fallback_graph("safe").compile(), Services()).replay(recorded.trace)


def test_replay_still_does_not_re_execute_a_raising_node() -> None:
    # The ADR 0039 property must survive the fix: re-running the fn would
    # raise the original exception and make the trace unreplayable.
    recorded = GraphExecutor(_fallback_graph("safe").compile(), Services()).run(
        AEFState(run_id="r1", agent_id="a", objective="o"), record_trace=True
    )
    assert recorded.trace is not None
    fallback_record = next(r for r in recorded.trace if r.is_fallback)
    assert fallback_record.node_id == "work"

    # No RuntimeError escapes: the raising node is trusted, not re-run.
    ReplayEngine(_fallback_graph("safe").compile(), Services()).replay(recorded.trace)
