"""Stage 1.2 — compute the layout OFFLINE, deterministically.

Positions are baked into the artifact at generation time. The delivered file
never runs a layout, which is what makes the map stable: the report's verdict
on the persistence dispute is that a fresh runtime layout renders the same data
differently on every open and destroys the spatial memory that is the whole
value.

## Determinism is a hard constraint, not a preference

`Math.random` is forbidden in the delivered file, and the same rule applies
here for a stronger reason: if the pipeline is random, two runs over identical
data produce different coordinates, the artifact churns on every build, and
"zero coordinate drift between two opens" (Stage 3's threshold) becomes
untestable. So there is no RNG in this module at all. Where a choice would
normally be random — where to put a node with nothing to anchor it to — the
report specifies the substitute: **perimeter placement by hash of the stable
ID**.

## Seeding, in the order the report gives

1. **Carried** — the node already has a position from the previous layout
   version. Keep it.
2. **Weighted centroid** — a new node with positioned neighbours starts at
   their centre of mass, weighted by edge traversals, so it appears where it
   belongs rather than drifting in from nowhere.
3. **Perimeter by hash** — a new node with no positioned neighbour goes on the
   ring, at an angle derived from a digest of its id. Deterministic, spread
   out, and stable: the same node lands in the same place every build.

`layout_reason` records which of the three applied, per node. Without it, a
node that moved and a node that was placed for the first time are
indistinguishable in the output, and only one of those is worth an operator's
attention.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import blake2b
from math import cos, isfinite, pi, sin, sqrt
from typing import Any

# The report's displacement budget: a node may move about one diameter per
# layout version. Bigger jumps are what destroy the reader's mental map, so
# this is enforced rather than hoped for.
NODE_DIAMETER = 52.0
DISPLACEMENT_BUDGET = NODE_DIAMETER

CANVAS_W = 900.0
CANVAS_H = 560.0
PERIMETER_RADIUS = 240.0

# Fixed iteration count. Not "until it converges" — a convergence test whose
# result depends on floating-point ordering is a subtle source of run-to-run
# difference, and this module must have none.
ITERATIONS = 220
REPULSION = 5200.0
SPRING = 0.010
IDEAL_EDGE_LENGTH = 130.0
DAMPING = 0.86
MAX_STEP = 6.0

# Coordinates are rounded before they are emitted. Unrounded floats differ in
# the last bits between platforms, and an artifact that differs byte-for-byte
# on every build cannot be diffed — so nobody notices the change that mattered.
PRECISION = 1


class LayoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class Placed:
    node_id: str
    x: float
    y: float
    previous_x: float | None
    previous_y: float | None
    layout_reason: str

    @property
    def displacement(self) -> float:
        if self.previous_x is None or self.previous_y is None:
            return 0.0
        return sqrt((self.x - self.previous_x) ** 2 + (self.y - self.previous_y) ** 2)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "x": self.x,
            "y": self.y,
            "previous_x": self.previous_x,
            "previous_y": self.previous_y,
            "layout_reason": self.layout_reason,
        }


def perimeter_angle(node_id: str) -> float:
    """A stable angle in [0, 2pi) derived from the node id.

    `blake2b` rather than the builtin `hash()`: Python salts string hashing per
    process by default, so `hash()` would place the same node somewhere
    different on every run — the exact non-determinism this module exists to
    avoid, arriving through a function that looks pure.
    """
    digest = blake2b(node_id.encode("utf-8"), digest_size=8).digest()
    return (int.from_bytes(digest, "big") / float(1 << 64)) * 2.0 * pi


def seed(
    node_ids: Sequence[str],
    edges: Sequence[tuple[str, str, int]],
    previous: Mapping[str, tuple[float, float]],
) -> dict[str, Placed]:
    """Initial positions, by the report's three-step rule."""
    placed: dict[str, Placed] = {}

    for node_id in node_ids:
        if node_id in previous:
            px, py = previous[node_id]
            placed[node_id] = Placed(node_id, px, py, px, py, "carried")

    # Weighted centroid, iterated: placing one new node can give its neighbour
    # something to anchor to, so a chain of new nodes resolves inward rather
    # than all landing on the perimeter.
    remaining = [n for n in node_ids if n not in placed]
    progress = True
    while remaining and progress:
        progress = False
        still: list[str] = []
        for node_id in remaining:
            weighted: list[tuple[float, float, float]] = []
            for source, target, count in edges:
                other = target if source == node_id else source if target == node_id else None
                if other is None or other not in placed:
                    continue
                # +1 so a declared-but-never-traversed neighbour still anchors.
                # A zero weight would silently drop the only anchor a new node
                # has, and it would land on the perimeter as if unrelated.
                weight = float(count) + 1.0
                weighted.append((placed[other].x, placed[other].y, weight))
            if not weighted:
                still.append(node_id)
                continue
            total = sum(w for _, _, w in weighted)
            cx = sum(x * w for x, _, w in weighted) / total
            cy = sum(y * w for _, y, w in weighted) / total
            placed[node_id] = Placed(node_id, cx, cy, None, None, "seeded_centroid")
            progress = True
        remaining = still

    for node_id in remaining:
        angle = perimeter_angle(node_id)
        placed[node_id] = Placed(
            node_id,
            CANVAS_W / 2.0 + PERIMETER_RADIUS * cos(angle),
            CANVAS_H / 2.0 + PERIMETER_RADIUS * sin(angle),
            None,
            None,
            "seeded_perimeter",
        )

    return placed


def relax(
    placed: Mapping[str, Placed],
    edges: Sequence[tuple[str, str, int]],
    *,
    iterations: int = ITERATIONS,
) -> dict[str, Placed]:
    """Bounded force relaxation, then clamp every carried node to the budget.

    Nodes are processed in sorted id order throughout. Iterating a dict in
    insertion order would make the result depend on how the graph was
    assembled, which is a difference that survives into the coordinates.
    """
    ids = sorted(placed)
    pos = {n: [placed[n].x, placed[n].y] for n in ids}
    vel = {n: [0.0, 0.0] for n in ids}
    adjacency = [(s, t) for s, t, _ in edges if s in pos and t in pos]

    for _ in range(iterations):
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                dx = pos[b][0] - pos[a][0]
                dy = pos[b][1] - pos[a][1]
                dist_sq = dx * dx + dy * dy
                if dist_sq < 1e-6:
                    # Coincident nodes: separate them along a direction derived
                    # from the id, never a random jitter.
                    angle = perimeter_angle(a + "|" + b)
                    dx, dy, dist = cos(angle), sin(angle), 1.0
                else:
                    dist = sqrt(dist_sq)
                    dx, dy = dx / dist, dy / dist
                force = REPULSION / max(dist * dist, 1.0)
                vel[a][0] -= dx * force
                vel[a][1] -= dy * force
                vel[b][0] += dx * force
                vel[b][1] += dy * force

        for source, target in adjacency:
            dx = pos[target][0] - pos[source][0]
            dy = pos[target][1] - pos[source][1]
            dist = sqrt(dx * dx + dy * dy) or 1e-6
            force = (dist - IDEAL_EDGE_LENGTH) * SPRING
            ux, uy = dx / dist, dy / dist
            vel[source][0] += ux * force
            vel[source][1] += uy * force
            vel[target][0] -= ux * force
            vel[target][1] -= uy * force

        for n in ids:
            vel[n][0] += (CANVAS_W / 2.0 - pos[n][0]) * 0.0016
            vel[n][1] += (CANVAS_H / 2.0 - pos[n][1]) * 0.0016
            vel[n][0] *= DAMPING
            vel[n][1] *= DAMPING
            pos[n][0] += max(-MAX_STEP, min(MAX_STEP, vel[n][0]))
            pos[n][1] += max(-MAX_STEP, min(MAX_STEP, vel[n][1]))
            pos[n][0] = max(NODE_DIAMETER, min(CANVAS_W - NODE_DIAMETER, pos[n][0]))
            pos[n][1] = max(NODE_DIAMETER, min(CANVAS_H - NODE_DIAMETER, pos[n][1]))

    out: dict[str, Placed] = {}
    for n in ids:
        prior = placed[n]
        x, y = pos[n][0], pos[n][1]
        if prior.previous_x is not None and prior.previous_y is not None:
            # The displacement budget. A carried node that the simulation wants
            # to move further than one diameter is pulled back onto the budget
            # circle: the reader's memory of where it was matters more than the
            # layout's opinion about where it belongs.
            dx, dy = x - prior.previous_x, y - prior.previous_y
            travelled = sqrt(dx * dx + dy * dy)
            if travelled > DISPLACEMENT_BUDGET:
                scale = DISPLACEMENT_BUDGET / travelled
                x = prior.previous_x + dx * scale
                y = prior.previous_y + dy * scale
        reason = prior.layout_reason
        if reason == "carried" and (round(x, PRECISION), round(y, PRECISION)) != (
            round(prior.previous_x or 0.0, PRECISION),
            round(prior.previous_y or 0.0, PRECISION),
        ):
            reason = "relaxed"
        out[n] = Placed(
            node_id=n,
            x=round(x, PRECISION),
            y=round(y, PRECISION),
            previous_x=prior.previous_x,
            previous_y=prior.previous_y,
            layout_reason=reason,
        )
    return out


def compute(
    node_ids: Sequence[str],
    edges: Sequence[tuple[str, str, int]],
    previous: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, Placed]:
    if not node_ids:
        raise LayoutError("no nodes to lay out")
    if len(set(node_ids)) != len(node_ids):
        raise LayoutError(
            "duplicate node ids; positions are keyed by id, so a duplicate would silently "
            "discard one node's placement"
        )
    previous = previous or {}
    # Reproduced: an infinite or NaN carried coordinate propagates through the
    # simulation and is serialised by json.dumps as a bare `Infinity`/`NaN`,
    # which JSON.parse rejects — so one bad coordinate renders the ENTIRE page
    # empty. Refused at the boundary rather than sanitised, because a silently
    # corrected position is a position the operator cannot trust.
    bad = sorted(
        n for n, (x, y) in previous.items() if not (isfinite(x) and isfinite(y))
    )
    if bad:
        raise LayoutError(
            f"carried positions for {bad} are non-finite. json.dumps writes bare "
            f"Infinity/NaN, JSON.parse rejects it, and the whole page renders empty "
            f"because of one coordinate."
        )
    return relax(seed(sorted(node_ids), edges, previous), edges)


def over_budget(placed: Mapping[str, Placed]) -> list[str]:
    """Carried nodes that moved further than the budget allows. Should always
    be empty; returned rather than asserted so the verifier can report which."""
    return sorted(
        n for n, p in placed.items() if p.displacement > DISPLACEMENT_BUDGET + 10**-PRECISION
    )
