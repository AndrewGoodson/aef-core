"""The child process that evaluates ONE node at a time and nothing else.

Three times a control was added to stop a candidate authoring the evidence
that judged it, and three times it was defeated (ADR 0085, 0088, 0093). Every
one of those fixes tried to make an in-process channel trustworthy, and none
could: the candidate's code and the reporting code shared an interpreter, so
any channel the reporter could write, the candidate could write.

So the reporting moved out. **This process does not know what a scenario is,
how many there are, what an `Outcome` is, or whether anything passed.** It
loads a graph, and then answers one question repeatedly: given this node, this
state and this context, what `(delta, route)` does the node return?

The parent owns the state, the routing, the step count, the trace and the
classification. What a candidate can still lie about is exactly what a node
returns — which is the surface the corpus, the tripwires and G2 are built to
judge. It can no longer claim scenarios it never ran, fabricate an aggregate,
or exit cleanly and have that read as success (ADR 0094).

Protocol: newline-delimited JSON on stdin/stdout, one request per line.
Deliberately boring — a candidate that writes garbage to stdout produces a
frame the parent cannot decode, which is a failed node, which is a result the
parent already knows how to handle.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from aef.harness.trace_codec import decode_context, encode_route
from aef.kernel.contracts import Edge, Node
from aef.kernel.graph import Graph
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta


def _frame(value: Any) -> str:
    """One frame, one line. `trace_codec.dumps` pretty-prints for corpus
    files on disk; a newline-delimited protocol needs the opposite."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _unframe(text: str) -> Any:
    return json.loads(text)


class WorkerError(RuntimeError):
    pass


def load_graph(entrypoint: str) -> Graph:
    """`module:factory`. Any raise — including `SystemExit` — is a bad
    entrypoint, not a clean exit (ADR 0085)."""
    import importlib

    if ":" not in entrypoint:
        raise WorkerError(f"entrypoint {entrypoint!r} must be '<module>:<factory>'")
    module_name, attribute = entrypoint.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001 - agent-authored import
        raise WorkerError(f"cannot import {module_name!r}: {type(exc).__name__}: {exc}") from exc
    factory = getattr(module, attribute, None)
    if factory is None:
        raise WorkerError(f"{module_name!r} has no attribute {attribute!r}")
    try:
        graph = factory()
    except BaseException as exc:  # noqa: BLE001 - agent-authored factory
        raise WorkerError(f"{entrypoint} raised {type(exc).__name__}: {exc}") from exc
    if not isinstance(graph, Graph):
        raise WorkerError(f"{entrypoint} returned {type(graph).__name__}, expected a Graph")
    return graph


def describe(graph: Graph) -> dict[str, Any]:
    """The graph's SHAPE, for the parent to drive with.

    This is the candidate's declaration about itself, exactly like its source
    — and it is judged the same way, by G0 and G4 reading the base ref. What
    matters here is that the parent, not the child, decides what to do with
    it.
    """
    return {
        "id": graph.id,
        "version": graph.version,
        "entry_node": graph.entry_node,
        "nodes": [
            {
                "id": node.id,
                "version": node.version,
                "deterministic": node.deterministic,
                "side_effects": node.side_effects.value,
                "fallback_node_id": node.fallback_node_id,
                "telemetry_tags": list(node.telemetry_tags),
                "has_idempotency_key_fn": node.idempotency_key_fn is not None,
            }
            for node in graph.nodes.values()
        ],
        "edges": [
            {
                "from_node": edge.from_node,
                "to_node": edge.to_node if isinstance(edge.to_node, str) else list(edge.to_node),
                "priority": edge.priority,
                "requires_human_approval": edge.requires_human_approval,
                "requires_deterministic_fallback": edge.requires_deterministic_fallback,
            }
            for edge in graph.edges
        ],
    }


def _evaluate(graph: Graph, request: dict[str, Any], services: Any) -> dict[str, Any]:
    node: Node | None = graph.nodes.get(request["node_id"])
    if node is None:
        return {"error": f"no such node {request['node_id']!r}"}
    state = AEFState.model_validate(request["state"])
    context = decode_context(request["context"])
    try:
        delta, route = node.fn(state, context, services)
    except BaseException as exc:  # noqa: BLE001 - the node is agent-authored
        # Reported as data, not raised. The parent decides what a failing node
        # means — fallback, error entry, or failed scenario — because the
        # parent is what the gates read.
        return {"error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(delta, StateDelta):
        return {"error": f"node returned {type(delta).__name__}, expected a StateDelta"}
    return {"delta": json.loads(delta.model_dump_json()), "route": encode_route(route)}


def _edges_for(graph: Graph) -> list[Edge]:  # pragma: no cover - kept for symmetry
    return list(graph.edges)


def _configure(services: Any, settings: Any) -> Any:
    """Swap the model provider for the scenario's cassette (ADR 0123).

    Only the provider changes. The rest of `services` — memory in
    particular — is kept, because one worker serves the whole corpus so
    module-level and store-level agent state behave as they do in
    production, and rebuilding everything per scenario would quietly undo
    that. A live provider is built ONLY when the parent says so, from the
    impl and model it passes; nothing here reads a config file, since the
    workspace's config is the candidate's to edit (ADR 0082).
    """
    from dataclasses import replace

    from aef.providers.cassette_provider import CassetteProvider, RecordedCall

    if not isinstance(settings, dict):
        raise WorkerError(f"configure payload must be an object, got {type(settings).__name__}")
    calls = tuple(RecordedCall.from_payload(c) for c in settings.get("model_calls", ()))
    on_miss = str(settings.get("on_miss", "fail"))
    live = settings.get("live")
    inner = None
    if live is not None:
        from aef.config.factory import build_model_provider
        from aef.config.schema import ModelProviderConfig

        inner = build_model_provider(
            ModelProviderConfig(impl=str(live["impl"]), model=str(live.get("model", "")))
        )
    return replace(services, model_provider=CassetteProvider(inner, calls, on_miss=on_miss))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: python -m {__package__}.node_worker <module:factory>", file=sys.stderr)
        return 2

    try:
        graph = load_graph(argv[1])
    except WorkerError as exc:
        sys.stdout.write(_frame({"error": str(exc)}) + "\n")
        sys.stdout.flush()
        return 1

    services = agent_services()
    sys.stdout.write(_frame({"graph": describe(graph)}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = _unframe(line)
        except Exception as exc:  # noqa: BLE001 - a malformed frame is a failed step
            response: dict[str, Any] = {"error": f"malformed request: {exc}"}
        else:
            if isinstance(request, dict) and "configure" in request:
                try:
                    services = _configure(services, request["configure"])
                except Exception as exc:  # noqa: BLE001 - reported, the parent decides
                    response = {"error": f"configure failed: {type(exc).__name__}: {exc}"}
                else:
                    response = {"configured": True}
            else:
                response = _evaluate(graph, request, services)
        sys.stdout.write(_frame(response) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main(sys.argv))
