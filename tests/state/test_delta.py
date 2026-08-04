from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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


def test_context_budget_tokens_rejects_non_positive_override() -> None:
    with pytest.raises(ValidationError):
        StateDelta(context_budget_tokens=0)
    with pytest.raises(ValidationError):
        StateDelta(context_budget_tokens=-1)


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


def test_scores_with_infinity_rejected_at_construction() -> None:
    """AEFState.scores is exactly where a Financial Agent's Sharpe/PF/MaxDD
    domain gates land (report §16). A division-by-zero upstream (e.g. zero
    volatility) produces inf/nan; model_dump_json() silently rewrites both
    as JSON null on the very first checkpoint write (confirmed directly —
    standard JSON has no Infinity/NaN literal). Rejecting at StateDelta
    construction catches this at its true origin instead of as a mysterious
    validation crash several steps later, at an unrelated checkpoint-load
    site (docs/adr/0022)."""
    with pytest.raises(ValidationError, match="finite"):
        StateDelta(scores={"sharpe": float("inf")})


def test_scores_with_negative_infinity_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        StateDelta(scores={"max_dd": float("-inf")})


def test_scores_with_nan_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        StateDelta(scores={"pf": float("nan")})


def test_scores_error_names_every_offending_key() -> None:
    with pytest.raises(ValidationError, match=r"sharpe.*max_dd|max_dd.*sharpe"):
        StateDelta(scores={"sharpe": float("inf"), "max_dd": float("nan"), "pf": 1.5})


def test_normal_finite_scores_still_accepted() -> None:
    delta = StateDelta(scores={"sharpe": 0.9, "max_dd": -0.15, "pf": 1.3})
    assert delta.scores == {"sharpe": 0.9, "max_dd": -0.15, "pf": 1.3}
