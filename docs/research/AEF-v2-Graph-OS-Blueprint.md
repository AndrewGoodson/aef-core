# Agent Engineering Foundation (AEF) v2.0: A Graph-Native, Self-Improving Agent Operating System

## Executive Summary

The dominant agent frameworks of 2025-2026 solved narrow problems well but none solved the composite problem AEF must solve: running thousands of heterogeneous agents (security, procurement, trading, healthcare, coding) on one substrate that is model-agnostic, durable across failures, observable end-to-end, and capable of improving its own graphs, prompts, and routing without human intervention between iterations. LangGraph solved typed state and checkpointing but stops at single-process durability. Temporal solved distributed durable execution via event-sourced replay but has no native concept of "LLM state" or reasoning. CrewAI and AutoGen solved role-based and conversational multi-agent coordination respectively but neither unifies planning, memory, and evaluation into one contract. DSPy/GEPA solved automatic prompt and program optimization via reflective evolution but is not a runtime. Langfuse and OpenTelemetry solved observability but do not close the loop back into graph structure. AEF v2.0's core thesis is that **the graph is the operating system kernel**: every capability (planning, memory, evaluation, reflection, optimization, security, multi-agent coordination) is expressed as a typed, versioned, checkpointed subgraph that composes through one universal contract, so that Cyber Security Agents and Financial Agents differ only in their knowledge, policies, tools, and objectives — never in their execution substrate.[^1][^2][^3][^4][^5][^6][^7][^8][^9][^10][^11]

This report reverse-engineers fifteen production and research architectures, extracts their strongest primitives, and recombines them into a fourteen-layer specification: a Temporal-style durable execution core wrapping a LangGraph-style typed StateGraph, with DSPy/GEPA-style reflective self-optimization operating on the graph definition itself, Graphiti/Neo4j-style temporal knowledge-graph memory replacing flat vector stores, OpenTelemetry/Langfuse-style tracing as a first-class kernel service, and Reflexion/ACON-style critique loops feeding both short-term context compression and long-term graph evolution.

***

## Part 1: Reverse-Engineering the Landscape

### 1.1 Graph Execution Architectures — What Each Actually Solved

| System | Core Primitive | Strongest Idea | Fatal Limitation for AEF | Confidence |
|---|---|---|---|---|
| LangGraph | StateGraph, super-step, Pregel-style BSP | Typed shared state auto-merged across nodes; checkpoint-per-superstep gives free time-travel debugging[^12][^13] | Checkpointer choice (`MemorySaver`/`SqliteSaver`) is not production-durable by default; no built-in cross-process worker fleet[^2][^14] | High |
| Temporal | Workflow + Activity, event-sourced replay | True crash-proof durable execution: any worker can resume a workflow by replaying its event history deterministically[^4][^3] | No native LLM/agent semantics — you must bolt on "state" as ordinary activity payloads; workflow code must be strictly deterministic, which conflicts with LLM sampling unless isolated into activities[^4] | High |
| Prefect | Flow/Task DAG, hybrid worker execution | Python-native, no code restructuring, outbound-only worker polling keeps infra inside customer VPC[^15] | DAG-centric; not designed for long-lived stateful agent loops or human-in-the-loop pauses | Medium |
| Dagster | Software-Defined Assets | Strong lineage/type-safety for data-asset pipelines[^15][^16] | Forces asset paradigm onto everything — poor fit for reasoning loops and non-asset-producing agent steps[^15] | Medium |
| PocketFlow | 100-line graph core | Radical minimalism proves the *irreducible* graph kernel is tiny — node + edge + shared store, nothing else is essential[^17][^18][^19] | Zero built-in durability, memory, or observability — must be rebuilt entirely for production | High |
| CrewAI | Role + Task + Crew/Flow | Fast time-to-first-crew; Flows add deterministic event-driven control atop role abstraction[^20][^10] | Role metaphor breaks down for graph-native reasoning DAGs that aren't "job titles" (e.g., a critique-and-revise loop) | Medium |
| AutoGen / MS Agent Framework | Conversable agents, async actor model, GroupChat | Dynamic emergent routing driven by the model itself; async event-driven runtime scales to real distributed messaging[^8][^10] | Emergent routing is non-deterministic and hard to audit for compliance-heavy domains (federal contracting, healthcare)[^20] | Medium |
| OpenAI Agents SDK | Handoffs (tool-call-as-control-transfer) | Handoff-as-tool-call is elegantly simple; `input_filter` gives explicit control over what context rides along[^21][^22][^23] | Handoff defaults to passing the *entire* transcript, causing context bleed unless every handoff is manually filtered[^24] | Medium |
| Google ADK | Sub-agents, Artifacts, A2A protocol | Strict typed Artifacts and hierarchical parent→child transfer give enterprise-grade state discipline[^25][^26] | Sibling agents cannot transfer to each other without explicit tree redesign — rigid hierarchy fights swarm patterns[^24] | Medium |
| Graph of Thoughts / Tree of Thoughts | Reasoning as DAG/tree over "thought" vertices | GoT generalizes ToT: thoughts can merge, aggregate, and refine via arbitrary edges, not just branch/backtrack — empirically beats ToT on aggregation-heavy tasks[^27][^28][^29] | Reasoning-graph research treats the graph as a prompting artifact per-query, not as a durable, checkpointed execution substrate | High |

**What AEF inherits:** LangGraph's typed shared-state super-step model, Temporal's event-sourced durability guarantee, PocketFlow's minimal node/edge/store kernel, OpenAI SDK's handoff-as-tool-call simplicity (with mandatory input filtering), Google ADK's strict Artifact typing, and GoT's arbitrary-graph reasoning topology (not just trees).

**What AEF improves:** Unlike every framework above, AEF makes the graph *self-describing and self-modifying* — nodes carry machine-readable contracts (see Part 2) that a meta-optimizer can read, mutate, and re-validate, closing the loop from Part 4 research directly into Part 2 structure.

**What AEF avoids:** Vendor-specific state schemas (ADK Artifacts, OpenAI Handoff objects), non-deterministic emergent routing as the *default* (AutoGen GroupChat), and any framework-level coupling to a single model provider's tool-calling format.

***

## Part 2: Universal Graph Scaffold

### 2.1 Node Contract

Every node in AEF — regardless of whether it performs planning, memory retrieval, tool execution, evaluation, or reflection — implements one contract:

```
Node {
  id: str                      # stable, versioned identifier
  version: semver               # independent node versioning
  input_schema: TypedContract   # Pydantic/JSON-Schema, validated at entry
  output_schema: TypedContract  # validated at exit — no untyped dict blobs
  side_effects: enum[pure, io, external_call, mutating]
  cost_model: {tokens, latency_p50, latency_p99, $_per_call}
  idempotency_key_fn: callable  # required if side_effects != pure
  telemetry_tags: [str]
  fallback_node_id: Optional[str]
}
```

This borrows LangGraph's typed-state discipline and Temporal's idempotent-activity requirement, but pushes typing to the *node* boundary rather than only the *global state* boundary — this is what lets a self-improvement engine safely swap one node implementation for another without breaking the graph, because contracts (not implementations) are the compatibility surface.[^30][^4]

### 2.2 Edge Contract

Edges are typed routing functions, not implicit `next()` calls:

```
Edge {
  from_node: str
  to_node: str | list[str]      # supports fan-out
  condition: callable(state) -> bool
  priority: int                  # deterministic tie-break, no LLM randomness by default
  requires_human_approval: bool  # HITL gate
}
```

Conditional edges follow LangGraph's pattern, but AEF forbids *unconditional* LLM-decided routing as a default — every AutoGen-style "let the model pick" edge must declare `requires_deterministic_fallback: true`, addressing the auditability failure identified in Part 1.[^20][^30]

### 2.3 Graph State, Checkpointing, and Durability

AEF adopts a two-tier durability model combining LangGraph's super-step checkpoint with Temporal's event-sourced replay:

- **Tier 1 (fast path):** After every node super-step, a `StateSnapshot` (channel values, channel versions, next-node queue, task metadata) is written to PostgreSQL, matching LangGraph's `PostgresSaver` pattern. This gives sub-second time-travel debugging and human-in-the-loop pause/resume.[^2][^31]
- **Tier 2 (durability guarantee):** Every node execution is wrapped as a Temporal Activity with a deterministic idempotency key; the enclosing Workflow's event history is the system of record for crash recovery across the entire worker fleet, not just one process. If a worker dies mid-node, another worker resumes by replaying history — LangGraph alone cannot do this across machines, and Temporal alone has no concept of LLM state, so the combination is required, not optional.[^3][^4]
- **Checkpoint size discipline:** empirical guidance from production LangGraph deployments caps a single checkpoint at 50KB before latency degrades; anything larger (documents, embeddings, large tool outputs) is written to an external object store (S3-equivalent) with only a reference pointer in the checkpoint, following AWS's DynamoDB/S3 pattern.[^14][^12]

### 2.4 Graph Versioning, Composition, and Testing

- **Semantic versioning per subgraph.** A subgraph (e.g., "ORB signal-gate subgraph") is a package with its own version, independently testable and independently rollback-able — this directly supports RAPTOR's own WFA validation discipline, where a graph version must be pinned to the exact model artifact that passed Sharpe/PF/MaxDD gates.
- **Graph diffing.** Structural diff (nodes added/removed, edge conditions changed) plus behavioral diff (regression suite pass/fail deltas) run in CI before any subgraph promotion — this is the graph-native analog of DSPy/GEPA's requirement that only mutations improving the validation metric survive.[^32]
- **Golden-trace regression testing.** Every promoted graph version retains N golden execution traces (captured via the observability layer, Part 10) that must still reproduce equivalent outputs (not byte-identical, since LLMs are stochastic, but equivalent under the evaluation rubric from Part 9) before deployment.

***

## Part 3: Universal Planning Graph

### 3.1 Hierarchical Plan Structure

AEF planning is itself a subgraph with three tiers, borrowed from hierarchical task network planning and refined by GoT's arbitrary-graph reasoning:

1. **Meta-planner node** — decomposes the goal into a DAG of sub-goals (not a flat list), because dependency planning requires knowing which sub-goals block others.
2. **Tactical planner nodes** (one per sub-goal) — each emits an executable subgraph reference plus resource/risk budget (for RAPTOR: this is where a 3% risk-per-trade constraint would be injected as a hard planning constraint, not a post-hoc filter).
3. **Constraint/risk validator node** — runs before any tactical plan is admitted to execution; rejects plans violating hard gates (analogous to RAPTOR's Sharpe/PF/MaxDD/min-trade-count validation gates, generalized as a pluggable `PlanValidator` interface every domain agent implements with its own criteria).

### 3.2 Plan Evolution and Reusability

Plans that pass execution and evaluation (Part 9) are distilled into **Plan Templates** — parameterized subgraphs stored in the Knowledge Graph (Part 6) with edges to the goal-types they solved, the evaluation scores they achieved, and the failure modes they avoided. Future meta-planner calls retrieve the top-k templates by goal-embedding similarity before generating from scratch, mirroring how ACON distills expensive compression strategies into reusable, cheaper guidelines. This is the mechanism by which "plans become reusable" — not prompt caching, but structural template caching in the graph memory itself.[^33][^34]

***

## Part 4: Universal Self-Improvement Architecture

### 4.1 The Three-Layer Improvement Stack

| Layer | Mechanism | Improves | Evidence Base |
|---|---|---|---|
| L1: In-episode reflection | Actor/Evaluator/Self-Reflection triad; episodic memory buffer of verbal critiques grounded in external signals (test results, tool errors) | The current execution's next attempt | Reflexion: 91% pass@1 vs 80% baseline on HumanEval[^35][^36] |
| L2: Cross-episode prompt/program optimization | Reflective evolutionary search over textual components (instructions, few-shot examples) using a reflection LM that reads full execution traces, not just scalar rewards | All future executions of a given node/subgraph | GEPA: outperforms GRPO by up to 20% with up to 35x fewer rollouts; beats MIPROv2 by 10%+[^37][^38][^7] |
| L3: Structural graph evolution | Automatic node/edge mutation, pruning, merging, specialization, evaluated against golden-trace regression + validation gates before promotion | The graph topology itself | Extrapolated from GEPA's Pareto-aware candidate selection[^32] applied to graph structure rather than text |

### 4.2 Closing the Loop: Failure-Driven Optimization (ACON Pattern)

AEF generalizes ACON's insight beyond context compression to the entire self-improvement stack: **improvement should be driven by paired trajectory analysis** — find cases where configuration A succeeded and configuration B (a candidate mutation) failed, have a capable reflection model diagnose *why*, and update the guideline/prompt/graph-edge accordingly. This is strictly better than scalar-reward-only optimization because it produces human-auditable rationale for every accepted change — a hard requirement for regulated domains (federal contracting, healthcare, financial agents) where "the graph mutated and got better" is not an acceptable audit trail; "the graph mutated because trace analysis showed X, here is the diff" is.[^39][^33]

### 4.3 Stability Guarantees for Self-Modifying Graphs

Unconstrained self-modification is the single largest risk in this entire architecture. AEF enforces:

- **Shadow execution before promotion:** every structural mutation runs in parallel shadow mode against live traffic (read-only, no side effects) for a minimum trace count before being eligible for promotion.
- **Validation-gate parity with RAPTOR's own discipline:** just as RAPTOR requires Sharpe > 0.8, PF > 1.3, MaxDD < 20%, and ≥100 OOS trades before accepting a trading strategy, every AEF graph mutation requires domain-specific quantitative gates plus a null-hypothesis baseline (a randomized-mutation control) before promotion — this null-baseline requirement, borrowed directly from RAPTOR's own anti-overfitting discipline, is the single most effective safeguard against an optimizer convincing itself noise is signal.
- **Bounded mutation rate and automatic rollback:** at most K structural mutations per graph per time window; any promoted mutation whose live-traffic evaluation score regresses beyond a tolerance triggers automatic rollback to the last stable version (checkpointed per Part 2.3).

***

## Part 5: Universal Memory Architecture

### 5.1 Memory Taxonomy and Storage Mapping

| Memory Type | What Is Stored | When Written | Storage Substrate |
|---|---|---|---|
| Working memory | Current node's input/output within one super-step | Every node call | In-process, ephemeral |
| Episodic memory | Full execution trace of one graph run (thoughts, tool calls, outcomes) | End of run | Checkpoint store (Part 2.3) + trace store (Part 10) |
| Semantic memory | Extracted entities, facts, preferences generalized across runs | Post-run entity extraction | Knowledge graph (Part 6) |
| Procedural memory | Reusable plan templates, optimized prompts, validated subgraphs | On promotion (Part 4.3) | Graph-versioned package registry |
| Failure memory | Paired trajectories where an approach failed, plus diagnosed cause | On evaluation failure | Knowledge graph, tagged `failure_mode` |
| Success memory | Trajectories that passed all validation gates | On evaluation success | Knowledge graph, tagged `validated_pattern` |
| Tool memory | Tool call signatures, latency/cost profile, historical reliability | Every tool invocation | Time-series store, aggregated into node `cost_model` |

This taxonomy directly extends the three-tier memory model already emerging in production agent-memory frameworks (short-term conversational, long-term entity/preference, reasoning-trace memory), but AEF adds **failure memory** and **success memory** as first-class citizens because Part 4's self-improvement loop cannot function without an explicit corpus of paired trajectories to reflect on.[^40]

### 5.2 The "Why" of Temporal, Not Flat, Memory

Zep AI's Graphiti demonstrates the core justification: static vector-store RAG cannot represent that a fact was true *then* and is false *now* — a temporally-aware knowledge graph incrementally updates entities and relationships without batch recomputation. For AEF this matters concretely: a Cyber Security Agent's "known vulnerable dependency" fact and a Financial Agent's "current position size" fact both have validity windows; flat embeddings cannot express invalidation, only similarity.[^41]

***

## Part 6: Universal Knowledge Graph Architecture

### 6.1 Graph Database Selection

| Engine | Strength | Weakness | AEF Fit |
|---|---|---|---|
| Neo4j | Mature Cypher ecosystem, native GraphRAG context providers, temporal memory providers (Graphiti)[^40][^42] | JVM-based ops overhead at Mac-Studio/local scale | Recommended for cloud/enterprise deployment tier |
| Memgraph | In-memory speed, Cypher-compatible, lower ops footprint | Smaller ecosystem than Neo4j | Recommended for low-latency local-first deployment (fits RAPTOR's Mac Studio local stack) |
| Apache AGE | PostgreSQL extension — graph queries over existing Postgres | Less mature GraphRAG tooling | Best fit when infra standardizes on Postgres (RAPTOR already runs PostgreSQL :5434, making AGE a near-zero-new-infra option) |

**Recommendation for AEF's reference deployment:** Apache AGE as the default embedded graph layer (zero new infrastructure, reuses the existing PostgreSQL dependency already present in the checkpoint store), with a pluggable adapter interface so enterprise tenants can swap to Neo4j/Memgraph for scale without touching graph logic.

### 6.2 Memory-Replaces-Memory: The Core Argument

Traditional agent memory (flat key-value or vector-embedding stores) cannot answer "why did node X make this decision three executions ago, and what changed since." A knowledge graph memory can, because episodic traces are stored as connected entities (goal → plan → node execution → tool call → outcome → evaluation score) rather than isolated blobs — this is precisely what GraphRAG-style retrieval enables (retrieving connected subgraphs, not isolated chunks) and what the Neo4j Memory Provider formalizes into short-term/long-term/reasoning-trace tiers.[^42][^40]

***

## Part 7: Universal Context Engineering Engine

### 7.1 The Governing Principle

Context engineering is now considered the primary bottleneck in agent engineering, more so than model capability. The governing metric is not compression ratio but **task-relevant information density per token retained** — AEF never optimizes for "fewer tokens" as an end in itself.[^34][^43]

### 7.2 The Three-Layer Cascade

AEF standardizes the emerging industry-convergent pattern of layered, threshold-triggered context management:[^44][^43]

- **Layer 1 — Tool-output compression (always-on, zero LLM cost).** Any tool output exceeding ~2,000 tokens is truncated in the response with the full payload written to the object store and replaced by a path reference plus preview. For RAPTOR specifically: a Databento OHLCV pull or full COT report is never dumped into context — only the reference plus derived summary statistics are.[^43]
- **Layer 2 — Input eviction (threshold-triggered, zero LLM cost).** Stale tool results and superseded reasoning steps are dropped once their originating decision is finalized.
- **Layer 3 — LLM summarization / compaction (threshold-triggered, highest cost).** Triggered at ~70% of effective context window, not at exhaustion, because a model already suffering context rot produces a degraded summary of itself. AEF adopts the anchored-iterative pattern: only the newly-evicted span is summarized and merged into a persistent structured anchor (Session Intent / Decisions / Active Goals / Next Steps), never a full from-scratch resummarization.[^45][^39][^44][^43]

### 7.3 Adaptive Retrieval and Ranking

Context assembly per node is a ranked retrieval problem, not a static template: each node's contract (Part 2.1) declares its `context_budget`, and the context engine retrieves from working memory, episodic memory, and knowledge-graph memory in priority order until the budget is filled, applying recency decay and task-relevance scoring — directly implementing the "dynamic context assembly" principle validated across the 2026 context-engineering literature.[^46][^43]

***

## Part 8: Universal Token Optimization Engine

### 8.1 Maximizing Intelligence-per-Token, Not Minimizing Tokens

| Technique | Mechanism | Reported Impact | Confidence |
|---|---|---|---|
| Prompt caching (provider-native) | Stable system-prefix + tool-definitions cached at API level; never vary the prefix between turns[^45] | Claude ~90% cost savings on cached prefix, Gemini 75-90%, OpenAI ~50%[^46] | High |
| Semantic caching (Redis/GPTCache-style) | Cache LLM responses keyed by embedding similarity of the request, not exact match | Eliminates redundant calls for near-duplicate queries (e.g., repeated ORB signal checks under similar market conditions) | Medium |
| Structural token compression (LLMLingua) | Perplexity-guided surgical token removal, not summarization | 2-5x compression with minimal quality loss[^46] | Medium |
| Tool-output pre-filtering (Headroom-style) | Compress tool outputs/logs/RAG chunks before they reach the LLM, at the proxy/MCP-server layer | 60-95% token reduction, same-quality answers, +14K GitHub stars in one week signaling strong practitioner validation[^47] | High |
| Sub-agent isolation pattern | Sub-agents consume large context for deep focused work, return only 1-2K token summaries to the orchestrator[^44] | Prevents orchestrator context pollution in multi-agent swarms (Part 12) | High |

### 8.2 Application to RAPTOR's Own Stack

Concretely: RAPTOR's LightGBM signal-gate node should never receive raw 1-minute OHLCV bars as LLM context — feature vectors are computed in Python (already the case), and any LLM-facing node discussing strategy performance should retrieve pre-aggregated WFA fold summaries from the knowledge graph, not raw trade logs, applying Layer 1 of the context cascade (Part 7.2) by default.

***

## Part 9: Universal Evaluation Engine

### 9.1 Framework Selection

| Framework | Best For | Weakness | AEF Role |
|---|---|---|---|
| DeepEval | pytest-style CI/CD integration, 50+ metrics including agent trajectory/tool-correctness, every metric ships LLM reasoning alongside score[^48][^49] | Newer than Ragas for pure RAG grounding metrics | Primary CI/CD gate for node/subgraph promotion |
| Ragas | Reference-free faithfulness/context-precision/recall, now extended with agent goal accuracy and tool-call F1[^49][^48] | Known NaN-on-invalid-JSON production issue outside LangChain/LlamaIndex[^48] | RAG-component grounding checks specifically |
| Langfuse (eval layer) | Production trace-based scoring, user feedback capture, dataset curation from live traces | Not a standalone offline benchmark harness | Continuous online evaluation, feeding L2/L3 self-improvement (Part 4) |

### 9.2 Scoring Every Graph Execution

Every graph run produces a structured `EvaluationRecord`: task-completion score, tool-call accuracy, trajectory quality (did the plan DAG execute in a sane order), cost (tokens/latency/$), and domain-specific gates (for RAPTOR: Sharpe/PF/MaxDD/trade-count against the null-hypothesis baseline). This record is the atomic unit consumed by Part 4's self-improvement loop and Part 11's graph-evolution engine — evaluation is not a separate reporting concern, it is the fuel for the entire self-improving system.

***

## Part 10: Universal Observability Architecture

### 10.1 Two-Pipeline Model

AEF standardizes on the industry-convergent pattern of parallel Langfuse (trace-level, LLM-specific) and OpenTelemetry (infrastructure-level, vendor-neutral) pipelines feeding one dashboard:[^5][^6]

- **Langfuse pipeline:** every node execution becomes a span/generation capturing prompt, response, token usage, cost, and latency, nested to mirror the graph's actual topology. Because Langfuse is fully OTel-based and framework-agnostic, it works identically whether the underlying node calls OpenAI, Anthropic, Gemini, or a local Llama/DeepSeek/Qwen model.[^6][^50][^51][^52]
- **OpenTelemetry pipeline:** infrastructure metrics (worker CPU/memory, queue depth, checkpoint write latency) flow to Grafana/Prometheus, correlated to Langfuse traces via a shared trace ID.[^5]
- **W3C Trace Context compliance:** deterministic trace IDs allow correlating an external system event (e.g., an IBKR order rejection) directly to the graph execution that caused it.[^53]

### 10.2 Execution Replay

Because checkpoints (Part 2.3) capture full state per super-step, and Langfuse traces capture full LLM I/O per node, any historical execution can be replayed exactly for debugging — this is the direct payoff of investing in typed state contracts rather than free-form message logs.

***

## Part 11: Autonomous Graph Evolution Engine

### 11.1 Can Graphs Improve Themselves? Yes, With Guardrails

The research base for automatic architecture search on textual/graph systems is genuinely production-validated at the *prompt* level (GEPA achieving ICLR 2026 Oral recognition, outperforming both MIPROv2 and GRPO-style RL with up to 35x fewer rollouts), and AEF extrapolates this reflective-evolution mechanism one level up, to graph structure itself:[^37][^38]

1. **Candidate generation:** propose node additions, edge rewiring, subgraph merges, or node specialization, generated by a reflection LM analyzing failure-mode clusters from the evaluation engine (Part 9).
2. **Pareto-aware selection:** candidates are scored across multiple axes simultaneously (accuracy, cost, latency, risk-gate compliance) rather than collapsing to one scalar, following GEPA's Pareto-frontier approach — critical because a graph mutation that improves accuracy but silently increases cost 10x is not an acceptable trade for a $25K RAPTOR account operating under strict risk parameters.[^11][^32]
3. **Shadow validation and null-baseline test** (Part 4.3) before any promotion.
4. **Bounded, reversible deployment** with automatic rollback on live regression.

### 11.2 Instability Modes to Guard Against

- **Reward hacking on the evaluation metric itself** — mitigated by requiring the same null-hypothesis-baseline discipline RAPTOR already applies to trading strategies (a randomized-mutation control group must be beaten, not just an absolute score threshold).
- **Runaway mutation cascades** — mitigated by the bounded mutation-rate cap (Part 4.3).
- **Silent capability regression on rare edge cases** — mitigated by the golden-trace regression suite (Part 2.4), which is never allowed to shrink; every new promoted graph must pass 100% of the accumulated golden-trace corpus, not just new tests.

***

## Part 12: Universal Multi-Agent Architecture

### 12.1 Role Taxonomy

AEF standardizes seven canonical agent roles that compose into any domain-specific swarm: Supervisor (routes and owns final output), Planner (Part 3), Research/Worker (domain execution), Critic (Reflexion-style critique, Part 4.1), Judge/Verifier (Part 9 evaluation), Tool Agent (wraps external systems), and Memory Agent (Part 5/6 read-write gateway).

### 12.2 Coordination Pattern Selection

| Pattern | When to Use | Framework Precedent |
|---|---|---|
| Deterministic hierarchical handoff | Compliance-critical domains (federal contracting, healthcare, financial) where auditability is mandatory | Google ADK's parent→child sub-agent transfer[^24][^26] |
| Tool-call handoff with mandatory input filtering | Sequential specialist pipelines (triage → domain specialist) | OpenAI Agents SDK handoffs, always with `input_filter` applied[^22][^23] |
| Emergent conversational routing | Exploratory/research tasks where the path genuinely cannot be predetermined (e.g., open-ended vulnerability research for Bug Hunting Agents) | AutoGen GroupChat[^20][^8], used only where `requires_deterministic_fallback` (Part 2.2) is explicitly waived and logged |
| Sub-agent isolation with summary-only return | Any swarm where deep-context work must not pollute the orchestrator's window | Context-engineering sub-agent pattern[^44] |

AEF's default is deterministic hierarchical handoff for every regulated domain in scope (Cyber Security, Azure, Red/Purple Team, Procurement, Federal Contracting, Healthcare, Financial), reserving emergent routing as an explicitly opt-in, logged exception — directly addressing the auditability gap identified in Part 1 for AutoGen-style architectures.

***

## Part 13: Universal Agent Scaffold

Every agent in the AEF ecosystem — Cyber Security, Red Team, Procurement, Financial, Healthcare, Coding, Sales, Data Mining — inherits identically:

- Graph engine (Part 2) with checkpointing/durability
- Planning subgraph (Part 3)
- Memory stack: working/episodic/semantic/procedural/failure/success (Part 5) backed by the knowledge graph (Part 6)
- Evaluation engine (Part 9) and reflection loop (Part 4.1)
- Self-optimization engine (Part 4.2-4.3) and graph evolution engine (Part 11)
- Context engineering cascade (Part 7) and token optimization layer (Part 8)
- Observability pipeline (Part 10)
- Security/guardrail gate (input/output validation, PII/secrets redaction at the context-engine boundary)
- Telemetry tagging (Part 2.1 `telemetry_tags`)

**What differs per domain** (and only this): the knowledge graph's domain ontology, the policy/constraint set injected into the plan validator (Part 3.1), the tool registry, the objective function, and the evaluation metric weights. A Cyber Security Agent's plan validator enforces attack-surface and blast-radius constraints; a Financial Agent's plan validator enforces RAPTOR-style Sharpe/PF/MaxDD/risk-per-trade gates — same validator *interface*, different constraint payload.

***

## Part 14: Engineering Standards

- **Node/Edge design:** pure functions wherever possible; all side effects declared and idempotency-keyed (Part 2.1); no node exceeds one clearly-named responsibility.
- **Graph APIs:** every subgraph exposes `compile()`, `validate()`, `diff(other_version)`, `visualize()` as mandatory interface methods.
- **Testing:** unit tests per node contract, integration tests per subgraph, golden-trace regression per full graph (Part 2.4), null-baseline tests per self-improvement promotion (Part 4.3).
- **Versioning/CI/CD:** semantic versioning per subgraph package; CI gate = golden-trace pass + evaluation-metric non-regression + cost/latency budget check.
- **Dependency injection:** model provider, knowledge-graph backend, checkpoint store, and observability sink are all injected interfaces — this is the literal mechanism by which "no architecture change" is required to move between OpenAI, Anthropic, Gemini, local Llama, DeepSeek, Qwen, Mistral, or future models; only the model-adapter implementation changes, never the graph.
- **Plugin architecture:** tools, evaluators, and memory backends register through a common plugin manifest (name, version, contract, capability tags), enabling the "thousands of specialized agents" claim without a combinatorial explosion of bespoke integration code.

***

## Technology Comparison Matrix (Consolidated)

| Concern | AEF Choice | Primary Alternative Rejected | Why |
|---|---|---|---|
| Graph runtime kernel | Custom typed StateGraph (LangGraph-inspired) wrapped in Temporal workflows | LangGraph alone | Needs cross-process durability Temporal provides[^4] |
| Durability | Temporal event-sourced replay + Postgres checkpoint tier | Dagster/Prefect native retry | Neither guarantees deterministic cross-worker resume for LLM-state workflows[^15] |
| Knowledge graph | Apache AGE (default), Neo4j/Memgraph (pluggable) | Pure vector store | Cannot express temporal fact invalidation[^41] |
| Multi-agent default | Deterministic hierarchical handoff | AutoGen emergent GroupChat | Auditability required across regulated domains[^20] |
| Prompt/graph optimization | GEPA-style reflective evolution | RL/GRPO fine-tuning | 20% better with up to 35x fewer rollouts, model-agnostic (no weight access needed)[^38] |
| Observability | Langfuse + OpenTelemetry dual pipeline | Framework-native logging only | Vendor-neutral, works across all target model providers[^6] |
| Evaluation | DeepEval (CI gate) + Ragas (grounding) + Langfuse (online) | Single-framework lock-in | Each covers a distinct gap; no single tool covers all three[^49] |

***

## Risk Analysis and Tradeoffs

- **Complexity risk:** a fourteen-layer OS is dramatically more complex than any single framework surveyed. Mitigation: Part 13's scaffold ensures 90% of this complexity is inherited invisibly by every new domain agent — the marginal cost of adding agent #1,001 is low even though the cost of building layer 1 was high.
- **Self-modification risk:** the single greatest hazard in the entire design is an evolution engine that convinces itself a regression is an improvement. Mitigation is layered (Part 4.3, Part 11.2) but ultimately depends on evaluation-metric quality — garbage evaluation criteria will produce garbage self-improvement regardless of how sophisticated the graph engine is.
- **Latency/cost overhead:** Temporal's durability guarantee and dual-pipeline observability both add real per-call overhead versus a bare LLM call. This is an explicit, accepted tradeoff for production-grade reliability across regulated domains; latency-critical paths (e.g., RAPTOR's sub-second signal gate) should bypass full graph overhead and call the LightGBM model directly, using the graph only for the surrounding orchestration/risk-check layer, not the hot path itself.
- **Vendor-neutrality tax:** maintaining strict model-adapter abstraction (Part 14) costs upfront engineering time versus coupling directly to one provider's SDK (e.g., OpenAI Agents SDK handoffs). This is justified given the explicit decade-long, multi-model requirement in scope.

***

## Phase-by-Phase Implementation Roadmap

1. **Phase 0 (Foundation):** Build the node/edge contract system and minimal graph kernel (PocketFlow-scale simplicity, ~100-500 lines), Postgres checkpoint tier, single-process execution only.
2. **Phase 1 (Durability):** Wrap kernel execution in Temporal workflows/activities; validate crash-recovery across worker restarts.
3. **Phase 2 (Memory):** Stand up Apache AGE knowledge graph, implement the six memory-type taxonomy (Part 5), migrate any existing flat-store memory.
4. **Phase 3 (Observability):** Instrument every node with the dual Langfuse/OpenTelemetry pipeline before adding any self-improvement logic — you cannot safely evolve what you cannot observe.
5. **Phase 4 (Evaluation):** Deploy DeepEval CI gates and Langfuse online scoring; establish golden-trace corpus.
6. **Phase 5 (Context/Token Engineering):** Implement the three-layer context cascade and provider-native prompt caching.
7. **Phase 6 (Self-Improvement L1-L2):** Add Reflexion-style episodic reflection, then GEPA-style prompt/program optimization, gated by Phase 4's evaluation infrastructure.
8. **Phase 7 (Graph Evolution L3):** Only after Phase 6 is stable in production, enable structural graph mutation with shadow execution and null-baseline gating.
9. **Phase 8 (Multi-Agent Scale-Out):** Onboard domain agents (starting with the lowest-compliance-risk domain, e.g., Research Agents, before Financial/Healthcare) using the universal scaffold (Part 13).
10. **Phase 9 (Vendor-Neutral Hardening):** Validate the model-adapter abstraction against at least three providers (one frontier API, one open-weight local model) before declaring the graph architecture "future-model-proof."

***

## Final Recommended Architecture for AEF v2.0

The recommended reference architecture is a **Temporal-durable, Postgres/AGE-checkpointed, typed StateGraph kernel**, instrumented end-to-end with Langfuse/OpenTelemetry, evaluated continuously by DeepEval/Ragas/Langfuse-online, improved via a three-layer stack culminating in GEPA-style reflective structural graph evolution bounded by shadow-execution and null-hypothesis-baseline gates, with every domain agent (RAPTOR's Financial Agent included) inheriting the identical scaffold and differing only in knowledge, policy, tools, and objectives. This design directly generalizes RAPTOR's own hard-won discipline — anti-lookahead rules, null-hypothesis validation gates, and OOS-concatenated performance thresholds — into the universal architecture, making AEF's most rigorous existing production agent the template for how every future agent must prove itself before promotion.

---

## References

1. [LangGraph State: Checkpoints, Threads, and Recovery | Easton](https://eastondev.com/blog/en/posts/ai/20260424-langgraph-agent-architecture/) - A checkpoint is a recovery point for interruption, timeout, human handoff, and service restart, not ...

2. [checkpoints | langgraph](https://reference.langchain.com/python/langgraph/checkpoints) - Checkpoints allow LangGraph agents to persist their state within and across multiple interactions. A...

3. [Temporal: Durable Execution That Survives the Apocalypse](https://james-carr.org/posts/2026-01-29-temporal-workflow-orchestration/) - Building reliable distributed systems with Temporal durable execution using a cyberpunk-themed examp...

4. [Temporal for Durable Workflow Orchestration — Activities ...](https://www.datasops.com/blog/temporal-workflow-engine) - Event-sourcing replay model, Python SDK workflow and activity definitions, retry policies with heart...

5. [Langfuse + OpenTelemetry: Build Agent Observability from Scratch (Python)](https://www.youtube.com/watch?v=sedNDoJC-Rc) - Build a full observability stack for your LangGraph agents using Langfuse for trace-level inspection...

6. [OpenTelemetry (OTEL) for LLM Observability](https://langfuse.com/integrations/native/opentelemetry) - Connect Langfuse to OpenTelemetry (OTEL) and send OTLP traces from your application or collector to ...

7. [GEPA optimization](https://dspy.ai/getting-started/gepa-optimization/) - The framework for programming—rather than prompting—language models.

8. [AutoGen vs CrewAI: Which Multi-Agent Framework Wins in 2026?](https://www.sandbase.ai/blog/autogen-vs-crewai-multi-agent-showdown-2026/) - A head-to-head comparison of AutoGen and CrewAI for multi-agent systems in 2026: architecture, devel...

9. [Microsoft AutoGen vs CrewAI for Production AI Agents (2026) | AI Agents Guide](https://www.aiagentlearn.site/comparisons/autogen-vs-crewai/) - Side-by-side comparison of Microsoft AutoGen and CrewAI for production multi-agent development. Arch...

10. [CrewAI vs AutoGen (2026): Multi-Agent Framework Verdict](https://genai.qa/blog/crewai-vs-autogen/) - CrewAI vs AutoGen compared - role-based crews and flows vs conversation-driven agents, control model...

11. [gepa/README.md at main - GitHub](https://github.com/gepa-ai/gepa/blob/main/README.md) - Optimize prompts, code, and more with AI-powered Reflective Text Evolution - gepa-ai/gepa

12. [Build durable AI agents with LangGraph and ...](https://aws.amazon.com/blogs/database/build-durable-ai-agents-with-langgraph-and-amazon-dynamodb/) - In this post we show you how to build production-ready AI agents with durable state management using...

13. [Persistence System | langchain-ai/langgraph | DeepWiki](https://deepwiki.com/langchain-ai/langgraph/4-human-in-the-loop-and-control-flow) - LangGraph's persistence layer provides two complementary mechanisms for maintaining state across exe...

14. [LangGraph State Management: Checkpointing & Recovery](https://activewizards.com/blog/langgraph-state-management-checkpointing-recovery-and-the-persistence-layer-decision/) - This post covers the four decisions that determine whether your LangGraph state architecture survive...

15. [Prefect vs Dagster - Python-First Workflow Orchestration](https://www.prefect.io/compare/dagster?_rsc=iuhms)

16. [Prefect vs Dagster – Which Data Orchestration Tool is BETTER in 2025](https://www.youtube.com/watch?v=2f-FuFOM0oA) - 🔍 What You’ll Learn:
Compare Prefect and Dagster, two leading data orchestration frameworks in 2025....

17. [Pocket Flow: 100-line LLM framework. Let Agents build ...](https://github.com/the-pocket/PocketFlow) - Pocket Flow is a 100-line minimalist LLM framework Lightweight: Just 100 lines. Zero bloat, zero dep...

18. [Home | Pocket Flow](https://the-pocket.github.io/PocketFlow/) - Pocket Flow. A 100-line minimalist LLM framework for Agents, Task Decomposition, RAG, etc. Lightweig...

19. [PocketFlow: 100-Line LLM Agent Framework](https://dev.co/ai/rag/pocketflow) - PocketFlow is a minimalist Python LLM framework in just 100 lines of code, enabling agents, workflow...

20. [CrewAI vs AutoGen: Multi-Agent Orchestration 2026](https://freeacademy.ai/blog/crewai-vs-autogen-multi-agent-orchestration) - How CrewAI and AutoGen orchestrate multi-agent systems: role-based crews, conversational teams, and ...

21. [Handoffs - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/handoffs/)

22. [Mastering Agent Handoffs in OpenAI Agents SDK – Expert Notes | Medium](https://medium.com/@abdulkabirlive1/mastering-handoff-agents-in-the-openai-agents-sdk-complete-guide-6103bd85217a) - When building multi-agent workflows, one agent often needs to delegate tasks to another — for exampl...

23. [Orchestration and handoffs | OpenAI API](https://developers.openai.com/api/docs/guides/agents/orchestration) - Learn how to orchestrate multiple agents with handoffs and agents-as-tools in the OpenAI Agents SDK.

24. [Agent Handoffs in LangGraph, OpenAI Agents SDK, and Google ADK: What Actually Transfers With Control](https://dreaming.press/posts/agent-handoffs-langgraph-openai-adk.html) - Every multi-agent framework now has a handoff primitive, and they all look the same in the demo. The...

25. [The Agent SDK Landscape | The AI Agent Factory](https://agentfactory.panaversity.org/docs/Building-Agent-Factories/introduction-to-ai-agents/agent-sdk-landscape) - OpenAI's approach focuses on handoffs. Architecture: Lightweight Python/Node implementation using "H...

26. [OpenAI Agents SDK vs. Google ADK (後編) - 株式会社調和技研](https://www.chowagiken.co.jp/future-studio/series2_openai_vs_googleadk/) - 今回は2部構成で発信している「OpenAI Agents SDK vs. Google ADK」の後編です。前編では、AIエージェントの開発環境である OpenAI Agents SDK と Goog...

27. [[PDF] GoT: Effective Graph-of-Thought Reasoning in Language Models](https://aclanthology.org/2024.findings-naacl.183.pdf)

28. [Review of “Graph of Thoughts: Solving](https://cis.temple.edu/tagit/presentations/Review%20of%20Besta23.pdf)

29. [Boosting Logical Reasoning in Large Language Models through a New Framework: The Graph of Thought](https://ar5iv.labs.arxiv.org/html/2308.08614) - Recent advancements in large-scale models, such as GPT-4, have showcased remarkable capabilities in ...

30. [LangGraph in Production: Building Stateful AI Agents](https://www.kalviumlabs.ai/blog/langgraph-in-production-stateful-multi-step-agents/) - State schema design is the most consequential decision in a LangGraph project. · Checkpointing gives...

31. [Persistence - Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/persistence)

32. [gepa-ai/gepa: Optimize prompts, code, and more with AI ... - GitHub](https://github.com/gepa-ai/gepa) - Optimize prompts, code, and more with AI-powered Reflective Text Evolution - gepa-ai/gepa

33. [ACON: Optimizing Context Compression for Long-horizon ...](https://www.microsoft.com/en-us/research/publication/acon-optimizing-context-compression-for-long-horizon-llm-agents/) - Large language models (LLMs) are increasingly deployed as agents in dynamic, real-world environments...

34. [Agent Context Compression 2026: The Techniques Preventing ...](https://agentmarketcap.ai/blog/2026/04/10/agent-context-compression-techniques-2026) - 65% of enterprise AI agent failures trace to context drift, not raw token exhaustion. Here's the pro...

35. [Self-Improving Agents in 5 Minutes: Reflect, Refine, Repeat](https://www.developersdigest.tech/blog/self-improving-agents-in-5-minutes) - Reflexion stores reflections in an episodic memory buffer, not model weights. The agent gets better ...

36. [Reflection Agents](https://www.langchain.com/blog/reflection-agents) - Reflexion by Shinn, et. al., is an architecture designed to learn through verbal feedback and self-r...

37. [dspy.GEPA: Otimizador de prompts reflexivo](https://dspy.ai/api/optimizers/GEPA/overview/) - The framework for programming—rather than prompting—language models.

38. [DSPy GEPA vs MIPROv2: Auto Prompt Optimization 2026](https://particula.tech/blog/dspy-gepa-vs-miprov2-automatic-prompt-optimization) - GEPA beats MIPROv2 by over 10% and outperforms GRPO with up to 35x fewer rollouts. Here's how DSPy's...

39. [AI Agent Context Compression: Strategies for Long-Running ...](https://zylos.ai/research/2026-02-28-ai-agent-context-compression-strategies/) - A deep-dive into how production AI agents manage and compress growing context windows — covering anc...

40. [Fournisseur de mémoire Neo4j pour Agent Framework](https://learn.microsoft.com/fr-fr/agent-framework/integrations/neo4j-memory) - Découvrez comment utiliser le fournisseur de mémoire Neo4j pour ajouter de la mémoire de graphe de c...

41. [Graphiti: Knowledge Graph Memory for an Agentic World](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) - Zep AI's Graphiti framework introduces a flexible, real-time memory layer built on temporally aware ...

42. [Neo4j GraphRAG Context Provider for Agent Framework](https://learn.microsoft.com/en-us/agent-framework/integrations/neo4j-graphrag) - Learn how to use the Neo4j GraphRAG Context Provider to add knowledge graph retrieval capabilities t...

43. [Context Engineering for Long-Running AI Agents | Zylos Research](https://zylos.ai/research/2026-06-20-context-engineering-long-running-agents/) - How production AI agents manage their context windows — from dynamic assembly and compression to mul...

44. [Context Engineering: Memory, Compaction, and Tool ...](https://tianpan.co/blog/2026-02-26-context-engineering-memory-compaction-tool-clearing) - How to prevent context drift in production AI agents using compaction, tool-result clearing, and ext...

45. [Agent Context Compaction for Long-Running Sessions ...](https://zylos.ai/research/2026-04-21-agent-context-compaction-long-running-sessions/) - A 2026 review of the compaction problem for persistent AI agents: summarization, eviction, retrieval...

46. [Context Engineering 2026: 8 Tools to Stop Token Bloat](https://techsy.io/en/blog/best-context-engineering-tools) - Token bloat is killing your LLM bill. We ranked 8 context engineering tools in 2026 — retrieval, mem...

47. [GitHub Trending: Context Engineering Dominates This Week](https://www.shareuhack.com/en/posts/github-trending-weekly-2026-06-10) - June 2–10 Trending: Headroom dominates with token compression. Skills ecosystem grows (design, PPT, ...

48. [Ragas vs DeepEval: Which AI Evaluation Framework Wins in 2026?](https://www.youtube.com/watch?v=Yqk8xRK7rN0) - 🏷️ Check Current Price on Amazon: https://amzn.to/3I8udfq 🔖 Bookmark & Use for ANY Amazon Purchase (...

49. [AI Agent Evaluation Frameworks (2026): 7 Compared](https://www.morphllm.com/ai-agent-evaluation-frameworks) - Seven agent evaluation frameworks compared on open source, offline vs online, trajectory eval, LLM-a...

50. [Langfuse Intro - Observability & Tracing Deep Dive](https://www.youtube.com/watch?v=pTneXS_m1rk) - In this video our Co-Founder and CEO Marc walks you through the Observability and Tracing product of...

51. [AI Agent Observability, Tracing & Evaluation with Langfuse](https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse) - Trace, monitor, evaluate, and test AI agents in production. Learn what agent observability is and ho...

52. [Tracing AI Calls with Agentgateway and Langfuse](https://www.solo.io/blog/llm-observability-agentgateway-langfuse) - A guide to LLM observability with agentgateway and Langfuse for tracing AI agent calls, monitoring t...

53. [Instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation) - Use native integrations or custom instrumentation patterns in Python and JavaScript/TypeScript to ca...

