"""G3 — improvement against a null hypothesis.

M5's acceptance properties. The one that matters most is the third: a
candidate that beats the incumbent but sits inside the random cohort's
spread is REJECTED. Without that rule, "beats the incumbent" launders chance
into evidence.
"""

import math

import pytest

from aef.harness.evaluation import CohortVerdict, ScoreSet, build_score_set, score_of
from aef.harness.gates.base import GateOutcome
from aef.harness.gates.g3_improvement import G3Improvement
from aef.services.eval.base import EvaluationRecord


def _scores(label: str, values: dict[str, float], cost: int = 100) -> ScoreSet:
    return ScoreSet(label=label, per_scenario=values, cost_tokens=cost)


def _uniform(label: str, value: float, n: int = 10, cost: int = 100) -> ScoreSet:
    return _scores(label, {f"s{i}": value for i in range(n)}, cost)


def _verdict(
    candidate: ScoreSet,
    incumbent: ScoreSet,
    cohort: tuple[ScoreSet, ...],
) -> CohortVerdict:
    return CohortVerdict(candidate=candidate, incumbent=incumbent, cohort=cohort)


def _cohort(values: list[float], n: int = 10) -> tuple[ScoreSet, ...]:
    return tuple(_uniform(f"random-{i}", v, n) for i, v in enumerate(values))


# --------------------------------------------------------------------------
# The statistics, stated honestly
# --------------------------------------------------------------------------


def test_an_empty_score_set_has_no_mean_to_report() -> None:
    # Returning 0.0 would be indistinguishable from "everything scored zero".
    with pytest.raises(ValueError, match="no mean"):
        _ = ScoreSet(label="empty").mean


def test_the_confidence_interval_widens_with_variance() -> None:
    tight = _scores("tight", {f"s{i}": 0.8 for i in range(10)})
    loose = _scores("loose", {f"s{i}": (0.1 if i % 2 else 0.9) for i in range(10)})
    tight_low, tight_high = tight.confidence_interval_95
    loose_low, loose_high = loose.confidence_interval_95
    assert (tight_high - tight_low) < (loose_high - loose_low)


def test_a_single_sample_reports_a_degenerate_interval_not_a_fake_one() -> None:
    low, high = _scores("one", {"s0": 0.7}).confidence_interval_95
    assert low == high == 0.7


def test_percentile_interpolates() -> None:
    scores = _scores("s", {f"s{i}": float(i) for i in range(5)})  # 0..4
    assert scores.percentile(0) == 0.0
    assert scores.percentile(100) == 4.0
    assert scores.percentile(50) == pytest.approx(2.0)


@pytest.mark.parametrize("p", [-1.0, 101.0])
def test_an_out_of_range_percentile_is_refused(p: float) -> None:
    with pytest.raises(ValueError, match="within"):
        _scores("s", {"a": 1.0, "b": 2.0}).percentile(p)


def test_a_failed_domain_gate_zeroes_the_score_rather_than_averaging_away() -> None:
    # ADR 0038: domain gates are hard constraints on top of task completion.
    record = EvaluationRecord(run_id="r", task_completion=1.0, domain_gates={"sharpe": False})
    assert score_of(record) == 0.0


def test_score_of_uses_task_completion_when_gates_hold() -> None:
    record = EvaluationRecord(run_id="r", task_completion=0.75, domain_gates={"sharpe": True})
    assert score_of(record) == 0.75


def test_a_score_set_builds_from_evaluation_records() -> None:
    records = {
        "s1": EvaluationRecord(run_id="r1", task_completion=1.0, cost_tokens=10),
        "s2": EvaluationRecord(run_id="r2", task_completion=0.0, cost_tokens=5),
    }
    scores = build_score_set("candidate", records)
    assert scores.mean == pytest.approx(0.5)
    assert scores.cost_tokens == 15
    assert scores.passing == frozenset({"s1"})


# --------------------------------------------------------------------------
# M5 ACCEPTANCE — the null hypothesis
# --------------------------------------------------------------------------


def test_no_cohort_fails_rather_than_passes() -> None:
    """Beating the incumbent proves nothing without a null hypothesis."""
    verdict = _verdict(_uniform("cand", 0.9), _uniform("inc", 0.5), cohort=())
    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "no null-hypothesis control cohort" in result.reason


def test_a_missing_verdict_fails_rather_than_passes() -> None:
    assert not G3Improvement().run(None).passed  # type: ignore[arg-type]


def test_a_cohort_too_small_to_form_a_percentile_fails() -> None:
    verdict = _verdict(_uniform("cand", 0.9), _uniform("inc", 0.5), _cohort([0.5, 0.5]))
    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "coin flip" in result.reason


def test_beating_the_incumbent_but_not_the_cohort_is_rejected() -> None:
    """THE null-hypothesis test. The candidate is better than the incumbent
    and still inside the spread of random mutations — which is exactly what
    chance produces."""
    candidate = _uniform("cand", 0.70)
    incumbent = _uniform("inc", 0.60)
    cohort = _cohort([0.55, 0.62, 0.68, 0.74, 0.80, 0.85])

    verdict = _verdict(candidate, incumbent, cohort)
    assert verdict.beats_incumbent
    assert not verdict.beats_cohort

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "null hypothesis" in result.reason
    assert any("inside the random cohort's spread" in line for line in result.evidence)


def test_beating_the_cohort_passes() -> None:
    candidate = _uniform("cand", 0.95)
    incumbent = _uniform("inc", 0.60)
    cohort = _cohort([0.55, 0.60, 0.62, 0.65, 0.68, 0.70])

    result = G3Improvement(verdict=_verdict(candidate, incumbent, cohort)).run(None)  # type: ignore[arg-type]
    assert result.passed


def test_the_report_always_names_the_confidence_interval() -> None:
    verdict = _verdict(_uniform("cand", 0.95), _uniform("inc", 0.6), _cohort([0.5] * 6))
    assert any("95% CI" in line for line in verdict.report)


def test_the_report_names_the_cohort_threshold() -> None:
    verdict = _verdict(_uniform("cand", 0.95), _uniform("inc", 0.6), _cohort([0.5] * 6))
    assert any("control cohort of 6" in line for line in verdict.report)


# --------------------------------------------------------------------------
# The deterministic rule that binds when statistics cannot
# --------------------------------------------------------------------------


def test_breaking_a_previously_passing_scenario_is_rejected_despite_a_better_mean() -> None:
    # The zero-tolerance rule. The candidate's aggregate is higher and it
    # still fails, because an averaged-away regression is still a regression.
    incumbent = _scores("inc", {"s1": 1.0, "s2": 0.5, "s3": 0.5, "s4": 0.5})  # mean 0.625
    candidate = _scores("cand", {"s1": 0.0, "s2": 1.0, "s3": 1.0, "s4": 1.0})  # mean 0.75
    assert candidate.mean > incumbent.mean

    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.1] * 6))).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "zero tolerance" in result.reason
    assert "s1" in result.evidence


def test_a_scenario_the_candidate_did_not_score_counts_as_regressed() -> None:
    # A missing score is not a passing one.
    incumbent = _scores("inc", {"s1": 1.0, "s2": 1.0})
    candidate = _scores("cand", {"s2": 1.0})
    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.1] * 6))).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "s1" in result.evidence


def test_improving_a_previously_failing_scenario_is_not_a_regression() -> None:
    incumbent = _scores("inc", {"s1": 0.0, "s2": 1.0})
    candidate = _scores("cand", {"s1": 1.0, "s2": 1.0})
    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.1] * 6))).run(None)  # type: ignore[arg-type]
    assert result.passed


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------


def test_a_cost_blowup_is_rejected_even_with_a_better_score() -> None:
    candidate = _uniform("cand", 0.99, cost=1000)
    incumbent = _uniform("inc", 0.60, cost=100)
    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.5] * 6))).run(None)  # type: ignore[arg-type]
    assert not result.passed
    assert "cost blow-up" in result.reason


def test_a_modest_cost_increase_is_allowed() -> None:
    candidate = _uniform("cand", 0.99, cost=120)
    incumbent = _uniform("inc", 0.60, cost=100)
    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.5] * 6))).run(None)  # type: ignore[arg-type]
    assert result.passed


def test_an_unmeasured_incumbent_cost_is_not_treated_as_free() -> None:
    # Dividing by zero, or reading 0 as "free", would make every candidate
    # look like an infinite cost increase (or none at all).
    candidate = _uniform("cand", 0.99, cost=500)
    incumbent = _uniform("inc", 0.60, cost=0)
    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.5] * 6))).run(None)  # type: ignore[arg-type]
    assert result.passed
    assert math.isfinite(candidate.mean)


# --------------------------------------------------------------------------
# ADR 0092 — cost is self-reported, and dropping it is not getting cheaper
# --------------------------------------------------------------------------


def test_a_candidate_cannot_zero_the_cost_rule_by_dropping_provenance() -> None:
    """`cost_tokens` is `sum(p.token_cost for p in state.provenance)`, and
    `Provenance` is written by agent-authored nodes in their own
    `StateDelta`. Nothing else produces it. So deleting `provenance=[...]`
    reported zero tokens and the cost rule could not bind — the same shape as
    ADR 0080's `recovered` marker, on the cost axis.

    Deleting the reporting is not a cheaper agent; it is an agent that
    stopped saying.
    """
    incumbent = ScoreSet(label="incumbent", per_scenario={"s1": 0.5}, cost_tokens=100)
    cohort = tuple(
        ScoreSet(label=f"c{i}", per_scenario={"s1": 0.4}, cost_tokens=100) for i in range(5)
    )
    dropped = ScoreSet(label="candidate", per_scenario={"s1": 1.0}, cost_tokens=0)

    result = G3Improvement(
        verdict=CohortVerdict(candidate=dropped, incumbent=incumbent, cohort=cohort)
    ).run(None)  # type: ignore[arg-type]

    assert result.outcome is GateOutcome.FAIL
    assert "reports none" in result.reason


def test_an_honest_cost_blow_up_is_still_caught() -> None:
    """The control that matters: the new branch must not have replaced the
    rule it was protecting."""
    incumbent = ScoreSet(label="incumbent", per_scenario={"s1": 0.5}, cost_tokens=100)
    cohort = tuple(
        ScoreSet(label=f"c{i}", per_scenario={"s1": 0.4}, cost_tokens=100) for i in range(5)
    )
    expensive = ScoreSet(label="candidate", per_scenario={"s1": 1.0}, cost_tokens=1000)

    result = G3Improvement(
        verdict=CohortVerdict(candidate=expensive, incumbent=incumbent, cohort=cohort)
    ).run(None)  # type: ignore[arg-type]

    assert result.outcome is GateOutcome.FAIL
    assert "cost blow-up" in result.reason


def test_an_honest_candidate_within_budget_still_passes() -> None:
    """And the control for the control: a gate that fails everything is not
    a gate."""
    incumbent = ScoreSet(label="incumbent", per_scenario={"s1": 0.5}, cost_tokens=100)
    cohort = tuple(
        ScoreSet(label=f"c{i}", per_scenario={"s1": 0.4}, cost_tokens=100) for i in range(5)
    )
    fine = ScoreSet(label="candidate", per_scenario={"s1": 1.0}, cost_tokens=120)

    result = G3Improvement(
        verdict=CohortVerdict(candidate=fine, incumbent=incumbent, cohort=cohort)
    ).run(None)  # type: ignore[arg-type]

    assert result.outcome is GateOutcome.PASS


def test_an_incumbent_that_never_reported_leaves_the_rule_unenforceable() -> None:
    """Stated as a test so the limit is recorded rather than discovered. An
    agent that has never emitted Provenance gives this rule nothing to
    compare against, and no amount of gate logic can invent it."""
    incumbent = ScoreSet(label="incumbent", per_scenario={"s1": 0.5}, cost_tokens=0)
    cohort = tuple(
        ScoreSet(label=f"c{i}", per_scenario={"s1": 0.4}, cost_tokens=0) for i in range(5)
    )
    candidate = ScoreSet(label="candidate", per_scenario={"s1": 1.0}, cost_tokens=999_999)

    result = G3Improvement(
        verdict=CohortVerdict(candidate=candidate, incumbent=incumbent, cohort=cohort)
    ).run(None)  # type: ignore[arg-type]

    assert result.outcome is GateOutcome.PASS, "nothing to compare against"
