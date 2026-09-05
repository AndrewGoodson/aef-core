# AEF scaffold contract

This is `aef-core`: a Python runtime for agent graphs, plus a scaffold
generator that drops it into an existing repo (`aef adopt`).

**What an adopting repo actually gets**, and this list is audited against the
code rather than aspirational: a deterministic graph kernel, shared `AEFState`,
checkpoint/replay durability, a deny-by-default policy engine with HITL gates
and an audit trail, memory, a memory-backed context retriever, OTel tracing,
an eval harness, rule-based reflection, and the self-rewiring loop harness.

**What it does NOT do, stated because the previous version of this paragraph
claimed otherwise:**

- **It does not migrate your agents.** `aef adopt` writes documentation, a
  config template, and a stub that raises `NotImplementedError`. It reads none
  of your existing code. Converting call sites into nodes is manual — that is
  literally step 5 of the checklist it generates. `aef migrate` (below) does
  the mechanical half; the semantics are still yours.
- **Planning, knowledge-graph access and token optimization do not exist.**
  `aef.reasoning.planner` and `aef.services.graph` were deleted (ADR 0101).
  `aef/services/tokens/` was an EMPTY DIRECTORY that still imported cleanly,
  because Python invents a namespace package for one — it is deleted now.
  The old paragraph listed all three as things you inherit.
- **LLM-backed reflection and offline optimization are typed interfaces**
  raising `NotImplementedError` (Phase 3/5). The rule-based reflection slice
  is real (ADR 0046).
- **If your "agents" are prompt files rather than Python** — Claude Code
  subagents, `.md` personas — this is the ordinary case, not the exception:
  every eligible repo in the 2026-09-04 survey had **zero** SDK call sites.
  `aef migrate` discovers `.claude/agents/**/*.md` recursively and writes
  **one graph per persona**, `prompt_agent -> reflect -> consolidate -> END`,
  with the persona read at execution time and sent as the *system* message
  of one completion (ADR 0152). Skills are found, counted and deliberately
  not migrated, with the reason printed. Under `claude_code`, `codex`,
  `grok` and `anthropic` the persona's own `tools:` frontmatter is parsed,
  reported and never obeyed — but **containment is the provider's answer,
  not migrate's**: only `claude_code` sends `--tools "" --max-turns 1
  --safe-mode`; `codex` and a `command:` template with no `{system}` slot
  put the persona in the *user* turn; and for `impl: command` the
  `isolation:` list is **the owner's assertion, recorded as one, never
  verified against the binary** (ADR 0169). Every run writes what it
  actually got to `working_memory["prompt_agent__containment"]`.
  **Zone A stays `agents/` by default**, which makes the generated graph
  agent-writable and the persona Zone C — so the loop may improve the
  wrapper and never the prompt. `aef migrate --agent-root .claude/agents`
  widens it, opt-in per repo, and the report says in words what that adds to
  the blast radius: a candidate may then rewrite any persona your harness
  loads. Pass the same `--agent-root` to every `aef loop` command.
  With that root, `--proposer rule_based_prompt` appends one consolidated
  lesson as a bullet under `## Lessons (aef)` — computed from records, no
  model call, provenance in the bullet (ADR 0157) — and the gates judge it
  with a prose control cohort (ADR 0170). **A prompt candidate is scored
  live or not at all:** a changed prompt is a changed cassette key, so
  replay scores it 0 and that is an artifact, not a verdict; the bar is
  S2's measured noise floor (mean 0.7639, spread 0.1666 on Opus, ADR 0156).
  `tests/cli/test_prompt_repo_acceptance.py` runs the whole sequence —
  `adopt -> migrate -> bootstrap --memory -> bless -> doctor -> cycle` — and
  ADR 0158 records what it measured, including the two defects that stop a
  live gate pass today.

Only five things are allowed to differ per agent: **Knowledge, Policies,
Tools, Objectives, Evaluation Metrics** — see the prime directive below.

New here? Read `AGENT_INTEGRATION.md` (canonical ingest-and-start guide) and
`docs/autonomy/self-improving-loop.md` (the autonomous-loop safety contract)
first.

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

## Should the loop merge on its own? (no)

`docs/trust/promotion-trust-case.md` assesses all seven Phase-4 criteria —
now all implemented — and recommends **against** enabling Tier-1
auto-merge. Its three load-bearing findings: criteria 1 and 6 have never run
against the live traffic and real tenants their text names; a shadow node
doing direct file I/O is not contained by the tool policy (demonstrated, and
now fixable by running the candidate in a container — opt-in, ADR 0105);
and every adversarial round in the program found a defect, six for six, in
freshly written code believed correct. Residual risk is stated as a number
(5-10 false accepts per 100 gated candidates) with its basis and its
weakness. Read it before changing anything about promotion.

## Evolution is disabled (constraint #7)

`aef/evolution/` ships real interfaces and a hard-enforced disablement:
`EvolutionConfig(enabled=True)` and `AgentConfig`'s `evolution.enabled: true`
both raise. All seven supporting safety mechanisms are implemented, but the
live-traffic and real-tenant evidence needed to enable evolution is not. Don't
try to route around this — enabling remains an explicit owner decision (see
`docs/roadmap.md` Phase 4 and `docs/trust/promotion-trust-case.md`).

## What's real vs. stubbed

`docs/roadmap.md` is the authoritative, currently-accurate answer. In
short: kernel, state, checkpointing/replay, provider+fallback, security
policy engine, memory (in-memory + Mem0), OTel tracing, and the eval
harness are real and tested (Phase 0/1), as is the rule-based
reflection slice (`RuleBasedCritic`/`RuleBasedJudge` + `make_reflect_node`,
ADR 0046), and the memory-backed context retriever (`MemoryRetriever`, ADR
0101 — the first thing here that enforces `context_budget_tokens`).
The model provider is real for three backends: `claude_code` (default —
the coding agent's login is the credential, reproduced end-to-end),
`codex` (built from the CLI's documented flags, **not reproduced** — the
Codex on the authoring box predates its server's model catalog), and
`anthropic` (SDK, needs `ANTHROPIC_API_KEY`). `model_provider.model` in
`aef.yaml` is the provider's default model; it validated for months while
nothing read it.
LLM-backed reflection, offline optimization, and multi-agent coordination
remain typed interfaces with `NotImplementedError` bodies (Phase 3/5). The
evolution engine is a typed interface, disabled (Phase 4).

`aef/services/knowledge/` (`KnowledgeEntry`/`KnowledgeStore` +
`InMemoryKnowledgeStore` + `RuleBasedConsolidator` + `make_consolidate_node`) is real, wired and tested —
the persistent-knowledge layer of ADR 0110. The consolidator groups repeated
`MemoryRecord`s into entries, requiring a signature to recur in **two distinct
runs** before it becomes knowledge (one occurrence is an episode).
`make_consolidate_node` runs it after reflection, `Services.knowledge` is
defaulted by `agent_services`, and `MemoryRetriever` admits entries alongside
raw records under one `context_budget_tokens`.

**Measured, not asserted** (ADR 0110's I4 A/B, corpus built from real
`GraphExecutor` runs): consolidation buys distinct-lesson coverage under a
tight budget, and the reason is that raw-records-only retrieval *degrades as
experience accumulates* — near-duplicate records about one recurring failure
crowd out every other lesson, so coverage falls 6→1 as recurrence rises while
the wiki holds at 6. **`knowledge_boost` defaults to 0.0**: swept at 0/0.5/1/3
it changed no coverage number anywhere, so the benefit is consolidation, not
ranking.

An **LLM-backed summariser** (`adapters/llm_summariser.py`) is implemented and
tested but **off by default**, and the reason is a measurement rather than
caution: it costs coverage at tight budgets (6→4 at budget 400, R=5) because the
summary is added to the verbatim feedback rather than replacing it, so entries
grow ~40%. Keeping both texts is deliberate — a paraphrase replacing the only
record of what was observed makes a lesson untraceable to its evidence — so this
is a trade, not a bug. The model is never trusted with provenance: it may write
one prose string, and every counted field is computed from records.

None of this feeds `aef/evolution/`, and a test AST-scans both directions to
keep that true.

**Landed 2026-09-03 by the improve loop** (`IMPROVE_LOOP.md`, rubric in
`docs/research/self-learning-rubric.md`, 50 → 79): scenarios carry owner
`checks` and the score can fail without an error (ADR 0113, `aef loop
score`); `aef loop run` keeps on a local branch, never main (0114), with an
archive that is measured to buy nothing on this proposer and is off (0121);
`reflection.impl: llm` exists, is bias-controlled, and is off by
measurement (0115); the retriever finally has a caller —
`make_retrieve_node` — and lessons carry helpful/harmful tallies (0118);
stale lessons are demoted by `runs_since_last_seen`, default half-life 5
by sweep (0116); `harvest` redacts the input and re-executes (0119);
`aef loop skills` drafts skill proposals, never installs them (0117);
`tests/test_prompt_surface.py` pins the prompt surface (0120).

The knowledge graph, token optimizer and planner interfaces were **deleted**
(ADR 0101), not deferred: a stub unimplemented across five phases is a
promise, and an unkept promise in a typed signature is worse than an honest
absence. `PlanValidator` in particular was redundant with the domain gates
Milestone 2 wired.

## Development pod

`.claude/skills/reproduce-first/` is the verification method — construct the
failing case and RUN it, assert every patch applied, never weaken a control
to make something pass. Load it for any audit or fix.
`.claude/agents/seam-hunter.md` hunts joins between components that are each
correct; three of ten defects lived there. See `docs/dev-pod.md`, including
why the other agents were cut.
`/new-model-check <model-id>` re-audits every model-facing surface — these
prompts, the loop contract, the provider, the `adopt` templates — against a
new model's documented breaking changes and behavioral guidance, applies
the fixes, and records `docs/model-checks/<date>-<model>.md`. Run it once
per model release (ADR 0111). It carries no per-model facts; it reads them
from the bundled `claude-api` skill each run.

All three are tracked (`.gitignore` re-includes `.claude/skills` and
`.claude/agents`); a clone has the whole pod.

Nothing under `agents/` — that is Zone A, inside the loop's blast radius.

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
the onboarding kit (`AGENT_INTEGRATION.md` — the self-contained
ingest-and-start guide, and `AUTONOMY.md` — the inlined autonomy safety
contract with HARD-STOP gates + green bar, see ADR 0034), and a native
entry file for every major coding-agent harness so the scaffold isn't
tied to one tool (ADR 0040): `AGENTS.md` (Codex + the cross-tool
convention; identical to `CLAUDE.md`), `.github/copilot-instructions.md`
(GitHub Copilot), and `.cursor/rules/aef.mdc` (Cursor) — the last two are
thin pointers into `AGENT_INTEGRATION.md`.
The generated `CLAUDE.md` is self-contained: a fresh coding-agent session
in that other repo, with no memory of this conversation, can pick up the
migration from it alone.
