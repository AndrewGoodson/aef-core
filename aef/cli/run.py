"""`aef run` — execute a graph module's `build_graph()` against an
objective, wired to in-memory backends only (memory, tracer, durability).
No config-driven backend selection here yet — that's config-to-Services
wiring, a Phase 2+ concern once real backends exist to select between.
"""

from __future__ import annotations

import importlib
import uuid

from aef.kernel import GraphExecutor, InMemoryDurabilityBackend, Services
from aef.observability.in_memory import InMemoryTracer
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState


def run_graph_module(module_path: str, *, agent_id: str, objective: str) -> AEFState:
    module = importlib.import_module(module_path)
    build_graph = getattr(module, "build_graph", None)
    if build_graph is None:
        raise ValueError(f"module {module_path!r} has no build_graph() function")

    graph = build_graph()
    services = Services(
        memory=InMemoryMemoryStore(),
        tracer=InMemoryTracer(),
        durability=InMemoryDurabilityBackend(),
    )
    state = AEFState(run_id=str(uuid.uuid4()), agent_id=agent_id, objective=objective)
    executor = GraphExecutor(graph.compile(), services)
    result = executor.run(state)
    return result.final_state
