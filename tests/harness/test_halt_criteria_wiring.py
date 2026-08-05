"""Two of the five halt criteria were dead parameters.

`assess_halt` accepts `drift_exhausted_twice` and
`consecutive_escalation_rejections`, is called from exactly two places, and
**neither ever computed them** — while the ledger held the evidence for both
all along. Same shape as ADR 0065's reflection wire: a correct function with
no caller supplying its input (found in ADR 0074, fixed in ADR 0077).

Each detector is exercised against planted faults in both directions. A
detector trusted only on the case it was written for is how ADR 0063 and
ADR 0073 both shipped false negatives.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aef.harness import ledger
from aef.harness.loop import _consecutive_escalation_rejections, _drift_exhausted_twice

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
GATED = ledger.EventKind.GATED
REJECTED = ledger.EventKind.REJECTED
ESCALATED = ledger.EventKind.ESCALATED
MERGED = ledger.EventKind.MERGED


def _ledger(root: Path, events: list[tuple[ledger.EventKind, str, dict]]):  # type: ignore[type-arg]
    for i, (kind, proposal_id, detail) in enumerate(events):
        ledger.append(
            root,
            kind=kind,
            at=NOW + timedelta(minutes=i),
            proposal_id=proposal_id,
            summary="s",
            detail=detail,
        )
    return ledger.read(root)


def _g5(outcome: str, reason: str) -> dict:  # type: ignore[type-arg]
    return {"gates": [{"gate": "G5", "outcome": outcome, "reason": reason}]}


_DRIFT = "cumulative drift 0.900 exceeds the budget of 0.500 — accumulated past the baseline"
_NO_BASELINE = "no owner-blessed baseline to measure drift against"


def test_two_consecutive_drift_failures_halt(tmp_path: Path) -> None:
    entries = _ledger(
        tmp_path, [(GATED, "a", _g5("fail", _DRIFT)), (GATED, "b", _g5("fail", _DRIFT))]
    )
    assert _drift_exhausted_twice(entries)


def test_a_single_drift_failure_does_not_halt(tmp_path: Path) -> None:
    assert not _drift_exhausted_twice(_ledger(tmp_path, [(GATED, "a", _g5("fail", _DRIFT))]))


def test_an_intervening_pass_resets_the_drift_criterion(tmp_path: Path) -> None:
    """ "In quick succession" means the proposer is not responding to the
    signal. One that exhausted the budget, adjusted, and exhausted it again
    later is not the same failure."""
    entries = _ledger(
        tmp_path, [(GATED, "a", _g5("fail", _DRIFT)), (GATED, "b", _g5("pass", "fine"))]
    )
    assert not _drift_exhausted_twice(entries)


def test_a_g5_failure_that_is_not_about_drift_does_not_count(tmp_path: Path) -> None:
    """G5 also fails when no baseline has been blessed — the state EVERY
    fresh adopter starts in. Counting that as drift exhaustion would halt
    the loop on the second run of every new repo."""
    entries = _ledger(
        tmp_path,
        [(GATED, "a", _g5("fail", _NO_BASELINE)), (GATED, "b", _g5("fail", _NO_BASELINE))],
    )
    assert not _drift_exhausted_twice(entries)


def test_consecutive_escalation_rejections_are_counted(tmp_path: Path) -> None:
    entries = _ledger(
        tmp_path,
        [(ESCALATED, "a", {}), (REJECTED, "a", {}), (ESCALATED, "b", {}), (REJECTED, "b", {})],
    )
    assert _consecutive_escalation_rejections(entries) == 2


def test_an_acceptance_resets_the_escalation_run(tmp_path: Path) -> None:
    """The criterion is about a proposer that keeps working outside its
    evidence base, not a lifetime total."""
    entries = _ledger(
        tmp_path,
        [
            (ESCALATED, "a", {}),
            (REJECTED, "a", {}),
            (MERGED, "m", {"archive_version": 1}),
            (ESCALATED, "b", {}),
            (REJECTED, "b", {}),
        ],
    )
    assert _consecutive_escalation_rejections(entries) == 1


def test_a_rejection_that_never_escalated_does_not_count(tmp_path: Path) -> None:
    entries = _ledger(tmp_path, [(REJECTED, "a", {}), (REJECTED, "b", {})])
    assert _consecutive_escalation_rejections(entries) == 0


def test_the_gate_acts_on_both_criteria() -> None:
    """Computing them and not halting on them would be the same defect one
    step further along."""
    import inspect

    from aef.harness.loop import gate

    source = inspect.getsource(gate)
    assert "_drift_exhausted_twice(history)" in source
    assert "_consecutive_escalation_rejections(history)" in source
    assert "if assessment.should_halt:" in source


# --------------------------------------------------------------------------
# ADR 0080 — criterion 4 was a lifetime counter with an unreachable reset
# --------------------------------------------------------------------------


def test_ordinary_rejections_break_the_escalation_run(tmp_path: Path) -> None:
    """The first implementation only reset on MERGED, which is written solely
    on the auto-merge path — and Tier-1 is off. So nothing reset it from the
    CLI: two re-gated proposals thirty days apart, with twenty ordinary
    rejections between them, halted the loop for "working outside its
    evidence base"."""
    entries = _ledger(
        tmp_path,
        [
            (ESCALATED, "a", {}),
            (REJECTED, "a", {}),
            (REJECTED, "x", {}),
            (REJECTED, "y", {}),
            (ESCALATED, "b", {}),
            (REJECTED, "b", {}),
        ],
    )
    assert _consecutive_escalation_rejections(entries) == 1


def test_an_open_escalation_at_the_tail_is_not_a_rejection(tmp_path: Path) -> None:
    """Escalation is the NORMAL terminal state while Tier-1 is off, so the
    criterion has to be about a trailing pattern or it is about nothing."""
    entries = _ledger(tmp_path, [(ESCALATED, "a", {}), (REJECTED, "a", {}), (ESCALATED, "b", {})])
    assert _consecutive_escalation_rejections(entries) == 0


def test_three_consecutive_are_counted(tmp_path: Path) -> None:
    entries = _ledger(
        tmp_path,
        [
            (ESCALATED, "a", {}),
            (REJECTED, "a", {}),
            (ESCALATED, "b", {}),
            (REJECTED, "b", {}),
            (ESCALATED, "c", {}),
            (REJECTED, "c", {}),
        ],
    )
    assert _consecutive_escalation_rejections(entries) == 3
