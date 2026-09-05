# ADR 0175: The arms were real this time, and the layer still did not pay

## Status

Accepted. Worker **S1b** of `UPGRADE_LOOP.md` — ADR 0155's four ACE arms re-run
on a corpus whose failures RECUR, which is the measurement ADR 0155's own
consequences asked for and ADR 0174's producer made possible.

**Model: `claude-opus-5[1m]`** (canonical `claude-opus-5`), the session default.
`--model` is deliberately absent from the argv so the session default answers;
the answering model was read back from `modelUsage` and is `claude-opus-5[1m]`
for **119 of 119** arm calls. **120 live calls** total (1 preflight + 119 arms),
against a budget of 130. Every number below was produced on this branch.

**Result: dimension 2 does not move. 12/20 stands, delta 0.** The falsification
stated before the run — *(c) ≤ (b) on a corpus that DOES form entries disproves
ADR 0110's coverage proxy for this corpus* — **FIRED**, and this time it fired
with the layer fully engaged: one knowledge entry formed from three distinct
train runs, and it reached the drafting model in 10 of 17 scored scenarios.

## What ADR 0155 could not measure, and what changed

S1 ran (a)/(b)/(c)/(d) and found (c) − (b) = −0.0207, then found the reason the
number meant nothing: **zero knowledge entries formed in any arm.** Every record
on the split was a `success` signed `"success:" + objective`, the objectives
were distinct, and ADR 0110's two-run threshold was unreachable by construction.
Arms (b) and (c) were the same arm.

Two things landed since:

- **ADR 0174** — a failed owner check now writes a `kind="failure"` record signed
  `check:<path>:<op>`, an identity that recurs across scenarios whose content
  differs.
- **ADR 0171 (S3b)** — a corpus with owner-check negatives in both splits: 3 in
  train, 4 in validation.

So the layer can now engage. This increment asks the only question that was
left: **with a real lesson in the store, does it move the task metric?**

## Step 0 — the seed, and the entries that formed

`docs/research/i12b/seed.py`. The TRAIN split (20 summary scenarios) is
**replayed from each scenario's own cassette** — `CassetteProvider(...,
on_miss="fail")`, so a single changed byte in a prompt would abort rather than
silently spend quota. The seed graph therefore has no retrieve node, which is
the prompt shape the scenarios were recorded under. **Zero live calls.**

```
  sum-22-marlowe-street: 0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-25-hollin-bridge:  0.7500 check_failure=YES ['check:working_memory.summary:max_words']
  sum-26-netherby-clinic:0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  (the other 17 train scenarios: 1.0000, no check failure)

train scenarios: 20   live calls: 0 (cassette, on_miss='fail')
memory: 3 failure record(s), 20 success record(s)
CONSOLIDATED: 1 knowledge entr(ies)
  failure:check:working_memory.summary:max_words  kind=failure runs=3
```

| | |
|---|---|
| entries formed | **1** |
| signature | `failure:check:working_memory.summary:max_words` |
| recurrence | **3 distinct runs** (`sum-22`, `sum-25`, `sum-26`) |
| lesson text | *"check failed: `working_memory.summary` is longer than the owner's maximum; observed 31 words, 208 chars: 'Vaccination clinics have relocated from Netherby Grange…'"* |

The arms are then scored on **VALIDATION**, whose 17 scenarios the seed never
saw. Every arm re-derives this identical seed rather than sharing a snapshot, so
no arm inherits another's validation-run reflections.

## The reproduction, before any quota: three of the four candidate (c)s were arm (b)

ADR 0155 spent 84 calls comparing one configuration against itself and found out
afterwards. Its check — hash every rendered draft prompt under a provider that
records instead of sending — was run **first** here, over the configuration this
worker intended (`docs/research/i12b/dry_identity.py`, offline):

| arm | `knowledge_boost` | SHA-256 over all 17 rendered draft prompts | lesson in prompt |
|---|---|---|---|
| a | – | `5956e7ffb9b0fcc9…` | 0/17 |
| b | – | `c6873a50bb4572db…` | 0/17 |
| **c** | **0.0 (shipped default)** | **`c6873a50bb4572db…`** | **0/17** |
| **c** | **0.5** | **`c6873a50bb4572db…`** | **0/17** |
| **c** | **1.0** | **`c6873a50bb4572db…`** | **0/17** |
| c | 3.0 | `77db3dc3d1002c07…` | 10/17 |
| d | 3.0 | `77db3dc3d1002c07…` | 10/17 |

**At the shipped default, and at two of the three swept alternatives, arm (c)
sends arm (b)'s prompts byte for byte.** Running (c) at 0.0 would have repeated
ADR 0155's mistake with an entry present — which is worse, because the null
would have looked like a result about the layer instead of a result about the
rig. The live (c) and (d) therefore ran at **`knowledge_boost = 3.0`**, and the
sweep that justifies it is below. `b_r0.json`'s live prompt hash is
`c6873a50bb4572db…` — the same as the dry run's, because the rendered lessons
are drawn from records whose text does not depend on what the model answered, so
this identity is a property of the live runs and not an artefact of the stub.

## Step 2 — the `knowledge_boost` sweep ADR 0174's defect 0 demanded

ADR 0110 swept 0 / 0.5 / 1 / 3 and recorded that the knob "changed no coverage
number anywhere". ADR 0174 found the first counter-example on a real corpus.
Here it is measured twice, offline, both from this rig's seed
(`docs/research/i12b/boost_sweep.py` and the dry runs above).

**Static** — the seeded store, each validation objective asked independently
(24 chunks retrieved; rank is the entry's position, `max_items=5` is what
`render_retrieved_context` shows a model):

| `knowledge_boost` | median rank | rank range | in top-5 (of 17 scenarios) |
|---|---|---|---|
| **0.0 (shipped)** | 23 | 21–23 | **0/17** |
| 0.5 | 20 | 1–20 | 1/17 |
| 1.0 | 20 | 0–20 | 2/17 |
| **3.0** | **0** | 0–0 | **17/17** |

**Sequential** — the arm as actually run, where each scored scenario adds a
fresh `success` record and ADR 0116's staleness demotion therefore walks the
entry down as the split proceeds:

| `knowledge_boost` | in top-5 | which scenarios |
|---|---|---|
| 0.0 / 0.5 / 1.0 | **0/17** | none |
| 3.0 | **10/17** | the first nine, plus `sum-33`; lost from `sum-32` onward |

3.0 is the first swept value at which the lesson reaches the model at all. That
is why (c) ran there, and the honest reading of the middle two rows is that
0.5 and 1.0 are *also* arm (b).

**The default is NOT changed.** The rule that killed the knob in ADR 0110 is
that it moves only if it moves the **task metric**, and the live arms below say
it does not: at boost 3.0, with the lesson demonstrably in ten prompts, (c)
scored **below** (b). `knowledge_boost` stays `0.0`, now for a stronger reason
than 0110's — 0110 could only say the knob changed no coverage number on a
corpus that could not produce this shape; this says the knob changes what the
model sees, decisively (0/17 → 10/17 in prompt), and the task metric still does
not follow. A pin test records that
(`tests/services/knowledge/test_ab_coverage.py::test_the_shipped_boost_default_is_the_measured_one`).

## The measurement — four arms, 17 validation scenarios, 119 live calls

Scored by the same `score_scenario` the gates use (ADR 0113). Raw JSON in
`docs/research/i12b/results/`.

| arm | mean | negatives (n=4) | rest (n=13) | calls | secs | draft-prompt sha256 |
|---|---|---|---|---|---|---|
| (a) no retrieve | **0.8941** | 0.8500 | 0.9077 | 17 | 45 | `5956e7ffb9b0fcc9…` |
| (b) raw records | **0.9176** | 0.9000 | 0.9231 | 17 | 46 | `c6873a50bb4572db…` |
| (c) + knowledge @ boost 3.0 | **0.9059** | 0.8500 | 0.9231 | 17 | 66 | `77db3dc3d1002c07…` |
| (d) + LLM reflection | **0.9529** | 0.8500 | 0.9846 | 68 | 373 | `77db3dc3d1002c07…` |

| scenario | (a) | (b) | (c) | (d) | lesson in (c)'s prompt |
|---|---|---|---|---|---|
| `sum-13-cider-press` | 0.80 | 1.00 | 1.00 | 1.00 | yes |
| `sum-14-quarry-lake` | 0.80 | 0.80 | 0.80 | 1.00 | yes |
| `sum-15-bookbinder` | 0.80 | 0.80 | 1.00 | 1.00 | yes |
| `sum-16-cliff-path` | 0.80 | 1.00 | 1.00 | 1.00 | yes |
| `sum-17-clockmaker` | 0.80 | 1.00 | 1.00 | 1.00 | yes |
| `sum-18-heron-rookery` | 1.00 | 1.00 | 1.00 | 1.00 | yes |
| `sum-29-brindle-viaduct` | 1.00 | 1.00 | 1.00 | 1.00 | yes |
| `sum-30-ganister-tarn` **NEG** | 0.80 | 1.00 | 1.00 | 1.00 | yes |
| `sum-31-quernmore-kiln` | 1.00 | 0.80 | 1.00 | 1.00 | yes |
| `sum-32-hessle-mills` | 1.00 | 0.80 | 0.60 | 0.80 | no |
| `sum-33-cotterdale-bus` **NEG** | 1.00 | 1.00 | 1.00 | 1.00 | yes |
| `sum-34-alder-carr` | 0.80 | 0.80 | 1.00 | 1.00 | no |
| `sum-35-priory-gatehouse` **NEG** | 0.80 | 0.80 | 0.80 | 0.80 | no |
| `sum-36-larkfield-quarry` **NEG** | 0.80 | 0.80 | 0.60 | 0.60 | no |
| `sum-37-ryhope-pool` | 1.00 | 1.00 | 1.00 | 1.00 | no |
| `sum-38-bewick-refusals` | 1.00 | 1.00 | 0.80 | 1.00 | no |
| `sum-39-coldbeck-society` | 1.00 | 1.00 | 0.80 | 1.00 | no |

| comparison | delta (mean) | delta (negatives) |
|---|---|---|
| (b) − (a) — retrieval vs none | **+0.0235** | +0.0500 |
| **(c) − (b) — knowledge vs raw records** | **−0.0117** | **−0.0500** |
| (d) − (c) — LLM reflection vs rule-based | **+0.0470** | +0.0000 |

### The noise bar, measured inside the experiment rather than imported

`a`+`b`+`c`+`d` cost 119 of the 130 budgeted live calls — arm (d) alone is 68,
because `LLMCritic` and `LLMJudge` add three calls per scenario — so **there was
no budget for a repeat and no within-arm spread was measured.** Rather than
import ADR 0156's floor (0.1666, on a different split of six scenarios) and
scale it, this rig measured its own, from the scenarios where two arms sent
**byte-identical draft prompts**:

| pair | scenarios with identical prompts | mean difference | scenarios whose score changed |
|---|---|---|---|
| (c) vs (d) | **17/17** | +0.0471 | 4 |
| (b) vs (c) | 7/17 | −0.0857 | 5 |

Two independent same-prompt samples, both live, both on this split, on the same
model. **Same-prompt variance runs to 0.0857 on a 7-scenario subset and 0.0471
across all 17, with a single scenario swinging 0.20.** Every arm-to-arm delta in
the table above — +0.0235, −0.0117, +0.0470 — sits inside that band. This is a
weaker instrument than repeats (it cannot separate arm-order effects from run
variance) and it is stated as such; what it has over an imported floor is that
it is this corpus, this model, this night.

### Falsification (c) ≤ (b): FIRED, on a corpus that formed an entry

This is the increment's result and it is not the same result as ADR 0155's.

- One entry formed, from three distinct runs. The store was not empty.
- The lesson reached the drafting model in **10 of 17** scenarios — verified per
  scenario, and visible in the rendered block:

  ```
  Lessons from this agent's earlier runs (most relevant first):
  - [failure:check:working_memory.summary:max_words] … check failed:
    working_memory.summary is longer than the owner's maximum; observed 31 words …
  - [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
  - [success] no failure signals: …   (×3 more)
  ```

  versus arm (b) on the same scenario, which is five copies of *no failure
  signals* — ADR 0110's own I4 finding, reproduced live: near-duplicate records
  crowd out every distinct lesson.
- And (c) still scored **0.9059 against (b)'s 0.9176**, and **0.8500 against
  0.9000 on the four owner-check negatives** — the very scenarios a word-cap
  lesson had to move.

**ADR 0110's coverage result is therefore DISPROVED as a predictor of task
outcome on this corpus**, not merely unconfirmed as ADR 0155 left it. The
distinction matters: 0155 could not run the experiment, and this one ran.

The counter-argument, stated because a reader is entitled to it: on the 10
scenarios where the lesson was in the prompt, (c) scored **0.9800** against (b)'s
**0.9400**, with two improvements and no regressions; on the 7 where the prompts
were identical it scored 0.8000 against 0.8857. So the whole of (c)'s deficit
lives in the subset where (c) *was* (b) — i.e. in same-prompt noise — and the
treated subset moved the right way. That reading is available in the numbers and
this ADR will not hide it. It is not claimed, for two reasons: +0.0400 on n=10 is
smaller than the 0.0857 same-prompt swing measured on n=7, and the split into
"treated" and "control" is not randomised — it is the tail of the run, where
staleness had demoted the entry, so the two subsets differ in more than
treatment. **A corpus-and-budget that could settle it needs repeats, which this
one did not have.** What is settled is the headline: the arm with the knowledge
layer did not beat the arm without it, on the metric, on the negatives, with the
layer engaged.

### Falsification (d) ≤ (c): did not fire numerically, and LLM reflection stays off anyway — fourth time

(d) − (c) = **+0.0470**. But arm (c) and arm (d) sent **byte-identical draft
prompts on all 17 scenarios** (`77db3dc3d1002c07…` for both). Arm (d)'s 51 extra
model calls went to `LLMCritic` and `LLMJudge`, whose records never entered
`render_retrieved_context`'s five bullets, so **nothing the drafting model saw
differed between the two arms.** The +0.0470 is same-prompt live variance by
construction — it is the same number the noise table reports, from the same
comparison.

`reflection.impl: llm` stays off (ADR 0115, ADR 0123, ADR 0155, here). The
finding is sharper than "the gain is inside the noise": on this graph the LLM
critic's output has **no path to a prompt at all**, so the arm is arm (c) at 4×
the cost. Anyone re-running it should first give the critic's record a way to be
retrieved, or stop paying for it.

### (b) − (a) = +0.0235: retrieval is not shown to help either

ADR 0155 measured this as exactly 0.0000. Here it is +0.0235, also inside the
same-prompt band. Two measurements, on two splits, neither showing that wiring
retrieval into the prompt improves this task. The capability is present; the
claim is still not made.

## Consequences

- **Rubric: dimension 2 stays 12/20, delta 0.** Not +2 (the (c) > (b) gain
  visible on the negatives did not happen — (c) was *worse* on the negatives),
  and not +1 (the negatives-only reading fails for the same reason). No row is
  prepended. The rubric's rule is that a score moves on a cited artifact showing
  improvement, and this artifact shows the opposite of one.
- **ADR 0110's coverage proxy is disproved for this corpus**, superseding ADR
  0155's "demoted to an unconfirmed proxy". The consolidation mechanism works —
  it collapses three near-duplicate check failures into one lesson that a model
  can read, exactly as designed — and the lesson did not change the answers.
- **`knowledge_boost` stays 0.0**, and the reason has been upgraded rather than
  repeated: the knob demonstrably controls whether the only lesson in the store
  reaches the model (0/17 vs 10/17 in prompt), and the task metric does not
  follow it. ADR 0110 said the benefit is consolidation and not ranking; this
  says the ranking knob is real and buys nothing measurable, which is a
  different and better-evidenced sentence.
- **`reflection.impl: llm` stays off**, fourth measurement.
- **What a next increment needs**, so it is not re-derived: repeats. Two repeats
  of (b) and (c) at 17 scenarios is 68 calls and would separate the treated-subset
  +0.0400 from the 0.0857 same-prompt swing. Cutting arm (d) pays for exactly
  that, and on the evidence above arm (d) currently buys nothing at all.

## Defects and findings outside this worker's files

Reported, not fixed. No file under `aef/` was modified by this worker.

1. **ADR 0116's staleness demotion walks a *training* lesson out of the prompt
   as a scored split proceeds, and nothing re-freshens it.** At boost 3.0 the
   entry is rank 0 for the first nine scenarios and rank 25–39 by the
   seventeenth: every scored run writes a fresh `success` record, so
   `runs_since_last_seen` climbs monotonically while the lesson can never be
   re-seen — the graph has no check-failure producer, because ADR 0174 wired one
   into `bootstrap` only. The effect is that **the two negatives late in the
   split (`sum-35`, `sum-36`) never saw the word-cap lesson at all**, halving
   the power of the very comparison this increment exists for. Not a bug in
   either mechanism; a seam between them, and it costs the measurement.
   (`aef/services/context/memory_retriever.py::_freshness`,
   `aef/services/knowledge/consolidate.py::_runs_since`.)
2. **Arm (d)'s reflection output cannot reach a prompt.** `LLMCritic`/`LLMJudge`
   write records that `MemoryRetriever` ranks below seventeen near-identical
   successes, so `reflection.impl: llm` costs 3 calls per run and changes
   nothing a model reads. Any future A/B of it should measure the prompt
   diff first — it is free, and here it would have saved 51 live calls.
3. **`render_retrieved_context(max_items=5)` is the real budget, not
   `context_budget_tokens`.** With 8000 tokens the retriever admits all 24–40
   chunks and the render cap discards all but five. `MemoryRetriever` enforces a
   budget nothing binds on this corpus while a constant five decides what the
   model sees. (`aef/reasoning/nodes.py`.)

## Quota preflight

ADR 0150's corrected argv, run first as the loop requires:

```
rc 0  is_error: False  result: 'OK'  usage.input_tokens: 2
modelUsage: claude-haiku-4-5-20251001 {in 1110, out 13}   <- the CLI's own side call
            claude-opus-5[1m]         {in 2, out 134}     <- answered
```

**Calls: 120 of a budget of 130** — 1 preflight + 17 (a) + 17 (b) + 17 (c) + 68
(d). Seeding cost **0**: the train split was replayed from its committed
cassettes. The 10 remaining calls do not buy a repeat of anything (an arm is 17),
so none was attempted.

## Artifacts

- `docs/research/i12b/seed.py` — the train replay and consolidation (step 0).
- `docs/research/i12b/boost_sweep.py` — the static boost sweep (step 2).
- `docs/research/i12b/dry_identity.py` — the pre-quota prompt-hash reproduction.
- `docs/research/i12b/arms.py` — one arm per invocation, checkpointing each
  scenario to JSONL-shaped partial output as it lands.
- `docs/research/i12b/aggregate.py` — every table above, from the raw JSON.
- `docs/research/i12b/results/` — `seed.json`, `boost_sweep.json`,
  `{a,b,c,d}_r0.json` (live, with every rendered draft prompt), `dry/`.

## Confidence

**High** that (c) did not beat (b) here: the arms differ in exactly one thing,
the difference is recorded per scenario, and the prompts are hashed.

**High** that the layer engaged: one entry, three source runs, ten prompts
carrying it, all recorded.

**Low** on the *magnitude* of anything. One repeat per arm, a same-prompt
variance of up to 0.0857, and a 17-scenario split scored in fifths. No delta in
this ADR clears its own noise bar, and the ADR claims none.
