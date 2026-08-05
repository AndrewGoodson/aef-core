"""Recovery was indistinguishable from failure.

A run that hit a transient error and then completed had
`Outcome.passed == False` — exactly like one that gave up. So a candidate
that taught the agent to recover scored identically to one that changed
nothing, and graceful recovery, one of the more valuable things an agent can
learn, was **unrewardable by the objective the loop optimises** (ADR 0068 A3,
fixed in ADR 0076).

Fixed the way `policy_denied` was (ADR 0064): an explicit marker set by the
node, never inferred from error text, defaulting to today's behaviour when
absent. `RuleBasedEvaluator.task_completion` is deliberately NOT touched —
that is ADR 0038 and every existing user.
"""

from datetime import UTC, datetime

from aef.harness.outcome import RECOVERED_KEY, Outcome, classify
from aef.state import AEFState, Plan

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _state(errors: list[dict[str, object]], status: str = "done") -> AEFState:
    return AEFState(
        run_id="r", agent_id="a", objective="o", plan=Plan(goal="o", status=status), errors=errors
    )


def test_a_recovered_run_is_not_a_failure() -> None:
    outcome = classify(
        _state([{"node_id": "w", "error": "transient timeout", RECOVERED_KEY: True}]),
        (),
        terminated=True,
    )
    assert outcome.passed
    assert outcome.error_count == 1, "the error still happened and is still reported"
    assert outcome.recovered_errors == 1
    assert outcome.unrecovered_errors == 0


def test_an_unmarked_error_still_fails_the_run() -> None:
    """The default must be exactly today's behaviour: an agent that marks
    nothing is scored exactly as it was before this field existed."""
    outcome = classify(_state([{"node_id": "w", "error": "gave up"}]), (), terminated=True)
    assert not outcome.passed
    assert outcome.recovered_errors == 0


def test_one_unrecovered_error_among_recovered_ones_still_fails() -> None:
    outcome = classify(
        _state(
            [
                {"node_id": "w", "error": "transient", RECOVERED_KEY: True},
                {"node_id": "w", "error": "fatal"},
            ]
        ),
        (),
        terminated=True,
    )
    assert not outcome.passed
    assert (outcome.error_count, outcome.recovered_errors, outcome.unrecovered_errors) == (2, 1, 1)


def test_recovery_does_not_rescue_a_failed_plan() -> None:
    """`plan_status == "done"` is still required. Marking every error
    recovered must not turn an abandoned task into a pass."""
    outcome = classify(
        _state([{"node_id": "w", "error": "x", RECOVERED_KEY: True}], status="failed"),
        (),
        terminated=True,
    )
    assert not outcome.passed


def test_the_marker_is_never_inferred_from_error_text() -> None:
    """Same rule as `policy_denied`: guessing from text was measured and is
    roughly anti-correlated with the truth."""
    for text in ("recovered from the timeout", "retry succeeded", "recovered"):
        outcome = classify(_state([{"node_id": "w", "error": text}]), (), terminated=True)
        assert not outcome.passed, f"inferred recovery from text: {text!r}"


def test_the_field_round_trips() -> None:
    outcome = Outcome(
        terminated=True,
        plan_status="done",
        error_count=3,
        policy_denials=0,
        node_path=("w",),
        recovered_errors=2,
    )
    assert Outcome.from_payload(outcome.to_payload()) == outcome


def test_a_payload_written_before_the_field_existed_reads_as_no_recovery() -> None:
    legacy = {
        "terminated": True,
        "plan_status": "done",
        "error_count": 1,
        "policy_denials": 0,
        "node_path": ["w"],
    }
    assert Outcome.from_payload(legacy).recovered_errors == 0
    assert not Outcome.from_payload(legacy).passed


def test_harvest_does_not_promote_a_recovered_run_as_a_failure() -> None:
    """Harvest promotes runs that failed. Counting a recovery as a failure
    made the corpus record successful recovery as the thing the loop should
    learn to stop doing."""
    from aef.harness.harvest import RecordedRun
    from aef.kernel import END, Context, NodeExecutionRecord
    from aef.state import StateDelta

    initial = AEFState(run_id="r", agent_id="a", objective="o")

    def _run(errors: list[dict[str, object]]) -> RecordedRun:
        record = NodeExecutionRecord(
            node_id="w",
            input_state=initial,
            context=Context(run_id="r", graph_version="1", trace_id="t", node_id="w", now=NOW),
            delta=StateDelta(plan=Plan(goal="o", status="done"), errors=errors),
            route=END,
        )
        return RecordedRun(
            run_id="r",
            graph_id="g",
            graph_version="1",
            initial_state=initial,
            trace=(record,),
            at=NOW,
        )

    assert not _run([{"node_id": "w", "error": "t", RECOVERED_KEY: True}]).failed
    assert _run([{"node_id": "w", "error": "t"}]).failed


def test_the_rule_based_evaluator_is_untouched() -> None:
    """ADR 0038 semantics and every existing user. If the honest fix ever
    requires changing it, that is a separate owner decision."""
    import inspect

    from aef.services.eval.rule_based import RuleBasedEvaluator

    source = inspect.getsource(RuleBasedEvaluator)
    assert RECOVERED_KEY not in source
