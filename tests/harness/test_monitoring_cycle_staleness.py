"""The metric that would have caught a scheduled loop doing nothing.

ADR 0165. This repo's own `.github/workflows/loop-monitor.yml` ran `aef loop
cycle` nightly with no `--memory`, so the cycle printed "no memory store
configured: nothing to learn from, no candidate" and exited 0 — every night
since the workflow was written, and nothing anywhere said so.

The property under test is the awkward one: **the ledger alone cannot
distinguish a loop that has never run from a loop that has run 180 times and
produced nothing**, because `cycle` writes a ledger entry only when it
proposes. So the alarm cannot be built from the ledger's silence; it needs a
record of the attempts, which is what the cycle journal is.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aef.harness.ledger import EventKind, LedgerEntry
from aef.harness.monitoring import (
    CycleAttempt,
    assess_cycle_staleness,
    read_cycle_attempts,
    record_cycle_attempt,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _entry(kind: EventKind, days_ago: float) -> LedgerEntry:
    return LedgerEntry(
        sequence=0,
        kind=kind,
        at=NOW - timedelta(days=days_ago),
        proposal_id="p1",
        summary="s",
    )


def _quiet(n: int, *, verdict: str = "no memory store configured") -> tuple[CycleAttempt, ...]:
    return tuple(
        CycleAttempt(at=NOW - timedelta(days=n - i), proposed=False, verdict=verdict)
        for i in range(n)
    )


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------


def test_an_attempt_round_trips(tmp_path: Path) -> None:
    record_cycle_attempt(tmp_path / "state", at=NOW, proposed=False, verdict="no candidate")
    (attempt,) = read_cycle_attempts(tmp_path / "state")
    assert attempt.at == NOW
    assert attempt.proposed is False
    assert attempt.verdict == "no candidate"


def test_attempts_accumulate_in_order(tmp_path: Path) -> None:
    state = tmp_path / "state"
    for i in range(3):
        record_cycle_attempt(state, at=NOW + timedelta(days=i), proposed=i == 2, verdict=f"v{i}")
    attempts = read_cycle_attempts(state)
    assert [a.verdict for a in attempts] == ["v0", "v1", "v2"]
    assert [a.proposed for a in attempts] == [False, False, True]


def test_no_journal_is_no_attempts_not_an_error(tmp_path: Path) -> None:
    assert read_cycle_attempts(tmp_path / "never-written") == ()


def test_a_corrupt_line_does_not_take_the_monitor_dark(tmp_path: Path) -> None:
    """Opposite of `FileMemoryStore`, deliberately. A memory file that
    silently drops records gives the proposer less evidence than it thinks it
    has, so it raises. This is a monitoring signal, and a monitor that refuses
    to report because one line is corrupt goes dark exactly when something is
    wrong."""
    state = tmp_path / "state"
    record_cycle_attempt(state, at=NOW, proposed=False, verdict="first")
    with (state / "cycles.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    record_cycle_attempt(state, at=NOW, proposed=True, verdict="third")

    assert [a.verdict for a in read_cycle_attempts(state)] == ["first", "third"]


# ---------------------------------------------------------------------------
# The ages
# ---------------------------------------------------------------------------


def test_it_reports_days_since_the_last_proposed_and_the_last_accepted() -> None:
    result = assess_cycle_staleness(
        (_entry(EventKind.PROPOSED, 4.0), _entry(EventKind.KEPT, 9.0)),
        _quiet(1),
        now=NOW,
    )
    assert result.days_since_last_proposed == 4.0
    assert result.days_since_last_accepted == 9.0
    assert "last PROPOSED: 4.0 day(s) ago" in result.lines()
    assert "last KEPT/MERGED: 9.0 day(s) ago" in result.lines()


def test_merged_counts_as_accepted_alongside_kept() -> None:
    """`KEPT` is `aef loop run` advancing its local branch (ADR 0114) and
    `MERGED` is Tier-1, which is off. Either means a candidate survived every
    gate, which is the thing being aged."""
    result = assess_cycle_staleness((_entry(EventKind.MERGED, 2.0),), _quiet(1), now=NOW)
    assert result.days_since_last_accepted == 2.0


def test_a_rejection_is_not_an_acceptance() -> None:
    result = assess_cycle_staleness((_entry(EventKind.REJECTED, 1.0),), _quiet(1), now=NOW)
    assert result.days_since_last_accepted is None
    assert "last KEPT/MERGED: never" in result.lines()


def test_the_most_recent_of_several_is_the_one_aged() -> None:
    result = assess_cycle_staleness(
        (_entry(EventKind.PROPOSED, 30.0), _entry(EventKind.PROPOSED, 2.0)),
        _quiet(1),
        now=NOW,
    )
    assert result.days_since_last_proposed == 2.0


# ---------------------------------------------------------------------------
# The warning — THE regression test for ADR 0165
# ---------------------------------------------------------------------------


def test_a_loop_that_runs_and_proposes_nothing_is_named() -> None:
    result = assess_cycle_staleness((), _quiet(3), now=NOW)

    assert result.cycles_run == 3
    assert result.cycles_since_last_proposal == 3
    assert result.warning is not None
    assert "SCHEDULED CYCLE PRODUCING NOTHING" in result.warning
    # The reason, in the cycle's own words, not a generic complaint.
    assert "no memory store configured" in result.warning
    assert any("SCHEDULED CYCLE PRODUCING NOTHING" in line for line in result.lines())


def test_the_ledger_alone_cannot_tell_the_two_cases_apart() -> None:
    """THE reason the journal exists. A loop that produces nothing writes no
    ledger entries, so its ledger is byte-identical to one nobody has run —
    and a missing signal cannot be the alarm."""
    never_run = assess_cycle_staleness((), (), now=NOW)
    ran_and_produced_nothing = assess_cycle_staleness((), _quiet(5), now=NOW)

    # Same ledger. Different verdicts, and only because of the journal.
    assert never_run.warning is None, "an unstarted loop is not stale, it is unstarted"
    assert ran_and_produced_nothing.warning is not None


def test_one_quiet_night_is_not_an_alarm() -> None:
    assert assess_cycle_staleness((), _quiet(1), now=NOW).warning is None
    assert assess_cycle_staleness((), _quiet(2), now=NOW).warning is None
    assert assess_cycle_staleness((), _quiet(3), now=NOW).warning is not None


def test_a_proposal_resets_the_run_of_quiet_cycles() -> None:
    attempts = (
        *_quiet(3),
        CycleAttempt(at=NOW, proposed=True, verdict="proposed c1"),
    )
    result = assess_cycle_staleness((), attempts, now=NOW)
    assert result.cycles_since_last_proposal == 0
    assert result.warning is None


def test_only_the_trailing_run_of_quiet_cycles_counts() -> None:
    """Nine quiet cycles a month ago followed by a proposal and one quiet
    night is a healthy loop, not a broken one."""
    attempts = (
        *_quiet(9),
        CycleAttempt(at=NOW - timedelta(days=2), proposed=True, verdict="proposed c1"),
        CycleAttempt(at=NOW, proposed=False, verdict="no admissible failure memory"),
    )
    result = assess_cycle_staleness((), attempts, now=NOW)
    assert result.cycles_run == 11
    assert result.cycles_since_last_proposal == 1
    assert result.warning is None


def test_the_threshold_is_a_parameter_not_a_constant() -> None:
    assert assess_cycle_staleness((), _quiet(2), now=NOW, quiet_cycles=2).warning is not None
    assert assess_cycle_staleness((), _quiet(9), now=NOW, quiet_cycles=10).warning is None
