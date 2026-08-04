"""Scoring a candidate over the corpus, and the statistics G3 gates on.

Two things worth stating before the code, because both are places where a
plausible implementation would quietly mislead.

**Aggregate means have no power at this sample size.** With n≈20 scenarios,
"candidate mean 0.81 vs incumbent 0.78" is noise. `ScoreSet` therefore
reports a confidence interval alongside the mean and G3 *gates* on a
deterministic per-scenario rule plus a percentile comparison against a
control cohort — never on the means alone.

**Beating the incumbent is not evidence of improvement.** Generate enough
random variants of anything and some will score higher on a fixed set of
scenarios by chance. That is the null hypothesis, and the only way to
reject it is to score a cohort of *random* mutations the same way and
require the candidate to beat them, not merely to beat the incumbent
(GEPA/AlphaEvolve both make this point; the Phase-4 gate criteria list it
as criterion 2). A candidate that beats the incumbent but sits inside the
random cohort's spread has demonstrated nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from aef.services.eval.base import EvaluationRecord


@dataclass(frozen=True)
class ScoreSet:
    """Per-scenario scores for one variant, plus the honest statistics."""

    label: str
    per_scenario: dict[str, float] = field(default_factory=dict)
    cost_tokens: int = 0

    @property
    def n(self) -> int:
        return len(self.per_scenario)

    @property
    def mean(self) -> float:
        if not self.per_scenario:
            raise ValueError(f"score set {self.label!r} is empty; there is no mean to report")
        return sum(self.per_scenario.values()) / self.n

    @property
    def stdev(self) -> float:
        if self.n < 2:
            return 0.0
        mean = self.mean
        return math.sqrt(sum((v - mean) ** 2 for v in self.per_scenario.values()) / (self.n - 1))

    @property
    def confidence_interval_95(self) -> tuple[float, float]:
        """Normal-approximation CI on the mean. Reported, never gated on —
        at n≈20 it is wide enough that overlapping intervals are the norm,
        which is precisely the fact a mean-comparison would hide."""
        if self.n < 2:
            return (self.mean, self.mean)
        margin = 1.96 * self.stdev / math.sqrt(self.n)
        return (self.mean - margin, self.mean + margin)

    @property
    def passing(self) -> frozenset[str]:
        return frozenset(sid for sid, score in self.per_scenario.items() if score >= 0.5)

    def percentile(self, p: float) -> float:
        """Linear-interpolated percentile of the per-scenario scores."""
        if not self.per_scenario:
            raise ValueError(f"score set {self.label!r} is empty")
        if not 0.0 <= p <= 100.0:
            raise ValueError(f"percentile must be within [0, 100], got {p}")
        ordered = sorted(self.per_scenario.values())
        if len(ordered) == 1:
            return ordered[0]
        position = (p / 100.0) * (len(ordered) - 1)
        low = math.floor(position)
        high = math.ceil(position)
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def score_of(record: EvaluationRecord) -> float:
    """The scalar G3 compares. `task_completion` gated by the domain gates,
    which is `EvaluationRecord.passed`'s logic expressed as a score rather
    than a boolean — a failed domain gate zeroes the score outright rather
    than being averaged away (ADR 0038)."""
    if not all(record.domain_gates.values()):
        return 0.0
    return record.task_completion


def build_score_set(label: str, records: dict[str, EvaluationRecord]) -> ScoreSet:
    return ScoreSet(
        label=label,
        per_scenario={sid: score_of(r) for sid, r in records.items()},
        cost_tokens=sum(r.cost_tokens for r in records.values()),
    )


@dataclass(frozen=True)
class CohortVerdict:
    """Did the candidate beat the random-mutation cohort, or merely the
    incumbent?"""

    candidate: ScoreSet
    incumbent: ScoreSet
    cohort: tuple[ScoreSet, ...]
    percentile: float = 95.0

    @property
    def cohort_means(self) -> tuple[float, ...]:
        return tuple(s.mean for s in self.cohort)

    @property
    def threshold(self) -> float:
        """The score the candidate must exceed: the `percentile`-th
        percentile of the control cohort's means."""
        means = ScoreSet(
            label="cohort-means",
            per_scenario={s.label: s.mean for s in self.cohort},
        )
        return means.percentile(self.percentile)

    @property
    def beats_cohort(self) -> bool:
        return bool(self.cohort) and self.candidate.mean > self.threshold

    @property
    def beats_incumbent(self) -> bool:
        return self.candidate.mean > self.incumbent.mean

    @property
    def report(self) -> tuple[str, ...]:
        low, high = self.candidate.confidence_interval_95
        lines = [
            f"candidate mean {self.candidate.mean:.4g} (95% CI {low:.4g}..{high:.4g}, "
            f"n={self.candidate.n})",
            f"incumbent mean {self.incumbent.mean:.4g}",
        ]
        if self.cohort:
            lines.append(
                f"control cohort of {len(self.cohort)} random mutation(s): "
                f"p{self.percentile:g} of means = {self.threshold:.4g}"
            )
            if self.beats_incumbent and not self.beats_cohort:
                lines.append(
                    "candidate beats the incumbent but sits inside the random cohort's "
                    "spread — that is the null hypothesis, not an improvement"
                )
        return tuple(lines)
