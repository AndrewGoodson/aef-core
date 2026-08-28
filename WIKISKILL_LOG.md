# WikiSkill loop — increment log

Append-only. Expectation stated BEFORE the work, measurement after, verdict last.

---

## I0 — ADR first (2026-08-28)

**Branch:** `wikiskill/knowledge-layer`, off `main` (`f945a72`).

**Expectation.** A design decision only, no code. Four things had to be pinned
or the later increments would each re-litigate them: where the wiki lives, what
keys an entry, when consolidation runs, and how entries compete with raw records
under one budget. Expected the ADR to be writable without touching `aef/`, and
the green bar therefore to be unchanged.

**Measurement.**

```
pytest -q                                 1455 passed, 0 failed
mypy aef                                  Success: no issues found in 108 source files
ruff check .                              All checks passed
ruff format --check aef tests examples    195 files already formatted
```

Baseline test count for this program: **1455**. It grows or holds; it never
silently shrinks.

Four cited claims were verified against source rather than recalled:

- ADR 0046 title is literally "The reflection slice is rule-based" and rejects
  an LLM-backed Critic first — the rule-based-first precedent is real.
- ADR 0096:33 contains the "flaky node" argument verbatim, so the
  `failing_nodes` signature key rests on a written decision, not on my summary.
- `aef/evolution/engine.py` imports only stdlib today, so the "knowledge does
  not import evolution, evolution does not import knowledge" constraint starts
  true and is a property to preserve rather than one to establish.
- `MemoryRetriever` is deterministic by construction (no model, stable total
  sort) because replay asserts deterministic nodes reproduce — which is what
  forced the write-time-vs-retrieval-time decision.

**Verdict.** I0 done. ADR 0110 accepted, indexed in `docs/adr/README.md`.

The non-obvious decision, recorded because I2/I3 depend on it: **consolidation
runs at write time**, and not for speed. Replay re-executes deterministic nodes
and asserts output equality, so a consolidator invoked during retrieval could
never be LLM-backed without breaking replay for every node that retrieves.
Consolidating at write time makes the entry stored *data*, which is what keeps
I5 possible at all.

Also recorded: the layer has a defined kill. If I4's A/B shows consolidated
entries do not improve what fits inside `context_budget_tokens`, the layer is
deleted and 0110 is superseded with the number that killed it.

**Next:** I1 — `KnowledgeEntry` + `KnowledgeStore` base + in-memory
implementation, mirroring `aef/services/memory/`.

---

## I1 — the store (2026-08-28)

**Expectation.** `KnowledgeEntry` + `KnowledgeStore` + in-memory backend,
mirroring `aef/services/memory/`. Expected the interesting part to be the merge
semantics rather than the storage, and expected two specific bugs to be
available to plant: cross-agent entry merging, and provenance that inflates on
re-consolidation.

**Measurement.**

```
pytest -q                                 1488 passed  (was 1455, +33)
mypy aef                                  Success: 111 source files (was 108)
ruff check .                              All checks passed
ruff format --check aef tests examples    200 files already formatted
```

**Seven planted faults, seven detections.** Each aimed at the specific guard it
should trip, reverted after:

| Fault planted | Test that caught it |
|---|---|
| `key` drops `agent_id` | `test_entries_from_different_agents_never_merge` |
| merge concatenates without dedupe | `test_reupserting_the_same_record_does_not_inflate_the_count` (+1) |
| tie-break sorts descending | `test_query_tie_break_is_ascending_by_key_not_reversed` |
| `deepcopy` removed from write | `test_upsert_snapshots_nested_content` |
| duplicate-provenance validation removed | `test_duplicate_provenance_rejected_at_construction` |
| real `aef.evolution` import into the package | `test_knowledge_does_not_import_evolution` |
| same, deferred inside a function body | `test_knowledge_does_not_import_evolution` |

**Verdict.** I1 done. Four decisions worth carrying into I2:

1. **Key is `(agent_id, signature)`, not `signature`.** Same seam that was
   found in `MemoryRetriever.agent_id`, where a default of "every agent" handed
   one agent another's recorded failures. Here it is worse — a merged entry
   cannot be un-merged — so `agent_id` is a required field, not a defaulted one.
2. **`occurrence_count` is derived from `source_record_ids`, never stored.**
   Two fields recording one quantity drift (ADR 0091). This also makes the
   dedupe load-bearing rather than tidy: without it, a consolidator re-run over
   an unchanged memory store manufactures confidence out of the same evidence.
3. **Merge lives in the store, not the consolidator.** Keying by signature is
   only an invariant if one place enforces it.
4. **`confidence` is a property of the entry; the retrieval multiplier is not.**
   Keeping the measurement separate from the policy is what lets I4 remove the
   thumb on the scale without editing stored data.

ADR 0110's evolution-separation claim is now enforced by an AST scan in **both**
directions rather than asserted in prose — the coupling could arrive from either
side, and a one-way scan would pass while the property was already broken.

**Next:** I2 — the rule-based consolidator. Reads `MemoryRecord`s, groups by
signature, emits entries only at >=2 occurrences. Planted fault to verify: a
consolidator that emits from a single record must fail its test.

---

## I2 — the rule-based consolidator (2026-08-28)

**Expectation.** Group `MemoryRecord`s by signature, emit `KnowledgeEntry` only
at >=2 occurrences. Expected the threshold to be the whole story. It was not —
the interesting question turned out to be *two occurrences of what?*

**Measurement.**

```
pytest -q                                 1514 passed  (was 1488, +26)
mypy aef                                  Success: 112 source files (was 111)
ruff check .                              All checks passed
ruff format --check aef tests examples    202 files already formatted
```

**The semantic decision, forced by reading the code rather than assumed.**
`AEFState.run_id` is required and validated, and `make_reflect_node`'s
idempotency key is keyed on `checkpoint_seq` *because a graph may reflect more
than once per run*. So "two records" and "two runs" are genuinely different
counts, and only one of them means recurrence. Three reflections inside one bad
run is one episode. The consolidator therefore takes **at most one
representative record per run**, which keeps `occurrence_count` meaning exactly
one thing and closes the intra-run inflation path.

Records with no `run_id` are dropped for the same reason: they cannot evidence
recurrence *across* runs, and inventing a run for them is the guess
`_failing_nodes` already refuses to make about unattributed errors.

**Six planted faults. Five detected on the first pass — and the sixth was a
real gap in the tests, not in the code.**

| Fault planted | Outcome |
|---|---|
| threshold ignored (emit from one occurrence) | caught by 5 tests |
| count records instead of distinct runs | caught |
| **unsignable records bucketed into a catch-all** | **NOT CAUGHT — gap** |
| group key drops `agent_id` | caught by 2 |
| feedback concatenated across runs | caught |
| `last_seen` uses min instead of max | caught by 2 |

The miss is the finding. `default_signature` returning `None` was asserted at
the unit level, but **nothing asserted what the consolidator does with it** —
so bucketing every unattributable failure under a shared `"unknown"` key passed
the entire suite. That fault fabricates knowledge: two unrelated failures, each
seen once, reach the threshold together and emerge as one entry claiming both
as evidence. Two tests added (`test_unsignable_records_are_dropped_not_pooled`,
`test_signable_and_unsignable_records_do_not_contaminate_each_other`); the
fault was re-planted and both fire.

This is the reproduce-first rule earning its place: the code was already
correct, and only a planted fault could show the *test* was not.

**One process note.** A green-bar run showed 2 failures that the source could
not explain — `git diff` on the file showed nothing, because the file was still
untracked and `git diff` never reports untracked files. `diff` against the
backup proved the source clean; clearing `__pycache__` cleared the failures.
Stale bytecode from a faulted revision. The lesson is narrow and worth keeping:
**`git diff` is not a revert check for a file git has never seen.**

**Verdict.** I2 done. The store now has a producer, and CLAUDE.md says the next
honest thing: nothing calls the consolidator from a graph yet.

**Next:** I3 — `make_consolidate_node` (contract-compliant, `SideEffect.IO`,
idempotency key from run id) plus the `MemoryRetriever` change that lets entries
compete with raw records under `context_budget_tokens`.

---

## I3 — the wiring (2026-08-28)

**Expectation.** A consolidate node plus a retriever that admits entries.
Expected the node to be the work. It was not — the wiring was, and two seams
found defects that the node itself never would have.

**Measurement.**

```
pytest -q                                 1538 passed  (was 1514, +24)
mypy aef                                  Success: 112 source files
ruff check .                              All checks passed
ruff format --check aef tests examples    204 files already formatted
```

**An existing guard caught a real bug I introduced.** Adding
`Services.knowledge` broke `test_suppression_nulls_no_service_the_incumbent_had`
in the promotion-safety suite: `_suppressed_services` builds the shadow
candidate's services field-by-field, so the new slot arrived as `None` and a
shadow would have **diverged for a harness reason and reported it as a
candidate defect**. Fixed by passing it through exactly as `memory` is. This is
the ADR 0073/0075/0079/0091 drift shape catching its fifth instance — and this
time the guard fired before the defect shipped rather than after.

Recorded consequence rather than hidden: a shadow's consolidate node writes
into the LIVE knowledge store. That is not a new exposure — every entry derives
from records the shadow's reflect node already writes to live memory — but it
is the kind of thing that should be written down when it is chosen, not
discovered later.

**Seven planted faults. Six detected. The seventh was mis-aimed, and the
re-aimed version exposed a genuine test gap.**

| Fault planted | Outcome |
|---|---|
| boost ignored | caught |
| knowledge bypasses the shared budget | caught |
| retriever reads every agent's knowledge | caught |
| `min_occurrences` filter dropped | caught |
| `agent_services` returns a SHARED store | caught |
| `agent_services` stops supplying knowledge | caught by 2 |
| node consolidates for every agent | **mis-aimed, then NOT CAUGHT** |

The seventh is the finding. My first patch replaced the first occurrence of
`agent_id=state.agent_id` in `nodes.py` — which belongs to `make_reflect_node`,
not the consolidate node. It failed three tests, so it *looked* detected. It
was not: I had broken a different node. Re-aimed at the correct line, **no test
failed at all** — because passing `None` there is behaviourally identical when
only one agent exists.

The real difference is containment: with `None`, agent a1 merely RUNNING causes
entries to be written about agent a2, out of a2's records, at a moment a2 did
nothing. Knowledge would appear for an agent that never executed. Test added
(`test_a_run_consolidates_only_its_own_agent`), fault re-planted, now caught.

This is the second increment running where the planted fault found a hole in
the tests rather than the code, and the second where a mutation aimed at the
wrong target first read as a false positive. **Both are arguments for checking
what the patch actually changed, not just that the count moved.**

**Verdict.** I3 done. The layer is now end-to-end: a real `GraphExecutor` run
over reflect -> consolidate produces entries a real `MemoryRetriever` admits
under `context_budget_tokens`, with provenance attached to each chunk.

`knowledge_boost` defaults to 1.0 and **that number is unjustified** — there is
no principled basis for it, which CLAUDE.md now says outright.

**Next:** I4 — the A/B. Same corpus retrieved twice, raw-records-only vs
wiki-enabled, reading the retrievals rather than only the scores. This is the
increment that can delete the layer.
