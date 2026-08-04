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


def test_scores_with_non_finite_values_rejected_on_direct_construction() -> None:
    """Belt-and-suspenders alongside StateDelta's own guard (docs/adr/0022)
    — AEFState.model_copy(), used by StateDelta.apply(), does NOT re-run
    validators, so this alone wouldn't catch the bug that motivated it, but
    direct AEFState construction (tests, or code bypassing StateDelta) is
    a real second entry point worth closing too."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="finite"):
        AEFState(run_id="r1", agent_id="a1", objective="x", scores={"sharpe": float("inf")})


def test_round_trip_survives_unicode_and_deeply_nested_subgoals() -> None:
    prov = _prov()
    deep_plan = Plan(
        goal="root goal with unicode: 日本語 and emoji 🚀",
        subgoals=[Plan(goal="a", subgoals=[Plan(goal="b", subgoals=[Plan(goal="c")])])],
    )
    state = AEFState(
        run_id="r1",
        agent_id="a1",
        objective="objective with accents: café, naïve, résumé",
        messages=[
            Message(
                role="user", content="special chars: \t\n quotes \" and 'apostrophes'", prov=prov
            )
        ],
        plan=deep_plan,
        working_memory={"unicode_key_日本語": "value", "empty_string": "", "explicit_none": None},
    )
    restored = AEFState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert restored.plan is not None
    assert restored.plan.subgoals[0].subgoals[0].subgoals[0].goal == "c"
    assert restored.working_memory["explicit_none"] is None
    assert restored.working_memory["empty_string"] == ""


def test_provenance_rejects_negative_token_cost() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Provenance(
            node_id="n1", graph_version="1.0.0", ts=datetime.now(UTC), trace_id="t", token_cost=-1
        )


def test_state_rejects_non_positive_context_budget_tokens() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AEFState(run_id="r1", agent_id="a1", objective="x", context_budget_tokens=0)
    with pytest.raises(ValidationError):
        AEFState(run_id="r1", agent_id="a1", objective="x", context_budget_tokens=-100)


def test_round_trip_survives_very_large_token_cost() -> None:
    prov = Provenance(
        node_id="n1",
        graph_version="1.0.0",
        ts=datetime.now(UTC),
        trace_id="t",
        token_cost=2**53,  # largest exact integer representable as a JS/JSON double
    )
    state = AEFState(run_id="r1", agent_id="a1", objective="x", provenance=[prov])
    restored = AEFState.model_validate_json(state.model_dump_json())
    assert restored.provenance[0].token_cost == 2**53
