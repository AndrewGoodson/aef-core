"""Stage 1.1 — derive the traversal graph from the event log.

A directly-follows graph, in the process-mining sense the report names:
activities are nodes, transitions are edges, frequency is thickness. The
load-bearing observation is that **consecutive execution records within one run
ARE the edge traversals** — if a run recorded `classify` and then
`fetch_invoice`, that edge fired. Nothing new is collected.

## Three inputs, not one

Deriving from the event log alone is the obvious mistake and it is fatal to the
whole point of this artifact: an edge nobody has taken would be
indistinguishable from an edge that does not exist. The report's Section 4.2
defines "never observed" as *configured + valid telemetry + zero count*, so all
three are required:

- the **event log** — what happened
- the **declared topology** — what is configured to exist
- the **coverage declaration** — whether we could have seen it

## What is never inferred

`retired` comes only from an explicit `retired_at`. The report is emphatic that
*dead is NEVER inferred from inactivity alone*, and the difference matters: an
edge that stopped firing is a fact about the agent, while an edge someone
switched off is a fact about a human decision. Inferring the second from the
first would attribute an intention nobody had.

`unknown` beats every other classification. An edge with no telemetry coverage
makes **no zero-count claim**, because absence of evidence here is literally
absence of evidence — we were not looking.

## pm4py was considered and not used

The report names pm4py as the formal tool for DFG discovery and flags it
GPLv3. The derivation below is about forty lines of standard library. Taking on
a copyleft obligation for forty lines would be a poor trade, and the loop's own
rule is to prefer boring.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any


class EdgeState(StrEnum):
    """Section 4.2's taxonomy. `ACTIVE` is the fifth, unnamed there because it
    is the ordinary case; naming it here keeps the classifier total."""

    ACTIVE = "active"
    DORMANT = "dormant"
    NEVER_OBSERVED = "never_observed"
    RETIRED = "retired"
    UNKNOWN = "unknown"


class TraversalError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    """One node execution. The event log is a flat sequence of these."""

    run_id: str
    node_id: str
    at: datetime
    token_cost: int = 0


@dataclass(frozen=True)
class DerivedNode:
    id: str
    kind: str
    instrumentation: str
    lifetime_execution_count: int | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    token_cost: int | None
    operational_state: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "instrumentation": self.instrumentation,
            "lifetime_execution_count": self.lifetime_execution_count,
            "first_seen_at": _iso(self.first_seen_at),
            "last_seen_at": _iso(self.last_seen_at),
            "token_cost": self.token_cost,
            "operational_state": self.operational_state,
        }


@dataclass(frozen=True)
class DerivedEdge:
    source: str
    target: str
    edge_state: EdgeState
    lifetime_traversal_count: int | None
    last_traversal_at: datetime | None
    telemetry_coverage: str
    retired_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "edge_state": self.edge_state.value,
            "lifetime_traversal_count": self.lifetime_traversal_count,
            "last_traversal_at": _iso(self.last_traversal_at),
            "telemetry_coverage": self.telemetry_coverage,
        }
        if self.retired_at is not None:
            payload["retired_at"] = _iso(self.retired_at)
        return payload


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_events(path: Path) -> list[Event]:
    """One JSON object per line. A malformed line RAISES rather than being
    skipped: silently dropping events would understate every count on the page,
    and an understated count is indistinguishable from a quiet agent."""
    events: list[Event] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            record = json.loads(line)
            at = _parse(record["at"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise TraversalError(
                f"{path}:{lineno} is malformed ({exc}). Refusing to skip it — a dropped "
                f"event understates a count, and an understated count reads as a quiet "
                f"agent rather than as a broken pipeline."
            ) from exc
        assert at is not None
        events.append(
            Event(
                run_id=record["run_id"],
                node_id=record["node_id"],
                at=at,
                token_cost=record.get("token_cost", 0),
            )
        )
    return events


def runs_from(events: Iterable[Event]) -> dict[str, list[Event]]:
    """Group by run, ordered within each run.

    Sorted by timestamp rather than trusting file order — an event log
    assembled from several exporters interleaves, and getting the order wrong
    silently invents edges that never fired.
    """
    runs: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        runs[event.run_id].append(event)
    return {run_id: sorted(evts, key=lambda e: e.at) for run_id, evts in runs.items()}


def derive(
    events: Sequence[Event],
    topology: dict[str, Any],
    *,
    data_through: datetime,
) -> tuple[list[DerivedNode], list[DerivedEdge]]:
    """The directly-follows graph, classified against the declared topology."""
    dormancy = timedelta(days=topology.get("dormancy_window_days", 14))
    declared_nodes = {n["id"]: n for n in topology["nodes"]}
    declared_edges = {(e["source"], e["target"]): e for e in topology["edges"]}

    counts: dict[str, int] = defaultdict(int)
    tokens: dict[str, int] = defaultdict(int)
    first: dict[str, datetime] = {}
    last: dict[str, datetime] = {}
    traversals: dict[tuple[str, str], int] = defaultdict(int)
    last_traversal: dict[tuple[str, str], datetime] = {}

    for run in runs_from(events).values():
        for event in run:
            counts[event.node_id] += 1
            tokens[event.node_id] += event.token_cost
            # min/max rather than first-write-wins: logs arrive out of order,
            # and a late-arriving old event must not redate a node's birth.
            first[event.node_id] = min(first.get(event.node_id, event.at), event.at)
            last[event.node_id] = max(last.get(event.node_id, event.at), event.at)
        for a, b in zip(run, run[1:], strict=False):
            key = (a.node_id, b.node_id)
            traversals[key] += 1
            last_traversal[key] = max(last_traversal.get(key, b.at), b.at)

    observed_only = set(counts) - set(declared_nodes)
    if observed_only:
        raise TraversalError(
            f"the event log contains nodes absent from the declared topology: "
            f"{sorted(observed_only)}. Either the topology is stale or the log is from a "
            f"different graph; drawing them anyway would present unconfigured activity as "
            f"part of the design."
        )

    nodes: list[DerivedNode] = []
    for node_id, declared in declared_nodes.items():
        instrumented = declared.get("telemetry_coverage") != "none"
        seen = last.get(node_id)
        # Found by wiring the contract in: the derivation produced no health
        # field at all, so EVERY node resolved UNKNOWN — correctly, since the
        # contract refuses to invent health from an absent field.
        #
        # What the event log can honestly support is exactly two states.
        # `degraded` and `failed` would need an error signal the log does not
        # carry, and inventing collection to make the picture look better is
        # forbidden. So they are absent, and their absence is a finding rather
        # than a gap to paper over.
        if not instrumented:
            operational_state = None
        elif seen is None:
            operational_state = "never_executed"
        elif data_through - seen > dormancy:
            operational_state = "stale"
        else:
            operational_state = "normal"
        nodes.append(
            DerivedNode(
                id=node_id,
                kind=declared["kind"],
                instrumentation=declared["instrumentation"],
                # An uninstrumented node reports None, not 0. Zero is a
                # measurement; None is "we were not looking", and the contract
                # turns the second into the UNKNOWN construction.
                lifetime_execution_count=counts.get(node_id, 0) if instrumented else None,
                first_seen_at=first.get(node_id) if instrumented else None,
                last_seen_at=last.get(node_id) if instrumented else None,
                token_cost=tokens.get(node_id, 0) if instrumented else None,
                operational_state=operational_state,
            )
        )

    edges: list[DerivedEdge] = []
    for (source, target), declared in declared_edges.items():
        coverage = declared.get("telemetry_coverage", "full")
        count = traversals.get((source, target), 0)
        seen_at = last_traversal.get((source, target))
        retired_at = _parse(declared.get("retired_at"))

        if coverage == "none":
            # Beats everything else, and makes NO zero-count claim.
            state, count_out, seen_out = EdgeState.UNKNOWN, None, None
        elif retired_at is not None:
            state, count_out, seen_out = EdgeState.RETIRED, count, seen_at
        elif count == 0:
            state, count_out, seen_out = EdgeState.NEVER_OBSERVED, 0, None
        elif seen_at is not None and data_through - seen_at > dormancy:
            state, count_out, seen_out = EdgeState.DORMANT, count, seen_at
        else:
            state, count_out, seen_out = EdgeState.ACTIVE, count, seen_at

        edges.append(
            DerivedEdge(
                source=source,
                target=target,
                edge_state=state,
                lifetime_traversal_count=count_out,
                last_traversal_at=seen_out,
                telemetry_coverage=coverage,
                retired_at=retired_at,
            )
        )

    undeclared = set(traversals) - set(declared_edges)
    if undeclared:
        raise TraversalError(
            f"observed traversals with no declared edge: {sorted(undeclared)}. The agent "
            f"took a path its own topology does not describe — that is a finding, not "
            f"something to draw silently."
        )

    nodes.sort(key=lambda n: n.id)
    edges.sort(key=lambda e: (e.source, e.target))
    return nodes, edges
