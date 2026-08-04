"""Post-merge monitoring, auto-rollback, the kill switch, and the digest.

ADR 0045 removed the human from the merge path. These four mechanisms are
what replaced them, and they are **load-bearing rather than optional**:
until this module exists, Tier-1 auto-merge must stay off, because an
auto-merge with nothing watching afterwards is unobserved in both
directions.

Three rules here are not the obvious ones.

**Ambiguity rolls back.** When the signal is unclear — too few observations,
or a difference inside the noise — the change is reverted, not held pending
more data. Reverting a good change costs one re-proposal; keeping a bad one
compounds through every subsequent merge that builds on it. "Wait and see"
is the option that quietly accumulates risk, so it is not offered.

**A rollback triggered by something the gates passed halts the loop.** It
means the gates have a blind spot. Continuing to merge through a known blind
spot is how a system with good local decisions ends up somewhere bad, and
the halt is what turns one bad merge into a bounded incident.

**The digest reports whether the loop is worth running at all.** Not only
whether it is safe. `05-approval-policy.md` §6 lists "no measurable benefit
over the owner editing code directly" as a halt criterion, and a digest that
cannot say so is a status page rather than an oversight surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from aef.harness.ledger import EventKind, LedgerEntry

# Q-A2 owner default: long enough to see real traffic variety.
DEFAULT_MIN_OBSERVATIONS = 20
DEFAULT_WINDOW = timedelta(days=7)
# A regression this size is acted on; below it, the difference is noise at
# these sample sizes and is treated as ambiguous rather than as evidence.
DEFAULT_REGRESSION_MARGIN = 0.05

KILL_SWITCH_FILENAME = "HALTED"


class Verdict(StrEnum):
    HEALTHY = "healthy"
    REGRESSED = "regressed"
    AMBIGUOUS = "ambiguous"


class Action(StrEnum):
    KEEP = "keep"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class Observation:
    """One live run after a merge."""

    at: datetime
    passed: bool
    cost_tokens: int = 0


@dataclass(frozen=True)
class MonitorPolicy:
    window: timedelta = DEFAULT_WINDOW
    min_observations: int = DEFAULT_MIN_OBSERVATIONS
    regression_margin: float = DEFAULT_REGRESSION_MARGIN

    def __post_init__(self) -> None:
        if self.min_observations < 1:
            raise ValueError("min_observations must be at least 1")
        if not 0.0 <= self.regression_margin < 1.0:
            raise ValueError("regression_margin must be within [0.0, 1.0)")


@dataclass(frozen=True)
class MonitorResult:
    verdict: Verdict
    action: Action
    reason: str
    observed_pass_rate: float | None
    baseline_pass_rate: float
    observations: int
    settled: bool

    @property
    def halts_loop(self) -> bool:
        """A rollback of a change every gate passed means the gates have a
        blind spot, and merging on through it is the failure this halts."""
        return self.action is Action.ROLLBACK and self.verdict is Verdict.REGRESSED


def evaluate_window(
    observations: list[Observation] | tuple[Observation, ...],
    *,
    baseline_pass_rate: float,
    merged_at: datetime,
    now: datetime,
    policy: MonitorPolicy | None = None,
) -> MonitorResult:
    """Judge one merged change from its live runs."""
    policy = policy or MonitorPolicy()
    in_window = [o for o in observations if merged_at <= o.at <= merged_at + policy.window]
    count = len(in_window)
    settled = count >= policy.min_observations or now >= merged_at + policy.window

    if count == 0:
        return MonitorResult(
            verdict=Verdict.AMBIGUOUS,
            # Not yet settled, so nothing is rolled back — but the verdict is
            # ambiguous, never "healthy". Absence of evidence is not health.
            action=Action.ROLLBACK if settled else Action.KEEP,
            reason=(
                "no live runs observed yet"
                if not settled
                else "the window closed with no live runs at all — nothing can be concluded, "
                "so the change reverts rather than persisting unverified"
            ),
            observed_pass_rate=None,
            baseline_pass_rate=baseline_pass_rate,
            observations=0,
            settled=settled,
        )

    observed = sum(1 for o in in_window if o.passed) / count

    if observed < baseline_pass_rate - policy.regression_margin:
        return MonitorResult(
            verdict=Verdict.REGRESSED,
            action=Action.ROLLBACK,
            reason=(
                f"live pass rate {observed:.3f} is below the pre-merge baseline "
                f"{baseline_pass_rate:.3f} by more than {policy.regression_margin:.3f}"
            ),
            observed_pass_rate=observed,
            baseline_pass_rate=baseline_pass_rate,
            observations=count,
            settled=settled,
        )

    if count < policy.min_observations:
        return MonitorResult(
            verdict=Verdict.AMBIGUOUS,
            # Rollback-by-default: reverting a good change costs one
            # re-proposal; keeping a bad one compounds through every merge
            # built on top of it.
            action=Action.ROLLBACK if settled else Action.KEEP,
            reason=(
                f"only {count} of {policy.min_observations} observations"
                + (
                    "; the window closed without enough evidence, so the change reverts"
                    if settled
                    else "; still collecting"
                )
            ),
            observed_pass_rate=observed,
            baseline_pass_rate=baseline_pass_rate,
            observations=count,
            settled=settled,
        )

    return MonitorResult(
        verdict=Verdict.HEALTHY,
        action=Action.KEEP,
        reason=(
            f"live pass rate {observed:.3f} holds against the baseline "
            f"{baseline_pass_rate:.3f} over {count} run(s)"
        ),
        observed_pass_rate=observed,
        baseline_pass_rate=baseline_pass_rate,
        observations=count,
        settled=True,
    )


# --------------------------------------------------------------------------
# Kill switch
# --------------------------------------------------------------------------


class LoopHaltedError(RuntimeError):
    """The loop is halted. Raised rather than returned so no caller can
    proceed by ignoring a return value."""


@dataclass(frozen=True)
class KillSwitch:
    """A file, deliberately. The owner must be able to stop the loop without
    the loop's cooperation, from a shell, under stress, without reading
    documentation — so the mechanism is `touch <root>/HALTED`, and the loop
    checks it before doing anything rather than reporting it afterwards."""

    root: Path

    @property
    def path(self) -> Path:
        return self.root / KILL_SWITCH_FILENAME

    @property
    def engaged(self) -> bool:
        return self.path.is_file()

    @property
    def reason(self) -> str:
        return self.path.read_text().strip() if self.engaged else ""

    def engage(self, reason: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason.strip() + "\n")

    def release(self) -> None:
        """Owner-only by convention and by consequence: nothing in the
        harness calls this. Restarting after a halt is a decision, and a loop
        that could clear its own halt has no halt."""
        self.path.unlink(missing_ok=True)

    def check(self) -> None:
        if self.engaged:
            raise LoopHaltedError(
                f"the self-rewiring loop is halted: {self.reason or '(no reason recorded)'}. "
                f"Remove {self.path} to resume — a deliberate act, not an automatic one."
            )


# --------------------------------------------------------------------------
# The digest
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Digest:
    """The owner's real oversight surface: trends, not diffs."""

    since: datetime
    until: datetime
    proposed: int = 0
    merged: int = 0
    rejected: int = 0
    escalated: int = 0
    rolled_back: int = 0
    halts: int = 0
    security_events: int = 0
    scenarios_added: int = 0
    drift: float = 0.0
    owner_edits: int = 0

    @property
    def acceptance_rate(self) -> float | None:
        return (self.merged / self.proposed) if self.proposed else None

    @property
    def net_accepted(self) -> int:
        return self.merged - self.rolled_back

    @property
    def beating_manual_editing(self) -> bool | None:
        """Whether the loop is delivering more accepted change than the owner
        editing code directly.

        `None` when there is nothing to compare — reported honestly rather
        than defaulting to `True`, which would make a loop that does nothing
        look like a loop that is winning.
        """
        if self.owner_edits == 0 and self.net_accepted == 0:
            return None
        return self.net_accepted > self.owner_edits

    def render(self) -> str:
        rate = (
            f"{self.acceptance_rate:.0%}"
            if self.acceptance_rate is not None
            else "n/a (none proposed)"
        )
        benefit = {
            None: "n/a — nothing to compare yet",
            True: "yes",
            False: "NO — the loop is not out-performing manual editing",
        }[self.beating_manual_editing]

        lines = [
            f"# Self-rewiring digest, {self.since:%Y-%m-%d} to {self.until:%Y-%m-%d}",
            "",
            f"- Proposed: {self.proposed}",
            f"- Merged: {self.merged} (acceptance rate {rate})",
            f"- Rolled back: {self.rolled_back} — net accepted {self.net_accepted}",
            f"- Rejected: {self.rejected}",
            f"- Escalated to you: {self.escalated}",
            f"- Security events: {self.security_events}",
            f"- Halts: {self.halts}",
            f"- Scenarios added to the corpus: {self.scenarios_added}",
            f"- Drift from the blessed baseline: {self.drift:.3f}",
            f"- Out-performing you editing code directly: {benefit}",
        ]
        if self.security_events:
            lines += ["", "**A proposal reached for the harness. Read the ledger.**"]
        if self.beating_manual_editing is False:
            lines += [
                "",
                "Halt criterion 5 (`05-approval-policy.md` §6): no measurable benefit over "
                "editing directly. The program should stop for cost-benefit reasons, not "
                "only safety ones.",
            ]
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "since": self.since.isoformat(),
                "until": self.until.isoformat(),
                "proposed": self.proposed,
                "merged": self.merged,
                "rejected": self.rejected,
                "escalated": self.escalated,
                "rolled_back": self.rolled_back,
                "halts": self.halts,
                "security_events": self.security_events,
                "scenarios_added": self.scenarios_added,
                "drift": self.drift,
                "owner_edits": self.owner_edits,
                "acceptance_rate": self.acceptance_rate,
                "beating_manual_editing": self.beating_manual_editing,
            },
            indent=2,
            sort_keys=True,
        )


_COUNTED: dict[EventKind, str] = {
    EventKind.PROPOSED: "proposed",
    EventKind.MERGED: "merged",
    EventKind.REJECTED: "rejected",
    EventKind.ESCALATED: "escalated",
    EventKind.ROLLED_BACK: "rolled_back",
    EventKind.HALTED: "halts",
}


def build_digest(
    entries: tuple[LedgerEntry, ...],
    *,
    since: datetime,
    until: datetime,
    drift: float = 0.0,
    scenarios_added: int = 0,
    owner_edits: int = 0,
) -> Digest:
    counts = dict.fromkeys(_COUNTED.values(), 0)
    security_events = 0

    for entry in entries:
        if not since <= entry.at <= until:
            continue
        field_name = _COUNTED.get(entry.kind)
        if field_name is not None:
            counts[field_name] += 1
        if entry.detail.get("security_event"):
            security_events += 1

    return Digest(
        since=since,
        until=until,
        security_events=security_events,
        scenarios_added=scenarios_added,
        drift=drift,
        owner_edits=owner_edits,
        **counts,
    )


# --------------------------------------------------------------------------
# Halt criteria (05-approval-policy.md §6)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HaltAssessment:
    should_halt: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def assess_halt(
    *,
    gated_rollback: bool = False,
    zone_violation: bool = False,
    drift_exhausted_twice: bool = False,
    consecutive_escalation_rejections: int = 0,
    digest: Digest | None = None,
) -> HaltAssessment:
    """The five halt criteria, evaluated together."""
    reasons: list[str] = []
    if gated_rollback:
        reasons.append(
            "a rollback was triggered by something every gate passed — the gates have a "
            "blind spot, and merging on through a known blind spot is the failure this stops"
        )
    if zone_violation:
        reasons.append(
            "a proposal reached for the harness or the core — a category signal, not a "
            "normal rejection"
        )
    if drift_exhausted_twice:
        reasons.append("the drift budget was exhausted twice in quick succession")
    if consecutive_escalation_rejections >= 2:
        reasons.append(
            f"{consecutive_escalation_rejections} consecutive escalations resolved by "
            f"rejection — the proposer is working outside its evidence base"
        )
    if digest is not None and digest.beating_manual_editing is False:
        reasons.append(
            "no measurable benefit over the owner editing code directly — the program is "
            "cost without benefit and should stop regardless of safety"
        )
    return HaltAssessment(should_halt=bool(reasons), reasons=tuple(reasons))
