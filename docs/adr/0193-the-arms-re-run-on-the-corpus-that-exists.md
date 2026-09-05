# ADR 0193: The arms re-run on the corpus that exists, and the knob answered for nothing

## Status

Accepted. Worker **N2** of `ABOVE_95_LOOP.md` — ADR 0184's four arms re-run on
the one-model corpus ADR 0186 produced, which is what ADR 0191 withdrew S1c's
`+2` for wanting.

**Model: `claude-opus-5[1m]`** (canonical `claude-opus-5`), the session
default. `--model` is deliberately absent from the argv so the session default
answers; the answering model was read back from `modelUsage` and is
`claude-opus-5[1m]` for **119 of 119** arm calls. **120 live calls** total
(1 preflight + 119 arms) against a budget of 120. Every number below was
produced on this branch, on this tree.

**Result: dimension 2 moves 12 → 14.** The pre-registered rule's first branch
fired: (c) − (b) = **+0.0470** on the mean against a larger repeat spread of
**0.0353**, and (c) is ahead of (b) on the eight owner-check negatives by
**+0.1167** against a 0.0250 spread. This is the same branch ADR 0184 reached
and it is not the same evidence: the corpus, the seed, the negatives, the boost
and the repeat structure all differ, and the margin is thinner (1.33× the bar,
against S1c's 1.5×).

**The knob's own A/B — never run in this programme — is answered here for zero
calls**, because arm (c) at the shipped default is arm (b) byte for byte and
arm (b) ran three times live.

## Why this run exists

ADR 0191 closed S1c's finding as **withdrawn, not disproved**:

> S1c's `+2` is **withdrawn**: its seed no longer reproduces after ADR 0186
> moved the corpus to one model.

ADR 0186 re-recorded eighteen scenarios on Opus **in the same hour**, on a
branch S1c never saw. Both workers were right about what they measured and the
tree underneath one of them moved. *A measurement that cannot be re-run on the
current tree is asserted* — the rubric's own first rule applied to a row of the
rubric. This increment re-runs it. Nothing here rehabilitates S1c's numbers;
they describe a corpus that no longer exists.

## Step 0 — the seed now, and how it differs from ADR 0184's

`docs/research/i12d/seed.py` is `docs/research/i12c/seed.py` with its docstring
rewritten and **not one line of its logic changed**. That is the point: the
same program, on the current tree, prints a different table. TRAIN is replayed
from each scenario's own cassette under `CassetteProvider(..., on_miss="fail")`,
so a changed prompt byte aborts rather than silently spending quota. **Zero
live calls.**

```
  sum-04-halden-reservoir:    0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-05-bramble-bakery:      0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-08-glasshouse-tomatoes: 0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-11-lantern-festival:    0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-22-marlowe-street:      0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  sum-25-hollin-bridge:       0.7500 check_failure=YES ['check:working_memory.summary:max_words']
  sum-26-netherby-clinic:     0.8000 check_failure=YES ['check:working_memory.summary:max_words']
  (the other 13 train scenarios: 1.0000, no check failure)

train scenarios: 20   live calls: 0 (cassette, on_miss='fail')
memory: 7 failure record(s), 20 success record(s)
EXCERPT PROPERTY (ADR 0180): 0 windows of 12 chars of any run's output found
  in any of the 27 record(s) derived from it
CONSOLIDATED: 1 knowledge entr(ies)
  failure:check:working_memory.summary:max_words  kind=failure runs=7
    conf=0.6364 since=1 tally=(h=0 x=0 xe=0)
```

| | S1c (ADR 0184) | N2 (here) |
|---|---|---|
| entries formed | 1 | **1** |
| signature | `failure:check:working_memory.summary:max_words` | **identical** |
| recurrence | 3 distinct runs (`sum-22`, `sum-25`, `sum-26`) | **7** (+ `sum-04`, `sum-05`, `sum-08`, `sum-11`) |
| confidence | 0.4286 | **0.6364** |
| `runs_since_last_seen` at seed | 2 | **1** |
| lesson text ends | `…observed 31 words, 208 chars` | **`…observed 37 words, 233 chars`** |
| owner-check negatives in VALIDATION | 4 | **8** |
| failure family | one (a word cap) | **one (a word cap)** |

**That table is why the `+2` was withdrawn.** Every one of those differences is
ADR 0186's Opus re-recording: on the identical prompt Opus wrote longer than
Fable in fourteen of eighteen scenarios and shorter in none, so four more train
scenarios and four more validation scenarios now fail the owner's word cap. The
layer's *shape* is unchanged — one entry, one signature, one failure family —
and every number attached to it moved.

`NEGATIVES` is therefore **derived and asserted** in this runner rather than
carried forward: `recorded_negatives()` reconstructs each scenario's recorded
final state from its own trace (`trace[-1].delta.apply(trace[-1].input_state)`)
and evaluates the owner's checks, and `arms.py` refuses to run if the derived
set differs from the eight written down. A hard-coded list is exactly how ADR
0184's numbers came to describe a tree that no longer existed.

## Step 1 — the knob's own A/B, run for zero calls

ADR 0184's own closing section named this as the next increment's cheapest
question and priced it at 34 live calls:

> The next dimension-2 increment's cheapest question is the knob's own A/B:
> (c) at 0.0 against (c) at 3.0, 34 calls, two repeats, everything else held.

It costs nothing, and here is why. `docs/research/i12d/dry_identity.py` runs the
whole sequential arm under a stub provider that records the rendered prompt
instead of sending it, and hashes them:

```
arm=a boost=0.0  hash=5956e7ffb9b0fcc9  entry_in_prompt= 0/17
arm=b boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17
arm=c boost=0.0  hash=c6873a50bb4572db  entry_in_prompt= 0/17   <- IS arm (b)
arm=c boost=3.0  hash=a7427ac0524ae6e0  entry_in_prompt= 4/17
arm=c boost=4.0  hash=bd92e98d844f2781  entry_in_prompt= 8/17
arm=c boost=5.0  hash=6bba02bc6997973a  entry_in_prompt=10/17
arm=c boost=6.0  hash=01b9836e72df8c14  entry_in_prompt=13/17
arm=c boost=7.0  hash=914814cfd2e35044  entry_in_prompt=16/17
arm=c boost=8.0  hash=c74f34b746ac1625  entry_in_prompt=17/17
```

**Arm (c) at `knowledge_boost=0.0` sends arm (b)'s prompts byte for byte on all
seventeen scenarios — one sha256, not a similar one.** So the arm that isolates
the knob at its shipped default is not a third measurement; it is arm (b) under
another name, and **arm (b) ran three times live**. The knob's A/B is therefore
`(b)` against `(c)@8.0`, which is the table below, at no extra cost.

The static sweep says the same thing from the other side, over the seeded store
and every validation objective, where rank is position among retrieved chunks
and `render_retrieved_context`'s `max_items=5` is what a model actually reads:

| `knowledge_boost` | median rank | rank range | in top-5 (of 17) |
|---|---|---|---|
| **0.0 (shipped)** | 21 | 20–23 | **0/17** |
| 0.5 | 20 | 0–20 | 5/17 |
| 1.0 | 0 | 0–8 | 11/17 |
| 3.0 … 8.0 | 0 | 0–0 | 17/17 |

**At the shipped default the only lesson in the store is invisible to the
model** — 0 of 17, on every scenario, by both instruments. ADR 0184 reported the
same identity on the pre-0186 corpus and it survives the re-recording.

### Why 8.0 and not 3.0

The static sweep is the BEST case: it holds the store at its seeded state, so
the entry never ages. The dry sequential run is the WORST case: the stub answers
a fixed 9-word string that never trips the word cap, so no scored run ever
refreshes the lesson and ADR 0116's staleness demotion walks it down
monotonically. **8.0 is the smallest value on a 1.0 grid that keeps the lesson
inside the model's five bullets in all seventeen scenarios even in the worst
case**, and it was chosen from the worst case, offline, before any quota — so
the arm engages whatever the live trajectory does. It did: 17/17 in every live
repeat, rank 0 at scenario 1 and rank 0 at scenario 17.

This is a deliberate departure from S1c, which ran at 3.0 and reported 2 of 17
prompts without the lesson as a confound. The cost of removing that confound is
stated under "what this does not license": 8.0 is a large thumb on a store
holding exactly one entry.

## Step 2 — the arms

Three arms, seventeen validation scenarios, **three repeats each of (b) and
(c)** — the symmetry S1c could not afford — scored by the same `score_scenario`
the gates use (ADR 0113). Raw JSON and a per-scenario JSONL written as each
scenario landed are in `docs/research/i12d/results/`.

| arm | repeat | boost | mean | negatives (n=8) | rest (n=9) | lesson in prompt | secs | draft-prompt sha256 |
|---|---|---|---|---|---|---|---|---|
| (a) no retrieve | 0 | – | 0.9529 | 0.9000 | 1.0000 | 0/17 | 46 | `5956e7ffb9b0fcc9…` |
| (b) raw records | 0 | – | 0.9412 | 0.8750 | 1.0000 | 0/17 | 45 | `c6873a50bb4572db…` |
| (b) raw records | 1 | – | 0.9412 | 0.8750 | 1.0000 | 0/17 | 45 | `c6873a50bb4572db…` |
| (b) raw records | 2 | – | 0.9294 | 0.8500 | 1.0000 | 0/17 | 46 | `c6873a50bb4572db…` |
| (c) + knowledge | 0 | 8.0 | 0.9647 | 0.9750 | 0.9556 | **17/17** | 82 | `3276d25ef3b0f2f8…` |
| (c) + knowledge | 1 | 8.0 | 1.0000 | 1.0000 | 1.0000 | **17/17** | 92 | `bf42e44e65ab8213…` |
| (c) + knowledge | 2 | 8.0 | 0.9882 | 0.9750 | 1.0000 | **17/17** | 75 | `992f4fa406f4eed7…` |

**Arm (a)'s and arm (b)'s prompt hashes are byte-identical to S1b's and S1c's**
(`5956e7ff…`, `c6873a50…`) even though eighteen scenarios were re-recorded
underneath them. That is the cross-check that three nights' control arms are the
same experiment: the re-recording changed what the model *answered*, and neither
control arm renders anything derived from an answer into the five bullets a
model reads.

| arm | repeats | mean | repeat spread | negatives | neg spread | calls |
|---|---|---|---|---|---|---|
| (a) no retrieve | 1 | 0.9529 | – | 0.9000 | – | 17 |
| (b) raw records | 3 | **0.9373** | **0.0118** | 0.8667 | 0.0250 | 51 |
| (c) + knowledge @ 8.0 | 3 | **0.9843** | **0.0353** | 0.9833 | 0.0250 | 51 |

| scenario | (a) | (b) | (c) | lesson in (c)'s prompt |
|---|---|---|---|---|
| `sum-13-cider-press` **NEG** | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-14-quarry-lake` **NEG** | 0.80 | 0.80 | 1.00 | 3/3 |
| `sum-15-bookbinder` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-16-cliff-path` **NEG** | 1.00 | 0.87 | 1.00 | 3/3 |
| `sum-17-clockmaker` **NEG** | 0.80 | 1.00 | 1.00 | 3/3 |
| `sum-18-heron-rookery` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-29-brindle-viaduct` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-30-ganister-tarn` **NEG** | 1.00 | 0.93 | 1.00 | 3/3 |
| `sum-31-quernmore-kiln` | 1.00 | 1.00 | 0.93 | 3/3 |
| `sum-32-hessle-mills` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-33-cotterdale-bus` **NEG** | 1.00 | 0.87 | 1.00 | 3/3 |
| `sum-34-alder-carr` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-35-priory-gatehouse` **NEG** | 0.80 | 0.80 | 0.87 | 3/3 |
| `sum-36-larkfield-quarry` **NEG** | 0.80 | 0.67 | 1.00 | 3/3 |
| `sum-37-ryhope-pool` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-38-bewick-refusals` | 1.00 | 1.00 | 1.00 | 3/3 |
| `sum-39-coldbeck-society` | 1.00 | 1.00 | 0.93 | 3/3 |

| comparison | delta (mean) | delta (negatives) |
|---|---|---|
| (b) − (a) — raw retrieval vs none | **−0.0156** | −0.0333 |
| **(c) − (b) — knowledge vs raw records** | **+0.0470** | **+0.1167** |
| (c) − (a) — knowledge vs no retrieval | +0.0314 | +0.0833 |

### What arm (b) actually put in front of the model

This is the whole lesson block of arm (b) r0 at `sum-13`, and at `sum-36` —
fourteen scenarios later, after thirteen more runs of experience:

```
Lessons from this agent's earlier runs (most relevant first):
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
```

Five byte-identical bullets carrying no information, in both. Seven records
describing a real, recurring word-cap failure sat in the same store and none of
them reached the model, because twenty near-identical success records out-ranked
them and `render_retrieved_context` renders five. **This is ADR 0110's crowding
thesis — "near-duplicate records about one recurring failure crowd out every
other lesson" — visible in a live prompt rather than in a coverage proxy**, and
it is the mechanism behind (b) − (a) = −0.0156 as much as behind (c) − (b) =
+0.0470. Arm (c)'s block is the same five bullets with the first replaced by the
consolidated lesson:

```
Lessons from this agent's earlier runs (most relevant first):
- [failure:check:working_memory.summary:max_words] 1 error(s) recorded; 0/0 tool
  call(s) failed. errors[0]: check failed: working_memory.summary is longer than
  the owner's maximum; observed 37 words, 233 chars
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
  (×4 more)
```

One bullet of the five. That is the entire difference between the two arms.

### The excerpt property, on the live prompts

`docs/research/i12d/leak_check.py`, ADR 0180's property asked one layer out: did
any run's own summary reach a later run's rendered lesson block?

| arm | repeats | later prompts carrying a lesson block | leaked windows |
|---|---|---|---|
| (a) | 1 | 0/17 | **0** |
| (b) | 3 | 17/17 each | **0** |
| (c) | 3 | 17/17 each | **0** |

**0 leaked 12-character windows across 119 live lesson blocks.** (The scanner's
first version, corrected in ADR 0184, scanned whole prompts and fired 28 times
on the arm with no retrieve node at all; it scans only the lesson block, which
is the only path an earlier output can travel.)

### The rank trajectory, and an off-by-one that is now closed

ADR 0184 reported as its defect 1 that `runs_since_last_seen` "floors at 1,
never 0", and that six of seventeen scored scenarios could not refresh a lesson
at all because `run_scenario` stamped `created_at=scenario.recorded_at`. ADR
0191's F4 changed the shipped path to stamp `datetime.now(UTC)`, and this
runner's copy tracks it. Visible in the live logs:

```
b/sum-14 … since=2  wrote_failure=['…max_words']
b/sum-15 … since=0  occ=8
```

`runs_since_last_seen` reaches **0** — the floor is gone — and the refresh
happens on the run that reproduced the failure rather than never. In arm (c) at
boost 8.0 the entry held rank 0 in all 17 scenarios of all three repeats, so the
trajectory no longer decides anything here; on a corpus where the entry sits
near the render cap it decides whether a lesson is read at all.

## The pre-registered decision rule

Stated in the worker's brief before any live call, and evaluated by
`docs/research/i12d/aggregate.py` rather than by hand:

> dim 2 moves 12 → 14 ONLY if (c) > (b) on the mean by more than the larger
> repeat spread AND (c) ≥ (b) on the negatives. 12 → 13 if the negatives alone
> clear it. (c) ≤ (b) → +0, and the ADR states that the knowledge layer does not
> help this agent on this corpus.

```
    (c) − (b) on the mean       = +0.0470
    larger repeat spread        =  0.0353
    (c) − (b) on the negatives  = +0.1167
    larger negatives spread     =  0.0250

    BRANCH: 12 -> 14
```

Both clauses hold. The mean delta clears the bar by **1.33×** — thinner than
S1c's 1.5×, and the bar is (c)'s own spread rather than (b)'s this time, which
is the harder of the two available choices and is what the rule specifies.

### The noise bar, from equal samples

| arm | distinct prompt hashes | mean spread | scenarios whose score differed across repeats |
|---|---|---|---|
| (a) no retrieve | 1 | – | – |
| (b) raw records | **1** | 0.0118 | **4/17** |
| (c) + knowledge @ 8.0 | 3 | 0.0353 | 3/17 |

Arm (b)'s three repeats sent **byte-identical prompts**, so its 0.0118 is a true
same-prompt live variance on the full 17-scenario split — three times tighter
than S1c measured on the pre-0186 corpus (0.0353).

**Arm (c)'s three repeats are NOT a same-prompt sample** — three distinct hashes
— and that is a consequence of the producer being on the scored split rather
than a flaw in the rig: whether a lesson is fresh depends on whether the model
failed a check, so what the model is shown depends on what the model previously
said. (c)'s spread is a *repeat* spread, which is the right instrument for the
rule and a weaker one for noise. The rule takes the larger, which is (c)'s.

Under S1b's imported instrument — a same-prompt band of **0.0857** measured on a
7-scenario subset — this delta does not clear the bar and dimension 2 does not
move. That comparison is recorded, as it was in ADR 0184, so a reader can apply
their own instrument: the spread of a mean shrinks with n, this is a
17-scenario mean, and 0.0118 / 0.0353 are what three repeats of it actually
produced.

### (b) − (a) = −0.0156: raw retrieval is still not shown to help

Fourth measurement of this comparison: 0.0000 (ADR 0155), +0.0235 (ADR 0175),
−0.0117 (ADR 0184), **−0.0156** here. The sign has now changed twice and the
magnitude has never cleared a noise bar. Wiring retrieval of raw records into
the prompt is a capability; that it improves this task remains unclaimed, and
the lesson block above shows why it might not. What (c) − (b) says is that
**consolidation** is the part that pays.

## The configuration fix — ADR 0184's defect 2, closed

ADR 0184 reported and could not fix (no file under `aef/` was its to touch):

> `knowledge_boost`, `staleness_half_life` and `knowledge_min_occurrences` are
> unreachable from `aef.yaml`. […] Fixing that surface belongs before arguing
> about its default.

`ContextConfig` carried `impl` and `token_budget`; `build_retriever` passed
`max_token_budget` and nothing else. So the configuration this measurement runs
at — a `MemoryRetriever` with `knowledge_boost=8.0` — could not be expressed by
an adopter at all, and neither could ADR 0110's or ADR 0116's measured defaults
be deliberately changed. The knob was reachable only by hand-constructing
`Services`, which is the shape ADR 0101 deleted `GraphStore` for.

All three are now `aef.yaml` fields:

```yaml
context:
  impl: memory
  token_budget: 8000
  knowledge_boost: 8.0          # ADR 0110's default is 0.0; this ADR measures 8.0
  staleness_half_life: 5        # ADR 0116
  knowledge_min_occurrences: 2
```

**Unset means `None`, and `build_retriever` OMITS an unset field** rather than
passing a literal, so `MemoryRetriever`'s dataclass defaults remain the single
source of every measured default. A measured default written down twice is two
numbers that must agree with nothing checking that they do (ADR 0091). `None`
rather than a falsy check because `staleness_half_life: 0` is meaningful — it
disables the demotion (ADR 0116) — and a falsy check would silently restore 5
for an owner who deliberately turned it off. Each field's validator mirrors
`MemoryRetriever.__post_init__`'s refusal at config-load time, which is
`CommandProviderConfig`'s rule (ADR 0154).

**Tests** (`tests/config/test_context_knobs.py`, +6): the three knobs reach the
retriever; the shipped defaults are asserted against `MemoryRetriever`'s own
dataclass fields rather than against numbers typed in the test, so the config
layer cannot acquire a private copy that drifts; the three refusals fire at load
time; and `0` is not treated as unset.

**Mutations, four, each caught:**

| mutation | test that failed |
|---|---|
| `if config.staleness_half_life:` instead of `is not None` | `test_zero_disables_the_staleness_demotion_and_is_NOT_treated_as_unset` |
| drop `**knobs` from the `MemoryRetriever(...)` call | `test_the_three_knobs_reach_the_retriever_from_the_config` (+ the zero test) |
| `knowledge_boost: float = 8.0` in the retriever | `test_the_shipped_defaults_are_the_measured_ones…` **and** ADR 0110's own `test_the_shipped_boost_default_is_the_measured_one` |
| delete the `knowledge_boost` validator | `test_an_invalid_knob_is_refused_at_config_load_time[knowledge_boost…]` |

Every file restored byte-identically, verified by `shasum -a 256 -c`.

## What this does and does not license about `knowledge_boost`

**The shipped default is NOT changed. It stays 0.0**, and the reason is narrower
and more uncomfortable than any previous statement of it.

What is now measured, on this corpus, on the task metric:

- at **0.0** the layer is **inert** — the one lesson never reaches the model,
  0/17 by two independent instruments, and the arm is arm (b) byte for byte;
- at **8.0** it is worth **+0.0470** on the mean and **+0.1167** on the
  negatives against that byte-identical control.

So the knob is the difference between a layer that reaches the model and one
that does not, and calling it "a knob that buys nothing" — ADR 0110's finding,
which was about *coverage* — would now be false on the task metric.

It stays 0.0 anyway, for three reasons stated rather than felt:

1. **8.0 was chosen to guarantee engagement on a store holding exactly ONE
   entry.** The multiplier is `1 + knowledge_boost * confidence`, so with fifty
   entries the same 8.0 puts all fifty above every raw record. ADR 0110 measured
   a raised boost walking a stale, loosely-related entry from 0.200 to 0.745
   against a 0.833 precisely-relevant record at boost 3. This corpus cannot
   reproduce that failure mode because it cannot produce a second entry.
2. **The benefit is not attributed between ranking and consolidation.** (c) −
   (b) is measured with the boost at 8.0 throughout; no arm holds the layer
   fixed and varies only the coefficient at a value where both settings show the
   entry. The knob's A/B answered here is *inert vs engaged*, which is a
   different question from *how much thumb*.
3. Making 8.0 the default for every adopter on the evidence of one corpus, one
   agent and one failure family is the substitution this repo's ADRs keep
   catching.

What changes instead is that **an adopter who reads this ADR can now act on it**
— one line in `aef.yaml` — which was the actual blocker and is fixed above.
`tests/services/knowledge/test_ab_coverage.py::test_the_shipped_boost_default_is_the_measured_one`
is untouched and still passes.

**What would move the default:** a corpus that forms more than one knowledge
entry, on which a sweep of the boost shows the same sign on the task metric
*and* no measured displacement of a precisely-relevant record. That is a
corpus-building increment, not a knob increment.

## Consequences

- **Rubric: dimension 2 moves 12/20 → 14/20.** One row prepended, heading
  69 → 71, recomputed by `tests/test_rubric_arithmetic.py` from the rows rather
  than carried by hand.
- **ADR 0191's withdrawal is discharged.** The `+2` is re-earned on the tree
  that exists, by a re-run rather than by an argument. The withdrawal itself
  stands as correct: S1c's numbers still do not reproduce, and this ADR's step-0
  table is the evidence of how far they were from doing so.
- **ADR 0184's defect 1 is closed by ADR 0191's F4 and confirmed here**:
  `runs_since_last_seen` reaches 0 on the run that reproduces the failure.
- **ADR 0184's defect 2 is closed**: the three knobs are `aef.yaml` fields with
  one copy of each default.
- **ADR 0184's defects 3, 4 and 5 stand.** They are restated below because a
  defect reported twice and fixed neither time is a defect nobody owns.
- **ADR 0110's crowding thesis has its first live-prompt evidence**, and it is
  not a coverage proxy: five byte-identical no-op bullets in arm (b)'s prompt at
  every scenario.
- **`knowledge_boost` stays 0.0**, with the basis restated: not "the knob buys
  nothing measurable", but "the knob is the difference between inert and engaged
  on a one-entry store, and 8.0 has not been shown safe on a many-entry one".

## Defects and findings standing after this worker

Reported, not fixed. The only files under `aef/` this worker modified are
`aef/config/schema.py` and `aef/config/factory.py`, for the field set above.

1. **`run_scenario` still cannot express the arms** (ADR 0184's defect 3,
   unchanged). ADR 0191's F4 corrected the timestamp it stamps, not the wiring:
   it builds its own `agent_services` with a throwaway `InMemoryMemoryStore()`,
   no knowledge store and no retriever, so the arms' single degree of freedom —
   what the retriever may read — is not expressible through it, and it serves
   model calls from the scenario's cassette, which every arm-(b)/(c) prompt
   misses by construction. `docs/research/i12d/arms.py` therefore copies
   `run_scenario`'s producer block argument for argument, which is recorded in
   its docstring so the two cannot drift silently. **An adopter running `aef loop
   score --memory` gets the producer and never the retrieval it feeds.**
2. **The consolidation lag** (ADR 0184's defect 4, unchanged). A graph's
   `consolidate` node is the last node of the current run, so a record written
   after scoring is first consolidated at the end of the *next* run — after that
   run has already retrieved. This runner consolidates immediately after
   `record_check_outcomes` to remove the one-scenario lag; a real `aef loop score
   --memory` does not, and its lessons are one scenario staler than they need to
   be.
3. **`render_retrieved_context(max_items=5)` is still the real budget**, not
   `context_budget_tokens` (ADR 0175's finding 3, ADR 0184's defect 5,
   unchanged): 27–49 chunks were admitted under an 8000-token budget that never
   bound, and a constant five decided what the model saw. Every result in this
   ADR is a result about that constant five.
4. **This corpus cannot produce a second knowledge entry**, and three ADRs have
   now measured the knowledge layer on a store holding exactly one. Everything
   about ranking *between* entries — the boost's real risk — is unmeasurable
   here. Named as the next dimension-2 increment.

## Green bar

```
pytest -q                 2891 passed, 7 skipped, 1 xfailed
mypy aef examples         Success: no issues found in 135 source files
ruff check .              All checks passed!
ruff format --check aef tests examples docs/research/i12d   All checks passed
```

## Quota preflight

ADR 0150's corrected argv, run first as the loop requires:

```
rc 0  is_error: False  result: 'OK'  usage.input_tokens: 2
modelUsage: claude-haiku-4-5-20251001 {in 898, out 11}    <- the CLI's own side call
            claude-opus-5[1m]         {in 2,   out 4}     <- answered
```

**Calls: 120 of a budget of 120** — 1 preflight + 17 (a) + 51 (b, three repeats)
+ 51 (c, three repeats). Seeding cost **0** (train replayed from committed
cassettes); the static boost sweep, the nine dry arms and the knob's own A/B cost
**0**. Arm (d) was cut on ADR 0175's evidence that it sends arm (c)'s prompts
byte for byte, and (c)'s third repeat — the symmetry S1c could not buy — is what
its calls paid for.

## Artifacts

- `docs/research/i12d/seed.py` — the train replay, ADR 0180's producer, and the
  excerpt assertion (step 0).
- `docs/research/i12d/boost_sweep.py` — the static rank sweep, 0.0 … 8.0.
- `docs/research/i12d/dry_identity.py` — nine offline arms; the knob's A/B and
  the choice of 8.0.
- `docs/research/i12d/arms.py` — one arm-repeat per invocation, derived
  negatives, the producer on the scored split at execution time, a JSONL line per
  scenario as it lands.
- `docs/research/i12d/leak_check.py` — the excerpt property on the live prompts.
- `docs/research/i12d/aggregate.py` — every table above and the rule's branch,
  computed from the raw JSON.
- `docs/research/i12d/results/` — `seed.json`, `boost_sweep.json`, `dry/`,
  `{a,b,c}_r*.json` (live, with every rendered draft prompt), `arms.jsonl`.

## Confidence

**High** that (c) beat (b) here, on this corpus and this model: seven live
arm-repeats, per-scenario scores written as they landed, prompt hashes pinned,
and the control arms' hashes byte-identical to two previous nights'.

**High** that the layer engaged: one entry, seven source runs, rank 0 in 17 of
17 scenarios in all three repeats.

**High** that (c)@0.0 is (b): one sha256 over all seventeen rendered prompts,
plus a static sweep that never puts the entry inside the render cap.

**Medium** on the size of the effect. +0.0470 clears this rig's own bar (0.0353)
by 1.33× and does not clear S1b's 0.0857. Three repeats of each arm, 17
scenarios scored in fifths, one corpus, one agent, one failure family — a word
cap — and a validation split whose eight negatives are eight instances of that
one family.

**Low** on generalisation of the boost. 8.0 is measured on a store with exactly
one entry and says nothing about a store with fifty, which is why the default
does not move.

**None claimed** about which of consolidation and ranking the +0.0470 belongs
to. No arm holds the layer fixed and varies only the coefficient at a value
where the entry is visible at both settings.
