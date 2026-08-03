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
  `AuditLogWriter` — `aef/security/tool.py`
- [x] Memory interface: `MemoryStore` (six-type + tool taxonomy), real
  `InMemoryMemoryStore`, real `Mem0Adapter` — `aef/services/memory/`
  (see ADR 0004)
- [x] Basic eval harness: `Evaluator` interface, `EvaluationRecord`, real
  `RuleBasedEvaluator` with pluggable `domain_gates` —
  `aef/services/eval/`
- [x] Per-agent config: `AgentConfig` (report §16, verbatim + `evolution`),
  unknown-key rejection, `agent.example.yaml` + `agent.azure_sec.yaml` —
  `aef/config/`
- [x] CLI: `aef init`/`adopt`/`doctor`/`run`/`eval`/`trace` —
  `aef/cli/`

**Deliberately out of Phase 0/1 scope** (see ADR 0007): fan-out/fan-in
execution (BSP super-steps) — declared in the `Edge`/`Route` contract,
not executed.

## Phase 2 — Knowledge graph, context engine, token optimizer, planner — **STUBBED**

Interfaces only, no implementation:
- `GraphStore` (`aef/services/kg/base.py`) — see ADR 0003 for the
  Neo4j/FalkorDB-vs-Apache-AGE decision, deferred
- `Retriever` (`aef/services/context/base.py`) — retrieve/rank/prune/
  compress/assemble cascade (report §12) not implemented
- `TokenOptimizer` (`aef/services/tokens/base.py`) — compression beyond
  provider-native prompt caching, not implemented
- `Planner`/`PlanValidator` (`aef/reasoning/planner.py`) — hierarchical
  goal decomposition, not implemented

## Phase 3 — Reflection, offline optimization, private evals — **STUBBED**

- `Critic`/`Judge` (`aef/reasoning/reflection.py`) — Reflexion-style
  verbal feedback and rubric-scored judgment, not implemented
- `Optimizer` (`aef/services/optimizers/base.py`) — GEPA/DSPy-style
  offline prompt/program optimization, not implemented

## Phase 4 — Evolution engine with full safety rails — **STUBBED, DISABLED**

`aef/evolution/engine.py`: `MutationProposer`, `ArchiveStore`, `EvalGate`,
`CanaryController`, `EvolutionConfig`. Every method raises
`NotImplementedError`; `EvolutionConfig(enabled=True)` itself raises,
naming every unmet gate criterion. See ADR 0006 for why this is enforced
in code, not just documented. Re-enabling requires implementing ALL of:

1. Shadow execution against live traffic before promotion eligibility
2. Null-hypothesis baseline (randomized-mutation control beaten, not just
   an absolute score threshold)
3. Golden-trace regression (100% of the accumulated corpus, never shrinks)
4. Bounded mutation rate per graph per time window
5. Cumulative-drift monitoring across sequential sub-threshold edits
6. Canary rollout stratified by tenant tag, gated on percentiles, previous
   version kept warm for rollback
7. Human-in-the-loop approval above a configurable risk threshold, signed
   release manifests

## Phase 5 — Multi-agent coordination, HITL at scale, first vertical agents — **STUBBED**

- `Coordinator`/`AgentRole`/`HandoffRequest` (`aef/coordination/base.py`)
  — deterministic hierarchical handoff as the intended default, emergent
  routing as an explicit opt-in exception; see ADR 0005. Nothing wired
  into `GraphExecutor`.
- `aef/agents/azure_sec/` exists as a directory (matching the report's
  reference layout) but has no implementation beyond
  `config/agent.azure_sec.yaml` — building the actual Azure Security
  Agent is Phase 5+ vertical work, out of this build's scope.
