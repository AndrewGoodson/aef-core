# AEF roadmap

Phased plan per report §19 (with the report's week/month estimates kept as
directional context, not commitments). Each phase lists what's real
(working, tested code) vs. what's an interface stub (typed contract,
`NotImplementedError`, no fake behavior).

## Phase 0 — Foundation — **DONE**

- [x] Graph kernel: `Node`/`Edge`/`Context`/`Services` contracts (fixed
  node signature, DI-only, no globals) — `aef/kernel/contracts.py`
- [x] `Graph`: static topology, `validate()`/`compile()`/`diff()`/`visualize()`
  — `aef/kernel/graph.py`
- [x] `GraphExecutor`: super-step execution, routing checked against
  declared edges, per-node tracing, per-node checkpointing, fallback
  routing on exception — `aef/kernel/executor.py`
- [x] Typed `AEFState` (report §5 schema, verbatim) + `schema_version` +
  `MigrationRegistry` — `aef/state/`
- [x] `StateDelta`: pure, append-mostly state application —
  `aef/state/delta.py`
- [x] Checkpointing: `DurabilityBackend` interface, real `InMemory` and
  `File` (JSON) backends — `aef/kernel/durability.py` (see ADR 0002)
- [x] Resume: `GraphExecutor.resume(run_id)` continues a crashed/paused
  run from a persisted per-run cursor instead of restarting at
  `entry_node` and duplicating already-executed nodes' side effects — a
  real gap found by testing, not designed in up front; see ADR 0009
- [x] `ReplayEngine`: asserts `deterministic=True` nodes reproduce
  identical output on replay; non-deterministic nodes are quarantined and
  trusted from the recorded trace — `aef/kernel/replay.py`
- [x] OTel token logging: every node execution emits a span; token counts
  land on the span whenever a node's `StateDelta.provenance` records them
  — `aef/observability/otel_tracer.py`, tested against the real OTel SDK
- [x] Single provider: `ModelProvider` interface + real `AnthropicProvider`
  adapter — `aef/providers/`

## Phase 1 — Durability & Services — **DONE**

- [x] Provider abstraction with fallback: `FallbackProvider` tries
  providers in declared order, falls through on `ModelProviderError`
- [x] Tool interface + sandbox hooks: `Tool` ABC (declared scopes),
  `PolicyEngine` (deny-by-default, HITL-above-risk-threshold gate),
  `AuditLogWriter` with a durable `FileAuditLogWriter` (JSONL, argument
  values redacted by default) — `aef/security/tool.py`. Policy is
  configurable from `aef.yaml` and the gate reads it from the base ref
  (ADR 0082); wire the audit log with `aef run --audit-log`.
- [x] Memory interface: `MemoryStore` (six-type + tool taxonomy), real
  `InMemoryMemoryStore`, real `Mem0Adapter` — `aef/services/memory/`
  (see ADR 0004)
- [x] Basic eval harness: `Evaluator` interface, `EvaluationRecord`, real
  `RuleBasedEvaluator` with `domain_gates` pluggable **in code** — nothing
  populates them from `aef.yaml` (`evaluator.suites` is read by nothing), so
  `record.domain_gates` is `{}` in every shipped path and `score_of`'s gate
  branch does not fire. Pass them to the constructor to use them (ADR 0014,
  ADR 0092) —
  `aef/services/eval/`
- [x] Per-agent config: `AgentConfig` (report §16, verbatim + `evolution`),
  unknown-key rejection, `agent.example.yaml` + `agent.azure_sec.yaml` —
  `aef/config/`
- [x] CLI: `aef init`/`adopt`/`doctor`/`run`/`eval`/`trace`/`migrate` —
  `aef/cli/`

**Deliberately out of Phase 0/1 scope** (see ADR 0007): fan-out/fan-in
execution (BSP super-steps) — declared in the `Edge`/`Route` contract,
not executed.

### Providers — **FIVE, REAL** (`aef/providers/`)

`model_provider.impl` in `aef.yaml`. Phase 0's line above ("Single provider …
real `AnthropicProvider`") is the history, not the state.

| `impl` | real? | note |
|---|---|---|
| `claude_code` | yes, **default**, reproduced end to end | the coding agent's own login is the credential — no API key anywhere (ADR 0112) |
| `codex` | yes, **not reproduced live** | built from the CLI's documented flags; the Codex on the authoring box predates its server's model catalog |
| `grok` | yes, parsed from a live run | none of its JSON field names are Claude's (`text`/`stopReason`, no `is_error`); each wrong guess yields an empty completion and no exception (ADR 0154) |
| `command` | yes | any CLI, from an argv template in a `command:` block. The path for every harness released after this file was written, GitHub Copilot's CLI included |
| `anthropic` | yes | SDK, needs `ANTHROPIC_API_KEY` |

Plus the two wrappers `cassette` (record/replay) and `fallback` (declared
order, falls through on `ModelProviderError`).

Every provider declares `isolation -> frozenset[str]` from a closed
vocabulary, **derived from the argv it actually builds** for a fixed probe, so
removing a flag retracts the claim in the same commit (ADR 0169). `command`'s
set is the owner's assertion, recorded and never verified; `fallback`'s is the
**intersection**. The full per-provider table, with what was measured versus
what is structural, is in `AGENT_INTEGRATION.md`.

### Prompt-file agents — **REAL** (`aef/reasoning/prompt_agent.py`, `aef/cli/migrate.py`)

The ordinary case rather than the exception: an adopting repo whose "agents"
are `.md` personas a coding harness runs, with no SDK call site to convert.
`aef adopt` labels it `prompt_files` with counts; `aef migrate` discovers
`.claude/agents/**/*.md` recursively and writes **one four-node graph per
persona** (`retrieve -> prompt_agent -> reflect -> consolidate -> END`,
`graph_id` = the agent's name), reading the persona at execution time so an
edit takes effect with no regeneration step (ADR 0152, 0179). Skills are
found, counted and deliberately not migrated, with the reason printed.

Zone A stays `agents/` by default, so the loop may edit the wrapper and not
the prompt; `--agent-root .claude/agents` is the opt-in that widens it and the
report states in words what that adds to the blast radius. A graph under such
a root has no dotted module name, so every `aef loop` subcommand and `aef run`
accept a **file path** as well as the two dotted spellings (ADR 0176/0177),
and `--agent-path` may name the persona `.md`, which preflight resolves to
that persona's generated graph through migrate's own mapping (ADR 0178).

## Phase 2 — Context engine — **PARTIALLY REAL**. The rest was **DELETED**.

ADR 0101 triaged the four named-but-unbuilt interfaces and deleted three of
them plus one more from Phase 3's neighbourhood. A stub unimplemented across
five phases is a promise, and an unkept promise in a typed signature is worse
than an honest absence — every reference to them outside their own modules was
either an unread `Services` slot or a test asserting they still raise.

- `Retriever` (`aef/services/context/base.py`) — **REAL** in the
  memory-backed form: `MemoryRetriever`
  (`aef/services/context/memory_retriever.py`), configured by an `aef.yaml`
  `context:` block and injected via `Services.retriever`. It is the first
  thing in this repo that enforces `AEFState.context_budget_tokens`, which
  had shipped since Phase 0 with nothing reading it. Ranking is lexical
  (deterministic, so replay holds); retrieve/rank/prune is real, and
  compress/assemble is deliberately absent — see below. It also admits
  consolidated knowledge entries alongside raw records under the same single
  budget — see `KnowledgeStore`.
- `KnowledgeStore` (`aef/services/knowledge/`) — **REAL and tested**, added
  after ADR 0101's triage. The persistent consolidated layer of ADR 0110,
  which is WikiSkill's middle layer (arXiv:2608.27454): raw experience already
  existed as failure/success `MemoryRecord`s, and this is what turns repeats
  of it into knowledge. `RuleBasedConsolidator` groups records by a derived
  signature and requires a signature to recur in **two distinct runs** — one
  occurrence is an episode, and a graph may reflect twice in one run, so runs
  are counted rather than records. `make_consolidate_node` runs it after
  reflection; `Services.knowledge` is defaulted by `agent_services`.

  **Kept on a mechanism, and the measurement that once justified it has been
  demoted.** Un-consolidated retrieval *degrades* as experience accumulates —
  distinct-lesson coverage falls 6→1 at a fixed budget as recurrence rises,
  because near-duplicate records about one failure crowd out every other
  lesson, and consolidation holds it at 6 (ADR 0110). That is a fact about
  *retrieval coverage* and it was used as a proxy for task outcome. **The
  proxy is disproved for this corpus** (ADR 0175): with the layer fully
  engaged — one entry formed from three distinct train runs, in the prompt for
  10 of 17 scored scenarios — the task metric did not move, and the treated
  subset was slightly worse. Consolidation stays because it is the level-2
  mechanism dimension 2 of the rubric describes; it is not a score gain and
  nobody should cite it as one.

  Both optional knobs are off by default for measured reasons.
  `knowledge_boost` is `0.0` — and the reason changed with ADR 0175. It used
  to read "swept at 0/0.5/1/3, it changed no coverage number anywhere, so the
  benefit is consolidation and not ranking"; on a real corpus the knob
  **demonstrably** controls whether the store's only lesson reaches the model
  (0/17 vs 10/17 in prompt), and what survives is that the task metric does
  not follow it. The LLM-backed summariser (`adapters/llm_summariser.py`,
  implemented and tested — **not a stub**) costs coverage at tight budgets
  because its summary is added to the verbatim feedback rather than replacing
  it, which trades coverage for traceability.

  **Reachable from an `aef.yaml`.** `build_retriever` takes `knowledge=` and
  `aef run --config` / `aef loop` build it, so a `context:` block is enough.
  This paragraph said the opposite — "no `knowledge=` parameter … item A1 in
  `MERGE_READY_LOOP.md`" — for a whole release after ADR 0118 closed it.

  It does not feed `aef/evolution/` and cannot be made to: an AST scan
  enforces the separation in both directions. Consolidated knowledge is not
  evidence for promotion — the trust case's three findings are about live
  traffic, real tenants and shadow containment, none of which a wiki moves.
- `GraphStore` — **DELETED** (ADR 0101). A knowledge graph needs a query
  interface, a budgetable result shape, and a provenance story for retrieved
  facts; the node signature carries none of them, and the config refuses a
  `knowledge_graph` block outright (ADR 0100). The contract is recorded in
  ADR 0101 for whenever it returns; ADR 0003's backend decision still stands
  unmade.
- `TokenOptimizer` — **DELETED** (ADR 0101). `compress` cannot be built
  honestly without a model, and a truncating compressor is a lossy edit
  wearing the word. The honest half — bounding a budget by pruning whole
  units rather than damaging them — is what `MemoryRetriever` does.
- `Planner`/`PlanValidator` — **DELETED** (ADR 0101). `PlanValidator` was
  redundant with `RuleBasedEvaluator.domain_gates`, which Milestone 2 built
  and wired (same report §16, same worked examples, same `-> bool` shape).
  `Planner` was design ambition the loop never invoked.

## Phase 3 — Reflection, offline optimization, private evals — **PARTIALLY REAL**

- `Critic`/`Judge` (`aef/reasoning/reflection.py`) — Reflexion-style
  verbal feedback and rubric-scored judgment. **Real and tested** in the
  rule-based form: `RuleBasedCritic`/`RuleBasedJudge`
  (`aef/reasoning/rule_based_reflection.py`) plus `make_reflect_node`
  (`aef/reasoning/nodes.py`), which writes `MemoryRecord(kind=
  "failure"|"success")` from a real graph run. Grounded strictly in
  recorded signals (`state.errors`, `state.tool_results`, `state.scores`)
  — no model call. See ADR 0046.
- **LLM-backed `Critic`/`Judge` — REAL, and off by measurement.**
  `aef/reasoning/llm_reflection.py`, selected by `reflection.impl: llm`, with
  the bias controls of ADR 0115. This line said "still stubbed" long after the
  file had a body. It is **not the default**, and the reason is four A/Bs
  rather than caution: ADR 0115, 0155 and 0175 each measured it and moved no
  task metric, and ADR 0159 showed why the earlier judge comparisons could not
  settle it at all — on a corpus with no true negatives the rule-based judge is
  constant-fail and the LLM judge constant-pass, so 3/18, 9/18 and 15/18 are
  all uninformative. ADR 0171 rebuilt the corpus with seven owner-check
  negatives and re-ran it: **LLM 16/17, AUC 1.000** against a 13/17 constant
  baseline — real separation, of exactly one failure family (word-cap
  overruns) with n=4 in validation. A self-preference control now exists
  (`PairwiseRanker`, ADR 0162) and measured self-preference **PRESENT** on
  this box's own models, with `allow_self_ranking=False` refusing rather than
  warning. Nothing in `run_loop` calls the ranker yet.
  **Still stubbed:** any use of a `Judgment` to gate or re-plan.
- `Optimizer` (`aef/services/optimizers/base.py`) — GEPA/DSPy-style
  offline prompt/program optimization, not implemented

## Self-rewiring harness (Zone B) — **M0–M10 REAL, Tier-1 OFF**

`aef/harness/` is the structurally-isolated harness that judges
agent-authored candidates (ADR 0044, ADR 0047). Real and tested:
`zones.py` (three-zone write scope, deny-by-default), `candidate.py`
(`git diff base...head` with the rename/symlink/submodule escapes closed),
`trust.py` (gates execute from the base ref — the load-bearing property),
`sandbox.py` (env scrubbing, timeouts, rlimits; declares what it cannot
enforce and refuses to run without attested network isolation), plus a
container-backed sandbox that can report `network_isolated=True`
truthfully (`container.py`, ADR 0102).

Also built since this section was first written: the corpus (M2,
`corpus.py`), all six gates (M3–M7, `gates/g0`–`g5`, run in the canonical
cheap-first order `G0 → G1 → G4 → G5 → G2 → G3`, ADR 0085), the proposer
(M8, `proposer.py` — numeric *and* the bounded structural catalogue in
`transformations.py`, ADR 0099), and post-merge monitoring (M10,
`monitoring.py`).

Built since **that** paragraph, each with the ADR that measured it:

- **Three proposers**, not one: `rule_based`, `llm`, and `rule_based_prompt`
  (ADR 0157) — the last appends one consolidated lesson as a bullet under
  `## Lessons (aef)` in a persona, computed from records with **no model
  call**, provenance in the bullet, never rewriting an owner's bullet, and
  raising rather than returning when aimed outside Zone A.
- **A prose control cohort.** G2 and G3 can now run on a candidate that
  changes no Python file; before ADR 0170 such a candidate died at G2 with a
  message about a scratch directory. Nothing about what the gates *accept*
  changed — no threshold, no p95 rule, no `PolicyEngine` switch. G3's answer
  for prose is only as good as its placebo, which controls for a bullet's
  shape and length and not its plausibility; that is stated residual risk.
- **Check-derived failure memory** (`check_memory.py`, ADR 0174). A run that
  answers and gets the owner's *task metric* wrong now leaves a `failure`
  record in the same shape `make_reflect_node` writes, so the consolidator,
  the retriever and the prompt proposer read it unchanged. The failures are
  applied to a **local copy** of the final state: injecting them into the real
  `state.errors` was measured to corrupt the metric twice over (0.75 → 0.0000,
  and `classify` reporting a run as raised that did not raise). The signature
  drops the check's *value*, which is what makes two runs failing the same
  check with different required terms one lesson instead of two — and what
  makes the lesson carry no answer for a `contains` check to match, measured
  in ADR 0158 as candidate and incumbent scoring identically. Teaching to the
  test is the alternative.
- **A durable candidate archive.** `<state>/lineage/` keeps every candidate
  including the rejections, which is where the information about a search
  actually is (ADR 0160). `sample_parents` — sampling a parent other than the
  current best — is **off**: the live A/B did not show the diversity gain its
  falsification required. The knob is kept rather than deleted, and dimension
  6 moved 5 → 6 for the artifact half only.
- **Shadow containment is the default, not an opt-in** (ADR 0161). The bypass
  is real under the explicit opt-out, and the opt-out is an owner statement
  that is announced and ledgered; `RunConfig.containment_mode` has **no
  default**, so a shadow caller cannot forget to read the owner's choice
  (ADR 0173).
- **The loop CLI refuses silences.** One of `--memory`/`--no-memory` on both
  commands that run a turn, enforced in the handler (ADR 0165/0167); every
  attempt journalled to `<state>/cycles.jsonl` including the paths that raise;
  `aef loop monitor` warns `SCHEDULED CYCLE PRODUCING NOTHING` after three
  quiet cycles, which the ledger alone provably cannot detect. Exit codes are
  `0` escalated · `1` rejected · `2` halted-or-usage · `3` the command could
  not do its job (ADR 0167/0178) — CI should fail on `>= 2`.

- **Live gating of a prompt candidate — REAL, and off by default** (ADR
  0181). A changed prompt is a changed cassette key, so replay cannot score
  it; the only honest way to gate one is `--cassette-miss live`. Until
  2026-09-05 no provider could serve that inside the gates on any repo: the
  worker's env allowlist inherited no login, so `claude -p` answered
  `Not logged in`, and `impl: command` could not be rebuilt on the far side
  of the boundary because only `{impl, model}` crossed it (ADR 0158's F-M5-3
  and F-M5-2, both now closed and their strict xfails now passing tests).
  The fix is an **opt-in and a refusal**, not a widening:
  `gates.live_model_calls: true` in `aef.yaml`, read from the base ref so a
  candidate cannot grant itself the login, adds the login variables to the
  worker's allowlist and records `live_model_calls` on every `gated` ledger
  event; with it false — the default, and what every existing repo gets — the
  allowlist is byte-for-byte what it was, and `--cassette-miss live` is
  **refused by name** rather than run. The refusal is the load-bearing half:
  without it the gate produces `G2 fail — N previously-passing scenario(s) no
  longer pass`, which is a subprocess that could not log in wearing the words
  of a verdict about the prompt.

**Tier-1 auto-merge remains OFF.** It is no longer blocked on
implementation — every candidate that passes all six gates escalates to a
human by design, and `docs/trust/promotion-trust-case.md` recommends
against changing that. See
`docs/design/self-rewiring/05-approval-policy.md`.

## Phase 4 — Evolution engine with full safety rails — **STUBBED, DISABLED**

`aef/evolution/engine.py`: `MutationProposer`, `ArchiveStore`, `EvalGate`,
`CanaryController`, `EvolutionConfig`. The evolution interfaces remain abstract;
`EvolutionConfig(enabled=True)` itself raises and explains that live-traffic and
real-tenant validation is still missing. See ADR 0006 for why disablement is
enforced in code, not just documented. Re-enabling requires owner acceptance of
ALL of:

1. Shadow execution against live traffic before promotion eligibility —
   **BUILT** (`aef/harness/shadow.py`, ADR 0103). Refuses any candidate
   declaring a mutating node: shadowing runs it on LIVE input, so a
   mutating node mutates for real, a second time.
2. Null-hypothesis baseline (randomized-mutation control beaten, not just
   an absolute score threshold) — **BUILT** (G3)
3. Golden-trace regression (100% of the accumulated corpus, never shrinks)
   — **BUILT** (G2 + `check_never_shrinks`)
4. Bounded mutation rate per graph per time window — **BUILT** (G5)
5. Cumulative-drift monitoring across sequential sub-threshold edits —
   **BUILT** (G5)
6. Canary rollout stratified by tenant tag, gated on percentiles, previous
   version kept warm for rollback — **BUILT** (`aef/harness/canary.py`,
   ADR 0103). Known coverage limit, tested and stated: a regression
   confined to a slice narrower than the smallest configured percentile's
   complement is invisible to it.
7. Human-in-the-loop approval above a configurable risk threshold, signed
   release manifests — **BUILT** (`PolicyConfig.require_hitl_above_risk`
   plus `aef/harness/release.py`, ADR 0103). The signature is HMAC-SHA256:
   it proves an agent cannot forge an approval, and does NOT give
   third-party verifiability, which is stated rather than implied.

**All seven are now implemented. Phase 4 remains DISABLED**, and that is a
separate decision from whether the criteria are met: the owner throws the
switch, on the evidence, not the harness on its own.

`docs/trust/promotion-trust-case.md` is the assessment, and its
recommendation is **do not enable**. Its load-bearing reason is that criteria
1 and 6 have never run against the live traffic and real tenants their own
text names — implemented and tested is not the same as demonstrated on the
evidence they exist to produce. The shadow-containment bypass that was its
second reason is **closed**: the candidate runs inside the Milestone 4
container, containment is the default rather than an opt-in, and running
without it is explicit and recorded on every observation (ADR 0105). The
recommendation is unchanged, because that reason was never the one carrying
it. See ADR 0006, ADR 0104, ADR 0105, ADR 0106.

## Phase 5 — Multi-agent coordination, HITL at scale, first vertical agents — **STUBBED**

- `Coordinator`/`AgentRole`/`HandoffRequest` (`aef/coordination/base.py`)
  — deterministic hierarchical handoff as the intended default, emergent
  routing as an explicit opt-in exception; see ADR 0005. Nothing wired
  into `GraphExecutor`.
- `aef/agents/azure_sec/` exists as a directory (matching the report's
  reference layout) but has no implementation beyond
  `config/agent.azure_sec.yaml` — building the actual Azure Security
  Agent is Phase 5+ vertical work, out of this build's scope.

## Self-rewiring agents — planning program (design only, not built)

A separate, owner-gated program: agents propose changes to their own graph
**wiring** as reviewable diffs, validated by automated gates, with the
owner's merge to `main` as the only promotion mechanism. **This is not the
Phase 4 evolution engine** — that stays disabled (ADR 0006/0042); the
owner's commit review replaces unsupervised auto-promotion.

Planning artifacts (no implementation yet):
`docs/design/self-rewiring/` — `00-current-state.md` (ground truth,
cited), `01-architecture.md` (the wiring-manifest design + Mermaid
pipeline), `gates/` (six gate specs), `02-risks.md`, `03-roadmap.md`
(milestones M0–M9). Decisions recorded in ADRs 0041–0043.
