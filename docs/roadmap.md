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
- [x] CLI: `aef init`/`adopt`/`doctor`/`run`/`eval`/`trace` —
  `aef/cli/`

**Deliberately out of Phase 0/1 scope** (see ADR 0007): fan-out/fan-in
execution (BSP super-steps) — declared in the `Edge`/`Route` contract,
not executed.

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
  compress/assemble is deliberately absent — see below.
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
  **Still stubbed:** an LLM-backed Critic/Judge, and any use of a
  `Judgment` to gate or re-plan.
- `Optimizer` (`aef/services/optimizers/base.py`) — GEPA/DSPy-style
  offline prompt/program optimization, not implemented

## Self-rewiring harness (Zone B) — **M0/M1 REAL**

`aef/harness/` is the structurally-isolated harness that judges
agent-authored candidates (ADR 0044, ADR 0047). Real and tested:
`zones.py` (three-zone write scope, deny-by-default), `candidate.py`
(`git diff base...head` with the rename/symlink/submodule escapes closed),
`trust.py` (gates execute from the base ref — the load-bearing property),
`sandbox.py` (env scrubbing, timeouts, rlimits; declares what it cannot
enforce and refuses to run without attested network isolation).

Not built yet: the gates themselves (M3-M7), the corpus (M2), the proposer
(M8), and post-merge monitoring (M10). **Tier-1 auto-merge is not
implemented and must not be enabled before M10** — see
`docs/design/self-rewiring/05-approval-policy.md`.

## Phase 4 — Evolution engine with full safety rails — **STUBBED, DISABLED**

`aef/evolution/engine.py`: `MutationProposer`, `ArchiveStore`, `EvalGate`,
`CanaryController`, `EvolutionConfig`. Every method raises
`NotImplementedError`; `EvolutionConfig(enabled=True)` itself raises,
naming every unmet gate criterion. See ADR 0006 for why this is enforced
in code, not just documented. Re-enabling requires implementing ALL of:

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
switch, on the evidence, not the harness on its own. See ADR 0006 and the
trust case.

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
