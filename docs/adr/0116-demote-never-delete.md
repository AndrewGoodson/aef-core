# ADR 0116: Demote, never delete

## Status
Accepted. Increment I4 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.
`staleness_half_life` defaults to 5, **by measurement**.

## Context

ADR 0110's layer fixed one kind of context collapse: near-duplicate records
about one recurring failure crowding out every other lesson. ACE (ICLR
2026) names the other kind — a playbook that keeps every strategy it ever
learned, so stale ones crowd out live ones — and its answer is curation:
grow the playbook, refine it, demote what stopped helping, delete nothing.

This repo had no curation signal at all. An entry for a failure the agent
fixed fifty runs ago ranked exactly as an entry for one that failed this
morning, because both matched the query equally and lexical overlap was the
only ranking. Under a tight `context_budget_tokens`, which lessons got in
was a tie broken by id.

The signal ACE uses — was this lesson *retrieved* and did the run then go
well — has no producer here: no node writes `retrieved_context`. What the
records do carry is *resolution*: a failure signature that has stopped
recurring while the agent keeps running.

## Decision

1. **`KnowledgeEntry.runs_since_last_seen`** — distinct runs of this agent
   whose latest record is newer than the entry's last occurrence. A field,
   not a `content` key, because the retriever spends budget rendering
   `content` and I4 measured that a longer entry loses coverage at tight
   budgets (this increment reproduced it: 6 → 5 at budget 400 before the
   field moved out of `content`).
2. **Recomputed by every consolidation from the records, never
   incremented.** The consolidator is a stateless recompute (ADR 0110) and a
   stored counter beside it would be two records of one fact (ADR 0091).
   Records without a run or a timestamp are not counted and not guessed at.
3. **The retriever demotes by `half_life / (half_life + runs_since)`** and
   removes nothing. An entry seen this run keeps its score; one unseen for
   `half_life` runs keeps half. `0` disables it.
4. **The default is 5 because the sweep said any positive value wins and
   none loses.** Live coverage at budget 400 went 2 → 3 of 3 at half-life
   2, 5 and 10; total coverage at budget 2000 stayed 6 of 6 at every
   setting; 5 is the middle of the swept range, not a tuned optimum.

## Evidence

Metric fixed first: *live-lesson coverage* — of the lessons still recurring,
how many are retrieved under a budget. Rig: six lessons, three resolved
(fail R times, then succeed Q), three live (fail R, then fail Q more), a
clock that advances so records order. Measured, R=3, Q=4:

- budget 400, live of 3: half-life 0 → **2**, 2 → **3**, 5 → **3**, 10 → **3**
- budget 2000, total of 6: **6** at every half-life
- control (no resolution, Q=0): identical coverage at every budget; the
  tie-break among live lessons is now recency, not id — the mechanism, not
  a leak
- the field costs no budget: `runs_since` appears in chunk metadata, never
  in chunk content
- ADR 0110's coverage A/B, run with the new default on: unchanged (its
  clock is fixed, so `runs_since` is 0 everywhere)

Three mutations (count the entry's own run as later; never compute
staleness; retriever ignores freshness) each failed tests.

Two predictions were wrong and are recorded as such: uncurated live coverage
was predicted 1 and measured 2 — the id tie-break happened to favour two
live lessons, so the gain is one lesson at this budget; and the control was
predicted to give identical *order* and gave identical *coverage* only.

## Consequences

- Rubric dimension 2: 8 → 12. Curation exists and is measured; what is
  still missing is the ACE signal proper (retrieved → outcome), which
  needs a retrieval node to produce it, and any curation of the lesson
  *text* — entries are still the latest occurrence's feedback verbatim.
- `runs_since_last_seen` is agent-scoped: another agent's runs do not age
  this agent's lessons. Same seam as `agent_id` on the retriever.
- A lesson for a task the agent simply stopped attempting is demoted the
  same as one it fixed. Both mean "less relevant to current runs"; the
  distinction is not recoverable from records and is not claimed.
- **The tallies are recomputed over the read window; the provenance is
  not.** `_merge` (ADR 0116's upsert) unions `source_record_ids` across
  consolidations but takes `helpful`, `harmful` and `runs_since_last_seen`
  from the incoming entry, and the incoming entry is computed from the last
  `candidates_per_kind` records only. Reproduced (`.scratch/repro_tally.py`
  part 5, six failing runs with the lesson in context): at the default window
  the entry reads `occurrence_count 6, harmful 4`; re-consolidating the same
  unchanged store with `candidates_per_kind=2` leaves it at
  `occurrence_count 6, harmful 2` — a tally over two runs standing against a
  provenance of six. That is a disclosure, not a defect to patch here: a
  windowed recompute is what "stateless recompute" buys, and the alternative
  (carrying tallies forward) is the second source of truth ADR 0091 forbids.
  An owner who shrinks `candidates_per_kind` shrinks the tally's evidence
  base with it, and the entry does not say so on its face.

## Confidence

High on the mechanism; the gain is one lesson at one budget on a six-lesson
rig, and the number 12 says so.
