"""G3 under live noise: dead calls, and the paired line beside p95 (ADR 0185).

ADR 0156 measured the live floor on Opus — mean 0.7639, spread 0.1666 over
3 repeats of 6 scenarios — and left two findings for this increment:

* **~a third of that spread was transient call failure.** A provider that
  raises and a provider that returns `""` both produce `score 0.0000,
  cost_tokens 0`, and nothing told them apart. Under K1 (ADR 0181) every gate
  pass may execute live, so every gate pass meets this.
* **The planted regression was invisible to the mean and visible per
  scenario.** It moved the mean of means 0.0278 against a 0.1666 spread;
  `sum-17` and `sum-18` fell in 3 of 3 repeats. ADR 0156 offered a paired
  test with the data and did not make it.

The fixture for the second half is ADR 0156's own committed output,
`docs/research/i13/{floor,regress}-r{1,2,3}.json`. No test here makes a model
call.

`tests/harness/test_g3_improvement.py` is UNCHANGED: every rule it pins still
decides exactly as it did.
"""

from __future__ import annotations

import json
from pathlib import Path

from aef.harness.evaluation import CohortVerdict, ScoreSet
from aef.harness.gates.base import GateOutcome
from aef.harness.gates.g3_improvement import G3Improvement, paired_sign_test

I13 = Path("docs/research/i13")


def _scores(label: str, values: dict[str, float], cost: int = 100) -> ScoreSet:
    return ScoreSet(label=label, per_scenario=values, cost_tokens=cost)


def _uniform(label: str, value: float, n: int = 10, cost: int = 100) -> ScoreSet:
    return _scores(label, {f"s{i}": value for i in range(n)}, cost)


def _cohort(values: list[float], n: int = 10) -> tuple[ScoreSet, ...]:
    return tuple(_uniform(f"random-{i}", v, n) for i, v in enumerate(values))


def _verdict(
    candidate: ScoreSet, incumbent: ScoreSet, cohort: tuple[ScoreSet, ...]
) -> CohortVerdict:
    return CohortVerdict(candidate=candidate, incumbent=incumbent, cohort=cohort)


def _with_dead(
    candidate: ScoreSet,
    incumbent: ScoreSet,
    cohort: tuple[ScoreSet, ...],
    *,
    dead: set[str] = frozenset(),  # type: ignore[assignment]
    retried: set[str] = frozenset(),  # type: ignore[assignment]
) -> CohortVerdict:
    return CohortVerdict(
        candidate=candidate,
        incumbent=incumbent,
        cohort=cohort,
        dead_scenarios=frozenset(dead),
        retried_scenarios=frozenset(retried),
    )


# --------------------------------------------------------------------------
# A dead call is not a wrong answer
# --------------------------------------------------------------------------


def test_a_dead_call_scored_zero_rejects_a_candidate_that_answered_everything() -> None:
    """The DEFECT, pinned at the gate's own boundary.

    Without the dead-call rule the zero-tolerance check reads a scenario the
    candidate was never asked as a regression. Reproduced end to end against a
    stub provider that exits non-zero on its third call — see
    `test_dead_calls.py`."""
    incumbent = _scores("inc", {"s1": 1.0, "s2": 1.0, "s3": 1.0, "s4": 1.0})
    candidate = _scores("cand", {"s1": 1.0, "s2": 1.0, "s3": 0.0, "s4": 1.0})

    result = G3Improvement(verdict=_verdict(candidate, incumbent, _cohort([0.1] * 6, n=4))).run(
        None
    )  # type: ignore[arg-type]

    assert not result.passed
    assert "zero tolerance" in result.reason
    assert "s3" in result.evidence


def test_the_same_zero_declared_dead_is_excluded_instead_of_counted() -> None:
    incumbent = _scores("inc", {"s1": 1.0, "s2": 1.0, "s3": 1.0, "s4": 1.0})
    candidate = _scores("cand", {"s1": 1.0, "s2": 1.0, "s3": 0.0, "s4": 1.0})
    verdict = _with_dead(candidate, incumbent, _cohort([0.1] * 6, n=4), dead={"s3"})

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]

    assert result.passed
    # Named, never silent: ADR 0156 had to infer a dead call from split-level
    # token accounting across repeats, and nobody should have to do that again.
    assert any("excluded 1 of 4" in line for line in result.evidence)
    assert any("s3" in line for line in result.evidence)
    # Judged on THREE scenarios, and the report says so.
    assert any("n=3" in line for line in result.evidence)


def test_excluding_a_dead_call_in_a_control_RAISES_the_bar() -> None:
    """The direction that matters most, and why this is a strengthening.

    A dead call in a control member is scored 0.0, which drags that member's
    mean down, which drags p95 down, which LOWERS the bar the candidate has to
    clear. Same numbers, same candidate: counted it passes, excluded it does
    not."""
    ids = ["s1", "s2", "s3", "s4", "s5"]
    candidate = _scores("cand", dict.fromkeys(ids, 0.9))
    incumbent = _scores("inc", {"s1": 0.0, **dict.fromkeys(ids[1:], 0.9)})
    cohort = tuple(
        _scores(f"random-{i}", {"s1": 0.0, **dict.fromkeys(ids[1:], 1.0)}) for i in range(5)
    )

    counted = G3Improvement(verdict=_verdict(candidate, incumbent, cohort)).run(None)  # type: ignore[arg-type]
    assert counted.passed, "the dead 0.0 in every control lowered p95 to 0.8"

    excluded = G3Improvement(verdict=_with_dead(candidate, incumbent, cohort, dead={"s1"})).run(
        None
    )  # type: ignore[arg-type]
    assert not excluded.passed
    assert "null hypothesis" in excluded.reason


def test_the_exclusion_is_symmetric_across_every_arm() -> None:
    """A one-sided drop would compute the candidate's mean over one scenario
    set and the threshold it must beat over another."""
    candidate = _scores("cand", {"s1": 0.0, "s2": 1.0})
    incumbent = _scores("inc", {"s1": 1.0, "s2": 0.5})
    cohort = tuple(_scores(f"random-{i}", {"s1": 0.2, "s2": 0.2}) for i in range(5))
    verdict = _with_dead(candidate, incumbent, cohort, dead={"s1"})

    judged = verdict.without(frozenset({"s1"}))

    assert set(judged.candidate.per_scenario) == {"s2"}
    assert set(judged.incumbent.per_scenario) == {"s2"}
    assert all(set(c.per_scenario) == {"s2"} for c in judged.cohort)
    # The dead set is carried forward, so the evidence can still name it.
    assert judged.dead_scenarios == frozenset({"s1"})


def test_dropping_nothing_returns_the_very_same_verdict() -> None:
    """Every replayed run takes this path: `is_dead_call` is False unless the
    run was live, so `without` has to be a true no-op."""
    verdict = _verdict(_uniform("cand", 0.9), _uniform("inc", 0.5), _cohort([0.1] * 5))
    assert verdict.without(frozenset()) is verdict


def test_more_dead_calls_than_the_ceiling_refuses_to_judge() -> None:
    """Not a pass and not a rejection: a refusal, which escalates the
    candidate exactly as an absent cohort does."""
    ids = [f"s{i}" for i in range(6)]
    verdict = _with_dead(
        _scores("cand", dict.fromkeys(ids, 1.0)),
        _scores("inc", dict.fromkeys(ids, 0.5)),
        _cohort([0.1] * 6, n=6),
        dead={"s0", "s1"},
    )

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]

    assert result.outcome is GateOutcome.FAIL
    assert "could not judge" in result.reason
    assert "2 dead call(s) of 6 scenario(s) (33%)" in result.reason


def test_one_dead_call_in_six_is_under_the_ceiling_and_still_judged() -> None:
    ids = [f"s{i}" for i in range(6)]
    verdict = _with_dead(
        _scores("cand", dict.fromkeys(ids, 1.0)),
        _scores("inc", dict.fromkeys(ids, 0.5)),
        _cohort([0.1] * 6, n=6),
        dead={"s0"},
    )

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]

    assert result.passed
    assert "could not judge" not in result.reason


def test_a_candidate_cannot_kill_the_corpus_down_to_a_pass() -> None:
    """The gaming case, stated as a test. A candidate that kills the provider
    on the scenarios it does badly on would otherwise shrink the comparison
    until it wins. Past the ceiling there is no comparison left to win."""
    ids = [f"s{i}" for i in range(6)]
    candidate = _scores("cand", {"s0": 1.0, "s1": 1.0, **dict.fromkeys(ids[2:], 0.0)})
    verdict = _with_dead(
        candidate,
        _scores("inc", dict.fromkeys(ids, 0.9)),
        _cohort([0.5] * 6, n=6),
        dead=set(ids[2:]),
    )

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]

    assert not result.passed
    assert "could not judge" in result.reason
    assert "4 dead call(s) of 6 scenario(s) (67%)" in result.reason


def test_a_rescued_retry_is_reported_even_though_nothing_was_excluded() -> None:
    """The retry spends a real call against somebody's quota. A silent extra
    call is how a bounded retry becomes an unbounded one nobody notices."""
    verdict = _with_dead(
        _uniform("cand", 0.9, n=4),
        _uniform("inc", 0.5, n=4),
        _cohort([0.1] * 5, n=4),
        retried={"s2"},
    )

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]

    assert result.passed
    assert any("answered on the second attempt: s2" in line for line in result.evidence)


def test_no_dead_calls_leaves_the_report_exactly_as_it_was() -> None:
    """Every replayed gate pass keeps its evidence, with the paired line
    appended and nothing removed."""
    verdict = _verdict(_uniform("cand", 0.95, n=4), _uniform("inc", 0.6, n=4), _cohort([0.5] * 6))

    result = G3Improvement(verdict=verdict).run(None)  # type: ignore[arg-type]

    assert result.evidence[: len(verdict.report)] == verdict.report
    assert not any("excluded" in line for line in result.evidence)


# --------------------------------------------------------------------------
# The paired statistic — REPORTED beside p95, never gating
# --------------------------------------------------------------------------


def _i13(name: str) -> dict[str, float]:
    """One repeat of ADR 0156's live measurement, exactly as committed."""
    payload = json.loads((I13 / name).read_text())
    return {str(k): float(v) for k, v in payload["validation"]["per_scenario"].items()}


def _pooled(label: str, arms: list[dict[str, float]], drop: str | None = None) -> ScoreSet:
    """The three repeats as one score set, keyed `<scenario>@r<n>`."""
    return ScoreSet(
        label=label,
        per_scenario={
            f"{sid}@r{r + 1}": v
            for r, arm in enumerate(arms)
            for sid, v in arm.items()
            if f"{sid}@r{r + 1}" != drop
        },
    )


def test_the_paired_line_sees_what_the_mean_could_not() -> None:
    """S2's own numbers, verbatim."""
    floor = [_i13(f"floor-r{r}.json") for r in (1, 2, 3)]
    regress = [_i13(f"regress-r{r}.json") for r in (1, 2, 3)]

    # First: the mean genuinely cannot resolve it. This is ADR 0156's verdict.
    floor_means = [sum(d.values()) / len(d) for d in floor]
    fall = sum(floor_means) / 3 - sum(sum(d.values()) / len(d) for d in regress) / 3
    assert round(sum(floor_means) / 3, 4) == 0.7639
    assert round(fall, 4) == 0.0278
    assert fall < (max(floor_means) - min(floor_means)), "inside the floor's own spread"

    paired = paired_sign_test(_pooled("regression", regress), _pooled("floor", floor))

    assert (len(paired.down), len(paired.up), len(paired.same)) == (7, 3, 8)
    assert paired.lines[0] == "paired: 7 down / 3 up / 8 same (sign test p=0.3438)"
    # The two scenarios ADR 0156 named: down in 3 of 3 repeats each.
    for sid in ("sum-17-clockmaker", "sum-18-heron-rookery"):
        assert sum(1 for d in paired.down if d.startswith(sid)) == 3
    # And the honest half, pinned so nobody reads the line as a verdict:
    # 18 pairs does not reach significance. That is why this never gates.
    assert paired.p_value > 0.05


def test_one_pass_worth_of_scenarios_is_far_too_few_to_gate_on() -> None:
    """Six scenarios is what a single G3 pass on this corpus actually sees.
    The same planted regression, per repeat, gives p = 0.625, 1, 1."""
    floor = [_i13(f"floor-r{r}.json") for r in (1, 2, 3)]
    regress = [_i13(f"regress-r{r}.json") for r in (1, 2, 3)]

    per_repeat = [
        paired_sign_test(_scores("cand", regress[r]), _scores("inc", floor[r])) for r in range(3)
    ]

    assert [round(p.p_value, 4) for p in per_repeat] == [0.625, 1.0, 1.0]
    assert all(p.p_value > 0.05 for p in per_repeat)


def test_S2s_one_dead_call_was_also_a_spurious_paired_up() -> None:
    """Where the two halves of ADR 0185 join.

    `sum-13` repeat 3 scored 0.00 because the call died (ADR 0156 established
    it from token accounting: 370 tokens against ~465). Paired against the
    regression arm's 1.00 that reads as the planted regression IMPROVING a
    scenario. Excluding the dead call removes the false 'up', and the paired
    test gets sharper rather than blunter."""
    floor = [_i13(f"floor-r{r}.json") for r in (1, 2, 3)]
    regress = [_i13(f"regress-r{r}.json") for r in (1, 2, 3)]
    dead = "sum-13-cider-press@r3"

    assert floor[2]["sum-13-cider-press"] == 0.0, "ADR 0156's transient failure"

    counted = paired_sign_test(_pooled("cand", regress), _pooled("inc", floor))
    assert dead in counted.up
    assert (len(counted.down), len(counted.up)) == (7, 3)

    excluded = paired_sign_test(
        _pooled("cand", regress, drop=dead), _pooled("inc", floor, drop=dead)
    )
    assert (len(excluded.down), len(excluded.up)) == (7, 2)
    assert round(excluded.p_value, 4) == 0.1797
    assert excluded.p_value < counted.p_value


def test_identical_arms_report_all_same() -> None:
    scores = {"s1": 1.0, "s2": 0.5, "s3": 0.0}
    paired = paired_sign_test(_scores("cand", scores), _scores("inc", dict(scores)))

    assert (len(paired.down), len(paired.up), len(paired.same)) == (0, 0, 3)
    assert paired.p_value == 1.0
    assert paired.lines == ("paired: 0 down / 0 up / 3 same (sign test p=1)",)


def test_only_scenarios_both_arms_scored_are_paired() -> None:
    """A scenario one arm never scored is not a pair. It is still caught by
    the zero-tolerance rule, which reads a missing score as a regression."""
    paired = paired_sign_test(
        _scores("cand", {"s1": 1.0, "s2": 1.0}), _scores("inc", {"s2": 0.5, "s3": 1.0})
    )
    assert (paired.down, paired.up, paired.same) == ((), ("s2",), ())


def test_the_paired_line_is_on_every_verdict_pass_or_fail() -> None:
    passing = G3Improvement(
        verdict=_verdict(_uniform("cand", 0.95), _uniform("inc", 0.6), _cohort([0.5] * 6))
    ).run(None)  # type: ignore[arg-type]
    failing = G3Improvement(
        verdict=_verdict(_uniform("cand", 0.70), _uniform("inc", 0.60), _cohort([0.85] * 6))
    ).run(None)  # type: ignore[arg-type]

    assert passing.passed and not failing.passed
    for result in (passing, failing):
        assert any(line.startswith("paired: ") for line in result.evidence)


def test_the_paired_direction_changes_no_verdict() -> None:
    """The p95 rule decides exactly as before. Two candidates with the same
    mean and opposite paired directions get the same outcome and the same
    reason string."""
    cohort = _cohort([0.5] * 6, n=4)
    incumbent = _scores("inc", dict.fromkeys(("s1", "s2", "s3", "s4"), 0.6))
    falling = _scores("cand", {"s1": 1.0, "s2": 1.0, "s3": 0.55, "s4": 0.55})
    rising = _scores("cand", dict.fromkeys(("s1", "s2", "s3", "s4"), 0.775))
    assert falling.mean == rising.mean

    assert len(paired_sign_test(falling, incumbent).down) == 2
    assert paired_sign_test(rising, incumbent).down == ()

    a = G3Improvement(verdict=_verdict(falling, incumbent, cohort)).run(None)  # type: ignore[arg-type]
    b = G3Improvement(verdict=_verdict(rising, incumbent, cohort)).run(None)  # type: ignore[arg-type]

    assert a.outcome is b.outcome is GateOutcome.PASS
    assert a.reason == b.reason
