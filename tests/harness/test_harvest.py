"""Corpus auto-growth. Every promotion path exercised against real runs.

The rules exist because their opposites each break the corpus in a different
way, so each has its own test and its own reason.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aef.harness.corpus import Expected, Split, load_corpus
from aef.harness.harvest import (
    RecordedRun,
    harvest,
    load_runs,
    save_run,
)
from aef.kernel import END, Context, Graph, GraphExecutor, Node, Route, Services
from aef.state import AEFState, Plan, StateDelta

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _graph(*, always_succeed: bool = False) -> Graph:
    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        should_fail = bool(state.working_memory.get("fail")) and not always_succeed
        if should_fail:
            return StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[{"node_id": ctx.node_id, "error": "boom"}],
            ), END
        return StateDelta(plan=Plan(goal=state.objective, status="done")), END

    node = Node(id="work", version="0.1.0", fn=work, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"work": node}, edges=[], entry_node="work")


def _record(runs: Path, run_id: str, *, fail: bool, at: datetime | None = None) -> RecordedRun:
    graph = _graph()
    state = AEFState(
        run_id=run_id, agent_id="demo", objective="task", working_memory={"fail": fail}
    )
    ticks = iter([NOW + timedelta(seconds=i) for i in range(20)])
    result = GraphExecutor(graph.compile(), Services(clock=lambda: next(ticks))).run(
        state, record_trace=True
    )
    assert result.trace is not None
    run = RecordedRun(
        run_id=run_id,
        graph_id=graph.id,
        graph_version=graph.version,
        initial_state=state,
        trace=result.trace,
        at=at or NOW,
    )
    save_run(runs, run)
    return run


def _harvest(tmp_path: Path, **kwargs: object):
    return harvest(
        tmp_path / "runs", tmp_path / "corpus", _graph(), now=NOW + timedelta(hours=1), **kwargs
    )  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------


def test_a_recorded_run_round_trips(tmp_path: Path) -> None:
    original = _record(tmp_path / "runs", "r1", fail=True)
    loaded = load_runs(tmp_path / "runs")
    assert len(loaded) == 1
    assert loaded[0].run_id == original.run_id
    assert loaded[0].initial_state == original.initial_state


def test_a_failing_run_is_recognised_as_failed(tmp_path: Path) -> None:
    assert _record(tmp_path / "runs", "r1", fail=True).failed


def test_a_passing_run_is_not(tmp_path: Path) -> None:
    assert not _record(tmp_path / "runs", "r2", fail=False).failed


def test_a_missing_runs_directory_reads_as_empty(tmp_path: Path) -> None:
    assert load_runs(tmp_path / "nope") == ()


# --------------------------------------------------------------------------
# Failures promoted, successes not
# --------------------------------------------------------------------------


def test_a_failing_run_is_promoted(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "fail-1", fail=True)
    outcome = _harvest(tmp_path)

    assert outcome.promoted == ("fail-1",)
    assert {s.id for s in load_corpus(tmp_path / "corpus").scenarios} == {"fail-1"}


def test_a_passing_run_is_not_promoted_by_default(tmp_path: Path) -> None:
    """Auto-promoting successes inflates the pass rate the gates measure
    against, so the corpus drifts toward 'everything passes' — and a corpus
    where everything passes cannot demonstrate an improvement."""
    _record(tmp_path / "runs", "pass-1", fail=False)
    outcome = _harvest(tmp_path)

    assert outcome.promoted == ()
    assert outcome.skipped_passing == ("pass-1",)


def test_a_passing_run_is_promoted_on_request(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "pass-1", fail=False)
    assert _harvest(tmp_path, include_successes=True).promoted == ("pass-1",)


# --------------------------------------------------------------------------
# Always TRAIN, and no owner claim
# --------------------------------------------------------------------------


def test_harvested_scenarios_land_in_train(tmp_path: Path) -> None:
    # If production could write to validation, the set that gates candidates
    # would be shaped by the same system being gated.
    _record(tmp_path / "runs", "fail-1", fail=True)
    _harvest(tmp_path)

    corpus = load_corpus(tmp_path / "corpus")
    assert [s.split for s in corpus.scenarios] == [Split.TRAIN]
    assert corpus.split(Split.VALIDATION) == ()
    assert corpus.split(Split.HOLDOUT) == ()


def test_harvest_offers_no_way_to_choose_a_split(tmp_path: Path) -> None:
    import inspect

    from aef.harness.harvest import harvest as harvest_fn

    assert "split" not in inspect.signature(harvest_fn).parameters


def test_a_harvested_scenario_carries_no_owner_claim(tmp_path: Path) -> None:
    """Only a human can say a task SHOULD have failed. A MUST_FAIL label the
    system invented would be a tripwire it set for itself."""
    _record(tmp_path / "runs", "fail-1", fail=True)
    _harvest(tmp_path)

    scenario = load_corpus(tmp_path / "corpus").scenarios[0]
    assert scenario.expected is Expected.UNSPECIFIED


# --------------------------------------------------------------------------
# Determinism, duplicates, rate limit
# --------------------------------------------------------------------------


def test_a_run_that_does_not_reproduce_is_rejected(tmp_path: Path) -> None:
    """One admitted flake poisons every future comparison — the cost is not
    one bad scenario, it is a corpus nobody can trust."""
    _record(tmp_path / "runs", "flaky-1", fail=True)

    # The recorded run failed; this graph succeeds on the same input, so
    # re-execution produces a different trace. Whether the divergence comes
    # from nondeterminism or from the graph having moved on, the scenario
    # cannot be trusted as a fixed point and must not be admitted.
    outcome = harvest(
        tmp_path / "runs",
        tmp_path / "corpus",
        _graph(always_succeed=True),
        now=NOW + timedelta(hours=1),
    )

    assert outcome.promoted == ()
    assert outcome.rejected_nondeterministic == ("flaky-1",)
    assert not (tmp_path / "corpus").exists() or not load_corpus(tmp_path / "corpus").scenarios


def test_an_already_harvested_run_is_not_promoted_twice(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "fail-1", fail=True)
    _harvest(tmp_path)

    second = _harvest(tmp_path)
    assert second.promoted == ()
    assert second.skipped_existing == ("fail-1",)


def test_the_daily_rate_limit_caps_promotions(tmp_path: Path) -> None:
    # One bad deploy can produce thousands of failing runs; without a cap the
    # corpus fills with a single incident and the gates measure that instead.
    for i in range(9):
        _record(tmp_path / "runs", f"fail-{i}", fail=True)

    outcome = _harvest(tmp_path, daily_limit=3)

    assert len(outcome.promoted) == 3
    assert len(outcome.skipped_rate_limited) == 6


def test_the_rate_limit_counts_what_was_already_recorded_today(tmp_path: Path) -> None:
    for i in range(4):
        _record(tmp_path / "runs", f"fail-{i}", fail=True)
    first = _harvest(tmp_path, daily_limit=2)
    assert len(first.promoted) == 2

    second = _harvest(tmp_path, daily_limit=2)
    assert second.promoted == (), "the limit must span runs, not reset per invocation"


def test_the_outcome_reports_every_category(tmp_path: Path) -> None:
    _record(tmp_path / "runs", "fail-1", fail=True)
    _record(tmp_path / "runs", "pass-1", fail=False)
    lines = " ".join(_harvest(tmp_path).lines)

    assert "promoted 1" in lines
    assert "passed, not promoted" in lines
