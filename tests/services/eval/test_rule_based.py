from aef.services.eval.rule_based import RuleBasedEvaluator
from aef.state import AEFState, Plan


def _state(**overrides: object) -> AEFState:
    defaults: dict[str, object] = {"run_id": "r1", "agent_id": "a1", "objective": "obj"}
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


def test_task_completion_one_when_plan_done_and_no_errors() -> None:
    state = _state(plan=Plan(goal="g", status="done"))
    record = RuleBasedEvaluator().evaluate(state)
    assert record.task_completion == 1.0
    assert record.passed


def test_task_completion_zero_when_errors_present() -> None:
    state = _state(plan=Plan(goal="g", status="done"), errors=[{"error": "boom"}])
    record = RuleBasedEvaluator().evaluate(state)
    assert record.task_completion == 0.0
    assert not record.passed


def test_task_completion_half_when_no_plan_and_no_errors() -> None:
    record = RuleBasedEvaluator().evaluate(_state())
    assert record.task_completion == 0.5
    assert record.passed  # >= 0.5 threshold when no domain_gates configured


def test_tool_call_accuracy_none_when_no_tools_called() -> None:
    record = RuleBasedEvaluator().evaluate(_state())
    assert record.tool_call_accuracy is None


def test_tool_call_accuracy_computed_from_tool_results() -> None:
    state = _state(tool_results=[{"result": "ok"}, {"error": "failed"}, {"result": "ok"}])
    record = RuleBasedEvaluator().evaluate(state)
    assert record.tool_call_accuracy == 2 / 3


def test_trajectory_quality_reflects_plan_status() -> None:
    assert (
        RuleBasedEvaluator()
        .evaluate(_state(plan=Plan(goal="g", status="failed")))
        .trajectory_quality
        == 0.0
    )
    assert (
        RuleBasedEvaluator()
        .evaluate(_state(plan=Plan(goal="g", status="active")))
        .trajectory_quality
        == 0.5
    )
    assert (
        RuleBasedEvaluator().evaluate(_state(plan=Plan(goal="g", status="done"))).trajectory_quality
        == 1.0
    )


def test_cost_tokens_summed_from_provenance() -> None:
    from datetime import UTC, datetime

    from aef.state import Provenance

    prov = [
        Provenance(
            node_id="n1", graph_version="1.0.0", ts=datetime.now(UTC), trace_id="t", token_cost=10
        ),
        Provenance(
            node_id="n2", graph_version="1.0.0", ts=datetime.now(UTC), trace_id="t", token_cost=5
        ),
    ]
    record = RuleBasedEvaluator().evaluate(_state(provenance=prov))
    assert record.cost_tokens == 15


def test_domain_gates_evaluated_and_gate_all_required_to_pass() -> None:
    evaluator = RuleBasedEvaluator(
        domain_gates={
            "sharpe_gate": lambda state: state.scores.get("sharpe", 0) > 0.8,
            "max_dd_gate": lambda state: state.scores.get("max_dd", 1.0) < 0.2,
        }
    )
    state = _state(scores={"sharpe": 0.9, "max_dd": 0.5})
    record = evaluator.evaluate(state)
    assert record.domain_gates == {"sharpe_gate": True, "max_dd_gate": False}
    assert not record.passed  # not ALL gates true


def test_domain_gates_all_true_passes() -> None:
    evaluator = RuleBasedEvaluator(domain_gates={"always_true": lambda state: True})
    record = evaluator.evaluate(_state())
    assert record.passed
