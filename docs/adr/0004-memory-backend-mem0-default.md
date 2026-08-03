# ADR 0004: Mem0 is the Phase 1 memory backend default; Graphiti/temporal-KG memory is deferred to Phase 2

## Status
Accepted

## Context
The report and blueprint agree memory should be pluggable behind one
interface (both explicitly warn against hardcoding a memory vendor) but
differ on emphasis: the report frames Mem0 as "cheapest tokens" and
Graphiti/Zep as the right default "for temporal reasoning or compliance,"
while recommending AEF "default Mem0 for cost." The build task's own scope
for Phase 1 names "memory interface (in-memory + Mem0 adapter)"
explicitly, settling the question for this phase.

## Decision
`MemoryStore` (report §7 / blueprint Part 5 taxonomy: working, episodic,
semantic, procedural, failure, success, tool) ships with two real
backends: `InMemoryMemoryStore` (the default, zero dependencies) and
`Mem0Adapter` (wraps `mem0ai`, the one module besides `providers/` allowed
to import it directly). A temporal knowledge-graph-backed memory store
(Graphiti/Zep, or the `GraphStore` from ADR 0003) is explicitly deferred
to Phase 2, at which point semantic/episodic memory with real temporal
validity windows becomes possible — `MemoryRecord` already carries
`valid_from`/`valid_until` fields in anticipation of this, but
`InMemoryMemoryStore` and `Mem0Adapter` do not enforce or query on them
today.

Mem0's own retrieval model is semantic (a free-text query ranked by
similarity), while `MemoryStore.query()` is taxonomy/filter-based (kind +
run_id + agent_id + tags, no free-text query parameter). `Mem0Adapter`
bridges this by round-tripping AEF's own `kind`/`tags`/`id` through Mem0's
`metadata` dict and falling back to a tag-derived query string when no
semantic query is available. This is documented in the adapter's own
docstring as best-effort for tag-only recall — real semantic recall (the
actual reason to reach for Mem0) still works when callers pass meaningful
tags, but this adapter's quality on pure-taxonomy lookups is unverified
against a live Mem0 backend (constructor takes an injected client
specifically so the *translation logic* is tested without needing one).

## Consequences
- Every memory-consuming node written against `MemoryStore` today works
  identically whether the underlying backend is `InMemoryMemoryStore` or
  `Mem0Adapter` — no per-backend code paths in `kernel/`/`reasoning/`.
- Temporal fact invalidation (the report's stated reason to eventually
  prefer a graph-backed store for semantic memory) is not enforced by
  either Phase 1 backend; a semantic-memory consumer that needs "this fact
  was true then, false now" semantics must wait for Phase 2.
- `Mem0Adapter`'s real-world retrieval quality is unverified — it has
  never been run against Mem0's live vector/embedding pipeline in this
  repo, only against an injected fake client that proves the
  request/response *shape* is handled correctly.

## Alternatives Considered
- **Default to Graphiti/Zep now.** Rejected: not named in Phase 1 scope,
  and adds a heavier dependency (a temporal KG backend) before any
  consumer needs temporal reasoning.
- **Skip Mem0 entirely and ship only `InMemoryMemoryStore`.** Rejected:
  the build task explicitly scopes a Mem0 adapter into Phase 1's "working,
  tested code," and `mem0ai` is confirmed actively maintained (verified
  live on PyPI, latest release within days of this build).

## Confidence
High on the interface/backend split; Medium on the Mem0 adapter's
retrieval-quality claims specifically, since those are untested against a
real Mem0 deployment.
