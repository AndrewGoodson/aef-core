# AEF scaffold contract

This is `aef-core`: a repo-agnostic Agent Operating System scaffold. It is
**not** another agent framework — it's the thing that gets dropped into any
existing repo (via `aef adopt`, see below) so agents there inherit planning,
graph execution, memory, evaluation, reflection, optimization, knowledge
graph access, observability, security, telemetry, token optimization,
context engineering, and continuous learning, without rebuilding any of it
per agent.

## Prime directive

Only five things are allowed to differ per agent: **Knowledge, Policies,
Tools, Objectives, Evaluation Metrics.** If you find yourself adding an
agent-specific branch anywhere outside those five, stop — the abstraction
is wrong, not the agent.

## The node contract (non-negotiable)

Every node in every graph has this fixed signature:

```python
(AEFState, Context, Services) -> tuple[StateDelta, Route]
```

- Nodes are pure with respect to their inputs: no globals, no `os.environ`
  reads, no constructing their own `anthropic.Anthropic()`/DB
  clients/whatever. Everything arrives via `Services` (dependency
  injection) — see `aef/kernel/contracts.py`.
- Nodes declare `deterministic: bool`. If `True`, `ReplayEngine` will
  actually re-execute the node with the same recorded input and assert the
  output matches — don't declare `deterministic=True` on anything that
  calls a model, reads a clock, or touches randomness.
- Nodes declare `side_effects` (`pure`/`io`/`external_call`/`mutating`).
  Anything other than `pure` requires an `idempotency_key_fn` — the `Node`
  constructor enforces this and raises `NodeContractError` otherwise.
- `Route` is a single node id or `END`. Fan-out (`tuple[str, ...]`) is part
  of the type but not yet executed — see `docs/adr/0007`.

## Vendor isolation (constraint #3, enforced by tests + CI)

`anthropic`, `openai`, `mem0`, `neo4j`, and friends are imported **only**
inside `aef/providers/` and `aef/services/*/adapters/`. Never in
`aef/kernel/`, `aef/reasoning/`, or `aef/agents/`.
`tests/test_vendor_isolation.py` enforces this with an AST scan; CI runs it
on every push. If you need a new vendor SDK, its import goes in a new
adapter module under one of those two allowed locations — never upstream
of them.

## Security defaults (constraint #6)

`aef/security/tool.py`'s `PolicyEngine` is deny-by-default: a `Tool` with
no declared scopes is denied outright, an undeclared scope is denied, and
any call whose risk exceeds `PolicyConfig.require_hitl_above_risk` (default
`0.0` — meaning any positive-risk call requires explicit approval) routes
to `REQUIRE_HITL`, not `ALLOW`. Assume prompt injection will sometimes
succeed; this is designed for containment (least privilege, explicit HITL
gates, a full audit trail via `AuditLogWriter`), not detection.

## Evolution is disabled (constraint #7)

`aef/evolution/` ships real interfaces and a hard-enforced disablement:
`EvolutionConfig(enabled=True)` and `AgentConfig`'s `evolution.enabled: true`
both raise, naming every unmet Phase 4 gate criterion. Don't try to route
around this — if you need self-modification, implement the seven gate
criteria first (see `docs/roadmap.md` Phase 4 and `docs/adr/0006`).

## What's real vs. stubbed

`docs/roadmap.md` is the authoritative, currently-accurate answer. In
short: kernel, state, checkpointing/replay, provider+fallback, security
policy engine, memory (in-memory + Mem0), OTel tracing, and the eval
harness are real and tested (Phase 0/1). Knowledge graph, context engine,
token optimizer, planner, reflection, offline optimization, and
multi-agent coordination are typed interfaces with `NotImplementedError`
bodies (Phase 2/3/5). The evolution engine is a typed interface, disabled
(Phase 4).

## Decisions and deviations

`docs/adr/` records every place the research report and research brief
disagreed, or where a design choice wasn't fully pinned down by either.
Read `docs/adr/README.md` for the index before assuming a design choice
was arbitrary — it probably has a written rationale.

## Working in this repo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,anthropic,mem0]"

ruff check aef tests          # lint
ruff format aef tests         # format
mypy aef                      # strict type-check
pytest -q                     # full test suite
```

- Small, reviewable commits, conventional-commit messages.
- Write the test alongside the code, not after — especially for
  `kernel/`/`state/`, where replay determinism and checkpoint round-trips
  are the actual safety properties being tested, not incidental coverage.
- `mypy --strict` must stay clean on the whole `aef/` package, not just
  `kernel/`/`state/`.
- No new dependency without a reason traceable to the research report; no
  vendor SDK anywhere outside `providers/`/`services/*/adapters/`.

## Adopting AEF into a different repo

Run `aef adopt --dir <path>` inside the target repo. It detects the
current framework (LangGraph/CrewAI/raw SDK/none), and writes — without
ever overwriting an existing file — a `CLAUDE.md` for that repo, an
`aef.yaml` stub, an `aef_adapter.py` shim, `AEF_MIGRATION_CHECKLIST.md`,
plus the onboarding kit: `AGENT_INTEGRATION.md` (the self-contained
ingest-and-start guide) and `AUTONOMY.md` (the inlined autonomy safety
contract — HARD-STOP gates + green bar, pointing at
`docs/autonomy/self-improving-loop.md` for the full spec, see ADR 0034).
The generated `CLAUDE.md` is self-contained: a fresh Claude Code session in
that other repo, with no memory of this conversation, can pick up the
migration from it alone.
