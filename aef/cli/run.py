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

import hashlib
import importlib
import importlib.util
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from aef.config import (
    build_domain_gates,
    build_model_provider,
    build_policy_config,
    build_retriever,
    load_agent_config,
)
from aef.config.factory import build_containment_mode
from aef.config.schema import ContextConfig, ShadowConfig
from aef.harness.memory_store import FileMemoryStore
from aef.harness.shadow import ContainmentMode
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

    **`containment_mode` has no consumer inside `aef/` yet, and that is
    stated rather than covered over.** Shadow execution still has no
    production caller (ADR 0161, ADR 0173): what this field buys is that when
    one is written it reads the owner's choice from here instead of accepting
    a signature default, and that `shadow_for` will no longer let it forget.
    A field carried for a caller that does not exist is a promise; the reason
    it is not the kind ADR 0101 deleted is that the wire is short, it is
    exercised end-to-end by tests through `shadow_for`, and its absence was a
    live defect rather than a deferred feature.
    """

    model_provider: ModelProvider | None = None
    policy_config: PolicyConfig | None = None
    context: ContextConfig | None = None
    reflection: str = "rule_based"
    reflection_model: str | None = None
    # `shadow.containment`, as the enum the shadow harness runs on (ADR 0173).
    # THE one place a caller reads the owner's containment choice from: before
    # this, the field validated in `aef.yaml`, `build_containment_mode` had
    # zero callers, and `shadow_for`'s `mode` defaulted to `auto` — so an owner
    # who wrote `off` got a container and an owner who wrote `fallback` got
    # `auto`'s refusal. Reproduced both ways; ADR 0173.
    #
    # The unconfigured value is DERIVED from `ShadowConfig()` rather than
    # written as `ContainmentMode.AUTO`, so "no aef.yaml" and "an aef.yaml
    # with no shadow block" cannot drift into two different answers.
    containment_mode: ContainmentMode = field(
        default_factory=lambda: build_containment_mode(ShadowConfig())
    )


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
        containment_mode=build_containment_mode(config.shadow),
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


def looks_like_a_path(module_path: str) -> bool:
    """Is this a FILE to load rather than a dotted module name to import?

    A `.py` suffix or a separator; nothing else. Deliberately not "try the
    import and fall back", because a dotted import that fails for its own
    reason — a typo inside the module, a missing dependency — would then be
    retried as a filename, miss, and be reported as "no such file", hiding the
    real error behind a second one.
    """
    return module_path.endswith(".py") or "/" in module_path or "\\" in module_path


def import_graph_module(module_path: str) -> ModuleType:
    """The one importer, for a dotted module name **or a file path**.

    ADR 0168, erratum on ADR 0152. `aef migrate --agent-root .claude/agents` —
    the opt-in ADR 0152 §4 chose, and the only way to put a persona in Zone A —
    writes `.claude/agents/migrated/<module>/graph.py`, and the report printed

        aef run .claude.agents.migrated.marlin_accela.graph --objective "..."

    which is not a module name at all. Reproduced:

        $ aef run .claude.agents.migrated.marlin_accela.graph --objective x
        error: the 'package' argument is required to perform a relative import
        for '.claude.agents.migrated.marlin_accela.graph'

    A leading dot means "relative import" to `importlib`, and no dotted spelling
    of that path exists — `.claude` is not an identifier, so no amount of
    quoting makes one. M1 shipped a flag whose own generated command could not
    be run under it, and M4 worked around it by keeping the graphs at the
    default root while passing `--agent-root .claude/agents` to the loop, which
    is the two-trees-one-loop state ADR 0152's blast-radius block warns about.

    Refusing the root instead was rejected: `.claude/agents` IS the documented
    opt-in, so a refusal would delete the feature rather than fix it. Loading a
    file is one function and no new concept — `aef init`'s CWD-on-`sys.path`
    fix already exists for the dotted case, and the file case needs neither.

    The module is registered in `sys.modules` under a derived name before it is
    executed, which is what the import system does for a normal import and what
    a module importing itself (or a dataclass being pickled out of it) needs.
    """
    _ensure_cwd_importable()
    if not looks_like_a_path(module_path):
        return importlib.import_module(module_path)

    path = Path(module_path)
    if not path.is_file():
        raise ValueError(
            f"{module_path!r} looks like a file path and there is no file there "
            f"(resolved to {path.resolve()}). Pass a dotted module name, or a path "
            f"to the .py file that defines build_graph()."
        )
    resolved = path.resolve()
    # Derived from the resolved path, so two graphs with the same basename in
    # different directories do not collide in `sys.modules` — `graph.py` is the
    # name `aef migrate` gives every single one of them.
    name = "aef_graph_" + hashlib.sha256(str(resolved).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:  # pragma: no cover - unreadable file
        raise ValueError(f"cannot load a Python module from {resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load_graph_module(module_path: str):  # type: ignore[no-untyped-def]
    """Import a module and call its `build_graph()`.

    Shared with `aef loop record`, which needs the same graph the runner
    would execute — recording against a different graph than production runs
    would make the corpus describe something nobody ships.
    """
    module = import_graph_module(module_path)
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
    module = import_graph_module(module_path)
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
