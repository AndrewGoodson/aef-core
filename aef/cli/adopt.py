"""`aef adopt` — run inside an existing, unrelated repo to start migrating it
onto the AEF scaffold. This is the adoption path the scaffold exists for:
detect what's there today, generate the artifacts a future session (in that
repo, possibly a different Claude Code session with no other context) needs
to continue the migration, and never silently overwrite anything already
in the target repo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

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
repo-agnostic Agent Operating System scaffold. This file is written so a
Claude Code session with **no other context** can pick up the migration.

## What AEF is

AEF is not another agent framework — it's a scaffold every agent in the AEF
ecosystem inherits wholesale. Only five things are allowed to differ per
agent: **Knowledge, Policies, Tools, Objectives, Evaluation Metrics.**
Planning, graph execution, memory, evaluation, reflection, optimization,
observability, security, and token/context engineering are all inherited.

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

- `aef/kernel/` — graph engine, Node/Edge contracts, Services, checkpointing, replay
- `aef/state/` — the shared `AEFState` schema every agent uses
- `aef/providers/`, `aef/services/*/` — pluggable backends behind stable interfaces
- `aef/security/tool.py` — the policy engine every tool call goes through
- `docs/roadmap.md` — what's implemented vs. stubbed, phase by phase
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
    raise NotImplementedError("wire your existing entrypoint into this node")


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

extends: _base

model_provider:
  impl: anthropic
  model: claude-sonnet
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


@dataclass(frozen=True)
class AdoptResult:
    framework: Framework
    written_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)


def run_adopt(target_dir: Path) -> AdoptResult:
    target_dir = target_dir.resolve()
    framework = detect_framework(target_dir)
    repo_name = target_dir.name

    written: list[Path] = []
    skipped: list[Path] = []

    def _write_if_absent(relative_name: str, content: str) -> None:
        path = target_dir / relative_name
        if path.exists():
            skipped.append(path)
            return
        path.write_text(content)
        written.append(path)

    _write_if_absent("CLAUDE.md", render_claude_md(framework, repo_name))
    _write_if_absent("aef.yaml", render_aef_yaml(repo_name))
    _write_if_absent("aef_adapter.py", render_adapter_shim(framework, repo_name))

    checklist = render_migration_checklist(framework)
    _write_if_absent(
        "AEF_MIGRATION_CHECKLIST.md",
        "# AEF migration checklist\n\n" + "\n".join(f"- [ ] {item}" for item in checklist),
    )

    return AdoptResult(
        framework=framework, written_files=written, skipped_files=skipped, checklist=checklist
    )
