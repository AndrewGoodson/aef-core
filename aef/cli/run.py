"""`aef run` — execute a graph module's `build_graph()` against an
objective. memory/tracer are always in-memory backends; the model
provider is real (built from `--config`'s `model_provider.impl`) if
config is given, otherwise unconfigured — a graph module that calls
`services.require_model_provider()` without `--config` gets a clear
`ServiceNotConfiguredError`, not a silent no-op.

Durability defaults to in-memory (a one-off run, nothing persisted) but
`checkpoints_dir` switches it to `FileDurabilityBackend` — this is what
makes `aef run --checkpoints-dir X` followed by `aef eval`/`aef trace
--checkpoints-dir X --run-id <id>` an actually-chainable workflow. Before
this, `aef run` always used `InMemoryDurabilityBackend`, whose data is
discarded the instant the process exits — `aef eval`/`aef trace` could
never find anything a prior `aef run` produced, confirmed by actually
running the two in sequence, not inferred from reading the code. See
docs/adr/0021.

Only `model_provider` is config-driven so far: `memory`/`knowledge_graph`/
`tools`/`policies` need a real plugin-registry design this repo doesn't
have yet (`MemoryConfig` alone can't build a real `mem0.Memory()`, and
there's no registry mapping `tools.allow` name strings to `Tool` objects).
See docs/adr/0014.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

from aef.config import build_model_provider, load_agent_config
from aef.kernel import (
    DurabilityBackend,
    FileDurabilityBackend,
    GraphExecutor,
    InMemoryDurabilityBackend,
    Services,
)
from aef.observability.in_memory import InMemoryTracer
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState


def _ensure_cwd_importable() -> None:
    """`aef` runs as an installed console script, whose sys.path[0] is the
    script's own directory (e.g. .venv/bin), NOT the caller's current
    directory — unlike `python script.py` or `python -m`, where the CWD is
    on sys.path automatically. Without this, `aef run agents.foo.graph`
    can never find a module `aef init` just scaffolded one directory below
    where you're standing: confirmed by actually running `aef init` then
    `aef run` end-to-end, not inferred from reading the code."""
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)


def load_graph_module(module_path: str):  # type: ignore[no-untyped-def]
    """Import a module and call its `build_graph()`.

    Shared with `aef loop record`, which needs the same graph the runner
    would execute — recording against a different graph than production runs
    would make the corpus describe something nobody ships.
    """
    _ensure_cwd_importable()
    module = importlib.import_module(module_path)
    build_graph = getattr(module, "build_graph", None)
    if build_graph is None:
        raise ValueError(f"module {module_path!r} has no build_graph() function")
    return build_graph()


def append_observation(path: Path, *, at: str, passed: bool, cost_tokens: int) -> None:
    """One JSON line per live run, for post-merge monitoring.

    Nothing wrote this file before M12, so every monitoring window reported
    as unobserved — which, correctly, rolled everything back. Monitoring with
    no input is not monitoring; it is a very expensive way to revert.
    """
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": at, "passed": passed, "cost_tokens": cost_tokens})
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_graph_module(
    module_path: str,
    *,
    agent_id: str,
    objective: str,
    config_path: str | Path | None = None,
    checkpoints_dir: str | Path | None = None,
) -> AEFState:
    _ensure_cwd_importable()
    module = importlib.import_module(module_path)
    build_graph = getattr(module, "build_graph", None)
    if build_graph is None:
        raise ValueError(f"module {module_path!r} has no build_graph() function")

    model_provider = None
    if config_path is not None:
        config = load_agent_config(config_path)
        model_provider = build_model_provider(config.model_provider)

    durability: DurabilityBackend = (
        FileDurabilityBackend(Path(checkpoints_dir))
        if checkpoints_dir is not None
        else InMemoryDurabilityBackend()
    )

    graph = build_graph()
    services = Services(
        model_provider=model_provider,
        memory=InMemoryMemoryStore(),
        tracer=InMemoryTracer(),
        durability=durability,
    )
    state = AEFState(run_id=str(uuid.uuid4()), agent_id=agent_id, objective=objective)
    executor = GraphExecutor(graph.compile(), services)
    result = executor.run(state)
    return result.final_state
