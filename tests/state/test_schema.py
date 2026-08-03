from datetime import UTC, datetime

from aef.state import AEFState, Message, Plan, Provenance


def _prov(node_id: str = "n1") -> Provenance:
    return Provenance(
        node_id=node_id,
        graph_version="1.0.0",
        ts=datetime.now(UTC),
        trace_id="trace-1",
    )


def test_minimal_state_has_defaults() -> None:
    state = AEFState(run_id="r1", agent_id="a1", objective="do the thing")
    assert state.schema_version == "1.0.0"
    assert state.messages == []
    assert state.plan is None
    assert state.checkpoint_seq == 0
    assert state.context_budget_tokens == 8000


def test_state_round_trips_through_json() -> None:
    state = AEFState(
        run_id="r1",
        agent_id="a1",
        objective="do the thing",
        messages=[Message(role="user", content="hi", prov=_prov())],
        plan=Plan(goal="root", subgoals=[Plan(goal="child")]),
        provenance=[_prov()],
    )
    raw = state.model_dump_json()
    restored = AEFState.model_validate_json(raw)
    assert restored == state


def test_plan_supports_recursive_subgoals() -> None:
    plan = Plan(goal="root", subgoals=[Plan(goal="a"), Plan(goal="b", subgoals=[Plan(goal="b1")])])
    assert plan.subgoals[1].subgoals[0].goal == "b1"


def test_unknown_field_rejected() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AEFState(run_id="r1", agent_id="a1", objective="x", not_a_real_field="boom")
