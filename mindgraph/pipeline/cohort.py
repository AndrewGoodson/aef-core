"""Stage 4.3 — the cohort flow, CONSORT-style rather than a funnel.

Section 3b adjudicates this and the reasoning is the whole design. A funnel's
visual grammar says *wider top is success, and everything that leaks out is
loss*. Applied here that is not merely unhelpful, it is **backwards**: a
rejected proposal is the gate doing its job. A funnel would draw the system
working correctly as a system leaking.

CONSORT's grammar treats every exclusion as an expected, counted,
reason-annotated branch. Nothing "leaks"; proposals arrive and are accounted
for. That is a precise match for
`proposed → (static | behavioural | human rejected | escalated | merged →
durable | rolled back)`.

## Colour carries abnormality, never rejection

Expected rejection branches are **neutral**. Red is reserved for the
operationally abnormal — a rollback, or a branch outside its own historical
band. Colouring rejections red would re-import the funnel's claim through the
palette after removing it from the shape.

## Every proposal is accounted for

The branches plus the unclassified count must equal the cohort. If they do not,
proposals have gone missing between stages, and that is surfaced rather than
absorbed into a rounding difference. The unclassified row is rendered **even
when it is zero**, because a hidden zero is indistinguishable from a figure
nobody computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Section 4.4: "<=6 top-level outcomes". More than that and the flow stops
# being scannable, which is the only thing it is for.
MAX_BRANCHES = 6


class CohortError(RuntimeError):
    pass


@dataclass(frozen=True)
class Branch:
    outcome: str
    count: int
    pct: float
    expected_low: float | None
    expected_high: float | None
    tone: str
    reason_top: str | None

    @property
    def band(self) -> str:
        """`in`, `below`, `above`, or `unknown` when no range was recorded.

        `unknown` is not `in`: a branch with no historical range has not been
        compared to anything, and saying it is within expectations would be a
        claim nobody made.
        """
        if self.expected_low is None or self.expected_high is None:
            return "unknown"
        if self.pct < self.expected_low:
            return "below"
        if self.pct > self.expected_high:
            return "above"
        return "in"

    @property
    def treatment(self) -> str:
        """Neutral unless genuinely abnormal.

        Rejection alone never earns red. Only an abnormal tone or a rate that
        has left its own band does — the second being a statement about the
        RATE, not about the rejections it counts.
        """
        if self.tone == "abnormal":
            return "abnormal"
        if self.band in ("below", "above"):
            return "abnormal"
        if self.band == "unknown":
            return "unknown"
        return "neutral"

    def to_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "count": self.count,
            "pct": round(self.pct, 1),
            "expected_low": self.expected_low,
            "expected_high": self.expected_high,
            "band": self.band,
            "treatment": self.treatment,
            "reason_top": self.reason_top,
        }


@dataclass(frozen=True)
class Cohort:
    proposed: int
    window_days: int | None
    branches: tuple[Branch, ...]
    unclassified: int
    unaccounted: int
    gaps: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "proposed": self.proposed,
            "window_days": self.window_days,
            "branches": [b.to_payload() for b in self.branches],
            "unclassified": self.unclassified,
            "unaccounted": self.unaccounted,
            "gaps": list(self.gaps),
        }


def build(raw: dict[str, Any] | None) -> Cohort | None:
    if not raw:
        return None
    proposed = int(raw.get("proposed") or 0)
    if proposed <= 0:
        raise CohortError(
            "the cohort reports no proposals. A flow diagram over an empty cohort would "
            "render as a set of clean zero branches, which reads as 'nothing went wrong' "
            "rather than 'nothing happened'."
        )

    entries = list(raw.get("branches") or [])
    if len(entries) > MAX_BRANCHES:
        raise CohortError(
            f"{len(entries)} top-level outcomes; the cap is {MAX_BRANCHES}. Beyond that the "
            f"flow stops being scannable, which is the only thing it is for. Group the tail "
            f"deliberately rather than letting it grow."
        )

    branches: list[Branch] = []
    for entry in entries:
        count = int(entry.get("count") or 0)
        low, high = (list(entry.get("expected_range") or [None, None]) + [None, None])[:2]
        branches.append(
            Branch(
                outcome=str(entry.get("outcome", "?")),
                count=count,
                pct=100.0 * count / proposed,
                expected_low=None if low is None else float(low),
                expected_high=None if high is None else float(high),
                tone=str(entry.get("tone", "neutral")),
                reason_top=entry.get("reason_top"),
            )
        )

    unclassified = int(raw.get("unclassified") or 0)
    counted = sum(b.count for b in branches) + unclassified
    # Not clamped, not absorbed. If proposals are missing between stages, the
    # number says so; if the branches over-count, the negative says that too.
    unaccounted = proposed - counted

    gaps: list[str] = []
    if not any("median_stage_seconds" in e for e in entries):
        gaps.append(
            "median and p-high time-in-stage — the cohort record carries no per-stage "
            "durations, so they are absent rather than estimated"
        )

    return Cohort(
        proposed=proposed,
        window_days=raw.get("window_days"),
        branches=tuple(branches),
        unclassified=unclassified,
        unaccounted=unaccounted,
        gaps=tuple(gaps),
    )
