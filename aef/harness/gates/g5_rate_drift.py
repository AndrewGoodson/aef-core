"""G5 — rate, drift, and budget.

Every other gate judges one candidate in isolation. G5 is the only one that
asks about the *sequence*, and it exists because a system that accepts
individually-defensible changes forever still ends up somewhere nobody
chose.

**Drift is distance from the baseline, not the sum of steps.** This
distinction is load-bearing. Summing step sizes makes an A→B→A round trip
look like two changes' worth of drift when the system is exactly where it
started; measuring distance from the baseline correctly reports zero. But
that round trip **still consumes rate**, because the cost of churn is real
even when the net displacement is not.

**Rebaselining is rate-limited, not merely owner-only.** The superseded G5
made rebaselining an owner decision and stopped there, which leaves a
standing-pressure hole (04 §1.9): once the drift budget binds, *every*
subsequent proposal is blocked until someone rebaselines, so the pressure to
rebaseline never lets up and the budget stops meaning anything. A rate limit
on rebaselines is what makes the drift budget a budget rather than a
speed bump.

The gate **reports its numbers on pass as well as fail** — a budget nobody
can see approaching is one that only ever announces itself by blocking
something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult

DEFAULT_WINDOW = timedelta(days=7)
DEFAULT_MAX_ACCEPTED_PER_WINDOW = 3
DEFAULT_MAX_DRIFT = 0.5
DEFAULT_MAX_REBASELINES_PER_WINDOW = 1


@dataclass(frozen=True)
class AcceptedChange:
    version: int
    at: datetime


@dataclass(frozen=True)
class DriftBudget:
    window: timedelta = DEFAULT_WINDOW
    max_accepted_per_window: int = DEFAULT_MAX_ACCEPTED_PER_WINDOW
    max_drift: float = DEFAULT_MAX_DRIFT
    max_rebaselines_per_window: int = DEFAULT_MAX_REBASELINES_PER_WINDOW

    def __post_init__(self) -> None:
        if not 0.0 < self.max_drift <= 1.0:
            raise ValueError(
                f"max_drift must be within (0.0, 1.0] — 0 would block every change and a "
                f"value above 1 is unreachable, so neither is a budget; got {self.max_drift}"
            )
        if self.max_accepted_per_window < 1:
            raise ValueError("max_accepted_per_window must be at least 1")
        if self.window <= timedelta(0):
            raise ValueError("window must be positive")


def structural_drift(baseline: dict[str, bytes], current: dict[str, bytes]) -> float:
    """Fraction of files that differ between the baseline and the current
    state, over the union of both.

    Distance, not path length: a file changed and changed back contributes
    nothing, which is the correct reading of "how far have we drifted from
    what the owner blessed".
    """
    paths = set(baseline) | set(current)
    if not paths:
        return 0.0
    differing = sum(1 for path in paths if baseline.get(path) != current.get(path))
    return differing / len(paths)


@dataclass(frozen=True)
class G5RateAndDrift(Gate):
    id: str = "G5"
    baseline_files: dict[str, bytes] | None = None
    candidate_files: dict[str, bytes] | None = None
    history: tuple[AcceptedChange, ...] = ()
    rebaselines: tuple[datetime, ...] = ()
    rebaseline_requested: bool = False
    now: datetime | None = None
    budget: DriftBudget = field(default_factory=DriftBudget)

    def run(self, ctx: GateContext) -> GateResult:
        if self.baseline_files is None or self.candidate_files is None or self.now is None:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    "no owner-blessed baseline to measure drift against — without a "
                    "reference point this gate has no signal, so the candidate escalates"
                ),
            )

        if self.rebaseline_requested:
            return self._judge_rebaseline()

        cutoff = self.now - self.budget.window
        recent = [c for c in self.history if c.at > cutoff]
        drift = structural_drift(self.baseline_files, self.candidate_files)
        numbers = (
            f"{len(recent)}/{self.budget.max_accepted_per_window} accepted in the last "
            f"{self.budget.window.days}d",
            f"drift {drift:.3f}/{self.budget.max_drift:.3f} from the blessed baseline",
        )

        if len(recent) >= self.budget.max_accepted_per_window:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"rate budget exhausted: {len(recent)} change(s) accepted in the last "
                    f"{self.budget.window.days} day(s), limit {self.budget.max_accepted_per_window}"
                ),
                evidence=numbers,
            )

        if drift > self.budget.max_drift:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"cumulative drift {drift:.3f} exceeds the budget of "
                    f"{self.budget.max_drift:.3f} — individually-small accepted changes have "
                    f"accumulated past what the owner blessed. This is a decision to make, "
                    f"not a threshold to raise"
                ),
                evidence=numbers,
            )

        # Reported on pass too: a budget nobody can see approaching is one
        # that only announces itself by blocking something.
        return GateResult(gate=self.id, outcome=GateOutcome.PASS, reason="; ".join(numbers))

    def _judge_rebaseline(self) -> GateResult:
        assert self.now is not None
        cutoff = self.now - self.budget.window
        recent = [at for at in self.rebaselines if at > cutoff]
        if len(recent) >= self.budget.max_rebaselines_per_window:
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=(
                    f"rebaseline rate limit reached: {len(recent)} in the last "
                    f"{self.budget.window.days} day(s), limit "
                    f"{self.budget.max_rebaselines_per_window}. Without this limit the drift "
                    f"budget is not a budget — once it binds, every proposal pushes for a "
                    f"rebaseline and the pressure never lets up"
                ),
            )
        return GateResult(
            gate=self.id,
            outcome=GateOutcome.FAIL,
            reason=(
                "a rebaseline is an owner decision, not a gate outcome — escalating "
                "(Tier 2). The question is 'do we accept where we have drifted to?', which "
                "is a judgement, not a measurement"
            ),
            security_event=True,
        )
