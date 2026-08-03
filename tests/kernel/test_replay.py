from aef.kernel import END, Edge, Graph, GraphExecutor, Node, ReplayEngine, Services
from aef.kernel.replay import DeterminismViolationError
from aef.state import AEFState, StateDelta


def _make_state(run_id: str = "run-1") -> AEFState:
    return AEFState(run_id=run_id, agent_id="agent-1", objective="test objective")


def _pure_increment_fn(state, ctx, services):
    count = state.working_memory.get("count", 0)
    return StateDelta(working_memory={"count": count + 1}), "finish"


def _finish_fn(state, ctx, services):
    return StateDelta(working_memory={"done": True}), END


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
