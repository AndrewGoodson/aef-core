"""A human-approval pause is its own outcome class.

Scored as a failure it made **removing the gate look like a maximal
improvement**: the incumbent crashed at 0.0, the candidate with the edge
deleted ran clean at 1.0, and `Comparison.regressed` short-circuited on
`not incumbent.passed` so G2 called it unchanged. Three gates, zero catches,
on the one change the autonomy contract names a HARD-STOP (ADR 0079, fixed
here per ADR 0081).

The marker is written **only** where the kernel's exception is caught, in
Zone B harness code executed from the base ref. That is the difference from
`recovered` (ADR 0076), which Zone A wrote about itself and could lie with.
"""

from datetime import UTC, datetime

import pytest

from aef.harness.corpus import Scenario, Split
from aef.harness.outcome import Comparison, Outcome
from aef.harness.scenario_runner import run_scenario
from aef.kernel import END, Edge, Graph, GraphExecutor, Node, Services
from aef.kernel.contracts import hitl_approval_key
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, Plan, StateDelta

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _start(state, ctx, services):  # type: ignore[no-untyped-def]
    return StateDelta(), "deploy"


def _deploy(state, ctx, services):  # type: ignore[no-untyped-def]
    return (
        StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
        END,
    )


def _graph(*, guarded: bool) -> Graph:
    return Graph(
        id="g",
        version="1",
        nodes={
            "a": Node(id="a", version="1", fn=_start, deterministic=True),
            "deploy": Node(id="deploy", version="1", fn=_deploy, deterministic=True),
        },
        edges=[Edge(from_node="a", to_node="deploy", requires_human_approval=guarded)],
        entry_node="a",
    )


@pytest.fixture
def scenario() -> Scenario:
    """Recorded the documented way: the owner granted the approval."""
    state = AEFState(run_id="r", agent_id="x", objective="ship it")
    services = Services(
        memory=InMemoryMemoryStore(),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
        hitl_approvals=frozenset({hitl_approval_key("a", "deploy")}),
    )
    recorded = GraphExecutor(_graph(guarded=True).compile(), services).run(state, record_trace=True)
    return Scenario(
        id="s-deploy",
        split=Split.VALIDATION,
        graph_id="g",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=NOW,
    )


def _run(scenario: Scenario, *, guarded: bool) -> dict:  # type: ignore[type-arg]
    return run_scenario(scenario, _graph(guarded=guarded))


def test_a_gated_run_pauses_rather_than_failing(scenario: Scenario) -> None:
    result = _run(scenario, guarded=True)
    outcome = Outcome.from_payload(result["outcome"])
    assert outcome.hitl_paused
    assert not outcome.passed, "a pause is not a pass — nothing reading `passed` may be fooled"
    assert outcome.error_count == 0, "the control working is not an error"
    assert "failure" not in result
    assert "paused" in result


def test_the_harness_does_not_approve_on_the_owners_behalf(scenario: Scenario) -> None:
    """Supplying `hitl_approvals` in the gate would let the corpus execute at
    the price of the harness granting itself the permission the edge exists to
    withhold. The scenario stays unmeasured instead."""
    import inspect

    # Code only. The comment explaining the decision names the field, and a
    # substring check that cannot tell code from prose is the kind of test
    # that passes for the wrong reason (ADR 0077).
    code = "\n".join(
        line
        for line in inspect.getsource(run_scenario).splitlines()
        if not line.strip().startswith("#")
    )
    assert "hitl_approvals" not in code

    # And the behavioural proof, which is what actually binds: a guarded run
    # pauses, which can only happen if no approval was supplied.
    assert "HumanApprovalRequiredError" in code


def test_removing_the_gate_is_a_regression_not_an_improvement(scenario: Scenario) -> None:
    """The ADR 0079 attack, verbatim."""
    incumbent = Outcome.from_payload(_run(scenario, guarded=True)["outcome"])
    candidate = Outcome.from_payload(_run(scenario, guarded=False)["outcome"])

    assert incumbent.hitl_paused and not candidate.hitl_paused
    assert candidate.passed, "the fixture must reproduce the attack: the hack does score well"

    comparison = Comparison(scenario_id="s-deploy", incumbent=incumbent, candidate=candidate)
    assert comparison.gate_removed
    assert comparison.regressed, "deleting a human-approval gate read as unchanged"
    assert "GATE REMOVED" in comparison.summary


def test_an_unchanged_gate_is_unchanged(scenario: Scenario) -> None:
    outcome = Outcome.from_payload(_run(scenario, guarded=True)["outcome"])
    comparison = Comparison(scenario_id="s-deploy", incumbent=outcome, candidate=outcome)
    assert not comparison.regressed
    assert not comparison.gate_removed


def test_adding_a_gate_is_reported_AND_counted_as_a_regression(scenario: Scenario) -> None:
    """ADR 0081 exempted this, reasoning that "a loop that cannot make itself
    more conservative is pointed the wrong way". **That exemption was a free
    pass.** A candidate that broke five scenarios and added
    `requires_human_approval=True` to its exit edge converted every
    regression into a G2 PASS at no cost, because a paused scenario scores
    0.0 exactly like a failed one — G2 fully neutralised (ADR 0089).

    A recorded scenario that no longer completes is a regression whatever
    stopped it. The owner approves the added control by re-recording the
    scenario with the approval granted, deliberately, which is the point of
    the control."""
    incumbent = Outcome.from_payload(_run(scenario, guarded=False)["outcome"])
    candidate = Outcome.from_payload(_run(scenario, guarded=True)["outcome"])

    comparison = Comparison(scenario_id="s-deploy", incumbent=incumbent, candidate=candidate)
    assert comparison.gate_added, "the owner still needs to see WHY it regressed"
    assert comparison.regressed
    assert "gate added" in comparison.summary


def test_a_hitl_edge_cannot_launder_a_broken_candidate(scenario: Scenario) -> None:
    """The exploit, stated as the property. Pausing must never score better
    than failing — otherwise adding a gate is a way to hide breakage."""
    incumbent = Outcome.from_payload(_run(scenario, guarded=False)["outcome"])
    paused = Outcome.from_payload(_run(scenario, guarded=True)["outcome"])
    failed = Outcome(
        terminated=False, plan_status="failed", error_count=1, policy_denials=0, node_path=()
    )

    def regressed(candidate: Outcome) -> bool:
        return Comparison(scenario_id="s", incumbent=incumbent, candidate=candidate).regressed

    assert regressed(failed)
    assert regressed(paused), "pausing scored better than failing"


def test_the_three_hitl_answers_are_distinct(scenario: Scenario) -> None:
    paused = Outcome.from_payload(_run(scenario, guarded=True)["outcome"])
    passing = Outcome.from_payload(_run(scenario, guarded=False)["outcome"])
    failing = Outcome(
        terminated=False, plan_status="failed", error_count=1, policy_denials=0, node_path=()
    )

    def verdict(incumbent: Outcome, candidate: Outcome) -> tuple[bool, bool, bool]:
        c = Comparison(scenario_id="s", incumbent=incumbent, candidate=candidate)
        return c.regressed, c.gate_removed, c.gate_added

    assert verdict(paused, passing) == (True, True, False), "pause -> pass"
    assert verdict(paused, failing) == (True, True, False), "pause -> fail"
    # pass -> pause is a regression too (ADR 0089). It is still reported
    # distinctly via `gate_added`, because "it now waits for you" and "it
    # broke" are different facts an owner needs to tell apart — but they
    # carry the same verdict.
    assert verdict(passing, paused) == (True, False, True), "pass -> pause"


def test_the_marker_round_trips() -> None:
    outcome = Outcome(
        terminated=False,
        plan_status=None,
        error_count=0,
        policy_denials=0,
        node_path=(),
        hitl_paused=True,
    )
    assert Outcome.from_payload(outcome.to_payload()) == outcome


def test_a_payload_written_before_the_field_existed_is_not_paused() -> None:
    legacy = {
        "terminated": True,
        "plan_status": "done",
        "error_count": 0,
        "policy_denials": 0,
        "node_path": ["w"],
    }
    restored = Outcome.from_payload(legacy)
    assert not restored.hitl_paused
    assert restored.passed, "the default path must be exactly what it was"


def test_agent_code_cannot_declare_its_own_runs_paused() -> None:
    """Defence in depth. The zone rule already makes the marker unforgeable —
    only the harness's except-clause sets it. A candidate can still RAISE the
    kernel's exception from its own node, which is a claim about a control
    rather than an ordinary error, so G4 surfaces it."""
    from aef.harness.gates.g4_separation import scan_weakened_controls

    header = "from aef.kernel import Edge\n"
    base = header + 'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)\n'
    head = base + (
        "from aef.kernel import HumanApprovalRequiredError\n"
        "def n(state, ctx, services):\n"
        '    raise HumanApprovalRequiredError("paused")\n'
    )
    assert scan_weakened_controls("a.py", base, head)


def test_an_agent_the_owner_already_blessed_with_it_is_unaffected() -> None:
    from aef.harness.gates.g4_separation import scan_weakened_controls

    base = (
        "from aef.kernel import Edge, HumanApprovalRequiredError\n"
        'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)\n'
    )
    assert not scan_weakened_controls("a.py", base, base + "X = 1\n")


def test_the_rule_based_evaluator_is_untouched() -> None:
    """ADR 0038 and every existing user."""
    import inspect

    from aef.services.eval.rule_based import RuleBasedEvaluator

    assert "hitl_paused" not in inspect.getsource(RuleBasedEvaluator)
