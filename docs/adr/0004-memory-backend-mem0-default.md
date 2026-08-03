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
docstring as best-effort for tag-only recall.

### Update: verified against a real, fully-local mem0 backend

The paragraph above originally ended with "unverified against a live Mem0
backend." It has since been verified — `mem0.Memory()` can be constructed
with zero paid/network-dependent services (`fastembed` local embedder +
`faiss` local vector store; see the new `mem0-integration` extra and
`tests/services/memory/test_mem0_adapter_integration.py`) — and doing so
surfaced two real bugs the fake-client unit tests could not, because the
fake didn't (and couldn't be expected to, without testing against the real
thing) mirror mem0's actual contract:

1. **mem0 requires an identity on every call.** `Memory.add()` and
   `Memory.search()` both raise if none of `user_id`/`agent_id`/`run_id`
   is present — mem0 has no unscoped-memory mode. `Mem0Adapter.write()`
   and `.query()` now raise a clear `Mem0IdentityRequiredError` up front
   instead of letting a `MemoryRecord`/query with neither `agent_id` nor
   `run_id` crash deep inside mem0 with a less legible error.
2. **`get()` cannot be an empty-query semantic search.** The original
   implementation called `search("", ...)` to emulate a by-id lookup —
   real mem0 rejects empty/whitespace-only queries outright. Fixed:
   `write()` now captures the native memory id mem0's own `add()` returns
   and stores it in an internal `record.id -> native_id` index; `get()`
   calls `mem0.Memory.get(native_id)` directly, a real by-id lookup with
   no query text and no relevance-ranking risk at all.
3. **A separate, non-bug gotcha worth knowing:** `mem0.Memory()` eagerly
   constructs an LLM client (default provider `openai`) at construction
   time, even though `write()` always passes `infer=False` and so never
   actually invokes it. Deploying `Mem0Adapter` therefore always requires
   *some* LLM credential (or a local server like Ollama) to be present at
   startup, even for a pure key-value-style memory use case that never
   needs LLM-driven fact extraction.

With those two bugs fixed, `test_real_semantic_recall_with_meaningful_tags`
confirms real semantic recall works correctly end-to-end: three semantically
distinct facts written, a tag-guided query for "azure, storage" correctly
retrieves only the one matching record via real vector similarity, not a
fake's exact-match logic. Retrieval quality for the *tag-only, no-tags-at-all*
degenerate query path (falling back to the bare `kind` string as the query
text) remains genuinely best-effort, not a guarantee — that part of the
original claim stands.

## Consequences
- Every memory-consuming node written against `MemoryStore` today works
  identically whether the underlying backend is `InMemoryMemoryStore` or
  `Mem0Adapter` — no per-backend code paths in `kernel/`/`reasoning/`.
- Temporal fact invalidation (the report's stated reason to eventually
  prefer a graph-backed store for semantic memory) is not enforced by
  either Phase 1 backend; a semantic-memory consumer that needs "this fact
  was true then, false now" semantics must wait for Phase 2.
- Every `MemoryRecord` written through `Mem0Adapter` must carry an
  `agent_id` or `run_id` — this is a hard mem0 constraint now enforced at
  the AEF layer, not an AEF design choice; `InMemoryMemoryStore` has no
  such restriction, so a node written against the interface in a
  backend-agnostic way should always set one of these two fields if it
  might ever run against Mem0.

## Alternatives Considered
- **Default to Graphiti/Zep now.** Rejected: not named in Phase 1 scope,
  and adds a heavier dependency (a temporal KG backend) before any
  consumer needs temporal reasoning.
- **Skip Mem0 entirely and ship only `InMemoryMemoryStore`.** Rejected:
  the build task explicitly scopes a Mem0 adapter into Phase 1's "working,
  tested code," and `mem0ai` is confirmed actively maintained (verified
  live on PyPI, latest release within days of this build).

## Confidence
High on the interface/backend split. High (upgraded from Medium) on the
Mem0 adapter's core write/query/get correctness, now that it's verified
against a real, fully-local mem0 backend and two real bugs found that way
were fixed. Medium remains on retrieval *ranking quality* for the
degenerate tag-less query path specifically, and on how mem0's behavior
holds up at a scale/complexity this test doesn't exercise (thousands of
records, concurrent writers, a non-faiss vector store).
