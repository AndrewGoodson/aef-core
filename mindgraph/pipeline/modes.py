"""Stage 5.1 — the temporal modes, declared rather than assumed.

The page has always shown one thing. Naming it as a MODE matters for a reason
that only becomes visible once a second mode exists: a reader who does not know
which temporal frame they are looking at will assume the most flattering one.

## What "accumulated present" means, precisely

Everything observed up to `data_through`, accumulated. Traversal counts never
decay, so an edge's width is its entire history, not its recent activity. This
is **not** a snapshot of an instant — a snapshot would show the last hour and
call the rest gone.

Saying so matters because the two read identically at a glance and answer
opposite questions. "This path is thick" means *it has carried a lot, ever*,
not *it is carrying a lot now*. The activity core answers the second question,
which is why the two channels are separate.

## Availability is derived, not asserted

Each of the other two modes is checked against the data that would be needed to
render it, and reports what it would take. A mode selector offering a mode that
cannot be drawn is worse than one that offers fewer modes and says why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACCUMULATED = "accumulated_present"
DIFFERENCE = "difference_map"
SCRUBBER = "scrubber"


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    describes: str
    available: bool
    requires: str = ""
    partial: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "describes": self.describes,
            "available": self.available,
            "requires": self.requires,
            "partial": self.partial,
        }


def build(payload: dict[str, Any]) -> dict[str, Any]:
    """Declare the three modes and which of them this artifact can actually offer."""
    nodes = payload.get("nodes") or []
    # Prior COORDINATES exist per node; a prior TOPOLOGY does not. That
    # asymmetry is the whole finding here: the pipeline carries where each node
    # used to sit, but not which nodes and edges used to exist — so "what
    # moved" is answerable and "what was added or removed" is not.
    with_previous = [n for n in nodes if n.get("previous_x") is not None]
    has_positions = len(with_previous) > 0
    has_prior_topology = False  # nothing in the record carries a previous node/edge set

    modes = [
        Mode(
            key=ACCUMULATED,
            label="accumulated present",
            describes=(
                "everything observed up to data_through, accumulated — edge width is "
                "an edge's entire history, not its recent activity. Not a snapshot of an "
                "instant"
            ),
            available=True,
        ),
        Mode(
            key=DIFFERENCE,
            label="difference map",
            describes="what changed between two wiring versions, as two synced panes",
            available=False,
            requires=(
                "a previous node and edge SET to diff against. The pipeline keeps one "
                "layout-state file and overwrites it each build, so there is no prior "
                "topology to compare"
            ),
            partial=(
                f"partial: {len(with_previous)} of {len(nodes)} nodes carry previous "
                f"coordinates, so where a node MOVED is answerable; which nodes or edges "
                f"were added or removed is not"
            )
            if has_positions
            else "",
        ),
        Mode(
            key=SCRUBBER,
            label="timeline scrubber",
            describes="trajectory across many versions, user-initiated, staged transitions",
            available=False,
            requires=(
                "a SEQUENCE of retained versions. One state file exists and it is "
                "overwritten on every build, so there is nothing to scrub through"
            ),
        ),
    ]

    return {
        "current": ACCUMULATED,
        # Stated so nothing downstream has to infer it from the list length.
        "available_count": sum(1 for m in modes if m.available),
        "modes": [m.to_payload() for m in modes],
        "has_prior_topology": has_prior_topology,
        "note": (
            "Section 3g makes the difference map primary and the scrubber secondary. "
            "Neither is offered here, because offering a mode that cannot be drawn is "
            "worse than offering fewer and saying why"
        ),
    }
