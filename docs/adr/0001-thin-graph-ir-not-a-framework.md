# ADR 0001: Build a thin custom graph IR instead of adopting LangGraph/Temporal/ADK wholesale

## Status
Accepted

## Context
The research brief's own Final Recommended Architecture (blueprint, "Final
Recommended Architecture for AEF v2.0") prescribes a specific stack: "a
Temporal-durable, Postgres/AGE-checkpointed, typed StateGraph kernel." The
research report — which the build task designates authoritative — reaches
a different conclusion in its Recommendations: "Do not adopt a heavyweight
framework wholesale; build a thin graph IR + adapter layer so you can swap
LangGraph/Temporal/ADK underneath," adding an explicit change trigger:
add a durable backend "if a single run must survive worker restarts or
exceed ~1 hour of wall-clock — otherwise a Postgres checkpointer
suffices." This is a direct conflict between the two source documents on
what AEF's control-plane substrate should be on day one.

## Decision
Follow the report. `aef/kernel/` is a from-scratch, dependency-light graph
engine (`Node`, `Edge`, `Graph`, `GraphExecutor`, `ReplayEngine`) — roughly
in PocketFlow's spirit of a minimal node/edge/state kernel, borrowing
LangGraph's typed-shared-state-with-super-step model and Temporal's
idempotent-activity discipline as *patterns*, not as dependencies. No
LangGraph, Temporal, or Google ADK package is imported anywhere in this
repo. `DurabilityBackend` is an interface with real `InMemory`/`File`
implementations today and typed `NotImplementedError` stubs for
`Postgres`/`Temporal` (see ADR 0002) — swapping in a real durable backend
later is an adapter addition, not a rewrite.

## Consequences
- No cross-process crash recovery today: if the process running
  `GraphExecutor.run` dies mid-graph, the run is not automatically resumed
  by another worker. This is acceptable for Phase 0/1's actual workloads
  (short, single-process runs) and is the report's own stated threshold
  for when this stops being acceptable.
- The kernel owns its own (small) durability/replay contract, so it isn't
  hostage to any one upstream framework's checkpoint-schema churn (the
  report cites ADK 2.0's breaking session-schema change as a cautionary
  example).
- We take on the engineering cost of building and testing our own graph
  engine rather than inheriting a mature one's edge cases and community
  hardening.

## Alternatives Considered
- **Wrap LangGraph directly.** Rejected for Phase 0/1: LangGraph's
  `MemorySaver`/`SqliteSaver` checkpointers are not production-durable by
  default, and coupling AEF's node contract to LangGraph's `StateGraph`
  API would work against constraint #3 (vendor/framework imports isolated
  behind interfaces) and against AEF's own "swap the backend without
  touching the graph" goal.
- **Wrap Temporal directly, per the blueprint's literal recommendation.**
  Rejected for Phase 0/1: Temporal has no native concept of LLM/agent
  state, and standing up a Temporal cluster (or Temporal Cloud) is
  disproportionate infrastructure for a scaffold whose Phase 0/1 mandate
  is "single provider," "working, tested code" runnable without external
  services. Revisit per the report's own change trigger (long-running or
  crash-critical runs).

## Confidence
High — this directly follows the report's explicit Recommendation #1 and
its stated change trigger, over the blueprint's more prescriptive (but
context, not authoritative) stack choice.
