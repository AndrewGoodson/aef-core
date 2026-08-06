"""Stage 1.3 — the build entry point, and the layout state that survives it.

`layout.py` can carry positions forward within one process. That is not the
property the artifact needs. The property is that **build N+1 reproduces build
N's coordinates**, which means the positions have to outlive the process — so
this module owns a persisted layout state and is the only thing that writes it.

Run twice over unchanged inputs and the coordinates are identical. Add a node
and every existing node stays put within the displacement budget while the new
one is seeded from its neighbours. That is the whole of Stage 3's threshold,
established here rather than asserted later.

## Why the state file is separate from the artifact

The delivered HTML is a snapshot: it carries the positions it was built with.
The state file is the pipeline's memory across builds. Conflating them would
mean reading coordinates back out of the rendered page, which makes the artifact
an input to its own generation — and a corrupted or hand-edited page would then
silently rewrite the layout everyone else sees.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from math import log1p
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as contract_mod  # noqa: E402
import layout as layout_mod  # noqa: E402
import traversal as traversal_mod  # noqa: E402

STATE_VERSION = 1
STATE_FILENAME = "layout-state.json"


class BuildError(RuntimeError):
    pass


def load_state(path: Path, graph_id: str) -> dict[str, tuple[float, float]]:
    """Previous coordinates, or empty on a first build.

    A missing file is a first build. A CORRUPT file raises: starting fresh
    would silently rearrange every node on the page, and the operator would
    read that as the agent having been rewired rather than as a broken
    pipeline.
    """
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(
            f"{path} is unreadable ({exc}). Refusing to start fresh — that would rearrange "
            f"every node, and the operator would read a broken pipeline as a rewired agent."
        ) from exc
    if payload.get("version") != STATE_VERSION:
        raise BuildError(
            f"layout state version {payload.get('version')!r} is not {STATE_VERSION}; "
            f"refusing to reinterpret coordinates written under a different shape"
        )
    if payload.get("graph_id") != graph_id:
        raise BuildError(
            f"{path} holds the layout for {payload.get('graph_id')!r}, not {graph_id!r}. "
            f"Two graphs sharing one state file would blend their maps into a picture of "
            f"neither."
        )
    return {n["id"]: (n["x"], n["y"]) for n in payload.get("nodes", [])}


def save_state(
    path: Path, graph_id: str, placed: dict[str, layout_mod.Placed], layout_version: int
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "version": STATE_VERSION,
        "graph_id": graph_id,
        "layout_version": layout_version,
        "nodes": [
            {"id": p.node_id, "x": p.x, "y": p.y}
            for p in sorted(placed.values(), key=lambda p: p.node_id)
        ],
    }
    path.write_text(
        json.dumps(body, sort_keys=True, separators=(",", ":"), indent=2) + "\n",
        encoding="utf-8",
    )


def build(
    *,
    events_path: Path,
    topology_path: Path,
    state_path: Path,
    generated_at: datetime,
    data_through: datetime,
) -> dict[str, Any]:
    """Derive, lay out, persist, and return the payload.

    `generated_at` and `data_through` are passed IN rather than read from the
    clock. A pipeline that stamps `datetime.now()` produces a different artifact
    every run over identical data, which destroys the byte-stability the state
    file exists to provide — and makes "did anything actually change?"
    unanswerable from a diff.
    """
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    graph_id = topology["graph_id"]
    dormancy_days = float(topology.get("dormancy_window_days", 14))
    # Gate dispositions are human decisions declared in config. Deriving one
    # from the event log would attribute an approval to nobody.
    gates = {
        (g["edge"][0], g["edge"][1]): g
        for g in topology.get("gates", [])
        if not str(g.get("disposition", "")).startswith("_")
    }
    events = traversal_mod.read_events(events_path)
    nodes, edges = traversal_mod.derive(events, topology, data_through=data_through)

    previous = load_state(state_path, graph_id)
    node_ids = [n.id for n in nodes]
    edge_tuples = [(e.source, e.target, e.lifetime_traversal_count or 0) for e in edges]

    # Reproduced on this increment's first run: building twice over UNCHANGED
    # inputs moved every node. Relaxation was applied unconditionally, so each
    # build seeded from the last build's output and drifted further — the
    # artifact churned on every build, could not be diffed, and the reader's
    # mental map decayed a little each time for no reason at all.
    #
    # The layout is recomputed when the TOPOLOGY changes, not when a build
    # runs. An unchanged node set means there is nothing to accommodate, so the
    # carried coordinates are returned verbatim.
    topology_changed = set(node_ids) != set(previous)
    if previous and not topology_changed:
        placed = {
            n: layout_mod.Placed(n, previous[n][0], previous[n][1], previous[n][0], previous[n][1], "carried")
            for n in sorted(node_ids)
        }
    else:
        placed = layout_mod.compute(node_ids, edge_tuples, previous)

    over = layout_mod.over_budget(placed)
    if over:
        raise BuildError(
            f"nodes exceeded the displacement budget: {over}. The budget is what keeps the "
            f"reader's mental map valid across versions; exceeding it silently is worse "
            f"than failing the build."
        )

    # The layout version tracks the LAYOUT, not the build count. Bumping it on
    # every run would make "which version of the map am I looking at?"
    # meaningless, and the displacement budget is stated per layout version.
    layout_version = int(topology.get("layout_version", 1))
    if previous and topology_changed:
        layout_version += 1
    save_state(state_path, graph_id, placed, layout_version)

    node_payloads = []
    for node in nodes:
        body = node.to_payload()
        body.update(placed[node.id].to_payload())
        body["id"] = node.id
        # The CONTRACT decides the construction, here, at build time — and the
        # decision is baked in. The page draws what it is told; it never
        # re-derives health from a field, so there is no code path in the
        # browser that could produce a healthy circle over a null.
        resolved = contract_mod.resolve_node(body)
        body["render"] = {
            "construction": (
                contract_mod.Construction.UNKNOWN.value
                if contract_mod.is_unknown_node(resolved)
                else contract_mod.Construction.MEASURED.value
            ),
            "radius": (
                resolved["node.radius"].value
                if resolved["node.radius"].is_measured
                else contract_mod.UNKNOWN_TREATMENT["radius"]
            ),
            "fill_state": (
                resolved["node.fill"].value if resolved["node.fill"].is_measured else None
            ),
            "border": (
                resolved["node.border"].value if resolved["node.border"].is_measured else "broken"
            ),
            "glyph": resolved["node.glyph"].value if resolved["node.glyph"].is_measured else "?",
            "annotation": (
                "" if resolved["node.fill"].is_measured else contract_mod.UNKNOWN_TREATMENT["annotation"]
            ),
        }
        node_payloads.append(body)

    return {
        "schema_version": 1,
        "graph_id": graph_id,
        "layout_version": layout_version,
        "generated_at": _iso(generated_at),
        "data_through": _iso(data_through),
        "expected_report_interval_seconds": topology.get(
            "expected_report_interval_seconds", 3600
        ),
        "nodes": sorted(node_payloads, key=lambda n: str(n["id"])),
        "edges": [
            _edge_render(e.to_payload(), data_through, dormancy_days, gates) for e in edges
        ],
    }


GATE_GLYPH = {
    "awaiting": "H\u2026",
    "approved": "H\u2713",
    "rejected": "H\u2717",
    "escalated": "H!",
    "rolled_back": "H\u21b6",
}


def _edge_render(
    body: dict[str, Any],
    data_through: datetime,
    dormancy_days: float,
    gates: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Two channels, computed here and never in the browser.

    They are kept independent on purpose, and that independence IS the feature:

    - **rail width** comes from the cumulative traversal count and never
      decays, so a path that was once busy stays visibly wide forever;
    - **core luminance** comes from recency alone and decays to zero.

    A single blended "activity" number would collapse the two cases this whole
    artifact exists to separate — an abandoned path (wide rail, dark core) and
    a path never taken (hairline rail, no core) would land on the same faint
    line. `core_luminance` is **null**, never 0.0, when there is nothing to
    measure: a zero is a reading, and null is the absence of one.
    """
    count = body.get("lifetime_traversal_count")
    last = body.get("last_traversal_at")
    gate = (gates or {}).get((body["source"], body["target"]))
    if gate is not None:
        disposition = gate["disposition"]
        if disposition not in GATE_GLYPH:
            raise BuildError(
                f"gate on {body['source']}->{body['target']} has disposition "
                f"{disposition!r}, which has no glyph. An unrecognised disposition would "
                f"draw nothing, and a checkpoint that renders as no checkpoint is the one "
                f"mark an operator must never miss."
            )
        body["gate"] = {
            "disposition": disposition,
            "glyph": GATE_GLYPH[disposition],
            "pending_since": gate.get("pending_since"),
            "decided_at": gate.get("decided_at"),
        }

    if count is None:
        # Unknown coverage makes no count claim, so it gets no rail width
        # claim either.
        body["render"] = {
            "construction": "unknown",
            "rail_width": None,
            "core_luminance": None,
        }
        return body

    if last is None:
        luminance = None  # never fired: an absence, not a dim reading
    else:
        seen = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        days = max(0.0, (data_through - seen).total_seconds() / 86400.0)
        luminance = max(0.0, min(1.0, 1.0 - (days / dormancy_days)))

    body["render"] = {
        "construction": "measured",
        "rail_width": round(log1p(count), 4),
        "core_luminance": None if luminance is None else round(luminance, 4),
    }
    return body


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise BuildError(
            "timestamps must be timezone-aware; a naive one means a different instant "
            "depending on where the page is opened, and every visible age is computed "
            "from these"
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="build the mind-graph payload")
    parser.add_argument("--events", type=Path, default=root / "fixtures" / "events.jsonl")
    parser.add_argument("--topology", type=Path, default=root / "fixtures" / "topology.json")
    parser.add_argument("--state", type=Path, default=root / "build" / STATE_FILENAME)
    parser.add_argument("--out", type=Path, default=root / "build" / "payload.json")
    parser.add_argument(
        "--html", type=Path, default=root / "dist" / "index.html",
        help="the delivered single-file artifact",
    )
    parser.add_argument(
        "--generated-at",
        default="2026-08-05T18:00:00Z",
        help="pinned rather than read from the clock, so the build is reproducible",
    )
    parser.add_argument("--data-through", default="2026-08-05T17:42:00Z")
    args = parser.parse_args(argv)

    payload = build(
        events_path=args.events,
        topology_path=args.topology,
        state_path=args.state,
        generated_at=_parse(args.generated_at),
        data_through=_parse(args.data_through),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), indent=2) + "\n",
        encoding="utf-8",
    )
    import emit as emit_mod

    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(emit_mod.emit(payload), encoding="utf-8")

    reasons: dict[str, int] = {}
    for node in payload["nodes"]:
        reasons[node["layout_reason"]] = reasons.get(node["layout_reason"], 0) + 1
    print(
        f"built {len(payload['nodes'])} nodes, {len(payload['edges'])} edges "
        f"-> {args.html}  (layout v{payload['layout_version']}, {reasons})"
    )
    return 0


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


if __name__ == "__main__":
    raise SystemExit(main())
