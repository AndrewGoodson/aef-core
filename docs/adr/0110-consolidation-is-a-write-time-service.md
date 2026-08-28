# ADR 0110: Consolidation is a write-time service, and it does not touch evolution

## Status
Accepted. Increment I0 of the WikiSkill program (`WIKISKILL_LOOP.md`).
**Decides a design. Ships no code.**

## Context

WikiSkill (arXiv:2608.27454, Tang et al.) separates three layers: raw
execution experience, a persistent consolidated knowledge base, and executable
skills. Its ablation is the part that matters here — **the persistent wiki
carried the result, not the skill updater.** That is what makes it coherent to
build the middle layer alone, which is the only layer this repo can honestly
build today.

Mapping the three layers onto what already exists:

| WikiSkill layer | aef-core today | Verdict |
|---|---|---|
| Raw experience | `make_reflect_node` writes `MemoryRecord(kind="failure"\|"success")` per run (ADR 0046) | **exists — do not rebuild** |
| Consolidated knowledge | nothing | **the gap** |
| Executable skills | `aef/evolution/` | **hard-disabled, constraint #7 — out of scope** |

`MemoryRetriever` (ADR 0101) ranks raw records by lexical overlap and admits
them under `context_budget_tokens`. It is the consumer a wiki would serve.

## Decision

### 1. The wiki is a service under `aef/services/knowledge/`

Same base / in-memory / `adapters/` split as `aef/services/memory/`, for the
same reason: a vendor-backed implementation must be expressible without moving
the interface, and constraint #3 puts vendor imports only under `providers/`
or `services/*/adapters/`.

A `KnowledgeEntry` is keyed by a **signature** — a deterministic value derived
from record content by a named pure function, not by a hash of the whole
record (two runs of the same failure differ in `run_id`, timestamps, and
excerpt text, so a whole-record hash consolidates nothing). The default
signature:

- failures: `(kind, tuple(failing_nodes))`
- successes: `(kind, objective)`

`failing_nodes` is the right key because ADR 0096 already established it as
the field a structural proposer cannot begin without — *"add a fallback to the
flaky node" requires knowing which node was flaky.* It is also the field
`make_reflect_node` was amended to record precisely because a reader could not
otherwise tell which node failed.

The signature function is **injectable**, and this is not a per-agent branch
smuggled in: per the prime directive, Knowledge is one of the five things
allowed to differ per agent. What must stay shared is the consolidation
*mechanism*, and it does.

### 2. Consolidation is rule-based first, and it happens at WRITE time

Rule-based first is the pattern reflection itself shipped under (ADR 0046) and
the reason it was testable against hand-built adversarial state rather than
only against a live model.

**Write time, not retrieval time, and this is load-bearing rather than a
performance preference.** `ReplayEngine` re-executes nodes declared
`deterministic=True` and asserts their output matches. A retriever a node
calls during a replayed run must therefore produce the same answer twice —
which is exactly why `MemoryRetriever` is deterministic, unranked by any
model, and sorts to a stable total order. If consolidation ran during
retrieval, an LLM consolidator could never be admitted behind that interface
at all. Because an entry is *stored data* by the time anything retrieves it,
a non-deterministic consolidator stays compatible with replay.

**Occurrence threshold: an entry requires ≥2 distinct records.** A signal seen
once is an episode; knowledge is what recurred. This is the planted-fault
check for I2 — a consolidator that emits an entry from a single record must
fail its test, per reproduce-first's rule that a detector is verified against
a planted fault before "nothing found" is trusted.

No clock reads. Time arrives as `ctx.now`, as it already does in
`make_reflect_node`.

### 3. Consolidation is its own node, not a hook on the reflect node

The loop prompt left this open. Decided: a separate `make_consolidate_node`.

- Scope differs. Reflection is **within-run**; consolidation reads **across
  runs**. Folding the second into the first gives one node two write paths
  under one idempotency key.
- A graph that does not want a wiki omits the node. A hook is not omittable.
- It stays independently testable against a store hand-loaded with records
  from runs that never happened.

Contract: `deterministic=False`, `side_effects=SideEffect.IO`,
`idempotency_key_fn=lambda s: f"{s.run_id}:{node_id}:{s.checkpoint_seq}"` —
the same at-least-once resume semantics ADR 0010 defines.

### 4. Entries and records compete under one budget, scored by the same function

Not "entries first". A stale consolidated entry outranking a fresh, precisely
relevant record is the obvious failure mode, and a priority rule would hard-code
it.

Entries are scored by the **same** lexical function as records, then multiplied
by a `confidence` derived from occurrence count. **This is a thumb on the
scale and is written down as one.** The multiplier is configurable, and I4's
A/B is what decides whether it earns its place; the honest kill is to set it to
1.0, and the honest kill of the whole layer is to delete it.

Ties break toward the entry, then by id — the total order must stay stable or
`ReplayEngine` reports a determinism violation that is really a sort-order
artefact.

## What this explicitly does NOT do

**It does not unblock evolution, and no commit in this program may claim it
does.** `aef/evolution/` stays hard-disabled. `docs/trust/promotion-trust-case.md`
recommends against Tier-1 auto-merge on three findings: criteria 1 and 6 have
never run against the live traffic and real tenants their text names; a shadow
node doing direct file I/O is not contained by the tool policy; and every
adversarial round in the program found a defect, six for six. **A knowledge
layer moves none of those three.** Claiming otherwise would be the exact error
`memory_retriever.py`'s own docstring names — *a true statement about one
property offered as an answer about a different one.*

Enforced structurally: nothing under `aef/services/knowledge/` imports from
`aef/evolution/`, and nothing in `aef/evolution/` imports the knowledge
service.

**It does not auto-update skills, graphs, or prompts.** WikiSkill's third layer
is not built here. The shippable value is better retrieval under a budget, full
stop.

**It does not add a stub for the LLM consolidator.** Per ADR 0101 — *a stub
unimplemented across five phases is a promise, and an unkept promise in a typed
signature is worse than an honest absence.* The LLM-backed consolidator is I5,
gated on I4 surviving; if this loop does not reach it, it is recorded here as
future work by name and nothing else.

## I4 ran. The layer survived; the knob did not.

**Amends decision 4 above with the number.** `knowledge_boost` now defaults to
**0.0**, not 1.0.

Metric fixed before measuring: *distinct-lesson coverage* under a budget.
Corpus built from real `GraphExecutor` runs, six lessons, coverage out of six
(raw → wiki):

```
budget   R=1      R=2      R=3      R=5      R=10
   200   1 -> 1   1 -> 3   1 -> 3   1 -> 3   1 ->  2
   400   3 -> 3   2 -> 6   1 -> 6   1 -> 6   1 ->  5
   800   6 -> 6   5 -> 6   4 -> 6   3 -> 6   1 ->  6
  2000   6 -> 6   6 -> 6   6 -> 6   6 -> 6   5 ->  6
```

The wiki never covers less. The more interesting column is the raw one: at
budget 800 it falls **6 → 5 → 4 → 3 → 1** as recurrence rises, because
near-duplicate records about one failure crowd out every other lesson. **More
experience makes the un-consolidated agent retrieve worse.** That is the defect
consolidation removes, and it is why the layer earns its surface area.

**The boost bought nothing.** Swept at 0.0 / 0.5 / 1.0 / 3.0 across four budgets
and five recurrence levels, every coverage number was identical. The entire
benefit is consolidation collapsing duplicates; none of it is ranking entries
above records. And a raised boost measurably walks a stale, loosely-related
entry toward displacing a precisely-relevant one — 0.200 → 0.745 against a
0.833 record — which is exactly the failure mode decision 4 refused to
hard-code. Buying nothing while costing something is not a tuning parameter.

The knob stays expressible, because an owner with a different corpus may
measure differently. The default is now the number the A/B produced, and a test
pins it so raising it means re-running the measurement rather than editing a
line.

## I5 ran. The LLM summariser is implemented, and OFF by default.

Built as `LLMSummariser` under `aef/services/knowledge/adapters/`, injected
through one `summarise` hook so it swaps **prose and nothing else** — the
grouping, the two-run threshold, the per-run dedupe and the agent keying stay on
the single code path I4 measured.

**This is the increment the write-time decision was reserving room for.** A
non-deterministic summariser is only safe here because consolidation happens at
write time, so its output is stored data by the time any retriever reads it and
never sits inside a replayed read path.

**Measured on the same ruler, and it loses** (coverage out of 6,
rule-based → LLM-backed):

```
budget   R=2      R=5
   200   3 -> 2   3 -> 2
   400   6 -> 5   6 -> 4
   800   6 -> 6   6 -> 6
  2000   6 -> 6   6 -> 6
```

The cause is not subtle: the summary is **added** to the verbatim feedback
rather than replacing it, so entries grow about 40% (227 → 317 chars at R=2),
and larger entries mean fewer fit under a fixed budget.

Keeping both texts is deliberate. A model's paraphrase replacing the only record
of what was actually observed makes the lesson untraceable to its evidence, even
with provenance ids intact. **So this is a real trade, not a bug: traceability
costs coverage.** Substituting instead of adding might reverse the sign; that is
a different experiment, named as future work rather than tried here, because
tuning a design after seeing the result until it wins is how a measurement stops
meaning anything.

Disposition, matching how this repo treats evolution: **implemented, tested,
default off, with the number that argues against enabling it recorded.** It is
not a stub, so ADR 0101's rule is satisfied. An owner who wants cross-run prose
synthesis can enable it knowing it costs one to two lessons of coverage at tight
budgets and nothing at loose ones.

The model is never trusted with provenance. A summariser may return one string,
which lands in `content["summary"]`; `source_record_ids`, `occurrence_count`,
`run_ids` and the timestamps are computed from records. A hostile-model test
pins this — one that could write provenance could manufacture confidence for a
lesson nothing supports. Provider failure returns `None` and leaves the
rule-based text, so the worst case is the previous behaviour rather than a lost
or corrupted entry.

## The measurement that could have killed this

I4 is an A/B through the existing eval harness: one corpus retrieved twice,
raw-records-only versus wiki-enabled, reading the retrievals and not only the
scores. **If consolidated entries do not measurably improve what fits inside
`context_budget_tokens`, the layer is deleted and this ADR is superseded with
the number that killed it.** A consolidation layer that loses to the top-N raw
records is not worth its surface area, and that outcome is a result rather than
a failure.

## Consequences

Five increments follow: store (I1), rule-based consolidator (I2), node +
retriever wiring (I3), A/B eval (I4), LLM adapter only if I4 survives (I5).

Every increment that adds a capability updates CLAUDE.md's "what's real vs
stubbed" paragraph in the same commit — that paragraph is audited against the
code, and a knowledge service absent from it is the same defect class this ADR
exists to avoid.
