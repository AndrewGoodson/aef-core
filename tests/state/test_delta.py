from datetime import UTC, datetime

from aef.state import AEFState, Message, Plan, Provenance, StateDelta


def _prov(node_id: str) -> Provenance:
    return Provenance(node_id=node_id, graph_version="1.0.0", ts=datetime.now(UTC), trace_id="t")


def _base_state() -> AEFState:
    return AEFState(run_id="r1", agent_id="a1", objective="obj")


def test_empty_delta_only_advances_checkpoint_seq() -> None:
    state = _base_state()
    new_state = StateDelta().apply(state)
    assert new_state.checkpoint_seq == 1
    assert new_state.messages == []
    assert new_state.run_id == state.run_id


def test_messages_append_not_replace() -> None:
    state = _base_state()
    state = StateDelta(messages=[Message(role="user", content="a", prov=_prov("n1"))]).apply(state)
    state = StateDelta(messages=[Message(role="assistant", content="b", prov=_prov("n2"))]).apply(
        state
    )
    assert [m.content for m in state.messages] == ["a", "b"]
    assert state.checkpoint_seq == 2


def test_working_memory_merges_with_delta_priority() -> None:
    state = _base_state()
    state = StateDelta(working_memory={"x": 1, "y": 2}).apply(state)
    state = StateDelta(working_memory={"y": 3, "z": 4}).apply(state)
    assert state.working_memory == {"x": 1, "y": 3, "z": 4}


def test_plan_replaces_when_set_else_preserved() -> None:
    state = _base_state()
    state = StateDelta(plan=Plan(goal="root")).apply(state)
    assert state.plan is not None and state.plan.goal == "root"
    state = StateDelta().apply(state)
    assert state.plan is not None and state.plan.goal == "root"


def test_scores_and_context_budget() -> None:
    state = _base_state()
    state = StateDelta(scores={"accuracy": 0.9}, context_budget_tokens=4000).apply(state)
    assert state.scores == {"accuracy": 0.9}
    assert state.context_budget_tokens == 4000


def test_apply_is_pure_does_not_mutate_input_state() -> None:
    state = _base_state()
    original_seq = state.checkpoint_seq
    StateDelta(working_memory={"x": 1}).apply(state)
    assert state.checkpoint_seq == original_seq
    assert state.working_memory == {}


def test_apply_deterministic_same_inputs_same_output() -> None:
    state = _base_state()
    delta = StateDelta(
        messages=[Message(role="user", content="hi", prov=_prov("n1"))],
        working_memory={"k": "v"},
        scores={"s": 1.0},
    )
    out1 = delta.apply(state)
    out2 = delta.apply(state)
    assert out1 == out2
