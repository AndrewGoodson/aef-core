"""`aef adopt` — run inside an existing, unrelated repo to start migrating it
onto the AEF scaffold. This is the adoption path the scaffold exists for:
detect what's there today, generate the artifacts a future session (in that
repo, possibly a different coding-agent session with no other context) needs
to continue the migration, and never silently overwrite anything already
in the target repo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from aef.cli.adopt_loop import (
    render_agents_zone_readme,
    render_corpus_readme,
    render_loop_gate_workflow,
    render_loop_md,
    render_loop_monitor_workflow,
)

_IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "site-packages",
        ".mypy_cache",
        ".ruff_cache",
    }
)

_LANGGRAPH_RE = re.compile(r"^\s*(?:import|from)\s+langgraph\b", re.MULTILINE)
_CREWAI_RE = re.compile(r"^\s*(?:import|from)\s+crewai\b", re.MULTILINE)
_RAW_SDK_RE = re.compile(r"^\s*(?:import|from)\s+(?:openai|anthropic)\b", re.MULTILINE)

# Dependency-manifest signals use a looser word-boundary match (no
# import/from syntax to anchor on) — a freshly-scaffolded repo that has
# `langgraph` in requirements.txt/pyproject.toml but hasn't written much
# code yet is exactly the adoption-path moment `aef adopt` should still
# get right, not report as "none" until enough code accumulates.
_LANGGRAPH_MANIFEST_RE = re.compile(r"\blanggraph\b")
_CREWAI_MANIFEST_RE = re.compile(r"\bcrewai\b")
_RAW_SDK_MANIFEST_RE = re.compile(r"\b(?:openai|anthropic)\b")
_MANIFEST_GLOBS = ("requirements*.txt", "pyproject.toml", "Pipfile")

Framework = str  # one of "langgraph", "crewai", "raw_sdk", "none"


def _is_ignored(path: Path, root: Path) -> bool:
    return any(part in _IGNORED_DIR_NAMES for part in path.relative_to(root).parts)


def _read_all(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        try:
            parts.append(path.read_text(errors="ignore"))
        except OSError:
            continue
    return "\n".join(parts)


def detect_framework(repo_root: Path, *, max_files: int = 2000) -> Framework:
    """Scans `.py` files AND dependency manifests (requirements*.txt,
    pyproject.toml, Pipfile — anywhere in the tree, for monorepos with the
    framework declared in a subdirectory) under `repo_root` for the agent
    framework in use today. Detection order is deliberate: a repo using
    LangGraph or CrewAI almost always also imports openai/anthropic
    underneath, so those two are checked first and raw_sdk only matches
    when neither is present — across both signal sources combined, not
    just imports."""
    py_files = [p for p in repo_root.rglob("*.py") if not _is_ignored(p, repo_root)][:max_files]
    manifest_files = [
        p
        for pattern in _MANIFEST_GLOBS
        for p in repo_root.rglob(pattern)
        if not _is_ignored(p, repo_root)
    ][:max_files]

    code_text = _read_all(py_files)
    manifest_text = _read_all(manifest_files)

    if _LANGGRAPH_RE.search(code_text) or _LANGGRAPH_MANIFEST_RE.search(manifest_text):
        return "langgraph"
    if _CREWAI_RE.search(code_text) or _CREWAI_MANIFEST_RE.search(manifest_text):
        return "crewai"
    if _RAW_SDK_RE.search(code_text) or _RAW_SDK_MANIFEST_RE.search(manifest_text):
        return "raw_sdk"
    return "none"


_FRAMEWORK_MIGRATION_NOTES: dict[Framework, str] = {
    "langgraph": (
        "Detected LangGraph. Your `StateGraph` nodes map closely onto AEF `Node`s: "
        "the biggest mechanical change is that a LangGraph node closes over whatever "
        "clients/config it wants, while an AEF node receives everything through "
        "`Services` (constraint #2) and returns `(StateDelta, Route)` instead of "
        "mutating/returning a raw state dict. Your `MemorySaver`/`SqliteSaver` "
        "checkpointer becomes an `aef.kernel.DurabilityBackend`; your conditional "
        "edges become `aef.kernel.Edge` with an explicit `condition`."
    ),
    "crewai": (
        "Detected CrewAI. If you're using Crews (role-based, non-deterministic "
        "routing), each role becomes an AEF `Node` and the crew's implicit "
        "coordination becomes explicit `Edge`s — this is the main shift, since AEF's "
        "default is deterministic hierarchical handoff (blueprint §12.2), not "
        "emergent role delegation. If you're using Flows (already deterministic, "
        "event-driven), the mapping to AEF `Node`/`Edge` is close to 1:1."
    ),
    "raw_sdk": (
        "Detected direct OpenAI/Anthropic SDK calls with no orchestration "
        "framework. This is actually the simplest migration: wrap each existing "
        "call site in a `Node` function, move the vendor client construction "
        "behind a `ModelProvider` adapter (constraint #3 — vendor SDK imports "
        "only live in `providers/`), and inject it via `Services` instead of "
        "constructing it inline."
    ),
    "none": (
        "No agent framework or raw model-SDK usage detected. Start from "
        "`aef adopt`'s generated `aef.yaml` and build your first `Node` directly "
        "against the AEF kernel — there's no existing orchestration code to "
        "migrate away from."
    ),
}


def render_claude_md(framework: Framework, repo_name: str) -> str:
    return f"""# {repo_name} — AEF scaffold contract

This repo is being migrated onto AEF (Agent Engineering Foundation), a
repo-agnostic Agent Operating System scaffold. This file is written so any
coding agent (Claude, Codex, Cursor, GitHub Copilot, …) with **no other
context** can pick up the migration. `AGENTS.md` is an identical copy for
harnesses that read that filename; Copilot/Cursor entry files
(`.github/copilot-instructions.md`, `.cursor/rules/aef.mdc`) point here.

## What AEF is

AEF is a Python runtime for agent graphs. Only five things are allowed to
differ per agent: **Knowledge, Policies, Tools, Objectives, Evaluation
Metrics.**

Inherited, audited against the code: graph execution, checkpoint/replay,
memory, context retrieval, evaluation, rule-based reflection, observability,
OTel telemetry, and a deny-by-default security policy with HITL gates.

NOT inherited, stated because an earlier version of this text claimed
otherwise: **planning** and **knowledge-graph access** do not exist (deleted,
ADR 0101); **token optimization** does not exist; LLM-backed **reflection**
and **optimization** are typed interfaces raising `NotImplementedError`.

And nothing here is inherited *automatically*. `aef adopt` wrote docs and a
stub; it read none of your code. `aef migrate --dir .` generates node wrappers
for your real call sites, but wiring and semantics remain yours.

## The node contract (non-negotiable)

Every node has this fixed signature:

    (AEFState, Context, Services) -> tuple[StateDelta, Route]

Nodes never construct their own clients, never read env vars, never reach
for globals. Everything arrives via `Services` (dependency injection).
See the `aef-core` package's `aef/kernel/contracts.py` for the exact types.

## Detected framework in this repo: `{framework}`

{_FRAMEWORK_MIGRATION_NOTES[framework]}

## Migration checklist

See `AEF_MIGRATION_CHECKLIST.md` (generated alongside this file) for the
prioritized, ordered list of concrete next steps.

## Config

`aef.yaml` (generated alongside this file) stubs the five per-agent fields.
Fill in `objectives`, `tools.allow`, `policies`, and `evaluator.suites`
before running anything against real credentials — the scaffold defaults
to `require_hitl_above_risk: 0.0`, meaning **any** positive-risk tool call
requires human approval until you explicitly raise that threshold.

## Where to look in aef-core

These paths are inside the `aef-core` package/repository, not this one — if
`aef-core` was installed via pip, find its on-disk location with
`python -c "import aef; print(aef.__path__[0])"`; `docs/` is only present
if you have the `aef-core` source checked out (it isn't bundled into the
pip package), so `docs/roadmap.md` below requires that checkout.

- `aef/kernel/` — graph engine, Node/Edge contracts, Services, checkpointing, replay
- `aef/state/` — the shared `AEFState` schema every agent uses
- `aef/providers/`, `aef/services/*/` — pluggable backends behind stable interfaces
- `aef/security/tool.py` — the policy engine every tool call goes through
- `docs/roadmap.md` (source checkout only) — what's implemented vs. stubbed, phase by phase
"""


def render_migration_checklist(framework: Framework) -> list[str]:
    common = [
        "Read the generated CLAUDE.md in full before writing any code.",
        "Fill in aef.yaml: objectives, tools.allow, policies, evaluator.suites.",
        "Identify your current entrypoint(s) — the function(s) that start an agent run.",
    ]
    by_framework: dict[Framework, list[str]] = {
        "langgraph": [
            "List your StateGraph's nodes; give each one a stable `id` and `version`.",
            "For each node, decide side_effects (pure/io/external_call/mutating) and "
            "deterministic (true only if identical input always produces identical output).",
            "Replace direct client construction (OpenAI/Anthropic clients, DB "
            "connections) inside nodes with a `Services` parameter.",
            "Convert conditional edges to `aef.kernel.Edge` with an explicit `condition`.",
            "Replace your checkpointer with an `aef.kernel.DurabilityBackend` "
            "(start with `InMemoryDurabilityBackend` or `FileDurabilityBackend`).",
            "Wire the aef_adapter.py shim's `run_via_aef()` to your old entrypoint "
            "and run both side by side until outputs match.",
        ],
        "crewai": [
            "List your Crew's roles/tasks or Flow's steps as candidate AEF Nodes.",
            "If using Crews: decide which handoffs should become deterministic "
            "Edges vs. remain an explicitly-logged emergent-routing exception.",
            "If using Flows: map each `@start`/`@listen` step to a Node/Edge pair roughly 1:1.",
            "Move any tool definitions behind `aef.security.tool.Tool` with "
            "declared scopes — CrewAI tools have no default-deny policy engine.",
            "Wire the aef_adapter.py shim to your old entrypoint and compare outputs.",
        ],
        "raw_sdk": [
            "Wrap your vendor client construction in an "
            "`aef.providers.base.ModelProvider` adapter.",
            "Convert each call site into a Node function receiving Services.model_provider.",
            "Add a second provider + FallbackProvider if you want vendor fallback.",
            "Wire the aef_adapter.py shim to your old entrypoint and compare outputs.",
        ],
        "none": [
            "Write your first Node directly against aef.kernel — no legacy code to migrate.",
            "Start with a two-node graph (do-the-thing -> END) and grow it.",
        ],
    }
    tail = [
        "Add an Evaluator (start with aef.services.eval.rule_based.RuleBasedEvaluator).",
        "Run `aef doctor` to confirm the config and imports are wired correctly.",
    ]
    return common + by_framework[framework] + tail


_ADAPTER_SHIM_TEMPLATE = '''"""AEF adapter shim — generated by `aef adopt`.

Routes this repo's existing agent entrypoint through the AEF kernel without
requiring a rewrite. Replace the TODOs below with your actual entrypoint.
"""

from __future__ import annotations

from aef.kernel import END, Context, Graph, GraphExecutor, Node, Route, Services
from aef.state import AEFState, StateDelta


def legacy_entrypoint_node(
    state: AEFState, ctx: Context, services: Services
) -> tuple[StateDelta, Route]:
    """TODO: call your existing entrypoint here. It currently detected as:
    framework = "{framework}"
    See AEF_MIGRATION_CHECKLIST.md for the per-framework migration steps.
    """
    # Returning END keeps this file lint-clean and importable before you
    # wire it — `aef doctor` imports it, and a template that fails its own
    # repo's `ruff check .` is a poor first impression (ADR 0079). Replace
    # the body; do not leave it returning END.
    raise NotImplementedError("wire your existing entrypoint into this node")
    return StateDelta(), END  # unreachable; keeps the imports honest


def build_graph() -> Graph:
    node = Node(
        id="legacy_entrypoint", version="0.1.0", fn=legacy_entrypoint_node, deterministic=False
    )
    return Graph(
        id="{repo_name}",
        version="0.1.0",
        nodes={{"legacy_entrypoint": node}},
        edges=[],
        entry_node="legacy_entrypoint",
    )


def run_via_aef(objective: str, *, services: Services | None = None) -> AEFState:
    import uuid

    state = AEFState(run_id=str(uuid.uuid4()), agent_id="{repo_name}", objective=objective)
    executor = GraphExecutor(build_graph().compile(), services or Services())
    result = executor.run(state)
    return result.final_state
'''


def render_adapter_shim(framework: Framework, repo_name: str) -> str:
    return _ADAPTER_SHIM_TEMPLATE.format(framework=framework, repo_name=repo_name)


def render_aef_yaml(repo_name: str) -> str:
    return f"""# Generated by `aef adopt` for {repo_name}.
# Fill in the five fields allowed to differ per agent: objectives,
# policies, tools.allow, evaluator.suites, and memory/knowledge_graph.
#
# WHAT IS WIRED TODAY: `model_provider`, `policies`, `tools.allow`,
# `objectives` and `evaluator.suites`.
#   - `tools.allow` is a list of SCOPES, not tool names. The policy engine
#     gates on a tool's required_scopes, so an allowlist of names could not
#     authorise anything. Names are the DENY axis: `policies.forbid`.
#   - Empty `tools.allow` allows nothing. That is deny-by-default, on purpose.
#   - Pass `--config aef.yaml` to `aef run`, and `--config` to `aef loop
#     gate`/`cycle`, or the engine falls back to its own deny-by-default.
#     The gate reads this file FROM THE BASE REF, so editing it on a
#     candidate branch cannot widen the rules that candidate is judged by.
#   - `objectives` is the default objective for `aef run --config`; an
#     explicit `--objective` still overrides it.
#   - `evaluator.suites` are DOMAIN GATES, applied by `aef run --observations`
#     and `aef eval --config`. Each entry is a `module:function` reference to
#     a callable taking the run's AEFState and returning bool. A gate can only
#     make a run FAIL that would otherwise pass; it can never rescue one.
#
# REFUSED, so it cannot be believed by mistake:
#   - `knowledge_graph` — no builder exists, so the block raises at load time
#     rather than validating a claim nothing honours (aef-core ADR 0100).
#   - `extends` — nothing resolves a base config, so any value but the
#     default `_base` is rejected (aef-core ADR 0084).

extends: _base

model_provider:
  impl: anthropic
  model: claude-opus-5  # a real current ID; claude-fable-5-1 for the hardest long-horizon work
  fallback: []

memory:
  impl: in_memory

evaluator:
  suites: []

tools:
  allow: []

policies:
  require_hitl_above_risk: 0.0
  forbid: []

objectives: "TODO: describe this agent's objective in one or two sentences."

evolution:
  enabled: false
"""


def render_agent_integration_md(repo_name: str) -> str:
    return f"""# AEF Agent Integration — ingest & start here ({repo_name})

You are a coding agent (Claude, Codex, Cursor, GitHub Copilot, or any other)
in a repo adopting **aef-core**, a repo-agnostic Agent Operating System
scaffold. This file is self-contained:
read it top to bottom and you can install aef-core, wire your first node, and
safely run the self-improving loop with no other context.

## What you inherit (and what you don't)
aef-core gives every agent, for free: a deterministic graph kernel, shared
`AEFState`, checkpoint/replay durability, a deny-by-default security policy +
HITL gates, memory, OTel tracing, and an eval harness. **Only five things
differ per agent:** Knowledge, Policies, Tools, Objectives, Evaluation
Metrics. An agent-specific branch anywhere else means the abstraction is
wrong, not the agent.

Two always-on invariants:
- **Two-plane determinism.** The kernel is pure bookkeeping. Every
  LLM/nondeterministic call lives inside a node declared
  `deterministic=False`. Never call a model from the kernel.
- **Vendor isolation.** `anthropic`/`openai`/`mem0`/`neo4j` imports live ONLY
  in `aef/providers/` and `aef/services/*/adapters/`. CI fails otherwise.

## Start (5 steps)
1. `pip install aef-core` — then `pip install -e .` too, if this repo is
   itself installable. (Add the `anthropic`/`mem0` extras only when wiring
   those backends; the base package imports without them.)
2. `aef doctor` — confirms Python >=3.11, CLAUDE.md present, aef.yaml valid.
   Fix any `[FAIL]`; `[WARN]` advisories are optional.
3. Fill `aef.yaml`: objectives, tools.allow, policies, evaluator.suites.
4. Write one node with the fixed signature and wire it in `aef_adapter.py`:
   `(AEFState, Context, Services) -> tuple[StateDelta, Route]`. Nodes take
   everything via `Services` (dependency injection) — no globals, no env
   reads, no self-constructed clients.
5. Execute, score, and replay. **`--checkpoints-dir` is required on the
   run**, or the run is held in memory and discarded — `aef eval` then
   reports "no checkpoints found for run_id=..." and blames the run id
   rather than the missing flag:

   ```
   aef run <your.module> --objective "..." --checkpoints-dir .aef-runs
   aef eval  --checkpoints-dir .aef-runs --run-id <the id printed above>
   aef trace --checkpoints-dir .aef-runs --run-id <the id printed above>
   ```

   `aef trace` prints provenance, and provenance only exists if your nodes
   emit it: `StateDelta(provenance=[Provenance(...)])`. A graph that emits
   none replays empty and scores `cost_tokens=0`.

## The node contract (non-negotiable)
- Declare `deterministic: bool`. `True` means the replay engine WILL
  re-execute it and assert identical output — never declare it on anything
  that calls a model, clock, or RNG.
- Declare `side_effects` (`pure`/`io`/`external_call`/`mutating`). Anything
  non-pure REQUIRES an `idempotency_key_fn` (enforced by the `Node`
  constructor). Resume is at-least-once — your key is what makes a
  re-executed side effect safe; the kernel does not dedupe for you.

## Running the self-improving loop (autonomously, safely)
See `AUTONOMY.md` (generated alongside this file) for the safety contract,
and aef-core's `docs/autonomy/self-improving-loop.md` for the full spec.
The loop in one line: **audit by adversarial construction -> reproduce
failing -> fix -> verify -> ADR -> commit -> repeat until a bounded work-list
is done.** Green bar every step:

    pytest -q                              # exit 5 = no tests collected, not a pass
    mypy --strict <your package>
    ruff check .
    ruff format --check <your source dirs>

A freshly adopted repo has no tests, so `pytest -q` exits 5 on day one. That
is the bar telling you the truth: write the first test before you rely on it,
and note the same code fails G1 if you pass `pytest -q` as `--build-command`.

"Self-learning" means writing reflections into memory (rule-based
critic/judge first). It does NOT mean self-modification: `aef/evolution/` is
gated by design and stays off.

## Guardrails you cannot route around
- Security is deny-by-default: a tool with no declared scopes is denied; any
  positive-risk call routes to REQUIRE_HITL until explicitly approved.
- Every state change is a `StateDelta`; state is append-mostly; `plan`
  REPLACES on set. Scores/tokens/budgets are range-validated. Durability
  writes are atomic and resume recovers past a torn checkpoint; HITL pauses
  are always resumable.

## Getting the loop to five green — run this as your task

This is the whole job, in order. `aef loop doctor` reports five obligations
and prints the exact command that fixes each; work down its output until
every line is OK. Do not skip ahead to running the loop — with obligations
unmet the gates refuse for lack of evidence, which is correct behaviour and
reads as "broken".

```
aef loop doctor --repo . --state ~/.aef-loop-state --corpus corpus \\
                --agent-path agents/<yours>/graph.py
```

1. **CORPUS + TRIPWIRE.**
   ```
   aef loop record <your.module> --corpus corpus --scenario-id s1 \\
     --objective "..." --split validation \\
     --working-memory '{{"difficulty": 5}}'
   ```
   Record scenarios that **fail** as well as ones that pass — a corpus where
   everything already passes cannot demonstrate an improvement.
   Then at least one tripwire:
   ```
   ... --scenario-id tripwire-1 --expected must_fail \\
       --working-memory '{{"difficulty": 99}}'
   ```
   It must be impossible **in principle**, not merely hard; `record` refuses
   the label if the agent completes the task. Without a tripwire the gates
   cannot detect reward hacking — a one-line change making an agent always
   report success passes every cheap gate, because they read the agent's own
   claim about itself.

2. **REFLECT NODE, ROUTED TO.** You need BOTH an edge and a route:
   ```python
   return delta, "reflect"                            # in your work node
   edges=[Edge(from_node="work", to_node="reflect")]  # in build_graph
   ```
   An Edge alone does not route; a route with no edge is refused by the
   executor. This catches everyone once.

3. **OBSERVATIONS.** Pass `--observations` from production runs. With no
   input every monitoring window reports unobserved, which correctly rolls
   every change back — monitoring with no input is an expensive way to revert.

4. **HALT CHANNEL.** A halt fails a CI job. If nobody watches that, nothing
   has told you.

5. **BLESSED BASELINE.** Commit first; the baseline is read from git.
   ```
   aef loop bless --repo . --state ~/.aef-loop-state \\
                  --agent-path agents/<yours>/graph.py
   ```

### Then verify by RUNNING, not by reading

```
aef loop gate --repo . --state ~/.aef-loop-state --head <branch> \\
   --workdir /tmp/loop --corpus corpus \\
   --entrypoint <your.module>:build_graph \\
   --build-command "<your green bar>"
```

`--entrypoint` is **required** or G2 and G3 cannot execute your corpus and
refuse. `--build-command` is **your** green bar, not aef-core's; the default
`pytest -q` exits 5 in a repo with no tests and fails G1.

Confirm all six gates actually ran — read the ledger, not the summary
(`aef loop status` and the ledger's `gated` entry both show which gates ran).

Then **prove the containment works**: plant a one-line reward hack — make the
agent ignore its inputs and always report success — gate it, and confirm G2
rejects it as a SECURITY EVENT and the loop HALTS with exit 2. If it does
not, your tripwire is not a tripwire. Revert the hack afterwards.

Finally, edit `.github/workflows/loop-gate.yml` and set `AEF_ENTRYPOINT` and
`AEF_BUILD_COMMAND` to your values. The generated ones are placeholders.

### Know what is and is not wired
`model_provider`, `policies` and `tools.allow` reach a run — but only when you
pass `--config aef.yaml` to `aef run`, and `--config` to `aef loop
gate`/`cycle`. Without the flag the engine falls back to its own
deny-by-default, which denies every tool call.

`tools.allow` is a list of **scopes**, not tool names; `policies.forbid` is
the name-based deny axis. An empty `tools.allow` allows nothing, on purpose.

`objectives` and `evaluator.suites` now reach a run (aef-core ADR 0100):
`objectives` is the default for `aef run --config`, and each `evaluator.suites`
entry is a `module:function` reference resolved into a domain gate that can
only make a run fail, never pass. `knowledge_graph` and a non-default `extends`
are **refused at load time** rather than silently ignored — there is no builder
and no inheritance, and a field that validates while being read by nothing is
indistinguishable from a feature. The stub says which is which, field by field.

**Nothing merges automatically.** Tier-1 auto-merge is off and no flag, config
or environment variable enables it. A candidate passing all six gates is
escalated to a human. Do not try to route around this.

### Stop and ask
If you find yourself weakening a gate to make something pass, labelling an
achievable task `must_fail`, enabling auto-merge, or adding a secret to a
workflow — stop and ask. Those are the owner's calls, not yours.

### Report back
Which obligations are green, the six-gate ledger output, the reward-hack run
and its exit code, and **anything the docs told you to do that did not work**.
That last one is the most valuable thing you can send upstream: five defects
in aef-core were documentation instructing adopters to run commands the CLI
rejects, and they were only found by someone being the adopter.

## Where to look (inside the aef-core package, not necessarily this repo)
Locate an installed copy: `python -c "import aef; print(aef.__path__[0])"`.
`docs/` ships only in a source checkout.
- `aef/kernel/` — graph engine, Node/Edge, Services, checkpoint/replay
- `aef/state/` — the shared AEFState schema + migrations
- `aef/security/tool.py` — the policy engine every tool call passes through
- `docs/autonomy/self-improving-loop.md` — the full autonomy protocol
- `docs/adr/README.md` — every design decision, with rationale
"""


def render_autonomy_md(repo_name: str) -> str:
    return f"""# Autonomy contract for {repo_name} (inherited from aef-core)

This repo adopted aef-core, which is developed with an autonomous
self-improving loop. If you run that loop here, you inherit the SAME safety
contract. Full spec: aef-core `docs/autonomy/self-improving-loop.md`.

## Green bar (every step, all four must pass)

    pytest -q                              # exit 5 = no tests collected, not a pass
    mypy --strict <your package>
    ruff check .
    ruff format --check <your source dirs>

A freshly adopted repo has no tests, so `pytest -q` exits 5 on day one. That
is the bar telling you the truth: write the first test before you rely on it,
and note the same code fails G1 if you pass `pytest -q` as `--build-command`.

## Reproduce-first
Never write a fix before a test/command that reproduces the defect and fails
as reported. This is the single most load-bearing rule.

## HARD-STOP gates — the only things that require a human
Run unattended, but pause and ask a human for any of:
1. Any push to a repo other than this one, or any external publish (package
   upload, sending data off-box) beyond `git push` on this repo.
2. Enabling `aef/evolution/`, weakening the deny-by-default PolicyEngine, or
   removing/loosening a HITL approval gate.
3. Deleting or overwriting an existing user file.
4. A breaking public-contract change you are not confident about.

Everything else: decide and proceed.

## Self-learning is bounded
"Self-learning" = writing reflections/critiques into memory. It does NOT mean
self-modification. `aef/evolution/` is disabled in code and stays that way —
that boundary is what makes unattended autonomy safe rather than reckless.

## Bounded, not open-ended
Every loop run starts from a finite work-list and STOPS when it is shipped.
Do not manufacture new findings to keep running. A fresh audit is a new,
deliberately-started loop.
"""


_HARNESS_POINTER_BODY = """This repo uses **aef-core**, a repo-agnostic Agent Operating System
scaffold. It works with any coding agent (Claude, Codex, Cursor, GitHub
Copilot, …) — the scaffold is plain Python + the `aef` CLI; only the entry
file each agent reads differs.

**Read first (in this repo):** `AGENT_INTEGRATION.md` (ingest-and-start guide)
and `AUTONOMY.md` (the autonomy safety contract). `CLAUDE.md` / `AGENTS.md`
hold the full scaffold contract.

Two always-on invariants:
- Two-plane determinism — the kernel is pure bookkeeping; every LLM/
  nondeterministic call lives in a node declared `deterministic=False`.
- Vendor isolation — `anthropic`/`openai`/`mem0`/`neo4j` imports only in
  `aef/providers/` and `aef/services/*/adapters/`.

Green bar (all four must pass before any change is done):
`pytest -q` · `mypy --strict <pkg>` · `ruff check .` · `ruff format --check <dirs>`

HARD-STOP gates — pause and ask a human for any of: a push to another repo or
any external publish; enabling `aef/evolution/`, weakening the PolicyEngine, or
removing a HITL gate; deleting/overwriting a user file; a breaking
public-contract change you're unsure of. Everything else: decide and proceed.
"""


def render_harness_pointer(repo_name: str) -> str:
    """A thin, harness-neutral instructions file pointing at the canonical
    guide and inlining the safety contract — used for GitHub Copilot's
    `.github/copilot-instructions.md`."""
    return f"# {repo_name} — agent instructions (aef-core)\n\n{_HARNESS_POINTER_BODY}"


def render_cursor_rule(repo_name: str) -> str:
    """Cursor `.cursor/rules/*.mdc` — same pointer body, with the minimal
    frontmatter Cursor uses to always apply a rule."""
    frontmatter = "---\ndescription: aef-core scaffold contract\nalwaysApply: true\n---\n\n"
    return f"{frontmatter}# {repo_name} — agent instructions (aef-core)\n\n{_HARNESS_POINTER_BODY}"


@dataclass(frozen=True)
class AdoptResult:
    framework: Framework
    written_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)


def render_new_model_check_skill() -> str:
    """The `/new-model-check` skill (docs/adr/0111): a per-model-release
    re-audit of every prompt and API surface. Shipped as package data rather
    than a Python string so this repo's own copy under `.claude/skills/` can
    be pinned byte-identical to what adopters receive. It carries no
    per-model facts — those are read from the bundled `claude-api` skill at
    run time, because a fact table here would rot the day the next model
    ships."""
    return (
        resources.files("aef.cli")
        .joinpath("templates/skills/new-model-check/SKILL.md")
        .read_text(encoding="utf-8")
    )


def run_adopt(target_dir: Path) -> AdoptResult:
    target_dir = target_dir.resolve()
    framework = detect_framework(target_dir)
    repo_name = target_dir.name

    written: list[Path] = []
    skipped: list[Path] = []

    def _write_if_absent(relative_name: str, content: str) -> None:
        path = target_dir / relative_name
        # ``Path.exists()`` is false for a dangling symlink, and normal file
        # writes follow symlinked parent directories.  Treat either shape as
        # an existing repository entry: adoption promises to add files inside
        # the target repo, never to follow its links and create files
        # elsewhere.
        parent = path.parent
        blocked_parent = False
        while parent != target_dir:
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                blocked_parent = True
                break
            parent = parent.parent
        if path.exists() or path.is_symlink() or blocked_parent:
            skipped.append(path)
            return
        path.parent.mkdir(parents=True, exist_ok=True)  # for .github/, .cursor/rules/
        path.write_text(content)
        written.append(path)

    claude_md = render_claude_md(framework, repo_name)
    _write_if_absent("CLAUDE.md", claude_md)
    _write_if_absent("aef.yaml", render_aef_yaml(repo_name))
    _write_if_absent("aef_adapter.py", render_adapter_shim(framework, repo_name))

    checklist = render_migration_checklist(framework)
    _write_if_absent(
        "AEF_MIGRATION_CHECKLIST.md",
        "# AEF migration checklist\n\n" + "\n".join(f"- [ ] {item}" for item in checklist),
    )

    # Onboarding kit: the ingest-and-start guide plus the inlined autonomy
    # safety contract, so a new repo agent inherits both (see docs/adr/0034).
    _write_if_absent("AGENT_INTEGRATION.md", render_agent_integration_md(repo_name))
    _write_if_absent("AUTONOMY.md", render_autonomy_md(repo_name))

    # Cross-harness entry files (docs/adr/0040): every major coding-agent reads
    # a different instructions file. AGENTS.md carries the full contract
    # (Codex + the cross-tool convention); Copilot and Cursor get thin native
    # pointers into the canonical guide. All never-overwrite.
    _write_if_absent("AGENTS.md", claude_md)
    _write_if_absent(".github/copilot-instructions.md", render_harness_pointer(repo_name))
    _write_if_absent(".cursor/rules/aef.mdc", render_cursor_rule(repo_name))

    # The self-rewiring loop kit (ADR 0057/0058). LOOP.md leads with what does
    # NOT work yet: an adopting repo whose agents produce candidates against an
    # empty corpus sees every one rejected, and that reads as "the loop is
    # broken" rather than "the loop has nothing to judge against".
    _write_if_absent("LOOP.md", render_loop_md(repo_name))
    _write_if_absent("agents/README.md", render_agents_zone_readme(repo_name))
    _write_if_absent("corpus/README.md", render_corpus_readme(repo_name))
    _write_if_absent(".github/workflows/loop-gate.yml", render_loop_gate_workflow(repo_name))
    _write_if_absent(".github/workflows/loop-monitor.yml", render_loop_monitor_workflow(repo_name))

    # Per-model-release re-audit (docs/adr/0111). Without it an adopted
    # repo's prompts and call sites are checked against exactly one model:
    # whichever was current the day it adopted.
    _write_if_absent(".claude/skills/new-model-check/SKILL.md", render_new_model_check_skill())

    return AdoptResult(
        framework=framework, written_files=written, skipped_files=skipped, checklist=checklist
    )
