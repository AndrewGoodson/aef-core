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
    # 5.1 claimed that because every node carries previous_x/previous_y, "where
    # a node MOVED" was answerable. 5.2 checked, and it was WRONG.
    #
    # When the topology is unchanged the build writes
    # `Placed(n, prev, prev, prev, prev, "carried")` — previous is a COPY OF
    # CURRENT from the same build, not a coordinate from an earlier version. A
    # displacement computed from it is identically zero for every node, and a
    # diff showing "nothing moved" would report stability that was never
    # measured. Carrying a previous field is not the same as having a prior
    # version to compare against.
    #
    # So the test is displacement, not presence.
    def _moved(node: dict[str, Any]) -> bool:
        px, py = node.get("previous_x"), node.get("previous_y")
        if px is None or py is None:
            return False
        return abs(px - node["x"]) > 0.05 or abs(py - node["y"]) > 0.05

    with_previous = [n for n in nodes if _moved(n)]
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
                f"partial: {len(with_previous)} of {len(nodes)} nodes moved since the last "
                f"layout, so displacement is answerable; which nodes or edges were added "
                f"or removed is not"
            )
            if has_positions
            else (
                (
                    "no displacement either: every node's previous coordinate is a copy of "
                    "its current one from the same build, so nothing has been compared. An "
                    "empty diff here would report stability that was never measured"
                )
                if nodes
                # Caught by 5.1's own check: with NO nodes the message above is
                # false — there are no previous coordinates to be copies of.
                # Two different absences, and saying the wrong one sends the
                # reader to look for a comparison that was never possible.
                else ""
            ),
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
