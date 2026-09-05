"""A14 — kill the provider on the scenarios you lose.

ADR 0185 made G3 able to judge honestly under live noise: a dead model call —
the provider raised, nothing was answered — is not a wrong answer, so it is
retried once and then EXCLUDED symmetrically from candidate, incumbent and
every control. That exclusion is a strengthening, and it opens a loophole that
must be closed in the same breath.

The attack: a candidate that makes the provider die on exactly the scenarios
it does badly on shrinks the corpus until what remains is a corpus it wins.
Every excluded scenario is one fewer chance to fail, and exclusion is
symmetric, so nothing about the arithmetic objects.

The control is a refusal FLOOR: past `MAX_DEAD_FRACTION` of the scenarios G3
answers **"could not judge"** — a FAIL, and therefore an escalation, exactly
as an absent cohort is. Not a pass, and not a regression: neither would be a
statement about this candidate.

The residual is stated rather than hidden, and pinned below: a candidate can
still kill a quarter, which on six scenarios is one.
"""

from __future__ import annotations

from aef.harness.evaluation import CohortVerdict, ScoreSet
from aef.harness.gates.base import GateOutcome
from aef.harness.gates.g3_improvement import MAX_DEAD_FRACTION, G3Improvement

N = 12
LOSES = frozenset(f"s{i}" for i in range(N // 2, N))  # the half the candidate loses


def _scores(label: str, winner: bool, *, dead: frozenset[str], loses: frozenset[str]) -> ScoreSet:
    """A score set where the candidate wins everywhere except `loses` and,
    where the call died, scored a bare 0.0 in every arm."""
    values: dict[str, float] = {}
    for i in range(N):
        sid = f"s{i}"
        if sid in dead:
            values[sid] = 0.0
        elif sid in loses:
            values[sid] = 1.0 if not winner else 0.0
        else:
            values[sid] = 1.0 if winner else 0.4
    return ScoreSet(label=label, per_scenario=values, cost_tokens=100)


def _verdict(dead: frozenset[str], loses: frozenset[str] = LOSES) -> CohortVerdict:
    """The whole comparison, with `dead` scenarios marked as calls that died
    in some arm rather than as answers that scored zero."""
    return CohortVerdict(
        candidate=_scores("candidate", winner=True, dead=dead, loses=loses),
        incumbent=_scores("incumbent", winner=False, dead=dead, loses=loses),
        cohort=tuple(
            ScoreSet(
                label=f"random-{k}",
                per_scenario={f"s{i}": 0.9 for i in range(N)},
                cost_tokens=100,
            )
            for k in range(5)
        ),
        dead_scenarios=dead,
    )


def _run(verdict: CohortVerdict, **kw: object):  # type: ignore[no-untyped-def]
    return G3Improvement(verdict=verdict, **kw).run(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a14_killing_more_than_the_ceiling_is_could_not_judge(attack_log: list[str]) -> None:
    """The candidate kills the provider on every scenario it loses — half the
    corpus. G3 refuses to judge rather than judging the survivors."""
    result = _run(_verdict(LOSES))
    attack_log.append(f"{result.outcome.value}: {result.reason}")

    assert result.outcome is GateOutcome.FAIL, attack_log
    assert "could not judge" in result.reason
    assert f"{len(LOSES)} dead call(s) of {N} scenario(s)" in result.reason
    assert "ceiling" in result.reason


def test_a14_the_ceiling_is_a_fraction_not_a_count() -> None:
    """A count would be trivially evaded by a larger corpus."""
    assert 0.0 < MAX_DEAD_FRACTION < 1.0
    over = frozenset(list(LOSES)[: int(N * MAX_DEAD_FRACTION) + 1])
    assert _run(_verdict(over)).outcome is GateOutcome.FAIL


def test_a14_a_partial_kill_does_not_help_because_the_survivors_still_reject(
    attack_log: list[str],
) -> None:
    """Killing only as many as the ceiling allows buys the attacker nothing
    here: the losses it could not kill are still counted, and G3's
    zero-tolerance rule rejects on them.

    Worth running rather than reasoning about — it is the difference between
    "the floor stops this" and "the floor stops this AND the ordinary rule
    would have anyway".
    """
    under = frozenset(sorted(LOSES)[: int(N * MAX_DEAD_FRACTION)])
    result = _run(_verdict(under))
    attack_log.append(f"{len(under)} dead of {N}: {result.outcome.value} — {result.reason}")
    assert result.outcome is GateOutcome.FAIL, attack_log
    assert "could not judge" not in result.reason, attack_log
    assert any("excluded" in line for line in result.evidence), (
        f"scenarios were excluded and the evidence does not say so: {result.evidence}"
    )


def test_a14_the_residual_is_real_and_is_pinned(attack_log: list[str]) -> None:
    """The honest half, stated in ADR 0185 and asserted here so it cannot
    quietly change: a candidate that loses on no more than the ceiling's worth
    of scenarios, and kills the provider on exactly those, PASSES.

    On this 12-scenario corpus that is 3; on the real six-scenario one it is
    one. This test passing is not a defect — it is the documented boundary. If
    it starts failing, the ceiling moved and the trust case's residual-risk
    section needs re-reading.
    """
    few = frozenset(sorted(LOSES)[: int(N * MAX_DEAD_FRACTION)])
    result = _run(_verdict(few, loses=few))
    attack_log.append(f"{len(few)} dead of {N}: {result.outcome.value} — {result.reason}")
    assert result.outcome is GateOutcome.PASS, attack_log
    assert any("excluded" in line for line in result.evidence), (
        f"the exclusion happened and was not named in the evidence: {result.evidence}"
    )


def test_a14_a_clean_run_is_judged_normally() -> None:
    """The control for the control: with nothing dead, the floor is silent."""
    result = _run(_verdict(frozenset()))
    assert "could not judge" not in result.reason


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a14_the_control_is_load_bearing(attack_log: list[str]) -> None:
    """Raise the ceiling to 1.0 — the only knob — and the same candidate,
    having killed the provider on every scenario it loses, PASSES.

    The candidate's own numbers never change. What changes is which scenarios
    it is judged on, and the whole attack is that it chose them.
    """
    verdict = _verdict(LOSES)
    guarded = _run(verdict)
    unguarded = _run(verdict, max_dead_fraction=1.0)
    attack_log.append(
        f"ceiling {MAX_DEAD_FRACTION}: {guarded.outcome.value} — {guarded.reason}\n"
        f"ceiling 1.0: {unguarded.outcome.value} — {unguarded.reason}"
    )

    assert guarded.outcome is GateOutcome.FAIL, attack_log
    assert unguarded.outcome is GateOutcome.PASS, (
        "the candidate does not win on the survivors, so the floor is not what stopped it "
        f"and this attack proves nothing: {attack_log}"
    )
