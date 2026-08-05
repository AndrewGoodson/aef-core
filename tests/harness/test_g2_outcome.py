"""G2 — outcome non-regression.

M4's acceptance properties. The first two are the corrected semantic that
the three-reviewer audit produced: comparing execution *paths* admits only
no-ops, so G2 compares outcome classes and merely *reports* routing changes.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.outcome import Comparison, Outcome, classify
from aef.state import AEFState, Plan


def _outcome(**overrides: object) -> Outcome:
    defaults: dict[str, object] = {
        "terminated": True,
        "plan_status": "done",
        "error_count": 0,
        "policy_denials": 0,
        "node_path": ("a", "b"),
    }
    defaults.update(overrides)
    return Outcome(**defaults)  # type: ignore[arg-type]


def _state(**overrides: object) -> AEFState:
    defaults: dict[str, object] = {"run_id": "r1", "agent_id": "a1", "objective": "obj"}
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# What counts as passing
# --------------------------------------------------------------------------


def test_a_completed_run_with_no_errors_passed() -> None:
    assert _outcome().passed


@pytest.mark.parametrize(
    "override",
    [
        {"terminated": False},
        {"plan_status": "failed"},
        {"plan_status": "active"},
        {"plan_status": None},
        {"error_count": 1},
    ],
)
def test_anything_short_of_completion_did_not_pass(override: dict[str, object]) -> None:
    assert not _outcome(**override).passed


def test_classification_reads_the_final_state_and_trace() -> None:
    outcome = classify(
        _state(plan=Plan(goal="g", status="done"), errors=[]), trace=None, terminated=True
    )
    assert outcome.passed
    assert outcome.node_path == ()


def test_a_policy_denial_is_counted_separately_from_a_plain_error() -> None:
    # PolicyEngine is deny-by-default; a candidate that starts tripping it
    # has changed behaviour that matters even if the count of errors is
    # otherwise unremarkable.
    state = _state(errors=[{"error": "tool call denied by policy: scope not declared"}])
    outcome = classify(state, trace=None, terminated=True)
    assert outcome.error_count == 1
    assert outcome.policy_denials == 1


def test_an_ordinary_error_is_not_counted_as_a_policy_denial() -> None:
    outcome = classify(
        _state(errors=[{"error": "timeout talking to the API"}]), None, terminated=True
    )
    assert outcome.policy_denials == 0


# --------------------------------------------------------------------------
# M4 ACCEPTANCE — routing divergence is reported, never rejected
# --------------------------------------------------------------------------


def test_a_routing_change_with_the_same_outcome_is_not_a_regression() -> None:
    """THE corrected semantic. Path identity would reject this, and since
    every non-trivial change alters the path, that pipeline could only ever
    admit no-ops."""
    comparison = Comparison(
        scenario_id="s1",
        incumbent=_outcome(node_path=("a", "b", "c")),
        candidate=_outcome(node_path=("a", "d")),  # different route, same result
    )
    assert comparison.routing_diverged
    assert not comparison.regressed
    assert "reported, not a rejection" in comparison.summary


def test_a_shorter_route_to_the_same_outcome_is_not_a_regression() -> None:
    # The shape an actual improvement takes.
    comparison = Comparison(
        scenario_id="s1",
        incumbent=_outcome(node_path=("a", "b", "c", "d")),
        candidate=_outcome(node_path=("a", "d")),
    )
    assert not comparison.regressed


# --------------------------------------------------------------------------
# M4 ACCEPTANCE — a broken previously-passing scenario is rejected
# --------------------------------------------------------------------------


def test_breaking_a_previously_passing_scenario_is_a_regression() -> None:
    comparison = Comparison(
        scenario_id="s1", incumbent=_outcome(), candidate=_outcome(plan_status="failed")
    )
    assert comparison.regressed
    assert "REGRESSION" in comparison.summary


def test_introducing_an_error_into_a_passing_scenario_is_a_regression() -> None:
    comparison = Comparison(
        scenario_id="s1", incumbent=_outcome(), candidate=_outcome(error_count=1)
    )
    assert comparison.regressed


def test_failing_to_terminate_is_a_regression() -> None:
    comparison = Comparison(
        scenario_id="s1", incumbent=_outcome(), candidate=_outcome(terminated=False)
    )
    assert comparison.regressed


def test_newly_tripping_a_policy_gate_is_a_regression_even_while_passing() -> None:
    # Both outcomes "pass" by plan status, but the candidate now gets denied
    # somewhere the incumbent did not. That is a behavioural change the gate
    # must not wave through.
    comparison = Comparison(
        scenario_id="s1",
        incumbent=_outcome(),
        candidate=_outcome(policy_denials=1),
    )
    assert comparison.candidate.passed is False or comparison.regressed


def test_a_candidate_that_removes_a_policy_denial_is_not_a_regression() -> None:
    comparison = Comparison(
        scenario_id="s1",
        incumbent=_outcome(plan_status="failed", error_count=1, policy_denials=1),
        candidate=_outcome(),
    )
    assert not comparison.regressed


# --------------------------------------------------------------------------
# The asymmetry — previously-failing scenarios may change freely
# --------------------------------------------------------------------------


def test_a_previously_failing_scenario_may_change_freely() -> None:
    # The incumbent has no claim on behaviour it never got right.
    incumbent = _outcome(plan_status="failed", error_count=2)
    for candidate in (
        _outcome(),
        _outcome(terminated=False),
        _outcome(plan_status="active", error_count=9),
    ):
        assert not Comparison(scenario_id="s1", incumbent=incumbent, candidate=candidate).regressed


def test_fixing_a_previously_failing_scenario_is_not_a_regression() -> None:
    comparison = Comparison(
        scenario_id="s1",
        incumbent=_outcome(plan_status="failed", error_count=1),
        candidate=_outcome(),
    )
    assert not comparison.regressed


# --------------------------------------------------------------------------
# Serialisation across the sandbox boundary
# --------------------------------------------------------------------------


def test_an_outcome_round_trips_through_json() -> None:
    original = _outcome(node_path=("a", "b", "c"), policy_denials=2)
    assert Outcome.from_payload(original.to_payload()) == original


def test_an_unchanged_scenario_says_so() -> None:
    comparison = Comparison(scenario_id="s1", incumbent=_outcome(), candidate=_outcome())
    assert comparison.summary.endswith("unchanged")


# --------------------------------------------------------------------------
# The entrypoint loader
# --------------------------------------------------------------------------


def test_a_malformed_entrypoint_is_refused() -> None:
    from aef.harness.scenario_runner import EntrypointError, load_graph

    with pytest.raises(EntrypointError, match="module:factory"):
        load_graph("no_colon_here")


def test_an_unimportable_entrypoint_is_refused() -> None:
    from aef.harness.scenario_runner import EntrypointError, load_graph

    with pytest.raises(EntrypointError, match="cannot import"):
        load_graph("definitely_not_a_module:build_graph")


def test_an_entrypoint_that_returns_the_wrong_type_is_refused() -> None:
    from aef.harness.scenario_runner import EntrypointError, load_graph

    with pytest.raises(EntrypointError, match="expected a Graph"):
        load_graph("json:JSONDecoder")


def test_an_entrypoint_whose_factory_raises_is_refused() -> None:
    # An agent-authored build_graph() that throws must surface as a bad
    # entrypoint, not as an unhandled traceback out of the runner.
    from aef.harness.scenario_runner import EntrypointError, load_graph

    with pytest.raises(EntrypointError, match="raised TypeError"):
        load_graph("json:dumps")


def test_a_real_entrypoint_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from aef.harness.scenario_runner import load_graph

    module = tmp_path / "tiny_graph_mod.py"
    module.write_text(
        "from aef.kernel import END, Graph, Node\n"
        "from aef.state import StateDelta\n"
        "\n"
        "\n"
        "def _fn(state, ctx, services):\n"
        "    return StateDelta(), END\n"
        "\n"
        "\n"
        "def build_graph():\n"
        "    n = Node(id='n', version='1', fn=_fn, deterministic=True)\n"
        "    return Graph(id='g', version='1', nodes={'n': n}, edges=[], entry_node='n')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert load_graph("tiny_graph_mod:build_graph").id == "g"


# --------------------------------------------------------------------------
# The gate's own refusals
# --------------------------------------------------------------------------


def test_an_empty_corpus_fails_rather_than_passes() -> None:
    # Absence of evidence is not evidence of non-regression. ADR 0045
    # condition 7 makes this a Tier-2 escalation, never a quiet pass.
    from aef.harness.corpus import Corpus
    from aef.harness.gates.g2_outcome import G2OutcomeNonRegression

    gate = G2OutcomeNonRegression(corpus=Corpus(root=Path("/nowhere"), scenarios=()))
    result = gate.run(None)  # type: ignore[arg-type]  # never reaches ctx
    assert not result.passed
    assert "absence of evidence" in result.reason


def test_no_corpus_at_all_fails_rather_than_passes() -> None:
    from aef.harness.gates.g2_outcome import G2OutcomeNonRegression

    assert not G2OutcomeNonRegression().run(None).passed  # type: ignore[arg-type]


def test_the_holdout_split_is_not_spent_on_a_routine_gate_run() -> None:
    from aef.harness.corpus import Split
    from aef.harness.gates.g2_outcome import G2OutcomeNonRegression

    assert Split.HOLDOUT not in G2OutcomeNonRegression().splits


def test_the_recorded_outcome_is_derived_from_the_trace() -> None:
    # Derived rather than stored, so changing the classification rule
    # re-classifies the whole corpus consistently instead of leaving old
    # entries judged by an old rule.
    from aef.harness.corpus import Scenario, Split
    from aef.harness.gates.g2_outcome import recorded_outcome
    from aef.kernel import END, Context, NodeExecutionRecord
    from aef.state import StateDelta

    record = NodeExecutionRecord(
        node_id="only",
        input_state=_state(),
        context=Context(
            run_id="r1",
            graph_version="1",
            trace_id="t1",
            node_id="only",
            now=datetime(2026, 3, 1, tzinfo=UTC),
        ),
        delta=StateDelta(plan=Plan(goal="g", status="done")),
        route=END,
    )
    scenario = Scenario(
        id="s1",
        split=Split.TRAIN,
        graph_id="g",
        graph_version="1",
        initial_state=_state(),
        trace=(record,),
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    outcome = recorded_outcome(scenario)
    assert outcome.passed
    assert outcome.node_path == ("only",)


# --------------------------------------------------------------------------
# Tripwires (ADR 0061)
# --------------------------------------------------------------------------


def test_claiming_success_on_a_must_fail_scenario_is_a_tripwire_hit() -> None:
    comparison = Comparison(
        scenario_id="impossible",
        incumbent=_outcome(plan_status="failed", error_count=1),
        candidate=_outcome(),
        expected="must_fail",
    )
    assert comparison.tripwire_hit
    assert comparison.regressed
    assert "TRIPWIRE" in comparison.summary


def test_failing_a_must_fail_scenario_is_correct_behaviour() -> None:
    comparison = Comparison(
        scenario_id="impossible",
        incumbent=_outcome(plan_status="failed", error_count=1),
        candidate=_outcome(plan_status="failed", error_count=1),
        expected="must_fail",
    )
    assert not comparison.tripwire_hit
    assert not comparison.regressed


def test_failing_a_must_pass_scenario_is_a_regression() -> None:
    comparison = Comparison(
        scenario_id="basic",
        incumbent=_outcome(),
        candidate=_outcome(plan_status="failed"),
        expected="must_pass",
    )
    assert comparison.regressed


def test_an_unspecified_scenario_keeps_the_original_asymmetry() -> None:
    # No owner claim, so a previously-failing scenario may still change freely.
    comparison = Comparison(
        scenario_id="s1",
        incumbent=_outcome(plan_status="failed", error_count=1),
        candidate=_outcome(),
        expected="unspecified",
    )
    assert not comparison.regressed


def test_the_default_expectation_is_unspecified() -> None:
    assert Comparison(scenario_id="s1", incumbent=_outcome(), candidate=_outcome()).expected == (
        "unspecified"
    )
