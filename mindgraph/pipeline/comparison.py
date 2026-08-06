"""Stage 4.6 — loop-vs-human, which is not currently a comparison.

Section 4.5 asks for "durable changes per human review hour", labelled
OBSERVATIONAL, and says: *if the direct-human-edit counterfactual isn't stored,
say so on the panel.*

It is not stored. The record says so in as many words:

    counterfactual_stored: false
    "direct-human-edit counterfactual is not stored; the comparison cannot be
     made from this data"

So there is **one side of a two-sided question**. The loop's throughput is
measured; the alternative — what the same changes would have cost a human
editing directly — was never recorded. A panel titled "loop vs human" showing
a single number would answer a question it has no data for, and the reader
would supply the missing comparator from imagination, favourably.

## What is built instead

A one-sided measurement, named as one. The headline is the loop's rate with an
explicit "no comparator recorded" beside it, and the panel carries no ratio, no
delta, no better/worse arrow and no second bar — because every one of those is
a comparison rendered in a place where no comparison exists.

## Why OBSERVATIONAL survives even if a comparator arrives

The report is precise: the comparison stays observational "unless randomized or
matched on repo, size, subsystem, and risk". None of those has happened, so
even a stored counterfactual would give an adjusted association rather than a
causal claim. The label is not a placeholder waiting for more data; it is a
statement about study design.

## DORA framing, honestly

DORA pairs throughput with change-fail rate — and both halves of that pair are
loop-side, so it is computable without a comparator. Throughput alone is the
number that flatters; showing it beside the rollback rate is what makes it
worth reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Terms that would turn a one-sided measurement into an implied comparison.
# Checked against the rendered panel rather than trusted.
COMPARATIVE_TERMS = ("faster than", "better than", "outperform", "beats", "× human", "vs human")

# Section 4.5's supporting metrics. Each is listed with whether the record can
# supply it, so the panel can name what it is not showing.
SUPPORTING = (
    ("rollback / rework rate", True),
    ("median time from need to durable change", False),
    ("human minutes per durable change", False),
    ("post-change incident rate", False),
)


class ComparisonError(RuntimeError):
    pass


@dataclass(frozen=True)
class Comparison:
    label: str
    durable_per_review_hour: float | None
    has_comparator: bool
    counterfactual_note: str
    rollback_rate_pct: float | None
    durable_yield_pct: float | None
    absent: tuple[str, ...]

    @property
    def is_comparison(self) -> bool:
        """False whenever the other side is missing.

        Named as a property rather than inferred at the call site, so nothing
        downstream can quietly decide that one number is enough.
        """
        return self.has_comparator

    def to_payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "durable_per_review_hour": self.durable_per_review_hour,
            "has_comparator": self.has_comparator,
            "is_comparison": self.is_comparison,
            "counterfactual_note": self.counterfactual_note,
            "rollback_rate_pct": self.rollback_rate_pct,
            "durable_yield_pct": self.durable_yield_pct,
            "absent": list(self.absent),
            # Stated in the payload, not only in the prose, so a future consumer
            # cannot render this as a verdict by accident.
            "causal_claim": False,
            "why_observational": (
                "not randomized and not matched on repo, size, subsystem or risk, so this "
                "is an adjusted association at best — and with no comparator stored it is "
                "not yet even that"
            ),
        }


def build(raw: dict[str, Any] | None, cohort: dict[str, Any] | None) -> Comparison | None:
    if not raw:
        return None

    label = str(raw.get("label") or "").strip().upper()
    if label != "OBSERVATIONAL":
        # The label is load-bearing, not decorative. A panel that lost it would
        # read as a finding.
        raise ComparisonError(
            f"loop_vs_human is labelled {label!r}; it must be OBSERVATIONAL. The comparison "
            f"is not randomized and not matched on repo, size, subsystem or risk, so any "
            f"other label claims a design that was never run."
        )

    has_comparator = bool(raw.get("counterfactual_stored"))
    note = str(raw.get("counterfactual_note") or "").strip()
    if not has_comparator and not note:
        raise ComparisonError(
            "the counterfactual is not stored and no note explains that. Section 4.5 "
            "requires the panel to say so; an unexplained single number invites the reader "
            "to supply the missing comparator themselves, favourably."
        )

    rollback_pct: float | None = None
    durable_pct: float | None = None
    if cohort:
        proposed = cohort.get("proposed") or 0
        by = {str(b.get("outcome")): (b.get("count") or 0) for b in cohort.get("branches", [])}
        merged = by.get("merged_durable", 0) + by.get("merged_rolled_back", 0)
        if merged:
            rollback_pct = 100.0 * by.get("merged_rolled_back", 0) / merged
        if proposed:
            durable_pct = 100.0 * by.get("merged_durable", 0) / proposed

    return Comparison(
        label=label,
        durable_per_review_hour=raw.get("durable_changes_per_human_review_hour"),
        has_comparator=has_comparator,
        counterfactual_note=note,
        rollback_rate_pct=rollback_pct,
        durable_yield_pct=durable_pct,
        absent=tuple(name for name, available in SUPPORTING if not available),
    )
