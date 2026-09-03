"""The task metric can fail without an error (ADR 0113).

The reproduce-first case is the first test: a graph that finishes its plan
cleanly and writes the WRONG answer scored 1.0 before checks existed. That is
the defect — a metric that only moves when something raises cannot measure
learning. Every later test pins a property of the fix."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aef.harness.checks import CheckError, TaskCheck, evaluate_checks
from aef.harness.corpus import Scenario, Split
from aef.harness.evaluation import score_scenario
from aef.harness.scenario_runner import run_scenario
from aef.kernel import END, Graph, GraphExecutor, Node
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta


def _graph(answer: str) -> Graph:
    def do(state, ctx, services):  # type: ignore[no-untyped-def]
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="done"),
                working_memory={"answer": answer},
                scores={"quality": 1.0},
            ),
            END,
        )

    return Graph(
        id="g",
        version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[],
        entry_node="do",
    )


def _scenario(checks: tuple[TaskCheck, ...] = (), budget_ms: float | None = None) -> Scenario:
    state = AEFState(run_id="s", agent_id="a", objective="say 42")
    recorded = GraphExecutor(_graph("42").compile(), agent_services()).run(state, record_trace=True)
    assert recorded.trace is not None
    return Scenario(
        id="s",
        split=Split.TRAIN,
        graph_id="g",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=datetime(2026, 9, 3, tzinfo=UTC),
        checks=checks,
        budget_ms=budget_ms,
    )


# ---------------------------------------------------------------------------
# The defect, reproduced
# ---------------------------------------------------------------------------
def test_without_checks_a_clean_wrong_answer_scores_full_marks() -> None:
    """This is what the metric was: blind to content. Kept as the control —
    it must still hold, because a scenario with no checks carries no claim
    about the answer and scoring it lower would invent one."""
    wrong = run_scenario(_scenario(), _graph("wrong"))
    assert wrong["score"] == 1.0


def test_with_a_check_the_same_wrong_answer_scores_zero() -> None:
    checks = (TaskCheck(path="working_memory.answer", op="equals", value="42"),)
    right = run_scenario(_scenario(checks), _graph("42"))
    wrong = run_scenario(_scenario(checks), _graph("wrong"))
    assert right["score"] == 1.0
    assert wrong["score"] == 0.0
    assert wrong["checks"]["failures"] == ["working_memory.answer equals '42': got 'wrong'"]


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------
def test_score_is_the_fraction_of_checks_passed() -> None:
    checks = (
        TaskCheck(path="working_memory.answer", op="equals", value="42"),
        TaskCheck(path="working_memory.answer", op="contains", value="4"),
        TaskCheck(path="working_memory.answer", op="regex", value=r"^\d+$"),
        TaskCheck(path="working_memory.missing", op="exists"),
    )
    result = run_scenario(_scenario(checks), _graph("42"))
    assert result["score"] == pytest.approx(0.75)
    assert result["checks"] == {
        "passed": 3,
        "total": 4,
        "failures": ["working_memory.missing exists None: got <missing>"],
    }


def test_an_error_zeroes_the_score_even_when_checks_pass() -> None:
    """Checks refine task_completion; they do not override an errored run.
    A node that wrote the right answer and then raised did not complete."""
    state = AEFState(
        run_id="s",
        agent_id="a",
        objective="o",
        working_memory={"answer": "42"},
        plan=Plan(goal="o", status="done"),
        errors=[{"node_id": "do", "error": "boom"}],
    )
    checks = (TaskCheck(path="working_memory.answer", op="equals", value="42"),)
    record = score_scenario(_scenario(checks), state, elapsed_ms=1.0)
    assert record.task_completion == 0.0
    assert record.metadata["checks"]["passed"] == 1


def test_wall_clock_budget_zeroes_the_score_when_exceeded() -> None:
    """Latency under a pinned clock is the RECORDED latency, so the budget
    is judged on the runner's own stopwatch, passed in as elapsed_ms."""
    scenario = _scenario(budget_ms=50.0)
    state = _graph("42").compile()
    final = GraphExecutor(state, agent_services()).run(scenario.initial_state).final_state
    within = score_scenario(scenario, final, elapsed_ms=10.0)
    over = score_scenario(scenario, final, elapsed_ms=51.0)
    assert within.task_completion == 1.0
    assert over.task_completion == 0.0
    assert over.metadata["budget_exceeded"] is True
    assert over.metadata["elapsed_ms"] == 51.0


def test_runner_reports_its_own_elapsed_time() -> None:
    result = run_scenario(_scenario(), _graph("42"))
    assert result["elapsed_ms"] >= 0.0


# ---------------------------------------------------------------------------
# Checks are data with a schema, validated at load
# ---------------------------------------------------------------------------
def test_scenario_round_trips_checks_and_budget_through_its_payload() -> None:
    checks = (
        TaskCheck(path="scores.quality", op="equals", value=1.0),
        TaskCheck(path="working_memory.answer", op="exists"),
    )
    scenario = _scenario(checks, budget_ms=250.0)
    payload = scenario.to_payload()
    assert payload["checks"] == [
        {"path": "scores.quality", "op": "equals", "value": 1.0},
        {"path": "working_memory.answer", "op": "exists"},
    ]
    assert payload["budget_ms"] == 250.0
    back = Scenario.from_payload(payload)
    assert back.checks == checks
    assert back.budget_ms == 250.0


def test_legacy_payload_without_checks_still_loads() -> None:
    payload = _scenario().to_payload()
    del payload["checks"]
    del payload["budget_ms"]
    back = Scenario.from_payload(payload)
    assert back.checks == ()
    assert back.budget_ms is None


@pytest.mark.parametrize(
    "bad",
    [
        {"path": "scores.quality", "op": "gte", "value": 1},
        {"path": "", "op": "exists"},
        {"path": "a..b", "op": "exists"},
        {"path": "x", "op": "regex", "value": "("},
        {"path": "x", "op": "exists", "value": "not allowed"},
        {"op": "exists"},
    ],
)
def test_malformed_checks_are_refused_at_load(bad: dict[str, object]) -> None:
    with pytest.raises(CheckError):
        TaskCheck.from_payload(bad)


def test_evaluate_checks_walks_lists_and_dicts() -> None:
    state = AEFState(
        run_id="s",
        agent_id="a",
        objective="o",
        tool_results=[{"name": "search", "hits": ["a", "b"]}],
        reflections=["lesson one"],
    )
    report = evaluate_checks(
        (
            TaskCheck(path="tool_results.0.name", op="equals", value="search"),
            TaskCheck(path="tool_results.0.hits", op="contains", value="b"),
            TaskCheck(path="reflections.0", op="regex", value="lesson"),
            TaskCheck(path="tool_results.5.name", op="exists"),
        ),
        state,
    )
    assert (report.passed, report.total) == (3, 4)


# ---------------------------------------------------------------------------
# The isolated path (what the gates use) scores through the same function
# ---------------------------------------------------------------------------
_CANDIDATE = """
from aef.kernel import END, Graph, Node
from aef.state import Plan, StateDelta


def do(state, ctx, services):
    return (
        StateDelta(
            plan=Plan(goal=state.objective, status="done"),
            working_memory={"answer": "%s"},
            scores={"quality": 1.0},
        ),
        END,
    )


def build_graph():
    return Graph(
        id="g", version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[], entry_node="do",
    )
"""


@pytest.mark.parametrize(("answer", "expected_score"), [("42", 1.0), ("wrong", 0.0)])
def test_isolated_suite_scores_checks_too(tmp_path, answer: str, expected_score: float) -> None:  # type: ignore[no-untyped-def]
    """A candidate that runs cleanly but answers wrong must score 0.0 in the
    gate path as well, or G3 would judge candidates on a different metric
    than `loop score` reports (ADR 0091's drift, ADR 0113's metric)."""
    from aef.harness.isolated_suite import run_corpus_isolated

    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "__init__.py").write_text("")
    (tmp_path / "agents" / "graph.py").write_text(_CANDIDATE % answer)
    checks = (TaskCheck(path="working_memory.answer", op="equals", value="42"),)
    results = run_corpus_isolated(
        tmp_path, [_scenario(checks)], entrypoint="agents.graph:build_graph"
    )
    assert results["s"].failure is None
    assert results["s"].score == expected_score
