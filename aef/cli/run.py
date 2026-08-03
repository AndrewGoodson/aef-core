"""`aef run` — execute a graph module's `build_graph()` against an
objective. memory/tracer/durability are always in-memory backends; the
model provider is real (built from `--config`'s `model_provider.impl`) if
config is given, otherwise unconfigured — a graph module that calls
`services.require_model_provider()` without `--config` gets a clear
`ServiceNotConfiguredError`, not a silent no-op.

Only `model_provider` is config-driven so far: `memory`/`knowledge_graph`/
`tools`/`policies` need a real plugin-registry design this repo doesn't
have yet (`MemoryConfig` alone can't build a real `mem0.Memory()`, and
there's no registry mapping `tools.allow` name strings to `Tool` objects).
See docs/adr/0014.
"""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path

from aef.config import build_model_provider, load_agent_config
from aef.kernel import GraphExecutor, InMemoryDurabilityBackend, Services
from aef.observability.in_memory import InMemoryTracer
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState


def run_graph_module(
    module_path: str, *, agent_id: str, objective: str, config_path: str | Path | None = None
) -> AEFState:
    module = importlib.import_module(module_path)
    build_graph = getattr(module, "build_graph", None)
    if build_graph is None:
        raise ValueError(f"module {module_path!r} has no build_graph() function")

    model_provider = None
    if config_path is not None:
        config = load_agent_config(config_path)
        model_provider = build_model_provider(config.model_provider)

    graph = build_graph()
    services = Services(
        model_provider=model_provider,
        memory=InMemoryMemoryStore(),
        tracer=InMemoryTracer(),
        durability=InMemoryDurabilityBackend(),
    )
    state = AEFState(run_id=str(uuid.uuid4()), agent_id=agent_id, objective=objective)
    executor = GraphExecutor(graph.compile(), services)
    result = executor.run(state)
    return result.final_state
