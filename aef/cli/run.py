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

from aef.config import build_model_provider, build_policy_config, load_agent_config
from aef.harness.memory_store import FileMemoryStore
from aef.kernel import (
    DurabilityBackend,
    FileDurabilityBackend,
    GraphExecutor,
    InMemoryDurabilityBackend,
    Services,
)
from aef.observability.in_memory import InMemoryTracer
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.security.tool import FileAuditLogWriter, PolicyEngine
from aef.services.memory.base import MemoryStore
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
    working_memory: dict[str, object] | None = None,
    config_path: str | Path | None = None,
    checkpoints_dir: str | Path | None = None,
    record_runs_dir: str | Path | None = None,
    memory_path: str | Path | None = None,
    audit_log_path: str | Path | None = None,
    judge_rubric: dict[str, float] | None = None,
) -> AEFState:
    _ensure_cwd_importable()
    module = importlib.import_module(module_path)
    build_graph = getattr(module, "build_graph", None)
    if build_graph is None:
        raise ValueError(f"module {module_path!r} has no build_graph() function")

    model_provider = None
    policy_config = None
    if config_path is not None:
        config = load_agent_config(config_path)
        model_provider = build_model_provider(config.model_provider)
        # `policies` and `tools.allow` now reach a run. They validated and were
        # ignored before, so an adopter setting require_hitl_above_risk got the
        # engine's own default instead of the one they wrote (ADR 0014, 0082).
        policy_config = build_policy_config(config.tools, config.policies)

    durability: DurabilityBackend = (
        FileDurabilityBackend(Path(checkpoints_dir))
        if checkpoints_dir is not None
        else InMemoryDurabilityBackend()
    )

    graph = build_graph()
    # Critic and judge are wired because obligation 2 tells an adopter to put a
    # reflect node in their graph, and every reflect node requires them. Without
    # this, following obligation 2 made obligation 3 (observations, produced by
    # `aef run`) impossible: the run died with ServiceNotConfiguredError. Two
    # documented requirements contradicted each other (ADR 0073).
    #
    # A durable store when a memory path is given: reflections the loop can
    # never read back are not learning.
    memory: MemoryStore = (
        FileMemoryStore(path=Path(memory_path)) if memory_path else InMemoryMemoryStore()
    )
    services = Services(
        model_provider=model_provider,
        memory=memory,
        tracer=InMemoryTracer(),
        durability=durability,
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric=dict(judge_rubric or {"quality": 1.0})),
        # The adopter's configured policy when `--config` is given,
        # deny-by-default otherwise. Without an engine at all, an agent whose
        # tool calls go through `aef.security.tool.Tool` — which the generated
        # CLAUDE.md instructs — dies with ServiceNotConfiguredError (ADR 0079).
        policy_engine=PolicyEngine(
            policy_config,
            # Durable when a path is given. An audit trail that dies with the
            # interpreter is not one you can consult after an incident, which
            # is the only time anybody consults one (ADR 0083).
            audit_log=FileAuditLogWriter(Path(audit_log_path)) if audit_log_path else None,
        ),
    )
    # Without this an adopter cannot produce a FAILING run from the CLI, so the
    # workflow LOOP.md documents ("record scenarios that fail as well as ones
    # that pass") could not be followed at all (ADR 0070).
    state = AEFState(
        run_id=str(uuid.uuid4()),
        agent_id=agent_id,
        objective=objective,
        working_memory=dict(working_memory or {}),
    )
    executor = GraphExecutor(graph.compile(), services)
    # Tracing is on only when the run is being recorded: a trace costs memory
    # proportional to the run, and every other caller wants the final state.
    result = executor.run(state, record_trace=record_runs_dir is not None)

    if record_runs_dir is not None and result.trace is not None:
        from datetime import UTC, datetime

        from aef.harness.harvest import RecordedRun, save_run

        save_run(
            Path(record_runs_dir),
            RecordedRun(
                run_id=state.run_id,
                graph_id=graph.id,
                graph_version=graph.version,
                initial_state=state,
                trace=result.trace,
                at=datetime.now(UTC),
            ),
        )

    return result.final_state
