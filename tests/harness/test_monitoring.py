"""Post-merge monitoring, auto-rollback, kill switch, digest.

M10's acceptance properties. Two matter most:

  - an AMBIGUOUS signal rolls back, it does not wait for more data
  - a rollback of a change every gate passed HALTS the loop

Both are places where the comfortable behaviour is the wrong one.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aef.harness.ledger import EventKind, LedgerEntry
from aef.harness.monitoring import (
    Action,
    Digest,
    KillSwitch,
    LoopHaltedError,
    MonitorPolicy,
    Observation,
    Verdict,
    assess_halt,
    build_digest,
    evaluate_window,
)

MERGED_AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _runs(n: int, *, passed: int, offset_h: int = 1) -> tuple[Observation, ...]:
    return tuple(
        Observation(at=MERGED_AT + timedelta(hours=offset_h + i), passed=i < passed)
        for i in range(n)
    )


def _evaluate(
    observations: tuple[Observation, ...],
    *,
    baseline: float = 0.9,
    now: datetime | None = None,
    policy: MonitorPolicy | None = None,
):
    return evaluate_window(
        observations,
        baseline_pass_rate=baseline,
        merged_at=MERGED_AT,
        now=now or MERGED_AT + timedelta(hours=2),
        policy=policy,
    )


# --------------------------------------------------------------------------
# Healthy and regressed
# --------------------------------------------------------------------------


def test_a_healthy_window_keeps_the_change() -> None:
    result = _evaluate(_runs(20, passed=19))
    assert result.verdict is Verdict.HEALTHY
    assert result.action is Action.KEEP
    assert result.settled


def test_a_regression_rolls_back() -> None:
    result = _evaluate(_runs(20, passed=10))
    assert result.verdict is Verdict.REGRESSED
    assert result.action is Action.ROLLBACK
    assert "below the pre-merge baseline" in result.reason


def test_a_regression_is_detected_before_the_window_fills() -> None:
    # Waiting for a full window while a known regression runs live would be
    # the monitoring system choosing tidiness over the thing it exists for.
    result = _evaluate(_runs(5, passed=0))
    assert result.verdict is Verdict.REGRESSED
    assert result.action is Action.ROLLBACK


def test_a_difference_inside_the_margin_is_not_a_regression() -> None:
    result = _evaluate(_runs(20, passed=18), baseline=0.9)  # 0.90 vs 0.90
    assert result.verdict is Verdict.HEALTHY


# --------------------------------------------------------------------------
# M10 ACCEPTANCE — ambiguity rolls back
# --------------------------------------------------------------------------


def test_an_unsettled_window_keeps_but_never_reports_healthy() -> None:
    result = _evaluate(_runs(3, passed=3))
    assert result.verdict is Verdict.AMBIGUOUS
    assert result.action is Action.KEEP  # still collecting
    assert not result.settled


def test_a_settled_but_underobserved_window_rolls_back() -> None:
    """THE rollback-by-default test. Reverting a good change costs one
    re-proposal; keeping a bad one compounds through every merge built on
    top of it."""
    result = _evaluate(_runs(3, passed=3), now=MERGED_AT + timedelta(days=8))
    assert result.verdict is Verdict.AMBIGUOUS
    assert result.action is Action.ROLLBACK
    assert "reverts" in result.reason


def test_a_window_that_closed_with_no_runs_at_all_rolls_back() -> None:
    # Absence of evidence is not health.
    result = _evaluate((), now=MERGED_AT + timedelta(days=8))
    assert result.verdict is Verdict.AMBIGUOUS
    assert result.action is Action.ROLLBACK
    assert result.observed_pass_rate is None


def test_no_runs_yet_is_not_reported_as_healthy() -> None:
    result = _evaluate(())
    assert result.verdict is not Verdict.HEALTHY


def test_observations_outside_the_window_are_ignored() -> None:
    stale = (Observation(at=MERGED_AT + timedelta(days=30), passed=False),)
    assert _evaluate(stale).observations == 0


def test_observations_before_the_merge_are_ignored() -> None:
    earlier = (Observation(at=MERGED_AT - timedelta(hours=1), passed=False),)
    assert _evaluate(earlier).observations == 0


@pytest.mark.parametrize("value", [-0.1, 1.0, 1.5])
def test_an_invalid_regression_margin_is_refused(value: float) -> None:
    with pytest.raises(ValueError, match="regression_margin"):
        MonitorPolicy(regression_margin=value)


def test_a_zero_observation_requirement_is_refused() -> None:
    with pytest.raises(ValueError, match="min_observations"):
        MonitorPolicy(min_observations=0)


# --------------------------------------------------------------------------
# M10 ACCEPTANCE — a gated rollback halts the loop
# --------------------------------------------------------------------------


def test_a_regression_rollback_halts_the_loop() -> None:
    """Every gate passed and it still regressed, so the gates have a blind
    spot. Continuing to merge through a known blind spot is the failure."""
    assert _evaluate(_runs(20, passed=5)).halts_loop


def test_an_ambiguity_rollback_does_not_by_itself_halt_the_loop() -> None:
    # Not enough evidence is not the same as evidence the gates were wrong.
    result = _evaluate(_runs(3, passed=3), now=MERGED_AT + timedelta(days=8))
    assert result.action is Action.ROLLBACK
    assert not result.halts_loop


def test_the_halt_assessment_names_every_criterion_that_fired() -> None:
    assessment = assess_halt(
        gated_rollback=True,
        zone_violation=True,
        drift_exhausted_twice=True,
        consecutive_escalation_rejections=2,
    )
    assert assessment.should_halt
    assert len(assessment.reasons) == 4


def test_a_clean_state_does_not_halt() -> None:
    assert not assess_halt().should_halt


def test_one_escalation_rejection_does_not_halt() -> None:
    assert not assess_halt(consecutive_escalation_rejections=1).should_halt


def test_no_measurable_benefit_halts_the_program() -> None:
    # Halt criterion 5: cost without benefit, regardless of safety.
    digest = Digest(since=MERGED_AT, until=MERGED_AT, proposed=10, merged=1, owner_edits=9)
    assessment = assess_halt(digest=digest)
    assert assessment.should_halt
    assert "cost without benefit" in assessment.reasons[0]


# --------------------------------------------------------------------------
# Kill switch
# --------------------------------------------------------------------------


def test_the_kill_switch_starts_disengaged(tmp_path: Path) -> None:
    switch = KillSwitch(root=tmp_path)
    assert not switch.engaged
    switch.check()  # does not raise


def test_engaging_the_kill_switch_halts_and_raises(tmp_path: Path) -> None:
    switch = KillSwitch(root=tmp_path)
    switch.engage("gates have a blind spot")

    assert switch.engaged
    with pytest.raises(LoopHaltedError, match="blind spot"):
        switch.check()


def test_the_kill_switch_is_a_plain_file_the_owner_can_create(tmp_path: Path) -> None:
    # The owner must be able to stop the loop without the loop's cooperation,
    # from a shell, under stress, without reading documentation.
    (tmp_path / "HALTED").write_text("stopped by hand\n")
    with pytest.raises(LoopHaltedError, match="stopped by hand"):
        KillSwitch(root=tmp_path).check()


def test_the_halt_message_says_how_to_resume(tmp_path: Path) -> None:
    switch = KillSwitch(root=tmp_path)
    switch.engage("reason")
    with pytest.raises(LoopHaltedError, match="deliberate act"):
        switch.check()


def test_releasing_the_kill_switch_resumes(tmp_path: Path) -> None:
    switch = KillSwitch(root=tmp_path)
    switch.engage("reason")
    switch.release()
    switch.check()


def test_an_engaged_switch_with_no_reason_still_halts(tmp_path: Path) -> None:
    (tmp_path / "HALTED").write_text("")
    with pytest.raises(LoopHaltedError, match="no reason recorded"):
        KillSwitch(root=tmp_path).check()


# --------------------------------------------------------------------------
# The digest
# --------------------------------------------------------------------------


def _entry(seq: int, kind: EventKind, **detail: object) -> LedgerEntry:
    return LedgerEntry(
        sequence=seq,
        kind=kind,
        at=MERGED_AT,
        proposal_id=f"p{seq}",
        summary="",
        detail=dict(detail),
    )


def test_the_digest_counts_every_event_kind() -> None:
    entries = (
        _entry(1, EventKind.PROPOSED),
        _entry(2, EventKind.PROPOSED),
        _entry(3, EventKind.MERGED),
        _entry(4, EventKind.REJECTED),
        _entry(5, EventKind.ESCALATED),
        _entry(6, EventKind.ROLLED_BACK),
    )
    digest = build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7))

    assert digest.proposed == 2
    assert digest.merged == 1
    assert digest.rejected == 1
    assert digest.escalated == 1
    assert digest.rolled_back == 1
    assert digest.net_accepted == 0


def test_events_outside_the_period_are_excluded() -> None:
    entries = (_entry(1, EventKind.MERGED),)
    digest = build_digest(
        entries, since=MERGED_AT + timedelta(days=1), until=MERGED_AT + timedelta(days=7)
    )
    assert digest.merged == 0


def test_a_security_event_is_surfaced_prominently() -> None:
    entries = (_entry(1, EventKind.REJECTED, security_event=True),)
    digest = build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7))
    assert digest.security_events == 1
    assert "reached for the harness" in digest.render()


def test_the_digest_reports_whether_the_loop_beats_manual_editing() -> None:
    # 05 §6 halt criterion 5 needs this number, so a digest that cannot say
    # it is a status page rather than an oversight surface.
    winning = Digest(since=MERGED_AT, until=MERGED_AT, merged=9, owner_edits=2)
    losing = Digest(since=MERGED_AT, until=MERGED_AT, merged=1, owner_edits=8)

    assert winning.beating_manual_editing is True
    assert losing.beating_manual_editing is False
    assert "NO — the loop is not out-performing" in losing.render()


def test_a_loop_that_did_nothing_does_not_report_as_winning() -> None:
    # Defaulting to True would make a loop that achieves nothing look like a
    # loop that is succeeding.
    idle = Digest(since=MERGED_AT, until=MERGED_AT)
    assert idle.beating_manual_editing is None
    assert "n/a" in idle.render()


def test_rollbacks_are_netted_out_of_the_accepted_count() -> None:
    digest = Digest(since=MERGED_AT, until=MERGED_AT, proposed=10, merged=5, rolled_back=4)
    assert digest.net_accepted == 1
    assert digest.acceptance_rate == pytest.approx(0.5)


def test_the_acceptance_rate_is_none_when_nothing_was_proposed() -> None:
    assert Digest(since=MERGED_AT, until=MERGED_AT).acceptance_rate is None
    assert "n/a" in Digest(since=MERGED_AT, until=MERGED_AT).render()


def test_the_digest_serialises_to_json() -> None:
    import json

    digest = Digest(since=MERGED_AT, until=MERGED_AT, proposed=3, merged=1)
    payload = json.loads(digest.to_json())
    assert payload["proposed"] == 3
    assert payload["acceptance_rate"] == pytest.approx(1 / 3)


def test_the_digest_reports_drift_and_scenarios_added() -> None:
    digest = build_digest((), since=MERGED_AT, until=MERGED_AT, drift=0.42, scenarios_added=3)
    rendered = digest.render()
    assert "0.420" in rendered
    assert "Scenarios added to the corpus: 3" in rendered


# --------------------------------------------------------------------------
# An uncontained shadow is a security event, not an attack (ADR 0167)
#
# `render()` printed `**A proposal reached for the harness. Read the ledger.**`
# for any ledger entry carrying `security_event: True`, whatever wrote it. So
# S5's containment FALLBACK — no Docker on the runner, or an owner who wrote
# `containment: off` — was reported to that owner every Monday as an attack.
# An alarm that fires on the normal case is an alarm nobody reads, which is
# the same argument ADR 0165 makes for not warning about an unstarted loop.
# --------------------------------------------------------------------------


def test_a_containment_event_is_not_reported_as_a_proposal_reaching_the_harness() -> None:
    entries = (
        _entry(
            1,
            EventKind.CONTAINMENT,
            security_event=True,
            reason="no container runtime found (docker/podman)",
        ),
    )
    digest = build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7))
    rendered = digest.render()

    # Still a security event — the candidate was NOT contained and the owner
    # must know. Only the sentence changes.
    assert digest.security_events == 1
    assert digest.containment_events == 1
    assert "- Security events: 1" in rendered

    assert "reached for the harness" not in rendered, rendered
    assert "**Shadow runs were not contained.**" in rendered
    assert "- shadow ran uncontained: no container runtime found (docker/podman)" in rendered, (
        rendered
    )


def test_a_real_security_event_still_says_a_proposal_reached_for_the_harness() -> None:
    """The control. A guard that silenced the sentence for every event would
    be the alarm removed rather than the alarm fixed."""
    entries = (
        _entry(1, EventKind.REJECTED, security_event=True),
        _entry(2, EventKind.CONTAINMENT, security_event=True, reason="containment: off"),
    )
    rendered = build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7)).render()

    assert "reached for the harness" in rendered
    assert "- shadow ran uncontained: containment: off" in rendered


def test_a_containment_event_with_no_reason_still_renders_one_line() -> None:
    entries = (_entry(1, EventKind.CONTAINMENT, security_event=True),)
    rendered = build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7)).render()
    assert "- shadow ran uncontained: no reason recorded" in rendered


def test_repeated_containment_reasons_are_reported_once() -> None:
    entries = tuple(
        _entry(i, EventKind.CONTAINMENT, security_event=True, reason="containment: off")
        for i in range(1, 4)
    )
    digest = build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7))
    assert digest.containment_events == 3
    assert digest.render().count("- shadow ran uncontained:") == 1


def test_the_containment_count_reaches_the_json() -> None:
    import json

    entries = (_entry(1, EventKind.CONTAINMENT, security_event=True, reason="containment: off"),)
    payload = json.loads(
        build_digest(entries, since=MERGED_AT, until=MERGED_AT + timedelta(days=7)).to_json()
    )
    assert payload["security_events"] == 1
    assert payload["containment_events"] == 1
    assert payload["containment_reasons"] == ["containment: off"]
