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
from dataclasses import dataclass
from pathlib import Path

from aef.config import (
    build_domain_gates,
    build_model_provider,
    build_policy_config,
    build_retriever,
    load_agent_config,
)
from aef.config.schema import ContextConfig
from aef.harness.memory_store import FileMemoryStore
from aef.kernel import (
    DurabilityBackend,
    FileDurabilityBackend,
    GraphExecutor,
    InMemoryDurabilityBackend,
)
from aef.providers.base import ModelProvider
from aef.security.tool import FileAuditLogWriter, PolicyConfig
from aef.services.knowledge.consolidate import RuleBasedConsolidator
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState


@dataclass(frozen=True)
class RunConfig:
    """Everything `--config` contributes to a run's `Services`.

    **One construction site, two commands.** `aef run` and `aef loop
    bootstrap` both turn an `aef.yaml` into the pieces `agent_services`
    needs, and they used to do it in two places: `run_graph_module` built
    the provider, the policy config, the context config and the reflection
    impl; `cmd_bootstrap` built the provider and the reflection impl and
    nothing else. So a recording made by bootstrap ran under the engine's
    DEFAULT policy while the same graph under `aef run` ran under the
    adopter's — and the corpus would have pinned behaviour production never
    had. That is ADR 0091's drift shape, and this dataclass is the fix:
    both callers read the config here or not at all.

    `None` config path means no `aef.yaml` was given, and every field keeps
    the unconfigured default — a graph calling `require_model_provider()`
    then gets a clear refusal, never a silent no-op.
    """

    model_provider: ModelProvider | None = None
    policy_config: PolicyConfig | None = None
    context: ContextConfig | None = None
    reflection: str = "rule_based"
    reflection_model: str | None = None


def build_run_config(config_path: str | Path | None) -> RunConfig:
    """Read an `aef.yaml` into the parts `agent_services` takes.

    `build_domain_gates` is called and its result discarded ON PURPOSE: an
    unresolvable evaluator suite should stop the run before it costs
    anything, naming itself, rather than at the end of one (ADR 0100). The
    evaluator that actually uses the suites is built at scoring time.

    **The order below is a decision, and it changed.** `run_graph_module`
    used to build the model provider first and validate the evaluator suites
    second, so a config with both an unbuildable provider and an
    unresolvable suite reported the provider. Extracting this function
    reversed it by accident (ADR 0145 did not notice; ADR 0149 reproduced
    it). It is kept reversed and PINNED by
    `test_build_run_config_reports_the_evaluator_before_the_provider`:
    **validate before constructing.** `build_domain_gates` resolves names and
    builds nothing; `build_model_provider` constructs a live provider object
    and, for `impl: anthropic`, imports a vendor SDK to do it. Reporting the
    cheap, local, purely-declarative error first is the better answer, and
    the point of pinning it is that "which error the adopter sees" stops
    being whichever statement a refactor happened to leave on top.
    """
    if config_path is None:
        return RunConfig()
    config = load_agent_config(config_path)
    build_domain_gates(config.evaluator)
    return RunConfig(
        model_provider=build_model_provider(config.model_provider),
        policy_config=build_policy_config(config.tools, config.policies),
        context=config.context,
        reflection=config.reflection.impl,
        reflection_model=config.model_provider.model,
    )


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

    # `evaluator.suites` reaches the evaluator, and `policies`/`tools.allow`
    # reach the run — both validated and were ignored before (ADR 0014, 0082,
    # 0092, 0100). All of it is read in ONE place now, shared with
    # `aef loop bootstrap`, so a recording cannot run under a different
    # configuration than production does. See `build_run_config`.
    run_config = build_run_config(config_path)
    model_provider = run_config.model_provider
    policy_config = run_config.policy_config
    context_config = run_config.context
    reflection = run_config.reflection
    reflection_model = run_config.reflection_model

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
    # Same list the gate path uses (aef/services/runtime.py, ADR 0091), so
    # an agent that runs here can be re-executed there. Four separate defects
    # were the two lists drifting apart.
    # Built from the SAME memory store the agent writes to. A retriever over
    # a different store retrieves nothing and reads as an empty memory.
    # One knowledge store for the retriever AND the consolidate node, or the
    # lessons the graph writes are never the lessons it reads (A1, ADR 0118).
    #
    # And it is REBUILT FROM THE DURABLE MEMORY BEFORE THE GRAPH RUNS, because
    # a fresh store per process plus a retrieve node that runs before the
    # consolidate node means no consolidated lesson is ever in context on any
    # CLI run: `retrieved_signatures` was `[]` in every `aef run`, so ADR
    # 0118's helpful/harmful tally had no producer on the assembled path and
    # A1 was closed only for a caller that constructs `Services` by hand
    # (ADR 0125, reproduced end-to-end through `run_graph_module`).
    # Recompute rather than persist: the consolidator is a stateless function
    # of the memory store by design (ADR 0110), so re-deriving is exactly
    # equivalent to having stored it, with no second source of truth about
    # what has been seen. With an in-memory store there is nothing to rebuild
    # from — the run is a one-off — so this is skipped.
    knowledge = InMemoryKnowledgeStore()
    if memory_path is not None:
        RuleBasedConsolidator().consolidate(memory, knowledge, agent_id=agent_id)
    retriever = build_retriever(
        context_config, memory=memory, agent_id=agent_id, knowledge=knowledge
    )
    services = agent_services(
        model_provider=model_provider,
        memory=memory,
        knowledge=knowledge,
        retriever=retriever,
        durability=durability,
        policy=policy_config,
        judge_rubric=judge_rubric,
        audit_log=FileAuditLogWriter(Path(audit_log_path)) if audit_log_path else None,
        reflection=reflection,
        reflection_model=reflection_model,
        # Without a `context:` block `build_retriever` returns None and
        # `agent_services` defaults one — over THIS durable, multi-agent store.
        # Unscoped, that handed the run another tenant's records (ADR 0125).
        agent_id=agent_id,
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
