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

---

## I4 — the A/B (2026-08-28)

**Expectation.** Same corpus retrieved twice, raw-records-only vs wiki-enabled.
This increment was allowed to delete the layer. Metric fixed BEFORE measuring:
*distinct-lesson coverage* under a budget, because consolidation's mechanism is
collapsing R near-duplicate records into one entry, and if the freed budget does
not buy coverage of other lessons then the layer is surface area for nothing.

Falsification stated in advance: equal-or-worse coverage at every R>=2 kills it;
an advantage only at implausibly high R is reported as weak; R=1 must show no
change.

**Deviation from the loop prompt, stated rather than quietly taken.** The prompt
said "through the existing eval harness". I measured retrieval directly instead:
the harness scores agent answers against rubrics, and the claim under test is
retrieval coverage under a budget, so routing through it would have added
indirection without validity. The corpus is still built from **real
`GraphExecutor` runs** through reflect -> consolidate, so the measurement stays
end-to-end rather than synthetic.

**Measurement.**

```
pytest -q                                 1545 passed  (was 1538, +7)
mypy aef                                  Success: 112 source files
ruff check .                              All checks passed
ruff format --check aef tests examples    205 files already formatted
```

Coverage out of 6 lessons (raw -> wiki):

```
budget   R=1      R=2      R=3      R=5      R=10
   200   1 -> 1   1 -> 3   1 -> 3   1 -> 3   1 ->  2
   400   3 -> 3   2 -> 6   1 -> 6   1 -> 6   1 ->  5
   800   6 -> 6   5 -> 6   4 -> 6   3 -> 6   1 ->  6
  2000   6 -> 6   6 -> 6   6 -> 6   6 -> 6   5 ->  6
```

**The layer survives, and the interesting column is the raw one.** At budget
800, raw-records-only falls **6 -> 5 -> 4 -> 3 -> 1** as recurrence rises.
Near-duplicate records about one failure crowd out every other lesson, so **more
experience makes the un-consolidated agent retrieve worse**. The wiki holds at 6
throughout. That degradation is the defect consolidation removes, and it is a
better justification for the layer than "entries rank higher".

**The knob did not survive.** Swept at 0.0 / 0.5 / 1.0 / 3.0 across four budgets
and five recurrence levels: **every coverage number identical**. The entire
benefit comes from consolidation collapsing duplicates and none from ranking
entries above records. Separately, a raised boost measurably walks a stale,
loosely-related entry toward displacing a precisely-relevant one — 0.200 ->
0.745 against a 0.833 record — which is the failure mode ADR 0110's decision 4
refused to hard-code. Buys nothing, costs something. **Default is now 0.0**,
which the ADR named in advance as the honest kill for the knob, and a test pins
it so raising it requires re-running the A/B rather than editing a line.

**Three planted faults against the A/B itself. Two detected, one not — again a
gap in the test, not the code.**

| Fault planted | Outcome |
|---|---|
| retriever ignores the knowledge store | caught by 4 |
| boost default silently raised to 1.0 | caught |
| **consolidator threshold lowered to 1** | **NOT CAUGHT** |

The control claimed "R=1 produces no entries, so both arms must be identical".
With the threshold at 1, entries WERE produced at R=1 — and the control still
passed, because the retriever's own independent `knowledge_min_occurrences=2`
filtered them straight back out. The equality held for a reason that had nothing
to do with the docstring's claim: **the control was confirming itself rather
than the layer.** Now the precondition is asserted directly (zero entries at
R=1), the fault re-planted, and it fires.

Third increment running where a planted fault found a hole in the tests rather
than the code.

**Verdict.** I4 done. Layer kept on measured evidence; knob removed on measured
evidence. ADR 0110 amended with the table rather than superseded.

**Next:** I5 — the LLM-backed consolidator as a provider adapter, gated on I4
having survived, which it did. If not reached, ADR 0110 records it as future
work by name and it gets NO stub interface.

---

## I5 — the LLM summariser (2026-08-28)

**Expectation, stated before measuring.** The summary is ADDED to the verbatim
feedback rather than replacing it, so entries get bigger, so under a fixed
budget fewer fit — coverage should be **equal or worse**. Predicted a negative
result and got one.

**Measurement.**

```
pytest -q                                 1558 passed  (was 1545, +13)
mypy aef                                  Success: 114 source files
ruff check .                              All checks passed
ruff format --check aef tests examples    208 files already formatted
```

Coverage out of 6 (rule-based -> LLM-backed):

```
budget   R=2      R=5
   200   3 -> 2   3 -> 2
   400   6 -> 5   6 -> 4
   800   6 -> 6   6 -> 6
  2000   6 -> 6   6 -> 6
```

Mean entry size 227 -> 317 chars at R=2. The cost is entirely explained by size,
which the test asserts rather than assumes.

**Disposition: implemented, tested, default OFF, with the number recorded.**
Not a stub, so ADR 0101's rule is satisfied. Same shape as how this repo treats
evolution — built, disabled, evidence gap named.

**What I deliberately did NOT do.** Substituting the summary for the verbatim
feedback would shrink entries and might reverse the sign. I did not try it.
Changing the design after seeing the result until it wins is how a measurement
stops meaning anything; it is named as future work instead. The trade being
made is explicit: **traceability costs coverage**, because a paraphrase
replacing the only record of what was observed makes a lesson untraceable to its
evidence even with provenance ids intact.

**This increment is what I0's write-time decision was reserving room for.** A
non-deterministic summariser is safe here only because consolidation happens at
write time, so its output is stored data before any retriever reads it and never
sits in a replayed read path. Five increments later, that decision paid.

**Five planted faults, five detected**, each by its specific guard:

| Fault planted | Test that caught it |
|---|---|
| summariser output merged as JSON into content | `test_a_hostile_model_cannot_fabricate_evidence` |
| truncation removed | `test_an_oversized_summary_is_truncated` |
| provider errors propagate | `test_a_provider_outage_still_writes_the_rule_based_entry` |
| prompt record-bound removed | `test_the_prompt_is_bounded_by_record_count` |
| summary overwrites verbatim feedback | `test_the_verbatim_feedback_survives_alongside_the_summary` |

First increment in this program where no planted fault exposed a test gap —
after three consecutive ones that did.

**One fixture defect found and fixed**, not a code defect: the first draft wrote
every record with an identical `created_at`, so "most recent occurrence" fell to
the stable id tie-break rather than run order, and four tests asserted an
arbitrary-but-stable choice. Distinct timestamps per run.

**Verdict.** I5 done. The program's five increments are complete.

**Remaining, and none of it is agent work:** whether to merge
`wikiskill/knowledge-layer` to `main` is an owner decision. The layer is not
wired into any shipped example graph — an adopter gets it by adding
`make_consolidate_node` to their own graph and passing `knowledge=` to their
retriever, which is documented in CLAUDE.md and nowhere else yet.
