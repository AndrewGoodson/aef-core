# AEF Agent Integration — canonical guide

This is the source-of-truth onboarding guide for **aef-core**. `aef adopt`
emits a repo-tailored copy of this into every adopted repo (see
`aef/cli/adopt.py::render_agent_integration_md` and docs/adr/0034); this
root copy is what that template mirrors, and what to read when working in
aef-core itself.

If you are a fresh coding agent — **Claude, Codex, Cursor, GitHub Copilot, or
any other** — read this top to bottom and you can install aef-core, run its
example, wire a node, and safely start the self-improving loop with no other
context. aef-core is harness-agnostic: the scaffold is plain Python plus the
`aef` CLI, so any agent that writes Python can use it.

## Which file your agent reads
`aef adopt` emits a native entry file for each major harness, all pointing
back to this guide — so the scaffold is never tied to one tool:

| Agent / harness | Entry file it reads |
|---|---|
| Claude / Claude Code | `CLAUDE.md` |
| OpenAI Codex (+ the cross-tool convention) | `AGENTS.md` (identical to `CLAUDE.md`) |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Cursor | `.cursor/rules/aef.mdc` |
| any other | this file (`AGENT_INTEGRATION.md`) + `AUTONOMY.md` |

The self-improving-loop prompt below is written for Claude Code's `/loop`
command; on another harness, paste the same prompt body into that tool's
agent/chat and run it as an ordinary instruction — the phases and the
HARD-STOP gates are identical regardless of harness.

## What aef-core is
A repo-agnostic Agent Operating System scaffold: it is the thing dropped into
any repo so agents there inherit planning, graph execution, memory,
evaluation, security, observability, and durability without rebuilding any of
it per agent. **Only five things differ per agent:** Knowledge, Policies,
Tools, Objectives, Evaluation Metrics.

Two always-on invariants:
- **Two-plane determinism.** The kernel (control plane) is pure bookkeeping;
  every LLM/nondeterministic call lives inside a node declared
  `deterministic=False`. Never call a model from the kernel.
- **Vendor isolation (constraint #3).** `anthropic`/`openai`/`mem0`/`neo4j`
  imports live ONLY in `aef/providers/` and `aef/services/*/adapters/` —
  enforced by an AST scan in CI (`tests/test_vendor_isolation.py`).

## Start (working in aef-core)
```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,anthropic,mem0]"
pytest -q                     # full suite
python -m examples.hello_agent.main   # a real end-to-end run (see examples/hello_agent/)
```
Green bar (must all pass before any change is "done"):
```
pytest -q
mypy --strict aef
ruff check .
ruff format --check aef tests
```

## Start (adopting aef-core into another repo)
Inside the target repo: `aef adopt --dir <path>`. It detects the current
framework and writes six never-overwrite files: `CLAUDE.md`, `aef.yaml`,
`aef_adapter.py`, `AEF_MIGRATION_CHECKLIST.md`, `AGENT_INTEGRATION.md`, and
`AUTONOMY.md`. Then `aef doctor` to confirm the setup, fill `aef.yaml`'s five
surfaces, wire a node in `aef_adapter.py`, and `aef run` / `aef eval` /
`aef trace`.

## The node contract (non-negotiable)
Every node has the fixed signature:
```
(AEFState, Context, Services) -> tuple[StateDelta, Route]
```
- Nodes take everything via `Services` (dependency injection) — no globals,
  no env reads, no self-constructed clients.
- Declare `deterministic: bool`. `True` means the replay engine WILL
  re-execute it and assert identical output — never on anything that calls a
  model, clock, or RNG.
- Declare `side_effects` (`pure`/`io`/`external_call`/`mutating`). Non-pure
  REQUIRES an `idempotency_key_fn` (enforced by the `Node` constructor).
  Resume is at-least-once; your key is what makes a re-executed side effect
  safe. The kernel does not dedupe for you.

## Running the self-improving loop (autonomously, safely)
Full spec: **`docs/autonomy/self-improving-loop.md`** (ADR 0033). One line:
audit by adversarial construction → reproduce failing → fix → verify (the
green bar) → ADR → commit → repeat until a **bounded** work-list is done,
then stop.

Run unattended, but pause and ask a human at the **HARD-STOP gates**: any
push to another repo or external publish; enabling `aef/evolution/`,
weakening the PolicyEngine, or removing a HITL gate; deleting/overwriting a
user file; a breaking public-contract change you're unsure of.

"Self-learning" = writing reflections into memory (rule-based critic/judge
first — `docs/design/phase3-reflection-critic-judge-brainstorm.md`). It does
**not** mean self-modification: `aef/evolution/` is gated by design
(ADR 0006/0010) and stays off.

## Guardrails you cannot route around
- Deny-by-default security (constraint #6): a tool with no declared scopes is
  denied; any positive-risk call routes to REQUIRE_HITL until approved.
- State is append-mostly `StateDelta`s; `plan` REPLACES on set (ADR 0019);
  scores/tokens/budgets are range-validated (ADR 0022/0025).
- Durability writes are atomic and resume recovers past a torn checkpoint
  (ADR 0031); HITL pauses are always resumable (ADR 0032).

## Where to look
- `aef/kernel/` — graph engine, Node/Edge, Services, checkpoint/replay
- `aef/state/` — the shared AEFState schema + migrations
- `aef/security/tool.py` — the policy engine every tool call passes through
- `examples/hello_agent/` — a real, runnable end-to-end agent
- `docs/autonomy/self-improving-loop.md` — the full autonomy protocol
- `docs/autonomy/new-repo-bootstrap-loop.md` — copy-paste `/loop` prompt to bootstrap a new adopting repo
- `docs/adr/README.md` — every design decision, with rationale
