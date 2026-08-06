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

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

ACCUMULATED = "accumulated_present"
DIFFERENCE = "difference_map"
SCRUBBER = "scrubber"


def traffic_windows(events: Any) -> dict[str, Any] | None:
    """Measure whether a SEQUENCE of any kind exists in the event log.

    5.3 asked whether the scrubber could be built, and the useful answer turned
    out not to be a flat no. A sequence does exist — it is simply not the one
    Section 3g's scrubber is about, and the distinction is worth measuring
    rather than hand-waving, because "there is a timeline in the data" is
    exactly the observation that would tempt a later contributor to wire a
    scrubber onto the wrong axis.

    Returns the per-calendar-month set of edges that carried traffic. `None`
    when there is nothing to measure.
    """
    if not events:
        return None

    runs: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        runs[event.run_id].append(event)

    by_window: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for entries in runs.values():
        ordered = sorted(entries, key=lambda e: e.at)
        window = ordered[0].at.strftime("%Y-%m")
        for first, second in zip(ordered, ordered[1:], strict=False):
            by_window[window].add((first.node_id, second.node_id))

    if len(by_window) < 2:
        return None

    counts = [len(by_window[w]) for w in sorted(by_window)]
    sets = list(by_window.values())
    return {
        "window_count": len(by_window),
        "edges_per_window": counts,
        "edge_set_varies": any(s != sets[0] for s in sets),
    }


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


def _scrubber_partial(windows: dict[str, Any] | None) -> str:
    """State the sequence that DOES exist, and why it answers a different question.

    Saying only "no sequence" would be false — the event log is timestamped and
    the observed traffic does change across windows. Saying "a sequence exists"
    without the qualifier would be worse, because the reader would expect the
    scrubber to arrive by wiring it to that axis, and the resulting control
    would be labelled "wiring versions" while scrubbing traffic.
    """
    if not windows or not windows.get("edge_set_varies"):
        return ""
    # Guarded here as well as at the measurement, because this is the function
    # that writes the sentence. A probe that fabricated `edge_set_varies` on a
    # single window produced "the event log spans 1 windows and the set of edges
    # carrying traffic changes across them" — one window is not a sequence, and
    # the claim would have been false in the exact way the sentence exists to
    # prevent. The writer of a claim refuses it; it does not delegate that
    # upstream and hope.
    if int(windows.get("window_count", 0)) < 2:
        return ""
    counts = " → ".join(str(c) for c in windows["edges_per_window"])
    return (
        f"a DIFFERENT sequence does exist: the event log spans {windows['window_count']} "
        f"windows and the set of edges carrying traffic changes across them ({counts} "
        f"distinct edges). That is traffic over time, not wiring over time — the "
        f"declared edge set never changed. A scrubber built on it would answer “when "
        f"did this path go quiet”, not “what did the wiring look like at version "
        f"5”, and presenting the first as the second is the substitution this page "
        f"exists to refuse"
    )


def build(payload: dict[str, Any], windows: dict[str, Any] | None = None) -> dict[str, Any]:
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
            describes=(
                "trajectory across many WIRING versions, user-initiated, staged "
                "add/remove/persist transitions"
            ),
            available=False,
            requires=(
                "two independent things, and the absence of either alone is fatal. (1) a "
                "SEQUENCE of retained wiring versions: topology.json carries layout_version "
                "as a single scalar and no history, and the layout-state file is overwritten "
                "on every build, so there is no earlier version to scrub back to. (2) staged "
                "transitions, which are motion — motion is banned outright in this artifact, "
                "so the GraphDiaries treatment Section 3g specifies cannot be drawn here at "
                "all, with or without a sequence"
            ),
            partial=_scrubber_partial(windows),
        ),
    ]

    return {
        "current": ACCUMULATED,
        # Stated so nothing downstream has to infer it from the list length.
        "available_count": sum(1 for m in modes if m.available),
        "modes": [m.to_payload() for m in modes],
        "has_prior_topology": has_prior_topology,
        # Section 5 requires the page to respect prefers-reduced-motion and to keep
        # every static end-state fully interpretable. With motion banned outright
        # there is no transient state to end from — the static end-state is the
        # ONLY state, in both motion preferences. Stated as a field so the
        # verifier can render both preferences and compare, rather than take the
        # claim on trust.
        "static_only": True,
        "note": (
            "Section 3g makes the difference map primary and the scrubber secondary. "
            "Neither is offered here, because offering a mode that cannot be drawn is "
            "worse than offering fewer and saying why. Nothing on this page moves under "
            "either motion preference, so what you see is already the end state"
        ),
    }
