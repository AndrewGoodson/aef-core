"""Stage 4.4 — process stability, as far as the data honestly supports it.

Section 4.4 asks for Shewhart control charts. A Shewhart chart needs
**successive observations**: the run rules that make it worth anything — points
outside the limits, runs on one side of the centre line, trends — are all
statements about a sequence.

The available record carries per-window counts and expected ranges. It carries
no series. Checked, not assumed: the fixture's only numeric arrays are the
`expected_range` pairs, which are bands, not observations over time.

So this is a **band chart, not a control chart**, and it says so on the page.

## Why that is still worth building

The report's own worked example is a single-point comparison:

> 90% rejection is healthy if the band is 88-93%; a sudden 55% means the gate
> stopped; 99.9% means the generator broke.

That judgement needs one observation and one band. It does not need a series.
The half of the requirement the data supports is the half that carries the
example, so it is built — and the half it does not support is named rather than
faked.

## What faking it would look like, and why it is worse than nothing

A single observation drawn as a chart with a trend line implies a history that
was never recorded. An operator would read direction out of one point. The
absence of a series is itself information: it says nobody has been keeping the
sequence, which is a fixable gap, and drawing over it would hide the fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class StabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Metric:
    """One measurable, with an explicit account of what backs it."""

    key: str
    label: str
    unit: str
    observation: float | None
    band_low: float | None
    band_high: float | None
    note: str = ""

    @property
    def has_observation(self) -> bool:
        return self.observation is not None

    @property
    def has_band(self) -> bool:
        return self.band_low is not None and self.band_high is not None

    @property
    def status(self) -> str:
        """`in`, `below`, `above`, or `unknown`.

        `unknown` covers both "no observation" and "no band", because in either
        case nothing has been compared — and a metric that has not been
        compared must not render as one that passed.
        """
        if not self.has_observation or not self.has_band:
            return "unknown"
        assert self.observation is not None and self.band_low is not None
        assert self.band_high is not None
        if self.observation < self.band_low:
            return "below"
        if self.observation > self.band_high:
            return "above"
        return "in"

    @property
    def treatment(self) -> str:
        return "abnormal" if self.status in ("below", "above") else (
            "unknown" if self.status == "unknown" else "neutral"
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "observation": None if self.observation is None else round(self.observation, 2),
            "band_low": self.band_low,
            "band_high": self.band_high,
            "status": self.status,
            "treatment": self.treatment,
            "has_series": False,  # never true until a series is actually recorded
            "note": self.note,
        }


# Metrics Section 4.4 names that the record does not carry at all. Listed so
# the page can say what it is not showing — a panel that silently omits three
# of its seven metrics reads as a complete panel.
ABSENT_METRICS = (
    ("human decision latency", "no decided-at timestamps are recorded, only pending_since"),
    ("gate evaluation duration and timeouts", "not recorded in the cohort or the event log"),
)


def build(
    cohort: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics: list[Metric] = []

    if cohort:
        proposed = cohort.get("proposed") or 0
        by_outcome = {str(b.get("outcome")): b for b in cohort.get("branches", [])}

        for key, label in (
            ("static_rejected", "static rejection rate"),
            ("behavioral_rejected", "behavioural rejection rate"),
            ("human_rejected", "human rejection rate"),
            ("escalated_pending", "escalation rate"),
            ("merged_durable", "durable merge yield"),
            ("merged_rolled_back", "rollback rate"),
        ):
            branch = by_outcome.get(key)
            if branch is None or not proposed:
                continue
            low, high = (list(branch.get("expected_range") or [None, None]) + [None, None])[:2]
            note = ""
            if key == "merged_durable":
                rolled = (by_outcome.get("merged_rolled_back") or {}).get("count") or 0
                note = f"rollback-adjusted: {rolled} merged change(s) were undone and are excluded"
            metrics.append(
                Metric(
                    key=key,
                    label=label,
                    unit="%",
                    observation=100.0 * (branch.get("count") or 0) / proposed,
                    band_low=None if low is None else float(low),
                    band_high=None if high is None else float(high),
                    note=note,
                )
            )

        metrics.append(
            Metric(
                key="proposal_arrival",
                label="proposal arrival",
                unit=f"per {cohort.get('window_days', '?')}d",
                observation=float(proposed),
                band_low=None,
                band_high=None,
                note="no historical band recorded for this repo, so nothing to compare against",
            )
        )

    if coverage and coverage.get("total"):
        metrics.append(
            Metric(
                key="telemetry_coverage",
                label="telemetry coverage",
                unit="%",
                observation=100.0 * coverage["fresh"] / coverage["total"],
                band_low=None,
                band_high=None,
                note="no coverage baseline recorded, so this is a reading rather than a verdict",
            )
        )

    banded = [m for m in metrics if m.has_band]
    return {
        # Stated flatly rather than implied. Every consumer of this payload can
        # see that no series exists without inferring it from an empty list.
        "has_series": False,
        "chart_kind": "band",
        "why_not_control_chart": (
            "a Shewhart chart needs successive observations; the record carries "
            "per-window counts and expected ranges but no series, so run rules and "
            "trends are not computable and are not drawn"
        ),
        "metrics": [m.to_payload() for m in metrics],
        "banded_count": len(banded),
        "unbanded_count": len(metrics) - len(banded),
        "absent": [{"metric": name, "why": why} for name, why in ABSENT_METRICS],
    }
