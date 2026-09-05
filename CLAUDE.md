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
  config template, and a stub that raises `NotImplementedError`. It reads your
  code only to *label* it — an import scan for `langgraph`/`crewai`/`openai`/
  `anthropic` and a file-shape count of `.claude/agents`, `.claude/skills`,
  `AGENTS.md`, `.codex/` — and converts nothing. Converting call sites into
  nodes is manual; that is literally step 5 of the checklist it generates.
  `aef migrate` (below) does the mechanical half; the semantics are still
  yours — except for prompt-file agents, where there is no call site and
  migrate does the whole registration (next bullet).
- **Planning, knowledge-graph access and token optimization do not exist.**
  `aef.reasoning.planner` and `aef.services.graph` were deleted (ADR 0101).
  `aef/services/tokens/` was an EMPTY DIRECTORY that still imported cleanly,
  because Python invents a namespace package for one — it is deleted now.
  The old paragraph listed all three as things you inherit.
- **Offline optimization is a typed interface** raising
  `NotImplementedError` (Phase 5). The rule-based reflection slice is real
  (ADR 0046) and so is the **LLM-backed** one — `aef/reasoning/llm_reflection.py`,
  reached by `reflection.impl: llm`, bias-controlled (ADR 0115). It is
  **off by default**, and that is a measurement rather than a stub: four
  A/Bs (0115, 0155, 0175, and the judge run of 0171) and it has never moved
  the task metric. The previous version of this bullet called it a typed
  interface raising `NotImplementedError`; the file has had a body since
  ADR 0115.
- **If your "agents" are prompt files rather than Python** — Claude Code
  subagents, `.md` personas — this is the ordinary case, not the exception:
  every eligible repo in the 2026-09-04 survey had **zero** SDK call sites.
  `aef migrate` discovers `.claude/agents/**/*.md` recursively and writes
  **one graph per persona**, four nodes, `retrieve -> prompt_agent ->
  reflect -> consolidate -> END` (ADR 0179 added `retrieve` as the entry
  node; earlier text here said three), with the persona read at execution
  time and sent as the *system* message of one completion (ADR 0152).
  Skills are found, counted and deliberately not migrated, with the reason
  printed. The persona's own `tools:` frontmatter is parsed, reported and
  never obeyed under every impl — but **containment is the provider's
  answer, not migrate's, and it is per-provider evidence rather than a
  stamped sentence** (ADR 0169). Only `claude_code` was *measured* to
  suppress tools (`--tools ""`, `--max-turns 1`, `--safe-mode`, empty
  strict MCP config); on `grok` 1.0.5 the identical-looking `--tools ""`
  **suppresses nothing** — the same argv read a planted file with one more
  turn allowed; `codex` and a `command:` template with no `{system}` slot
  put the persona in the *user* turn, and the run records a
  `prompt_agent.persona_in_user_turn` error saying so; and for
  `impl: command` the `isolation:` list is **the owner's assertion,
  recorded as one, never verified against the binary** — omit it and the
  run claims nothing but the channel. Every run writes what it actually got
  to `working_memory["prompt_agent__containment"]`.
  **Zone A stays `agents/` by default**, which makes the generated graph
  agent-writable and the persona Zone C — so the loop may improve the
  wrapper and never the prompt. `aef migrate --agent-root .claude/agents`
  widens it, opt-in per repo, and the report says in words what that adds to
  the blast radius: a candidate may then rewrite any persona your harness
  loads. Pass the same `--agent-root` to every `aef loop` command; a graph
  under that root has no dotted module name, so name it **by file path** —
  `aef run .claude/agents/migrated/<agent>/graph.py`, and
  `--entrypoint <path>:build_graph` — which every `aef loop` subcommand now
  accepts alongside the two dotted spellings (ADR 0176/0177).
  `--agent-path` may name the persona `.md` itself: `aef loop doctor`
  resolves it to that persona's generated graph through migrate's own
  mapping and says which file it read (ADR 0178).
  With that root, `--proposer rule_based_prompt` appends one consolidated
  lesson as a bullet under `## Lessons (aef)` — computed from records, no
  model call, provenance in the bullet (ADR 0157) — and the gates judge it
  with a prose control cohort (ADR 0170). The evidence it grounds in is
  real: a run that answers and gets the owner's check wrong now writes a
  check-derived failure record, and two such runs make a lesson (ADR 0174).
  The lesson is redacted of the check's value, which is deliberate and has
  a measured cost: with the answer removed the bullet carried no
  information a `contains` check could act on, and the paired live A/B of
  ADR 0158 scored candidate and incumbent identically. Teaching to the test
  is the alternative, and it is worse.
  **A prompt candidate is scored live or not at all:** a changed prompt is
  a changed cassette key, so replay scores it 0 and that is an artifact,
  not a verdict; the bar is S2's measured noise floor (mean 0.7639, spread
  0.1666 on Opus, ADR 0156). **And live is an explicit per-repo opt-in,
  off by default**: `gates.live_model_calls: true` in `aef.yaml`, read from
  the **base ref** so a candidate cannot grant itself the login, is what
  lets the gates' sandbox worker inherit your harness credential — and
  therefore what lets a candidate's code spend your quota. Without it
  `--cassette-miss live` is **refused by name**, because the alternative is
  the verdict ADR 0158 measured: `G2 fail — 2 previously-passing
  scenario(s) no longer pass`, which was a subprocess that could not log in
  and not a judgement of the prompt. Every `gated` ledger event records
  which passes ran with it (ADR 0181, closing 0158's F-M5-2 and F-M5-3).
  `tests/cli/test_prompt_repo_acceptance.py` runs the whole sequence —
  `adopt -> migrate -> bootstrap --memory -> bless -> doctor -> cycle` —
  and ADR 0158 records what it measured, with 0181's errata on the two
  findings it has since closed.

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
The model provider is real for **five** backends, not the three this
paragraph used to list: `claude_code` (default — the coding agent's login
is the credential, reproduced end-to-end), `codex` (built from the CLI's
documented flags, **not reproduced** — the Codex on the authoring box
predates its server's model catalog), `grok` (parsed from a live run
rather than from `--help`, because none of its JSON field names are
Claude's — ADR 0154), `command` (any CLI, from an argv template in a
`command:` block; this is how a harness released after this file was
written gets wired, GitHub Copilot's CLI included — the owner configures
it and this repo ships no guess about its flags), and `anthropic` (SDK,
needs `ANTHROPIC_API_KEY`). Each declares its own `isolation` set, derived
from the argv it actually builds, so removing a flag retracts the claim in
the same commit (ADR 0169). `model_provider.model` in `aef.yaml` is the
provider's default model; it validated for months while nothing read it.
Offline optimization and multi-agent coordination remain typed interfaces
with `NotImplementedError` bodies (Phase 5); LLM-backed reflection does
not — see above. The evolution engine is a typed interface, disabled
(Phase 4).

`aef/services/knowledge/` (`KnowledgeEntry`/`KnowledgeStore` +
`InMemoryKnowledgeStore` + `RuleBasedConsolidator` + `make_consolidate_node`) is real, wired and tested —
the persistent-knowledge layer of ADR 0110. The consolidator groups repeated
`MemoryRecord`s into entries, requiring a signature to recur in **two distinct
runs** before it becomes knowledge (one occurrence is an episode).
`make_consolidate_node` runs it after reflection, `Services.knowledge` is
defaulted by `agent_services`, and `MemoryRetriever` admits entries alongside
raw records under one `context_budget_tokens`.

**Measured on retrieval coverage, and that proxy has since been disproved.**
ADR 0110's I4 A/B (corpus built from real `GraphExecutor` runs) showed that
consolidation buys distinct-lesson coverage under a tight budget, because
raw-records-only retrieval *degrades as experience accumulates* —
near-duplicate records about one recurring failure crowd out every other
lesson, so coverage falls 6→1 as recurrence rises while the wiki holds at 6.
That number is still true and it is **not** a prediction about task outcome:
S1b (ADR 0175) re-ran the four ACE arms on a corpus whose failures recur, with
the layer fully engaged and the task metric did not move (ADR 0175). **That
result was superseded, twice, and the sequence is the point.** ADR 0184
re-ran it with the model's own output excerpt removed from lessons and the
lesson kept fresh by the scored split, and the knowledge arm won — then ADR
0191 WITHDREW that row, because a sibling branch had re-recorded the corpus
in the same hour and the measurement's seed no longer reproduced. ADR 0193
re-ran it on the corpus that exists, with equal repeats: **(c) 0.9843 vs (b)
0.9373, +0.0470 against a 0.0353 spread, and +0.1167 on the negatives.** The
knowledge layer helps this agent on this corpus. Raw retrieval still does not
((b) − (a) = −0.0156, the fourth measurement and the third sign change).

**`knowledge_boost` defaults to 0.0**, and the reason has changed twice. It
first said the knob "changed no coverage number anywhere, so the benefit is
consolidation, not ranking" — wrong as stated: the knob controls whether the
only lesson in the store reaches the model at all (0/17 in prompt at 0.0,
17/17 at 8.0). It then said moving it moves no task metric; ADR 0193 moved it.
The default stays 0.0 anyway, and that is a judgement rather than a
measurement: the value that engages the layer is tuned to a store holding
exactly ONE entry, and this corpus cannot form a second, so nothing here has
measured what the knob does when lessons compete. `ContextConfig` now carries
it (with `staleness_half_life` and `knowledge_min_occurrences`), so an adopter
can set what the measurement used.

What arm (b) looks like from the inside is the sharpest finding: its lesson
block is **five byte-identical no-op bullets**, seven real word-cap records
out-ranked by twenty near-duplicate successes. That is ADR 0110's crowding
thesis, in a prompt rather than a coverage proxy.

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

**The score is the rubric's own heading, not a number repeated here.**
`docs/research/self-learning-rubric.md` carries it, recomputed from its rows
by `tests/test_rubric_arithmetic.py`:

```
$ grep '^## Current' docs/research/self-learning-rubric.md
## Current — 2026-09-05, J0b's re-score (ADR 0188) over J0's base (ADR 0151), plus the above-95 loop's increments — **71 / 100**
```

This paragraph used to open "Landed 2026-09-03 by the improve loop … 50 → 79".
The 79 was a self-score; an independent re-scorer with no access to the ADRs
or the loop files re-scored the same code at **68**, and that base — plus the
increments measured on top of it — is the 72 above (ADR 0151). Eighteen points
went, and not one of them because a control failed: they went on the repo's two
signature shapes, *wired but not consumed* and *asserted in prose rather than
shown by an artifact*.

**What that loop landed**, which is a list of capabilities and stays true:
scenarios carry owner `checks` and the score can fail without an error (ADR
0113, `aef loop score`); `aef loop run` keeps on a local branch, never main
(0114), with a lineage archive that is durable, complete and inspectable and
whose `sample_parents` knob is still off because no measurement has yet kept
anything (0121, superseded by 0160); `reflection.impl: llm` exists, is
bias-controlled, and is off by measurement (0115); the retriever has a caller
— `make_retrieve_node` — and lessons carry helpful/harmful tallies (0118);
stale lessons are demoted by `runs_since_last_seen`, default half-life 5
by sweep (0116); `harvest` redacts the input and re-executes (0119);
`aef loop skills` drafts skill proposals, never installs them (0117);
`tests/test_prompt_surface.py` pins the prompt surface (0120).

**The loop CLI says what it did, and a silence is not a choice.** One of
`--memory` / `--no-memory` is **required** by `aef loop cycle` *and* `aef loop
run`, enforced in the handler rather than only in the parser, because this
repo's own scheduled cycle was a no-op every night and exited 0 (ADR 0165,
0167). Every attempt is journalled to `<state>/cycles.jsonl` — including the
paths that raise — and `aef loop monitor` warns
`SCHEDULED CYCLE PRODUCING NOTHING` after three quiet cycles, which the ledger
alone cannot detect because a cycle that proposes nothing writes nothing to
it. The four exit codes are distinct and each names a different action:

| code | meaning | what to do |
|---|---|---|
| `0` | escalated to a human (the normal accept path; Tier-1 is off) | review it |
| `1` | the candidate was rejected | read the ledger's reason; retrying is fine |
| `2` | **halted**, or a usage error the command refuses to guess past | release the kill switch, or fix the invocation — do not retry |
| `3` | the command could not do its job — a crash, a bad config, an import error | fix it; `>= 2` is what CI should fail on |

`3` exists because `main()`'s catch-all returned `1` for any exception, so a
bad config, a missing corpus and a provider that is down all read as a healthy
rejection and the nightly job stayed green (reproduced, ADR 0167; the summary
line that called a crash a halt is ADR 0178).

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
current framework (LangGraph/CrewAI/raw SDK/**prompt files**/none, the
fourth added by ADR 0153 and reported with its counts), and writes — the
rule is **never-destroy**, and it is executable rather than claimed: five
named entry files (`CLAUDE.md`, `AGENTS.md`,
`.github/copilot-instructions.md`, `.cursor/rules/aef.mdc`, `.gitignore`)
gain a delimited block appended to whatever was there, everything else is
skipped when it exists, and `_verify_preserved` re-checks the bytes before
and after the block on every write and refuses rather than writing if
either moved (ADR 0153/0172) — a `CLAUDE.md` for that repo, an
`aef.yaml` stub, an `aef_adapter.py` shim, `AEF_MIGRATION_CHECKLIST.md`,
the onboarding kit (`AGENT_INTEGRATION.md` — the self-contained
ingest-and-start guide, and `AUTONOMY.md` — the inlined autonomy safety
contract with HARD-STOP gates + green bar, see ADR 0034), and a native
entry file for every major coding-agent harness so the scaffold isn't
tied to one tool (ADR 0040): `AGENTS.md` (Codex + the cross-tool
convention; identical to `CLAUDE.md`), `.github/copilot-instructions.md`
(GitHub Copilot), and `.cursor/rules/aef.mdc` (Cursor) — the last two are
thin pointers into `AGENT_INTEGRATION.md`. It also writes the loop kit —
`FIRST_DAY.md` (the sequence, in order, with every command's real output
pasted, ADR 0148), `LOOP.md`, `agents/README.md`, `corpus/README.md` and
two `.github/workflows/` — which for months nobody was told they had.
**Seventeen files**, counted from the report rather than from this
sentence: run on a real prompt-file repo it printed 15 `wrote` lines and 2
`appended` lines.

The marker adopt appends inside is **signed**:
`<!-- aef:begin sha256=<16 hex> -->` … `<!-- aef:end -->`, and in
`.gitignore` `# aef:begin sha256=…`. Only a signed pair is adopt's; a bare
`<!-- aef:begin -->` quoted in an adopter's own prose is inert text that is
never searched, matched or touched (ADR 0172). The digest is authorship,
not integrity — a hand edit inside the block does not stop adopt replacing
it, because the block is adopt's to maintain.

The generated `CLAUDE.md` is self-contained: a fresh coding-agent session
in that other repo, with no memory of this conversation, can pick up the
migration from it alone.
