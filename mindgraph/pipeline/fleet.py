"""Stage 4.1 — the fleet, assembled from a registry and LEFT-JOINed with telemetry.

The direction of that join is the entire point, and getting it backwards is the
failure the report spends most of Section 4.4 warning about.

If you build the list from whoever emitted data, a repo that stops reporting
does not go red — **it stops existing**. The page looks calm, every row on it is
green, and the one thing you needed to know is the row that is not there. That
is the cardinal anti-pattern ("everything looks healthy") in its most literal
form: the failure removes its own evidence.

So the registry is authoritative. Every repo in it gets a row, always. Telemetry
attaches where it exists and is absent where it does not, and absence is a
rendered state rather than a missing row.

## Four states, and why `error` is not `never`

- **fresh** — reported within the expected interval.
- **stale** — reported, but not recently enough. We know it was alive and we
  know it has gone quiet.
- **never** — in the registry, never reported at all. There is no last-known
  state to fall back on and no score to show.
- **error** — the collector itself failed. This is *not* no-data: we know we
  cannot see, rather than seeing nothing. Conflating the two would let a broken
  exporter masquerade as a quiet agent, and those need different people to fix
  them.

## The reverse case is a finding, not a filter

Telemetry arriving for a repo absent from the registry means the registry is
stale — someone stood up an agent nobody recorded. Dropping it would hide that;
it is surfaced as `unregistered`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Sort weight per state. Lower sorts first, and the ordering is the requirement:
# a repo that stopped reporting must float ABOVE healthy ones, because the
# operator is scanning for trouble and trouble must not be below the fold.
STATE_ORDER = {
    "error": 0,
    "never": 1,
    "stale": 2,
    "unregistered": 3,
    "fresh": 4,
}

# Rendered treatment per state. `fresh` is the only one that may look calm, and
# no other state inherits it — a repo that has gone quiet must never keep the
# green fill it had when it was last heard from.
STATE_TREATMENT = {
    "fresh": "normal",
    "stale": "stale",
    "never": "unknown",
    "error": "degraded",
    "unregistered": "degraded",
}


class FleetError(RuntimeError):
    pass


@dataclass(frozen=True)
class FleetRow:
    repo: str
    state: str
    last_report_at: datetime | None
    overdue_seconds: float | None
    telemetry_error: str | None = None

    @property
    def sort_key(self) -> tuple[int, float, str]:
        # Within a state, the longest-overdue sorts first: the climb is itself
        # the signal, so the number must be able to rise to the top.
        return (
            STATE_ORDER.get(self.state, 9),
            -(self.overdue_seconds or 0.0),
            self.repo,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "state": self.state,
            "treatment": STATE_TREATMENT.get(self.state, "unknown"),
            "last_report_at": (
                None if self.last_report_at is None else _iso(self.last_report_at)
            ),
            "overdue_seconds": self.overdue_seconds,
            "telemetry_error": self.telemetry_error,
        }


def _iso(value: datetime) -> str:
    return value.astimezone().isoformat().replace("+00:00", "Z")


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def left_join(
    registry: list[dict[str, Any]],
    *,
    data_through: datetime,
    expected_interval_seconds: float,
    emitters: set[str] | None = None,
) -> list[FleetRow]:
    """Registry first, telemetry second. Never the other way round."""
    rows: list[FleetRow] = []
    registered: set[str] = set()

    for entry in registry:
        repo = entry.get("repo")
        if not repo:
            raise FleetError(f"registry entry has no repo name: {entry!r}")
        registered.add(repo)
        declared = entry.get("telemetry")
        last = _parse(entry.get("last_report_at"))

        if declared == "error":
            state = "error"
        elif last is None:
            # No report ever. NOT stale — there is no last-known state to be
            # stale about, and no score to show.
            state = "never"
        else:
            overdue = (data_through - last).total_seconds()
            state = "fresh" if overdue <= expected_interval_seconds else "stale"

        overdue_seconds = None if last is None else max(0.0, (data_through - last).total_seconds())
        rows.append(
            FleetRow(
                repo=repo,
                state=state,
                last_report_at=last,
                overdue_seconds=overdue_seconds,
                telemetry_error=entry.get("telemetry_error"),
            )
        )

    # Telemetry with no registry entry: the registry is stale. Surfaced, never
    # dropped — dropping it would hide the fact that somebody stood up an agent
    # nobody recorded.
    for repo in sorted((emitters or set()) - registered):
        rows.append(
            FleetRow(repo=repo, state="unregistered", last_report_at=None, overdue_seconds=None)
        )

    return sorted(rows, key=lambda r: r.sort_key)


# Section 4.4 asks for two things per repo, and the registry supports one.
#
# A "Grafana-style state-timeline" needs a SEQUENCE of state changes — that is
# what makes duration-as-length meaningful, because the lengths sit side by
# side. The registry carries one `last_report_at` per repo and no transitions,
# so there is no sequence to draw. Checked, not assumed.
#
# The FRESHNESS RAIL is derivable and is the half carrying the requirement's
# substance: how long this repo has been in its current state, drawn as length,
# with a treatment per state. One segment, honestly labelled as one segment.
TIMELINE_GAP = (
    "per-repo state timeline \u2014 the registry records one last_report_at per repo "
    "and no state transitions, so there is no sequence to lay out; the rail below "
    "shows the CURRENT state's duration only"
)


def rails(rows: list[FleetRow]) -> dict[str, Any]:
    """One segment per repo: how long it has held its current state.

    Scaled against the longest duration in the fleet, so the repo that has been
    quiet longest has the longest bar — the climb is the signal, and a rail that
    normalised each row to its own maximum would flatten exactly that.

    A repo that has NEVER reported gets no bar at all. Zero-length would read as
    "in this state for no time", and a full-length bar would invent a duration;
    it gets the broken outline and no score instead.
    """
    durations = [r.overdue_seconds for r in rows if r.overdue_seconds is not None]
    longest = max(durations, default=0.0) or 1.0
    return {
        "gap": TIMELINE_GAP,
        "longest_seconds": max(durations, default=None),
        "segments": [
            {
                "repo": r.repo,
                "state": r.state,
                "treatment": STATE_TREATMENT.get(r.state, "unknown"),
                # None, never 0.0 — "never reported" is an absence of duration,
                # not a duration of nothing.
                "held_seconds": r.overdue_seconds,
                "length_pct": (
                    None
                    if r.overdue_seconds is None
                    else round(100.0 * r.overdue_seconds / longest, 1)
                ),
                "scored": r.state != "never",
            }
            for r in rows
        ],
    }


def coverage(rows: list[FleetRow], *, expected_interval_seconds: float) -> dict[str, Any]:
    """The strip that answers "can I trust the rest of this page?".

    It leads the dashboard because every other panel is conditional on it: a
    coverage figure of 40/100 makes the numbers below it a sample, not a
    measurement, and the reader needs to know that before reading them.
    """
    counts = {state: 0 for state in STATE_ORDER}
    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1

    overdue = [r for r in rows if r.state in ("stale", "never", "error")]
    worst = max(
        (r.overdue_seconds or 0.0 for r in overdue if r.overdue_seconds is not None),
        default=None,
    )
    return {
        "total": len(rows),
        "fresh": counts.get("fresh", 0),
        "stale": counts.get("stale", 0),
        "never": counts.get("never", 0),
        "error": counts.get("error", 0),
        "unregistered": counts.get("unregistered", 0),
        "not_reporting": len(overdue),
        "expected_interval_seconds": expected_interval_seconds,
        # None rather than 0 when nothing is overdue: zero would read as "the
        # oldest overdue report is 0 seconds old", which is a measurement about
        # a thing that does not exist.
        "oldest_overdue_seconds": worst,
    }


def load_registry(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    registry = payload.get("registry")
    if not isinstance(registry, list) or not registry:
        raise FleetError(
            f"{path} carries no registry. The fleet cannot be assembled from telemetry "
            f"alone — that is precisely the join direction this module exists to prevent."
        )
    return [entry for entry in registry if entry.get("repo")]


def humanise(seconds: float | None) -> str | None:
    """`19h42m`, the shape Section 4.4 asks for. None stays None."""
    if seconds is None:
        return None
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def default_interval(topology: dict[str, Any]) -> float:
    return float(topology.get("expected_report_interval_seconds", 3600))


def window(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)
