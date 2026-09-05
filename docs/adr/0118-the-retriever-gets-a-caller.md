# ADR 0118: The retriever gets a caller, and the lessons get an outcome

## Status
Accepted. Increment I9 of `IMPROVE_LOOP.md` (added mid-run: it was the
producer ADR 0116 said was missing); record in `IMPROVE_LOG.md`.

## Context

`MemoryRetriever` was described in ADR 0101 as "the first thing here that
enforces `context_budget_tokens`". It enforced it for any caller that asked.
No node asked. `Services.retriever` was a declared injection point with no
production caller — the ADR 0092 shape, the one this program has found
five times — and `context_budget_tokens` governed nothing in a real run.

ADR 0116 built curation on *resolution* because ACE's own signal —
was a lesson in context, and did the run then go well — had no producer.
Same root cause: nothing put lessons in context.

## Decision

1. **`make_retrieve_node`** asks `Services.retriever` with the state's
   objective (overridable) and the state's own `context_budget_tokens`, and
   writes the chunks to `state.retrieved_context` as plain dicts. One
   budget number governs what the owner configured and what a node
   receives. Non-deterministic by declaration: the store it reads learns
   between runs, and replay must trust the recorded chunks. Unconfigured
   retriever → `ServiceNotConfiguredError("retriever")` by name, the same
   refusal shape as critic/judge.
2. **The reflect node records `retrieved_signatures`** — the consolidated
   lessons that were in context for the run, computed from the chunks the
   retrieve node wrote. A lesson that existed but was not shown counts
   nothing; the signal is about what the agent had, not what the store held.
3. **The consolidator tallies `helpful` / `harmful` per entry** from the
   records: a run that had the lesson in context and did *not* reproduce
   that failure is helpful; one that reproduced it anyway is harmful.
   Agent-scoped. Recomputed every consolidation, never incremented.
4. **`agent_services` defaults a retriever** over the same throwaway memory
   and knowledge stores the container carries, agent-scoped where the gate
   paths know the scenario. This supersedes ADR 0101's "no default retriever
   whose ranking the agent never chose", on ADR 0091's grounds: the parity
   test showed a graph with a retrieve node running under `aef run --config`
   and raising `ServiceNotConfiguredError` in the gate — the fifth service
   to drift between the two lists. What a `context:` block still uniquely
   provides is the owner's budget ceiling. `agent_id=None` on the default is
   not the widening the adversarial round found: it fronts a throwaway
   store, and `aef run` builds a scoped retriever from config and passes it.
5. **A1 is closed on the way.** `build_retriever` takes `knowledge=`, and
   `aef run` shares one knowledge store between the retriever and the
   consolidate node — the lessons the graph writes are the lessons it reads.
   Until now the consolidated layer was unreachable from `aef.yaml`.
6. **Surfaced, not yet ranked on.** The tally travels in chunk metadata
   and in skill drafts (ADR 0117). It is *not* a retrieval multiplier: on
   the rigs that exist, "harmful" and "live" coincide — a lesson whose
   failure keeps recurring is exactly the one the agent should keep seeing
   — so ranking on it would need a rig where the two come apart, and none
   does yet. That is the same discipline as `knowledge_boost` (ADR 0110):
   a knob that has not been measured stays off.

## Evidence

Through the real executor (retrieve → work → reflect → consolidate): context
lands on state within the budget; a budget of 1 retrieves nothing (the
planted fault showing the state's number governs); an unconfigured
retriever refuses by name; `retrieved_signatures` is empty before any lesson
exists and names the lesson after; on two failures then three runs with the
lesson in context (two fail, one succeeds) the entry reads helpful 1,
harmful 2, and the same numbers reach chunk metadata and the skill draft;
another agent's run with the signature in context does not count. Four
mutations (retrieve ignores the budget; reflect drops the signatures; the
tally swapped; the tally not agent-scoped) each failed tests.

## Consequences

- Rubric dimension 2: 15 → 17. The knowledge layer now closes the loop
  ACE describes — generate, reflect, curate — and the last step's ranking
  input exists and is measured to be indistinguishable from staleness on
  the current rigs.
- `context_budget_tokens` is enforced in a real run for the first time.
- `examples/hello_agent` does not yet include a retrieve node; adding one
  is an example change, not a contract change.

## Confidence

High on the node and the tally; the tally's value as a ranking input is
explicitly unmeasured.

## Erratum (2026-09-03, ADR 0126)

Decision 3's tally as shipped was wrong in two ways, both reproduced through
the real executor by an adversarial round and both fixed in ADR 0126:

- It tallied **success** entries. Every run that repeats a success
  necessarily re-produces that success's signature, so a success lesson that
  was in context and then worked was scored `harmful` — the metric read
  backwards on exactly the entries it was most confident about. Four clean
  runs left `success:<objective>` at `helpful 0, harmful 2`. Only `failure`
  entries are tallied now; a success entry keeps `(0, 0)`.
- "Reproduced" was string equality on the signature. A run shown
  `failure:fetch` whose fetch failure cascaded into `parse` signs itself
  `failure:fetch>parse` — a different string — so the lesson was credited
  `helpful 1, harmful 0` for the very failure that had just recurred.
  Reproduction is now "the entry's failing-node list appears, in order,
  inside a failure signature the run produced" (`helpful 0, harmful 1` on
  the same case). Order is kept, because `default_signature` already states
  that `A>B` and `B>A` are different failures.

Neither correction changes what the tally is *used* for: it is still
surfaced, still not a retrieval multiplier (decision 6 stands).
## Erratum (2026-09-03, ADR 0125)

Two claims above were false on the assembled `aef run` path, and both were
found by running `run_graph_module` rather than by reading it.

- **"A1 is closed on the way" (decision 5) was closed only inside one
  process.** `aef run` built a fresh `InMemoryKnowledgeStore()` per
  invocation, and the retrieve node runs *before* the consolidate node — so
  across CLI runs no consolidated lesson was ever in context,
  `retrieved_signatures` was `[]` in every run, and the helpful/harmful
  tally of decision 3 had no producer here at all. The retriever and the
  consolidate node did share a store; the store was empty every time.
  `aef run` now rebuilds the knowledge store from the durable memory before
  the graph runs (`RuleBasedConsolidator` is a stateless recompute, ADR
  0110), so the third run of a recurring failure retrieves it.
- **"`agent_id=None` on the default is not the widening the adversarial
  round found ... this default only ever fronts a throwaway store"
  (decision 4) was wrong.** Without a `context:` block `build_retriever`
  returns `None`, so `agent_services` defaulted a retriever over the
  *durable, multi-agent* store `--memory` names, unscoped — and it returned
  another tenant's record. `aef run` now passes `agent_id`. The default
  itself stays `None`, which is the honest reading of an unspecified
  caller; what changed is that no real caller leaves it unspecified over a
  shared store.

Both are regression-tested in `tests/cli/test_run.py`. See ADR 0125 for the
reproductions and the numbers.

## Erratum (2026-09-04, ADR 0155): a caller that writes state nobody reads

**"The retriever finally has a caller" was true and insufficient.**
`make_retrieve_node` writes chunks to `state.retrieved_context`, and until
ADR 0155 the only code in the package that read them back was
`retrieved_signatures()` in this same module — which computes the
helpful/harmful tally and puts nothing in front of a model. No node built a
prompt from a retrieved lesson.

So retrieval could not change a run's behaviour, and this was measured
rather than argued: over the six summary validation scenarios, the arms
"no retrieve node", "retrieve, raw records" and "retrieve, records +
knowledge" produced **one identical SHA-256 over every rendered prompt**,
while the chunk counts climbed 0→5 as experience accumulated
(`docs/research/i12/prompt-identity-before-wiring.json`).

The gap is closed by `render_retrieved_context` and by `draft_node` reading
it (ADR 0155). Nothing in this ADR's own decisions is retracted — the node,
the budget enforcement, the `retrieved_signatures` outcome signal and the
`agent_id` correction all stand. What is retracted is the implication that
wiring the caller made retrieval *load-bearing*: a write with no reader is
an injection point nobody calls, which is the exact defect this ADR quotes
`MemoryRetriever`'s docstring as existing to prevent.
