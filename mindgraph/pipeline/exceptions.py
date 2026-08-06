"""Stage 4.2 — the exception queue.

One rule decides whether this panel is worth reading: **an ordinary rejection is
the gate working, and must never appear here.**

Most candidates are rejected. That is the designed behaviour of a system whose
job is to reject things, and a queue that listed them would be long, boring, and
always full — so the operator would learn to skip it. The next time something
genuinely abnormal appeared, it would be sitting in a list nobody reads. The
queue's value is entirely in what it *excludes*.

## What qualifies

Only conditions meaning the system is not behaving as designed:

- **rollback** — a change that passed every gate and still had to be undone. The
  gates have a blind spot.
- **gate error** — the evaluation itself failed. A gate that errored did not
  pass; treating those alike is how a broken gate reads as a clean run.
- **not reporting** — stale, never-reported, or a failed collector.
- **decision overdue** — a human gate has been waiting longer than the agreed
  window. The loop is blocked on a person and nobody has been told.
- **out of band** — a cohort branch outside its own historical expected range,
  in either direction. Section 4.4 is explicit that this cuts both ways: a
  sudden drop in the rejection rate means the gate stopped, and a spike toward
  100% means the generator broke.

## What is NOT derivable, and is reported rather than invented

Section 4.4 also names **repeated proposal loops** — an agent proposing the same
rejected change over and over. That needs per-proposal identity and history
across cycles, which the available data does not carry. It is listed as a known
gap rather than approximated by something that would look like it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Ordinary rejections. Named here so the exclusion is explicit and testable
# rather than an accident of which branches happened to be checked.
ROUTINE_OUTCOMES = frozenset(
    {"static_rejected", "behavioral_rejected", "human_rejected", "escalated_pending"}
)

SEVERITY_ORDER = {
    "rollback": 0,
    "gate_error": 1,
    "not_reporting": 2,
    "out_of_band": 3,
    "decision_overdue": 4,
}

# How long a human decision may sit before the loop is considered blocked on a
# person. The report says "long-pending" without a number, so this is a stated
# default rather than a discovered one, and the page prints it.
DEFAULT_DECISION_SLA_HOURS = 24.0


class ExceptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Exception_:
    kind: str
    subject: str
    detail: str
    age_seconds: float | None = None

    @property
    def sort_key(self) -> tuple[int, float, str]:
        return (SEVERITY_ORDER.get(self.kind, 9), -(self.age_seconds or 0.0), self.subject)

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "detail": self.detail,
            "age_seconds": self.age_seconds,
        }


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect(
    *,
    fleet_rows: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    cohort: dict[str, Any] | None,
    data_through: datetime,
    decision_sla_hours: float = DEFAULT_DECISION_SLA_HOURS,
) -> list[Exception_]:
    found: list[Exception_] = []

    for row in fleet_rows:
        if row.get("state") in ("stale", "never", "error", "unregistered"):
            found.append(
                Exception_(
                    kind="not_reporting",
                    subject=str(row.get("repo", "?")),
                    detail={
                        "stale": "stopped reporting",
                        "never": "in the registry, never reported",
                        "error": f"collector failed: {row.get('telemetry_error') or 'unknown'}",
                        "unregistered": "reporting but absent from the registry",
                    }.get(str(row.get("state")), str(row.get("state"))),
                    age_seconds=row.get("overdue_seconds"),
                )
            )

    for gate in gates:
        if gate.get("disposition") != "awaiting":
            continue
        since = _parse(gate.get("pending_since"))
        if since is None:
            # Awaiting with no start time: we cannot tell whether it is overdue.
            # Raised anyway, because "we do not know how long a human has been
            # blocking the loop" is itself worth an operator's attention.
            found.append(
                Exception_(
                    kind="decision_overdue",
                    subject=" → ".join(gate.get("edge", ["?", "?"])),
                    detail="awaiting a decision, and no pending_since was recorded",
                    age_seconds=None,
                )
            )
            continue
        waited = (data_through - since).total_seconds()
        if waited > decision_sla_hours * 3600:
            found.append(
                Exception_(
                    kind="decision_overdue",
                    subject=" → ".join(gate.get("edge", ["?", "?"])),
                    detail=(
                        f"awaiting a human decision beyond the "
                        f"{int(decision_sla_hours)}h window"
                    ),
                    age_seconds=waited,
                )
            )

    if cohort:
        total = cohort.get("proposed") or 0
        for branch in cohort.get("branches", []):
            outcome = str(branch.get("outcome", "?"))
            count = branch.get("count") or 0
            low, high = (branch.get("expected_range") or [None, None])[:2]

            if branch.get("tone") == "abnormal":
                found.append(
                    Exception_(
                        kind="rollback",
                        subject=outcome,
                        detail=(
                            f"{count} of {total} — changes that passed every gate "
                            f"and were undone"
                        ),
                        age_seconds=None,
                    )
                )
                continue

            # Routine rejections never qualify on tone alone. They can still be
            # OUT OF BAND, which is a different claim: not "this was rejected"
            # but "the rate itself has moved", and that cuts both ways.
            if low is None or high is None or not total:
                continue
            pct = 100.0 * count / total
            if pct < low:
                found.append(
                    Exception_(
                        kind="out_of_band",
                        subject=outcome,
                        detail=(
                            f"{pct:.0f}% of the cohort, below the expected {low:.0f}-{high:.0f}% "
                            f"— a gate that stopped rejecting looks like this"
                        ),
                    )
                )
            elif pct > high:
                found.append(
                    Exception_(
                        kind="out_of_band",
                        subject=outcome,
                        detail=(
                            f"{pct:.0f}% of the cohort, above the expected {low:.0f}-{high:.0f}% "
                            f"— a generator that broke looks like this"
                        ),
                    )
                )

        unclassified = cohort.get("unclassified")
        if unclassified:
            found.append(
                Exception_(
                    kind="gate_error",
                    subject="cohort",
                    detail=f"{unclassified} proposals with no recorded outcome",
                )
            )

    return sorted(found, key=lambda e: e.sort_key)


def excluded_outcomes(cohort: dict[str, Any] | None) -> list[str]:
    """Which routine outcomes were deliberately kept out.

    Printed on the page. An empty exception queue is only trustworthy if the
    reader can see what it chose not to list — otherwise "no exceptions" is
    indistinguishable from "nothing was checked".
    """
    if not cohort:
        return []
    return sorted(
        str(b.get("outcome"))
        for b in cohort.get("branches", [])
        if str(b.get("outcome")) in ROUTINE_OUTCOMES
    )


# Named gaps, surfaced rather than approximated.
KNOWN_GAPS = (
    "repeated proposal loops — needs per-proposal identity across cycles, "
    "which the available data does not carry",
)
