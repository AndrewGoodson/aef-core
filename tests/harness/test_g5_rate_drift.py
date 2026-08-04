"""G5 — rate, drift, budget.

M7's acceptance properties, from `03-roadmap.md` M7 ("the criterion-5 test"):

  1. several individually-small accepted changes accumulate past the drift
     budget => hard stop
  2. A -> B -> A churn nets ZERO drift but still consumes rate
  3. an agent-proposed rebaseline is refused
"""

from datetime import UTC, datetime, timedelta

import pytest

from aef.harness.gates.g5_rate_drift import (
    AcceptedChange,
    DriftBudget,
    G5RateAndDrift,
    structural_drift,
)

NOW = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)


def _gate(**overrides: object) -> G5RateAndDrift:
    defaults: dict[str, object] = {
        "baseline_files": {"agents/a.py": b"A\n", "agents/b.py": b"B\n"},
        "candidate_files": {"agents/a.py": b"A\n", "agents/b.py": b"B\n"},
        "now": NOW,
    }
    defaults.update(overrides)
    return G5RateAndDrift(**defaults)  # type: ignore[arg-type]


def _accepted(days_ago: list[int]) -> tuple[AcceptedChange, ...]:
    return tuple(
        AcceptedChange(version=i + 1, at=NOW - timedelta(days=d)) for i, d in enumerate(days_ago)
    )


# --------------------------------------------------------------------------
# The drift metric — distance, not path length
# --------------------------------------------------------------------------


def test_an_unchanged_tree_has_zero_drift() -> None:
    files = {"a.py": b"A\n"}
    assert structural_drift(files, dict(files)) == 0.0


def test_drift_is_the_fraction_of_files_that_differ() -> None:
    baseline = {"a.py": b"A\n", "b.py": b"B\n", "c.py": b"C\n", "d.py": b"D\n"}
    current = {"a.py": b"CHANGED\n", "b.py": b"B\n", "c.py": b"C\n", "d.py": b"D\n"}
    assert structural_drift(baseline, current) == pytest.approx(0.25)


def test_an_added_file_counts_as_drift() -> None:
    assert structural_drift({"a.py": b"A\n"}, {"a.py": b"A\n", "b.py": b"B\n"}) == pytest.approx(
        0.5
    )


def test_a_removed_file_counts_as_drift() -> None:
    assert structural_drift({"a.py": b"A\n", "b.py": b"B\n"}, {"a.py": b"A\n"}) == pytest.approx(
        0.5
    )


def test_two_empty_trees_have_no_drift() -> None:
    assert structural_drift({}, {}) == 0.0


# --------------------------------------------------------------------------
# M7 ACCEPTANCE 2 — A -> B -> A nets zero drift but consumes rate
# --------------------------------------------------------------------------


def test_churn_back_to_the_baseline_nets_zero_drift() -> None:
    """Summing step sizes would call this two changes' worth of drift while
    the system sits exactly where it started. Distance-from-baseline is the
    correct reading."""
    baseline = {"agents/a.py": b"A\n"}
    after_round_trip = {"agents/a.py": b"A\n"}
    assert structural_drift(baseline, after_round_trip) == 0.0


def test_churn_still_consumes_the_rate_budget() -> None:
    # Net displacement zero, but the cost of churn is real.
    gate = _gate(
        history=_accepted([1, 2, 3]),  # A->B, B->A, and one more
        budget=DriftBudget(max_accepted_per_window=3),
    )
    result = gate.run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "rate budget exhausted" in result.reason


# --------------------------------------------------------------------------
# M7 ACCEPTANCE 1 — accumulated small changes hard-stop
# --------------------------------------------------------------------------


def test_accumulated_small_changes_trip_the_drift_budget() -> None:
    """Each step was individually defensible; the destination was not chosen
    by anyone."""
    baseline = {f"agents/m{i}.py": b"ORIGINAL\n" for i in range(10)}
    drifted = {f"agents/m{i}.py": (b"CHANGED\n" if i < 6 else b"ORIGINAL\n") for i in range(10)}

    gate = _gate(
        baseline_files=baseline,
        candidate_files=drifted,
        budget=DriftBudget(max_drift=0.5),
    )
    result = gate.run(None)  # type: ignore[arg-type]

    assert not result.passed
    assert "cumulative drift" in result.reason
    assert "not a threshold to raise" in result.reason


def test_drift_within_budget_passes() -> None:
    baseline = {f"agents/m{i}.py": b"ORIGINAL\n" for i in range(10)}
    drifted = {f"agents/m{i}.py": (b"CHANGED\n" if i < 2 else b"ORIGINAL\n") for i in range(10)}

    assert _gate(baseline_files=baseline, candidate_files=drifted).run(None).passed  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# M7 ACCEPTANCE 3 — rebaselining
# --------------------------------------------------------------------------


def test_an_agent_proposed_rebaseline_is_refused() -> None:
    result = _gate(rebaseline_requested=True).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "owner decision" in result.reason
    assert result.security_event


def test_the_rebaseline_rate_limit_binds_before_the_escalation() -> None:
    # Closes the standing-pressure hole: once the drift budget binds, every
    # proposal pushes for a rebaseline, so without a limit the budget stops
    # meaning anything.
    result = _gate(
        rebaseline_requested=True,
        rebaselines=(NOW - timedelta(days=1),),
        budget=DriftBudget(max_rebaselines_per_window=1),
    ).run(None)  # type: ignore[arg-type]

    assert not result.passed
    assert "rebaseline rate limit" in result.reason


def test_a_rebaseline_outside_the_window_does_not_count() -> None:
    result = _gate(
        rebaseline_requested=True,
        rebaselines=(NOW - timedelta(days=30),),
    ).run(None)  # type: ignore[arg-type]
    assert "owner decision" in result.reason  # escalated, not rate-limited


# --------------------------------------------------------------------------
# Rate window mechanics
# --------------------------------------------------------------------------


def test_changes_outside_the_window_do_not_count() -> None:
    assert _gate(history=_accepted([30, 40, 50])).run(None).passed  # type: ignore[arg-type]


def test_the_rate_budget_binds_at_the_limit_not_past_it() -> None:
    assert _gate(history=_accepted([1, 2])).run(None).passed  # type: ignore[arg-type]
    assert not _gate(history=_accepted([1, 2, 3])).run(None).passed  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Reporting and configuration
# --------------------------------------------------------------------------


def test_the_numbers_are_reported_on_pass_as_well_as_fail() -> None:
    # A budget nobody can see approaching only announces itself by blocking
    # something.
    result = _gate(history=_accepted([1])).run(None)  # type: ignore[arg-type]
    assert result.passed
    assert "accepted in the last" in result.reason
    assert "drift" in result.reason


def test_no_baseline_fails_rather_than_passes() -> None:
    assert not _gate(baseline_files=None).run(None).passed  # type: ignore[arg-type]


def test_no_clock_fails_rather_than_passes() -> None:
    assert not _gate(now=None).run(None).passed  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0.0, -0.1, 1.5])
def test_an_unreachable_drift_budget_is_refused(value: float) -> None:
    # 0 blocks every change; above 1 can never trip. Neither is a budget.
    with pytest.raises(ValueError, match="max_drift"):
        DriftBudget(max_drift=value)


def test_a_zero_rate_budget_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        DriftBudget(max_accepted_per_window=0)


def test_a_nonpositive_window_is_refused() -> None:
    with pytest.raises(ValueError, match="window"):
        DriftBudget(window=timedelta(0))
