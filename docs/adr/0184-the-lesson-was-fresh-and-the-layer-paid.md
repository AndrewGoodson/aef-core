# ADR 0184: The lesson was fresh, it carried no quotation, and the layer paid

## Status

Accepted. Worker **S1c** of `UPGRADE_LOOP.md` — ADR 0175's arms re-run with ADR
0180's three instruments applied, which is the measurement ADR 0180's own last
section specified and declined to predict.

**Model: `claude-opus-5[1m]`** (canonical `claude-opus-5`), the session default.
`--model` is deliberately absent from the argv so the session default answers;
the answering model was read back from `modelUsage` and is `claude-opus-5[1m]`
for **102 of 102** arm calls. **103 live calls** total (1 preflight + 102 arms)
against a budget of 110. Every number below was produced on this branch.

**Result: dimension 2 moves 12 → 14.** The pre-registered rule's first branch
fired: (c) − (b) = **+0.0529** on the mean against a larger repeat spread of
**0.0353**, and (c) ≥ (b) on the four owner-check negatives (+0.0917). ADR
0175's falsification — *(c) ≤ (b)* — **did not fire this time**, and the
difference between the two runs is not the layer. It is the two defects ADR
0180 removed from underneath it.

## What ADR 0175 could not separate

S1b ran (a)/(b)/(c)/(d) on a corpus whose failures recur, found (c) 0.9059
against (b) 0.9176, and wrote down in its own last section why that number
could not be read as *the knowledge layer does not help*:

1. **The lesson quoted the model's own output back at it.** The bullet in front
   of the model read *"observed 31 words, 208 chars: 'Vaccination clinics have
   relocated from Netherby Grange…'"* — an example of an over-long summary,
   inside a lesson telling the model to be shorter. ADR 0162 rig B measured that
   exact shape making two at-cap runs LONGER (23 → 28 against a cap of 25;
   38 → 41 against 38) and breaking the very check the lesson describes. (c) lost
   on the negatives, which are the word-cap scenarios — precisely where that
   mechanism bites.
2. **The producer was wired into `bootstrap` alone.** Arm (c)'s own result file
   says `"failures": {}`: six scored runs failed an owner check and none could
   record it. Every scored run wrote a `success`, `runs_since_last_seen` climbed
   monotonically, ADR 0116's staleness demotion walked the entry from rank 0 to
   rank 25–39, and the two negatives late in the split never saw the lesson.
3. **No repeats.** Arm (d) cost 68 of the 119 arm calls while sending arm (c)'s
   prompts byte for byte, so the noise bar had to be inferred from same-prompt
   subsets rather than measured from repeating an arm.

ADR 0180 supplied instruments for (1) and (2) and claimed nothing about the
outcome. This increment spends the budget arm (d) was wasting on (3).

## Step 0 — the seed, and the entry that formed

`docs/research/i12c/seed.py`, unchanged from S1b except that it calls ADR
0180's `record_check_outcomes` (the function `bootstrap` and
`run_scenario(..., memory=…)` both call now) instead of the removed
`write_check_failure_record`. The TRAIN split is replayed from each scenario's
own cassette under `CassetteProvider(..., on_miss="fail")`, so a changed prompt
byte aborts rather than silently spending quota. **Zero live calls.**

```
  sum-22-marlowe-street:  0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-25-hollin-bridge:   0.7500 check_failure=YES ['check:working_memory.summary:max_words']
  sum-26-netherby-clinic: 0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  (the other 17 train scenarios: 1.0000, no check failure)

train scenarios: 20   live calls: 0 (cassette, on_miss='fail')
memory: 3 failure record(s), 20 success record(s)
EXCERPT PROPERTY (ADR 0180): 0 windows of 12 chars of any run's output found
  in any of the 23 record(s) derived from it
CONSOLIDATED: 1 knowledge entr(ies)
  failure:check:working_memory.summary:max_words  kind=failure runs=3
    conf=0.4286 since=2 tally=(h=0 x=0 xe=0)
```

| | S1b (ADR 0175) | S1c (here) |
|---|---|---|
| entries formed | 1 | **1** |
| signature | `failure:check:working_memory.summary:max_words` | **identical** |
| recurrence | 3 distinct runs (`sum-22`, `sum-25`, `sum-26`) | **identical** |
| lesson text ends | `…observed 31 words, 208 chars: 'Vaccination clinics have relocated from Netherby Grange…'` | **`…observed 31 words, 208 chars`** |

The seed is byte-comparable to S1b's in every respect but the one ADR 0180
changed. That is what makes the two nights' arm tables a comparison.

## The excerpt, checked twice — in the record and in the prompt

`assert_no_excerpt` is the seed's own gate: no 12-character window of any train
run's summary survives anywhere in the content of a record derived from it. 23
records checked, 0 windows.

`docs/research/i12c/leak_check.py` asks the question one layer out, on the six
LIVE arm runs: **did any run's own summary reach a later run's prompt?**

| arm | repeat | later prompts carrying a lesson block | leaked windows |
|---|---|---|---|
| (a) | 0 | 0/17 | **0** |
| (b) | 0 | 17/17 | **0** |
| (b) | 1 | 17/17 | **0** |
| (b) | 2 | 17/17 | **0** |
| (c) | 0 | 17/17 | **0** |
| (c) | 1 | 17/17 | **0** |

**The first version of that script was wrong and is worth recording.** It
scanned the whole later prompt and reported 28 leaked windows in arm (a) — the
arm with no retrieve node at all. The hits were ordinary English shared between
one summary and the next scenario's *passage*: nine overlapping windows of
`' for the first time '`. A detector that fires on an arm with no channel is
measuring the language, not the channel, so the script now scans only the
rendered lesson block, which is the only path a prior output can travel. The
zero above is a zero on the channel; the 28 was a zero-information number that
would have read as a finding.

This is what the model actually saw in arm (c), scenario 1:

```
Lessons from this agent's earlier runs (most relevant first):
- [failure:check:working_memory.summary:max_words] 1 error(s) recorded; 0/0 tool
  call(s) failed. errors[0]: check failed: working_memory.summary is longer than
  the owner's maximum; observed 31 words, 208 chars
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
  (×4 more)
```

Same bullet as ADR 0175 quotes, minus the sentence of the model's own prose.

## The boost arm (c) ran at, decided before any quota

`docs/research/i12c/boost_sweep.py`, offline, over the seeded store and every
validation objective. Rank is the entry's position among retrieved chunks;
`render_retrieved_context`'s `max_items=5` is what a model actually reads.

| `knowledge_boost` | median rank | rank range | in top-5 (of 17) |
|---|---|---|---|
| **0.0 (shipped)** | 20 | 20–23 | **0/17** |
| 0.5 | 20 | 1–20 | 2/17 |
| 1.0 | 20 | 0–20 | 2/17 |
| **3.0** | **0** | **0–0** | **17/17** |

At the shipped default the only lesson in the store is invisible to the model at
scenario 1, so **(c) at 0.0 is arm (b)** — ADR 0175's finding, reproduced with
the new lesson text. The brief's condition ("run (c) at 0.0 *and* at 3.0 if the
default still hides the entry at scenario 1") therefore resolved to 3.0, and
**both (c) repeats ran at 3.0**, because a repeat spread is only a spread if the
two repeats are the same configuration.

Two offline checks say the same thing from different directions, both at 0 calls.

**Directly** (`dry_identity.py`, the whole sequential arm under a stub provider,
with the producer wired):

```
arm=a boost=0.0  hash=5956e7ffb9b0fcc9  entry_in_prompt= 0/17  (= S1b's (a))
arm=b boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17  (= S1b's (b))
arm=c boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17  <- IS arm (b)
arm=c boost=3.0  hash=3868153f5bf8352e  entry_in_prompt=11/17
```

Arm (c) at the shipped default sends arm (b)'s prompts **byte for byte** on all
17. That is weaker evidence than S1b's identical check was, and the reason is
this increment's own fix: with the producer on the scored split, freshness
depends on whether a check failed, so the stub's fixed 9-word answer — which
never trips the word cap — walks the lesson out exactly as S1b's live run did.

**As an upper bound**, therefore, since the live trajectory is the one that
matters: with `staleness_half_life=0` (freshness pinned at 1.0, the best any
producer could ever achieve) the entry reaches the top-5 in **2 of 17**
scenarios at boost 0.0 — `sum-31` at rank 0, `sum-33` at rank 2. So (c) at the
shipped default is arm (b) on at least 15 of 17 prompts under the most generous
assumption available, and spending 34 live calls to re-measure that was refused.

## The measurement — three arms, 17 validation scenarios, six repeats, 102 calls

Scored by the same `score_scenario` the gates use (ADR 0113). Raw JSON and a
per-scenario JSONL written as each scenario landed are in
`docs/research/i12c/results/`.

| arm | repeat | boost | mean | negatives (n=4) | rest (n=13) | lesson in prompt | secs | draft-prompt sha256 |
|---|---|---|---|---|---|---|---|---|
| (a) no retrieve | 0 | – | 0.9176 | 0.8500 | 0.9385 | 0/17 | 46 | `5956e7ffb9b0fcc9…` |
| (b) raw records | 0 | – | 0.8941 | 0.8500 | 0.9077 | 0/17 | 46 | `c6873a50bb4572db…` |
| (b) raw records | 1 | – | 0.8941 | 0.8500 | 0.9077 | 0/17 | 48 | `c6873a50bb4572db…` |
| (b) raw records | 2 | – | 0.9294 | 0.8000 | 0.9692 | 0/17 | 49 | `c6873a50bb4572db…` |
| (c) + knowledge | 0 | 3.0 | 0.9647 | 0.9500 | 0.9692 | **15/17** | 67 | `e774d81e2d6fe4e5…` |
| (c) + knowledge | 1 | 3.0 | 0.9529 | 0.9000 | 0.9692 | **15/17** | 75 | `e21b8bf9dfaf5be5…` |

**Arm (a)'s and arm (b)'s prompt hashes are byte-identical to S1b's**
(`5956e7ff…`, `c6873a50…`), which is the cross-check that the two nights'
control arms are the same experiment: the excerpt lives only in a *knowledge
entry's* text, and (a) and (b) never render one.

| arm | repeats | mean | repeat spread | negatives | neg spread | calls |
|---|---|---|---|---|---|---|
| (a) no retrieve | 1 | 0.9176 | – | 0.8500 | – | 17 |
| (b) raw records | 3 | **0.9059** | **0.0353** | 0.8333 | 0.0500 | 51 |
| (c) + knowledge @ 3.0 | 2 | **0.9588** | **0.0118** | 0.9250 | 0.0500 | 34 |

| scenario | (a) | (b) | (c) | lesson in (c)'s prompt |
|---|---|---|---|---|
| `sum-13-cider-press` | 1.00 | 0.93 | 1.00 | 2/2 |
| `sum-14-quarry-lake` | 0.80 | 0.80 | 0.80 | 2/2 |
| `sum-15-bookbinder` | 1.00 | 0.87 | 1.00 | 2/2 |
| `sum-16-cliff-path` | 1.00 | 0.87 | 0.90 | 2/2 |
| `sum-17-clockmaker` | 0.80 | 0.93 | 1.00 | 2/2 |
| `sum-18-heron-rookery` | 1.00 | 1.00 | 1.00 | 2/2 |
| `sum-29-brindle-viaduct` | 1.00 | 1.00 | 1.00 | 2/2 |
| `sum-30-ganister-tarn` **NEG** | 1.00 | 0.93 | 1.00 | 2/2 |
| `sum-31-quernmore-kiln` | 0.80 | 0.93 | 1.00 | 2/2 |
| `sum-32-hessle-mills` | 1.00 | 0.87 | 1.00 | 2/2 |
| `sum-33-cotterdale-bus` **NEG** | 1.00 | 0.80 | 1.00 | 2/2 |
| `sum-34-alder-carr` | 1.00 | 1.00 | 1.00 | **0/2** |
| `sum-35-priory-gatehouse` **NEG** | 0.80 | 0.80 | 0.80 | **0/2** |
| `sum-36-larkfield-quarry` **NEG** | 0.60 | 0.80 | 0.90 | 2/2 |
| `sum-37-ryhope-pool` | 1.00 | 1.00 | 1.00 | 2/2 |
| `sum-38-bewick-refusals` | 1.00 | 1.00 | 1.00 | 2/2 |
| `sum-39-coldbeck-society` | 0.80 | 0.87 | 0.90 | 2/2 |

| comparison | delta (mean) | delta (negatives) |
|---|---|---|
| (b) − (a) — raw retrieval vs none | **−0.0117** | −0.0167 |
| **(c) − (b) — knowledge vs raw records** | **+0.0529** | **+0.0917** |
| (c) − (a) — knowledge vs no retrieval | +0.0412 | +0.0750 |

### The rank trajectory — ADR 0180's fix 2, visible

This is the number ADR 0180 predicted and did not measure.

| | S1b (`bootstrap` only) | S1c (producer on the scored split) |
|---|---|---|
| entry rank at scenario 1 | 0 | **0** (both repeats) |
| entry rank at scenario 17 | **25–39** | **0** (both repeats) |
| in the model's prompt | 10/17 | **15/17** (both repeats) |
| failure records the arm wrote | **`{}`** | 3 `max_words` (r0); 3 `max_words` + 1 `regex` (r1) |

`runs_since_last_seen` in arm (c) r0 runs 2, 2, 2, 2, 2, 2, 2, 3, 4, 5, 6, 7, 8,
**1**, 2, 3, 4 — it climbs while the model succeeds and resets the moment a
scored run reproduces the cap failure. S1b's climbed 2 → 17 and never came back.
The two scenarios (c) missed are `sum-34` and `sum-35`, the peak of that one
climb; `sum-36` failed the cap, wrote its record, and the lesson was rank 0
again for the remaining four.

**`runs_since_last_seen` never reaches 0, and the reason is a real off-by-one in
the shipped wiring** — reported below, not fixed here.

## The pre-registered decision rule

Stated in the worker's brief before any live call, and evaluated by
`docs/research/i12c/aggregate.py` rather than by hand:

> dim 2 moves 12 → 14 ONLY if (c) > (b) on the mean by more than the larger of
> the two arms' repeat spreads AND (c) ≥ (b) on the negatives. 12 → 13 if (c) >
> (b) on the negatives by more than the spread with the mean inside it. (c) ≤ (b)
> again → +0.

```
    (c) − (b) on the mean       = +0.0529
    larger repeat spread        =  0.0353
    (c) − (b) on the negatives  = +0.0917
    larger negatives spread     =  0.0500

    BRANCH: 12 -> 14
```

Both clauses hold: the mean delta clears the bar by 1.5×, and (c) is not merely
≥ (b) on the negatives but ahead of it by more than the negatives' own spread.

### The third (b) repeat was added after seeing the first two, and it made the bar harder

Two repeats of (b) returned **identical** means (0.8941, 0.8941) — a repeat
spread of 0.0000, which is an implausible noise estimate from n=2 and would have
made the decision bar 0.0118, (c)'s spread. With 24 calls left of the 110 budget,
a third (b) repeat was run for exactly that reason, and this is recorded rather
than quietly folded in because a post-hoc repeat is the shape of optional
stopping.

It cannot have been chosen to pass: adding it moved (b)'s mean **up** (0.8941 →
0.9059, shrinking the delta from +0.0647 to +0.0529) and widened the bar
**thirty-fold** (0.0000 → 0.0353). Both effects are against the claim, and the
claim survived both. There was no budget for a symmetric third (c) repeat
(103 + 17 > 110) and none was taken; the asymmetry (3 repeats of (b), 2 of (c))
is stated here because a mean of three and a mean of two are not equally
precise.

### The noise bar, measured properly this time

| arm | distinct prompt hashes | mean spread | scenarios whose score differed across repeats |
|---|---|---|---|
| (b) raw records | **1** | 0.0353 | **9/17** |
| (c) + knowledge @ 3.0 | 2 | 0.0118 | 3/17 |

Arm (b)'s three repeats sent **byte-identical prompts**, so its 0.0353 is a true
same-prompt live variance on the full 17-scenario split, and the 9-of-17
per-scenario churn behind a 0.0353 mean spread is the useful shape: individual
scenarios are very noisy and the mean of seventeen is not.

**Arm (c)'s two repeats are NOT a same-prompt sample** — two distinct hashes —
and that is a consequence of the fix, not a flaw in the rig: once the producer
is on the scored split, whether a lesson is fresh depends on whether the model
failed a check, so what the model is shown depends on what the model previously
said. (c)'s spread is therefore a *repeat* spread, which is the right instrument
for the rule but a weaker one for noise. The rule takes the larger of the two,
which is (b)'s.

S1b's imported alternative was a same-prompt band of **0.0857** measured on a
7-scenario subset. The delta here (+0.0529) does **not** clear that number.
It is not the bar used, for a reason stated rather than assumed: 0.0857 was the
spread of a 7-scenario mean and this is a 17-scenario mean, and the spread of a
mean shrinks with n — measured here as 0.0353 on this split, on this model, with
three repeats. The comparison against 0.0857 is recorded so a reader can apply
their own instrument and reach a different answer; under S1b's, this delta is
inside the noise and dimension 2 does not move.

### (b) − (a) = −0.0117: raw retrieval is still not shown to help

Third measurement of this comparison, third time it lands inside the noise:
0.0000 (ADR 0155), +0.0235 (ADR 0175), **−0.0117** here — and the sign has now
changed twice. Wiring retrieval of raw records into the prompt is a capability;
that it improves this task remains unclaimed. What (c) − (b) says is that
**consolidation** is the part that pays, which is ADR 0110's own thesis arriving
on the task metric for the first time.

## What this does and does not license about `knowledge_boost`

**The default is NOT changed. It stays 0.0.** The brief permits changing it only
if the task metric moves *with the knob*, and the knob was never varied live:
arm (c) ran at 3.0 in both repeats, and the arm that isolates the knob —
knowledge attached, boost 0.0 — was not run, because the offline bound above
says it is arm (b) on at least 15 of 17 prompts and 34 live calls were not worth
proving that a second time. So what is measured is *the layer at boost 3.0
against no layer*, and attributing +0.0529 to the coefficient rather than to the
layer would be exactly the substitution this repo's ADRs keep catching.

Two things follow, and the second is uncomfortable enough to state plainly:

- **The next dimension-2 increment's cheapest question is the knob's own A/B**:
  (c) at 0.0 against (c) at 3.0, 34 calls, two repeats, everything else held.
  That is the measurement that could move the default, and it has never been run
  in this programme.
- **At the shipped default, the benefit measured here is not available**, and it
  is not available *at all*: `knowledge_boost` appears nowhere outside
  `memory_retriever.py` (`grep -rn knowledge_boost aef/` returns five lines, all
  in that file). `ContextConfig` exposes `impl` and `token_budget` and nothing
  else, and `build_retriever` constructs `MemoryRetriever` without it — so an
  adopter cannot set it from `aef.yaml` even having read this ADR. The knob is
  reachable only by hand-constructing `Services`, which is the shape ADR 0101
  deleted `GraphStore` for tolerating. Fixing that surface belongs before
  arguing about its default.

`tests/services/knowledge/test_ab_coverage.py::test_the_shipped_boost_default_is_the_measured_one`
is untouched and still passes.

## Consequences

- **Rubric: dimension 2 moves 12/20 → 14/20.** One row prepended,
  heading 72 → 74, recomputed by `tests/test_rubric_arithmetic.py` from the rows
  rather than carried by hand.
- **ADR 0175's disproof of ADR 0110's coverage proxy is REVERSED for this
  corpus, and the reversal is attributed.** 0175's own text names the two
  candidates it could not separate — "the arms as run cannot tell a knowledge
  layer that does not help from a lesson text that hurts" — and this run removes
  both. It does not identify which of the two was doing the damage: the excerpt
  and the staleness walk were fixed together, and separating them would cost
  another 34 calls. ADR 0110's coverage result is restored to *consistent with
  the task metric on this corpus*, which is weaker than *confirmed* and much
  stronger than where 0175 left it.
- **ADR 0180's two instruments are validated by use.** The excerpt fix is proved
  on live data at the prompt (0 leaked windows in 85 lesson blocks), and the
  producer's second wiring site is proved by the rank trajectory (0 → 0 instead
  of 0 → 39, 15/17 prompts instead of 10/17). Neither was measured in 0180
  itself, which claimed nothing.
- **`knowledge_boost` stays 0.0**, for a reason that is now *narrower* than
  0175's rather than stronger: not "the knob buys nothing measurable", but "the
  knob's own A/B has not been run, and it cannot be set from `aef.yaml` if it
  were".
- **The dimension-2 line of inquiry on this corpus is not closed**, which is the
  branch the brief reserved for a null. What remains is listed under defects.

## Defects and findings outside this worker's files

Reported, not fixed. No file under `aef/` was modified by this worker.

1. **Freshness is computed from RECORDED time, not execution order, and
   `run_scenario` passes `created_at=scenario.recorded_at`.** Two consequences,
   both measured here.

   *It floors at 1.* The reflect node's success record for the same run is
   written with a `fixed_clock` value drawn from `scenario.clock_values`, ~2 ms
   after `recorded_at`. `_runs_since` counts runs whose latest record is newer
   than the entry's `last_seen`, so the producing run counts against its own
   lesson and `runs_since_last_seen` floors at **1**, never 0 — arm (c)'s
   minimum, immediately after the refresh at `sum-36`. One freshness step
   (5/6 = 0.833 instead of 1.0); it changed no rank here, and on a corpus where
   the entry sits near the render cap it decides whether a lesson is read.

   *Six of the seventeen scored scenarios cannot refresh a lesson at all.*
   `sum-13` … `sum-18` were recorded 2026-09-04, before the train failures the
   seed consolidates (2026-09-05 03:18). Their check-failure records are
   therefore **older** than the entry's `last_seen`, so `last_seen` does not
   advance and `runs_since_last_seen` does not reset: arm (c)'s series holds at
   2 for the first seven scenarios and resets only at `sum-36`, whose
   `recorded_at` is later than the seed's. The producer ran on all of them —
   `sum-14` and `sum-16` both wrote `max_words` records in r0 — and the refresh
   silently did not happen. On a corpus scored in recorded order this is
   invisible; on any other, a lesson's staleness depends on when its scenario
   was *recorded* rather than on what the agent has just done.
   (`aef/harness/scenario_runner.py::run_scenario`,
   `aef/services/knowledge/consolidate.py::_runs_since`.)
2. **`knowledge_boost`, `staleness_half_life` and `knowledge_min_occurrences` are
   unreachable from `aef.yaml`.** `ContextConfig` carries `impl` and
   `token_budget`; `build_retriever` passes `max_token_budget` and nothing else.
   Two of those three have defaults set by measurement (ADR 0110, 0116) and this
   ADR measures a large effect at a third value of the first — none of which an
   adopter can act on. (`aef/config/schema.py::ContextConfig`,
   `aef/config/factory.py::build_retriever`.)
3. **`run_scenario` cannot express the arms.** Its `memory=` parameter is the
   durable sink for check outcomes only; the agent's own memory is still a
   throwaway `InMemoryMemoryStore()` and it wires no knowledge store, so a caller
   scoring a corpus with `aef loop score --memory` gets the producer but never
   the retrieval it feeds. This runner therefore copies `run_scenario`'s producer
   block argument-for-argument rather than calling it, which is recorded in
   `arms.py`'s docstring so the two cannot drift silently.
4. **The consolidation lag.** A graph's `consolidate` node is the last node of
   the current run, so a record written after scoring is first consolidated at
   the end of the *next* run — after that run has already retrieved. This runner
   consolidates immediately after `record_check_outcomes` to remove the
   one-scenario lag; a real `aef loop score --memory` does not, and its lessons
   are one scenario staler than they need to be.
5. **`render_retrieved_context(max_items=5)` is still the real budget**, not
   `context_budget_tokens` (ADR 0175's finding 3, unchanged): 24–47 chunks were
   admitted under an 8000-token budget that never bound, and a constant five
   decided what the model saw.

## Green bar

```
pytest -q                 2720 passed, 7 skipped, 1 xfailed
mypy aef examples         Success: no issues found in 135 source files
ruff check .              All checks passed!
ruff format --check aef tests examples docs/research/i12c   286 files already formatted
```

No file under `aef/` or `tests/` was modified, and no test was added: this
worker measured a shipped configuration and shipped no behaviour.

One process note, because it nearly became a false finding. The first full run
of the suite reported **30 failures**, every one of them
`[Errno 2] No such file or directory: 'python'` from a sandbox subprocess — the
invocation had dropped the venv from `PATH`. Checked against a clean
`git archive c2ae339` export before concluding anything, which failed the
**identical 30** (`diff` of the sorted `FAILED` lines is empty). That is the
right answer for the wrong reason: the export shares the broken environment, so
"reproduces on the merge base" would have licensed calling an environment fault
a pre-existing defect. Re-run with `PATH=<repo>/.venv/bin:$PATH`, as this loop's
worker rules specify, the suite is green.

## Quota preflight

ADR 0150's corrected argv, run first as the loop requires:

```
rc 0  is_error: False  result: 'OK'  usage.input_tokens: 2
modelUsage: claude-haiku-4-5-20251001 {in 897, out 10}    <- the CLI's own side call
            claude-opus-5[1m]         {in 2,   out 4}     <- answered
```

**Calls: 103 of a budget of 110** — 1 preflight + 17 (a) + 51 (b, three repeats)
+ 34 (c, two repeats). Seeding cost **0** (train replayed from committed
cassettes); the boost sweep, the freshness bound and four dry-run arms cost 0.
Arm (d) was cut on ADR 0175's evidence that it sends arm (c)'s prompts byte for
byte, and its 51 calls are what paid for the four extra repeats.

## Artifacts

- `docs/research/i12c/seed.py` — the train replay, ADR 0180's producer, and the
  excerpt assertion (step 0).
- `docs/research/i12c/boost_sweep.py` — the static rank sweep that chose 3.0.
- `docs/research/i12c/arms.py` — one arm-repeat per invocation, the producer on
  the scored split, a JSONL line per scenario as it lands.
- `docs/research/i12c/leak_check.py` — the excerpt property on the live prompts.
- `docs/research/i12c/aggregate.py` — every table above and the rule's branch,
  computed from the raw JSON.
- `docs/research/i12c/results/` — `seed.json`, `boost_sweep.json`,
  `{a,b,c}_r*.json` (live, with every rendered draft prompt), `arms.jsonl`.

## Confidence

**High** that (c) beat (b) here on this corpus and this model: six live runs,
per-scenario scores recorded as they landed, prompt hashes pinned, and the
control arms' hashes byte-identical to the previous night's.

**High** that the layer engaged, and higher than S1b's: one entry, three source
runs, fifteen of seventeen prompts carrying it in both repeats, and the rank
trajectory recorded per scenario.

**Medium** on the size of the effect. +0.0529 clears this rig's own same-prompt
band (0.0353) by 1.5× and does not clear the band S1b measured on a smaller
subset (0.0857). Three repeats of one arm and two of the other, 17 scenarios
scored in fifths, one corpus, one agent, one failure family (a word cap).

**Low** on attribution between the two fixes. The excerpt and the staleness walk
were removed together and this run cannot say which mattered.

**None claimed** about `knowledge_boost`. Its own A/B was not run.
