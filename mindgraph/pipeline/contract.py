"""Stage 0 — the encoding contract, as code, before any rendering exists.

The report's hard rule, verbatim:

> no visual property renders unless its backing field is non-null; a null
> health field forces the UNKNOWN construction.

This module is that rule made mechanical. Every visual channel declares the
data field it reads. Resolution is the only way to get a value out, and a null
backing field cannot produce a measured construction — there is no branch that
does it.

## Why a construction and not a colour

The failure this prevents is subtle and it is the cardinal anti-pattern the
report names: *everything looks healthy*. A renderer that reads
`operational_state` and falls back to a default when it is null draws a
perfectly ordinary circle for a node nothing has ever measured. Nothing looks
missing, because on a graph there is no empty space to notice.

So `resolve` returns a **construction** — a named bundle of how the mark must
be drawn — rather than a value the renderer is free to interpret. `UNKNOWN` is
hatched interior, broken border, "?" glyph. It is not a shade of healthy and
it cannot be reached by defaulting.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import log1p, sqrt
from types import MappingProxyType
from typing import Any

# The report prints every transform and cap in the legend, so they live here as
# named constants rather than as magic numbers inside a painter.
RADIUS_MIN = 6.0
RADIUS_K = 3.4
RADIUS_CAP = 26.0

# Section 4.1: "Preattentive budget: <=3 variables (size, fill+icon, border
# pattern)." Enforced rather than remembered.
PREATTENTIVE_BUDGET = 3


class ContractError(RuntimeError):
    """A visual property was requested that the contract cannot honour."""


class Construction(StrEnum):
    """How a mark must be drawn. Not a colour — a whole treatment.

    `MEASURED` means the backing field was present and the value is real.
    `UNKNOWN` means it was not, and the mark must announce that. There is
    deliberately no third option and no default.
    """

    MEASURED = "measured"
    UNKNOWN = "unknown"


# The UNKNOWN treatment, from Section 4.1: "broken + '?' = none" for the
# border, hatched interior. Held as data so the renderer cannot invent its own
# quieter version.
#
# READ-ONLY, and that is not tidiness. This dict is handed out as the `value`
# of every unresolved channel, so while it was a plain dict a single caller
# writing `resolved.value["fill"] = "solid"` silently changed the treatment for
# every UNKNOWN produced afterwards — turning the cardinal anti-pattern
# ("everything looks healthy") into a one-line accident. Reproduced during
# Stage 0's self-critique.
#
# The backing dict is deleted after wrapping: MappingProxyType is a VIEW, so
# leaving the original bound by name would keep the write path open under a
# different spelling.
_UNKNOWN_TREATMENT: dict[str, Any] = {
    "fill": "hatched",
    "border": "broken",
    "annotation": "?",
    "radius": RADIUS_MIN,
    "makes_zero_claim": False,
}
UNKNOWN_TREATMENT: Mapping[str, Any] = MappingProxyType(_UNKNOWN_TREATMENT)
del _UNKNOWN_TREATMENT


@dataclass(frozen=True)
class Channel:
    """One visual property and the data field it is drawn from.

    `backing` is required and must be non-empty. A channel with no named
    backing field is exactly the thing Stage 0's threshold forbids: a visual
    property that means whatever the painter felt like.
    """

    name: str
    backing: tuple[str, ...]
    describes: str
    transform: str = "identity"

    def __post_init__(self) -> None:
        if not self.backing:
            raise ContractError(
                f"channel {self.name!r} declares no backing field. A visual property with "
                f"no named source encodes the painter's taste, and the reader cannot tell "
                f"the difference."
            )
        if not self.describes.strip():
            raise ContractError(f"channel {self.name!r} does not say what it describes")


# --------------------------------------------------------------------------
# The channel catalogue — Section 4.1 (nodes) and 4.2 (edges), one entry each.
# --------------------------------------------------------------------------

NODE_CHANNELS: tuple[Channel, ...] = (
    Channel(
        name="node.position",
        backing=("x", "y"),
        describes="structural identity and the reader's spatial memory — encodes nothing else",
        transform="baked offline; carried forward within a displacement budget",
    ),
    Channel(
        name="node.radius",
        backing=("lifetime_execution_count",),
        describes="how much traffic this node has ever handled",
        transform=f"{RADIUS_MIN} + {RADIUS_K} * sqrt(log1p(n)), capped at {RADIUS_CAP}",
    ),
    Channel(
        name="node.fill",
        backing=("operational_state",),
        describes="measured operational state ONLY — never a role palette",
    ),
    Channel(
        name="node.border",
        backing=("instrumentation",),
        describes="evidence quality — how much we can see, which is orthogonal to health",
    ),
    Channel(
        name="node.glyph",
        backing=("kind",),
        describes="node role, drawn INSIDE the circle so outlines stay uniform",
    ),
    Channel(
        name="node.birth_flag",
        backing=("first_seen_at",),
        describes="age since first observation, as a static tab — never a pulsing halo",
        transform="now - first_seen_at, against embedded generated_at",
    ),
)

EDGE_CHANNELS: tuple[Channel, ...] = (
    Channel(
        name="edge.rail_width",
        backing=("lifetime_traversal_count",),
        describes="cumulative traversals — monotonic, never decays",
        transform="log1p(count)",
    ),
    Channel(
        name="edge.core_luminance",
        backing=("last_traversal_at",),
        describes="recency — decays, and is a SEPARATE channel from the rail",
        transform="time since last traversal, against embedded data_through",
    ),
    Channel(
        name="edge.endpoint_state",
        backing=("edge_state", "telemetry_coverage"),
        describes="never_observed / dormant / retired / unknown — dead is never inferred from inactivity",
    ),
)

GATE_CHANNELS: tuple[Channel, ...] = (
    Channel(
        name="gate.glyph",
        backing=("disposition",),
        describes="human checkpoint state: awaiting / approved / rejected / escalated / rolled_back",
        transform="rectangle interrupting the edge — not a diamond, which would imply branching",
    ),
)

ALL_CHANNELS: tuple[Channel, ...] = NODE_CHANNELS + EDGE_CHANNELS + GATE_CHANNELS


@dataclass(frozen=True)
class Resolved:
    """The outcome of asking the contract for one visual property."""

    channel: str
    construction: Construction
    value: Any
    reason: str = ""

    @property
    def is_measured(self) -> bool:
        return self.construction is Construction.MEASURED


def _missing(record: dict[str, Any], field: str) -> bool:
    """A field is missing if it is absent OR null. Both mean "we do not know".

    Treating an absent key as different from an explicit null would give the
    pipeline two ways to say the same thing and one of them would eventually
    get a default.
    """
    return record.get(field) is None


def resolve(channel: Channel, record: dict[str, Any]) -> Resolved:
    """The only way to get a visual value out of a record.

    There is no `resolve_or_default`, and that absence is the design. Every
    caller must handle `Construction.UNKNOWN`, because the type gives them
    nothing else to do with it.
    """
    missing = [f for f in channel.backing if _missing(record, f)]
    if missing:
        return Resolved(
            channel=channel.name,
            construction=Construction.UNKNOWN,
            value=UNKNOWN_TREATMENT,
            reason=f"backing field(s) {', '.join(missing)} are null or absent",
        )
    values = tuple(record[f] for f in channel.backing)
    return Resolved(
        channel=channel.name,
        construction=Construction.MEASURED,
        value=values[0] if len(values) == 1 else values,
    )


def radius_for(execution_count: int | None) -> Resolved:
    """Radius, with the transform and cap the legend has to print."""
    if execution_count is None:
        return Resolved(
            channel="node.radius",
            construction=Construction.UNKNOWN,
            value=UNKNOWN_TREATMENT["radius"],
            reason="lifetime_execution_count is null",
        )
    if execution_count < 0:
        raise ContractError(
            f"lifetime_execution_count is {execution_count}; a negative count would produce "
            f"a NaN radius and the node would silently fail to draw"
        )
    r = min(RADIUS_MIN + RADIUS_K * sqrt(log1p(execution_count)), RADIUS_CAP)
    return Resolved(channel="node.radius", construction=Construction.MEASURED, value=r)


def resolve_node(record: dict[str, Any]) -> dict[str, Resolved]:
    resolved = {ch.name: resolve(ch, record) for ch in NODE_CHANNELS}
    resolved["node.radius"] = radius_for(record.get("lifetime_execution_count"))
    return resolved


def resolve_edge(record: dict[str, Any]) -> dict[str, Resolved]:
    return {ch.name: resolve(ch, record) for ch in EDGE_CHANNELS}


def is_unknown_node(resolved: dict[str, Resolved]) -> bool:
    """A node is drawn in the UNKNOWN construction if the channel carrying its
    HEALTH is unresolved.

    Specifically `node.fill`. A node can have an unknown *radius* and still be
    a legitimately measured node with an odd counter; it cannot have an unknown
    *operational state* and be drawn as anything but unknown.
    """
    return not resolved["node.fill"].is_measured


def preattentive_load(resolved: dict[str, Resolved]) -> int:
    """How many independent preattentive variables this mark is using.

    Position is spatial identity and glyph is a label, so neither counts
    against the budget the report sets; size, fill and border pattern do.
    """
    counted = ("node.radius", "node.fill", "node.border")
    return sum(1 for name in counted if name in resolved)


def audit_channels() -> list[str]:
    """Every channel, with its backing field — the material the legend and the
    Stage 0 completeness check are both built from."""
    return [f"{ch.name} <- {'+'.join(ch.backing)} ({ch.transform})" for ch in ALL_CHANNELS]
