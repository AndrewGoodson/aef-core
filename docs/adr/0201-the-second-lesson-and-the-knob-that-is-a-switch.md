# ADR 0201: The second lesson, and the knob that turns out to be a switch

## Status

Accepted. Worker **P2** of `TO_95_LOOP.md` — the increment ADR 0193 named as
the next one, in the sentence it closed on:

> **This corpus cannot produce a second knowledge entry**, and three ADRs have
> now measured the knowledge layer on a store holding exactly one. Everything
> about ranking *between* entries — the boost's real risk — is unmeasurable
> here. Named as the next dimension-2 increment.

**Model: `claude-opus-5[1m]`** (canonical `claude-opus-5`), the session
default. `--model` is deliberately absent from the argv so the session default
answers; it was read back from `modelUsage` and is `claude-opus-5[1m]` for
**105 of 105** arm calls. **120 live calls** against a budget of 140: 1
preflight, 14 scenario recordings, 105 arms. Every offline step — the rule
screen, the seed, the static boost sweep, twenty-one dry arms, the leak scan
and the aggregation — cost **zero**.

**Result: dimension 2 moves 14 → 17.** The store now holds **three** lessons,
and with all three in front of the model the mean is **0.9547 against arm (b)'s
0.9107** — `+0.0440` against a larger repeat spread of `0.0191`, 2.30× the bar
— and `+0.0975` on the ten owner-check negatives. The mechanism is visible
rather than inferred: **word-cap failures go from 8, 8 and 6 across the control
repeats to 0 and 0** in the knowledge arm.

**And the knob does not become the default**, even though the trigger this
worker pre-registered for moving it fired. §6 is that decision, stated as a
departure from its own pre-registration rather than smuggled past it.

---

## 1. What had to exist first: a second failure signature

`consolidate.default_signature` keys a check-derived failure on the joined
`check:<path>:<op>` of every check that failed. All fifteen of this corpus's
recorded failures were `check:working_memory.summary:max_words`. One key, one
signature, one lesson — for four ADRs.

The term checks that already use `regex` on that same field had **never
failed**: 39 of 39. ADR 0171 said why, and said it as a finding rather than an
aside — nineteen scenarios recorded against inputs chosen to be handled badly,
and *"all seven negatives are word-cap overruns. Every content trap was handled
correctly."*

### The screen — six candidate rules, offline, zero calls

`docs/research/i12e/screen.py` evaluates candidate owner rules of one shape —
*when the passage carries X, the summary must carry X* — against the
thirty-nine recordings that already exist. Re-derived by `make measure`:

| candidate | applies | fails | rate |
|---|---|---|---|
| money written with the £ symbol | 6 | 2 | 33% |
| the month is carried | 18 | 4 | 22% |
| **attribution is carried (Rule A)** | **9** | **9** | **100%** |
| the year is carried | 12 | 2 | 17% |
| the percentage is carried | 2 | 0 | 0% |
| the weekday is carried | 5 | 0 | 0% |

**Rule A**, then, as `docs/research/i12e/scenarios.py` states it before any of
its scenarios was recorded:

> When the passage states a forward-looking or contested claim and attributes
> it to an interested party in so many words ("the operator says…", "the
> council says…"), the summary may not present that claim as established fact.
> It must carry an attribution marker.

One constant regex, the same on every scenario, nothing tuned per passage.

This agent has never once carried an attribution through a summary. Three of
the nine are not omissions but launderings — the passage says *"the trust says
signage will be in place from the first of the month"* and the summary says
*"signage from the month's start"*; *"the operator says signalling commissioning
is the outstanding item"* becomes *"pending signalling commissioning"*; *"its
owner says talks … are at an early stage"* becomes *"the mill's sale talks
continue elsewhere"*.

### The disclosure, and the objection it does not answer

**Rule A was chosen because it fails.** That is ADR 0192's disclosure rule
applied to this increment, and a reader is entitled to hold it against the
result. Two things are offered and neither is a refutation:

1. The rule is not shaped to a subset — it fires wherever its precondition
   holds and fails 9 of 9, which is a property of the agent rather than of a
   check written to catch two particular answers.
2. **It is applied to no existing scenario.** The nine that motivated it keep
   the checks they were recorded under, so ADR 0193's baseline is untouched and
   its control arms stay comparable. Rule A is carried only by fourteen
   scenarios whose checks were written, in a committed file, **before** their
   first live call — ADR 0171's "strongest available order", and the only order
   under which a 100% base rate is a prediction rather than a description.

What is still disputable, and is not disposed of: the summaries Rule A fails
are not *wrong*. An owner who thinks a summary may compress "the trust says X
will happen" to "X happens" would delete this rule, and the second lesson with
it.

## 2. The fourteen scenarios, and the cap calibrated twice in the open

`sum-40` … `sum-53`: ten train, four validation, in the corpus's register, each
with exactly one attributed forward-looking claim. Checks per scenario in the
owner's declared order — the term regexes, Rule A, `max_words`, `min_words: 1`.

The cap took two corrections, both recorded in `scenarios.py` rather than
quietly applied:

| draft | passage | cap | what came back |
|---|---|---|---|
| 1 | 66 words | 34 | `sum-40` wrote **36** — over |
| 2 | 62–68 words | 40 | `sum-41`…`sum-45` wrote **44, 41, 43, 45, 43** — five of five over |
| 3 | 48–52 words | 40 | `sum-46`…`sum-53` wrote **36–41** — seven of eight under |

The finding inside that table is worth more than the calibration: **on a
62–68-word passage this agent writes ~0.65 of the source regardless of what the
cap says, and a roomier cap does not help.** Only shortening the passage does.

Why it had to be got right: a run that fails Rule A *and* the cap keys on
`check:…:regex>check:…:max_words`, a third signature. Nothing was re-recorded
to make that go away — the six long scenarios are kept, they are honest
recordings, and what they produce is a third lesson.

## 3. Three lessons (`seed.py`, zero live calls)

```
train scenarios: 30   live calls: 0 (cassette, on_miss='fail')
memory: 17 failure record(s), 30 success record(s)
EXCERPT PROPERTY (ADR 0180): 0 windows of 12 chars of any run's output found
  in any of the 47 record(s) derived from it
CONSOLIDATED: 3 knowledge entr(ies)
```

| signature | short | distinct runs | confidence | `runs_since_last_seen` at seed |
|---|---|---|---|---|
| `failure:check:working_memory.summary:regex` | **ruleA** | 4 | 0.5000 | 0 |
| `failure:check:…:regex>check:…:max_words` | **both** | 6 | 0.6000 | 4 |
| `failure:check:working_memory.summary:max_words` | **cap** | 7 | 0.6364 | 11 |

The two new ones are different signatures, not the same one twice, and each
clears ADR 0110's two-distinct-runs threshold on its own evidence. `ruleA` is
`sum-50`, `sum-51`, `sum-52`, `sum-53`; `both` is `sum-40`…`sum-45`; `cap` is
ADR 0193's seven, unchanged.

The validation split gains two negatives that are **not** word-cap overruns —
`sum-46` (Rule A alone) and `sum-47` (Rule A and the cap) — taking the scored
split to 21 scenarios and 10 negatives.

## 4. The arms

Four, `docs/research/i12e/arms.py`, one arm-repeat per invocation, per-scenario
JSONL written as each landed, and the pre-registered rule in
`docs/research/i12e/prereg.txt`, committed before the first live call.

| arm | retriever | knowledge | boost | repeats | live calls |
|---|---|---|---|---|---|
| (a) | none | – | – | 1 | 21 |
| (b) | `MemoryRetriever` | not attached | – | 2 | 42 |
| (c) | `MemoryRetriever` | attached | **0.0 (shipped)** | 2 | **0** |
| (d) | `MemoryRetriever` | attached | 16.0 | 2 | 42 |

### Arm (c) costs nothing, and is not skipped

`dry_identity.py` hashes every rendered prompt of every arm offline. **(c) at
the shipped `knowledge_boost=0.0` and (b) produce ONE sha256 over all
twenty-one prompts** — `28501c05e2af051f…` — and the live control arm produced
that same hash, twice. So (c) is (b) byte for byte, on a three-entry store as
it was on ADR 0193's one-entry store. Its two repeats are (b)'s two repeats;
reporting them as a separate arm would be reporting one experiment twice.

**"Ranking off" is therefore not a configuration in which lessons compete. It
is a configuration in which no lesson reaches the model at all.**

### Why 16.0, and the number that did not transfer

Chosen offline, before quota, from the WORST case, exactly as ADR 0193 chose
8.0: `dry_identity.py` runs the whole sequential arm under a stub whose fixed
answer refreshes no lesson, so ADR 0116's staleness demotion walks all three
down monotonically. On a 1.0 grid:

| boost | `ruleA` in prompt | `both` | `cap` | all three |
|---|---|---|---|---|
| 0.0 (shipped) | 0/21 | 0/21 | 0/21 | 0/21 |
| 2.0 | 21/21 | 0/21 | 0/21 | 0/21 |
| 4.0 | 21/21 | 2/21 | 0/21 | 0/21 |
| **8.0 (ADR 0193's value)** | 21/21 | 10/21 | **7/21** | 7/21 |
| 12.0 | 21/21 | 21/21 | 18/21 | 18/21 |
| **16.0** | **21/21** | **21/21** | **21/21** | **21/21** |

It saturates: 16, 17 and 18 give the identical prompt hash.

**8.0 was the smallest value that engaged the one lesson of ADR 0193's store,
and on this store it engages the freshest lesson always and the stalest one in
a third of scenarios.** The value that engages a store is a function of how
many lessons it holds and how stale they are. That single row is the strongest
thing this ADR has to say about `knowledge_boost` as a global default, and §6
acts on it.

### The results

| arm | repeat | boost | mean | negatives (n=10) | rest (n=11) | lessons in prompt | prompt sha256 |
|---|---|---|---|---|---|---|---|
| (a) no retrieve | 0 | – | 0.9000 | 0.8100 | 0.9818 | none | `20fddf3da03a57fa` |
| (b) raw records | 0 | – | 0.9095 | 0.8500 | 0.9636 | none | `28501c05e2af051f` |
| (b) raw records | 1 | – | 0.9119 | 0.8350 | 0.9818 | none | `28501c05e2af051f` |
| (c) = (b) | 0 | 0.0 | 0.9095 | 0.8500 | 0.9636 | none | `28501c05e2af051f` |
| (c) = (b) | 1 | 0.0 | 0.9119 | 0.8350 | 0.9818 | none | `28501c05e2af051f` |
| (d) + knowledge | 0 | 16.0 | 0.9452 | 0.9300 | 0.9591 | **all three, 21/21** | `7d3eb9aeb6a18084` |
| (d) + knowledge | 1 | 16.0 | 0.9643 | 0.9500 | 0.9773 | **all three, 21/21** | `93a8b5903df3b169` |

| arm | repeats | mean | repeat spread | negatives | neg spread | live calls |
|---|---|---|---|---|---|---|
| (a) no retrieve | 1 | 0.9000 | – | 0.8100 | – | 21 |
| (b) raw records | 2 | **0.9107** | **0.0024** | 0.8425 | 0.0150 | 42 |
| (c) + knowledge @ 0.0 | 2 | **0.9107** | 0.0024 | 0.8425 | 0.0150 | **0** |
| (d) + knowledge @ 16.0 | 2 | **0.9547** | **0.0191** | 0.9400 | 0.0200 | 42 |

| comparison | delta (mean) | delta (negatives) |
|---|---|---|
| (b) − (a) — raw retrieval vs none | +0.0107 | +0.0325 |
| **(c) − (b) — ranking off vs raw records** | **+0.0000** | **+0.0000** |
| **(d) − (c) — the knob, on a store where lessons compete** | **+0.0440** | **+0.0975** |
| (d) − (b) | +0.0440 | +0.0975 |
| (d) − (a) | +0.0547 | +0.1300 |

### Which lesson reached which prompt — the column that could not be asked

Every scenario, both repeats, arm (d): **`ruleA` at rank 0, `both` at rank 1,
`cap` at rank 2**, in the five bullets, 21 of 21, in each repeat. Arms (a),
(b) and (c) carried none, anywhere.

That constancy is itself a finding. The order among the three entries is the
same on every one of twenty-one different objectives, so **the boost is not
ranking lessons against the query at all** — the order is set by confidence and
by ADR 0116's freshness factor, and the knob scales all three together against
the raw records. `boost_sweep.py`, the static best case, says the same thing
from the other side: the order `ruleA < both < cap` holds at 0.0, 1.0, 2.0,
4.0, 8.0, 12.0 and 16.0 without a single inversion.

**`knowledge_boost` is a switch — lessons reach the model, or they do not —
and not a ranking control.** Between-lesson order belongs to staleness and
confidence. Three previous ADRs called this knob a ranking knob, this one
included until the table above was printed.

### The mechanism, in the failures rather than the mean

| arm | repeat | word cap only | Rule A only | both | clean |
|---|---|---|---|---|---|
| (a) no retrieve | 0 | **8** | 2 | 0 | 11 |
| (b) raw records | 0 | **8** | 1 | 0 | 12 |
| (b) raw records | 1 | **6** | 1 | 1 | 13 |
| (d) + knowledge @ 16.0 | 0 | **0** | 5 | 0 | 16 |
| (d) + knowledge @ 16.0 | 1 | **0** | 3 | 0 | 18 |

The word cap is not overrun once in forty-two scored runs with the lessons in
the prompt, and is overrun twenty-two times in sixty-three without them. The
`+0.0440` is that, and it is legible.

The residue is Rule A, and the honest note about it: **the Rule A lesson is
close to unactionable by construction.** ADR 0174 strips the check's expected
value from the record, so the bullet reads *"working_memory.summary does not
match the pattern the owner declared; observed 36 words, 228 chars"* — it names
the field and the operator and not the requirement. The word-cap lesson is
actionable because "longer than the owner's maximum" is self-describing. A
substring lesson is not. Arm (d) still failed Rule A five times and three
times; that is the layer's ceiling on this family and the reason the mean did
not go to 1.0.

### A harm, reported

`sum-48-marsden-gate-quarry` scored 1.00 in (a) and (b) and **0.75 in (d)**. It
had been passing Rule A for the wrong reason — its answer contained "reported",
belonging to a different party in the same sentence — and the rewritten answer
in arm (d) lost the word. The lessons made a passing scenario fail. One
scenario of twenty-one, and it is in the table above rather than in a footnote.

### The pre-registered rule

```
    knowledge entries seeded    =  3
    (d) − (b) on the mean       = +0.0440
    larger repeat spread (BAR)  =  0.0191
    (d) − (b) on the negatives  = +0.0975
    larger negatives spread     =  0.0200

    BRANCH: 14 -> 17
```

Both clauses hold, by 2.30× on the bar. Under S1b's imported instrument — a
same-prompt band of 0.0857 measured on a 7-scenario subset — this delta does
not clear the bar and dimension 2 does not move. That comparison is recorded,
as ADR 0184 and ADR 0193 recorded it, so a reader can apply their own
instrument. Arm (b)'s two repeats sent byte-identical prompts and their spread
is **0.0024** on a 21-scenario mean; arm (d)'s repeats are not a same-prompt
sample (the producer is on the scored split, so what the model is shown depends
on what the model previously said), and the rule takes the larger of the two,
which is (d)'s.

### The excerpt property, on the live prompts — and a false positive in it

`leak_check.py`, ADR 0180's property asked of the rendered lesson block:

| arm | repeat | later prompts carrying a lesson block | raw window hits | from a run's own output |
|---|---|---|---|---|
| (a) | 0 | 0/21 | 0 | **0** |
| (b) | 0, 1 | 21/21 each | 0 | **0** |
| (d) | 0 | 21/21 | 0 | **0** |
| (d) | 1 | 21/21 | 4 | **0** |

The four raw hits are all the same twelve-character window, `'er than the '`,
and they are **not a leak**: that window lives inside the harness's own fixed
phrase *"is longer than the owner's maximum"*, which is in every word-cap
lesson bullet, and `sum-39`'s answer in that repeat happened to contain "rather
than the". The discriminator is reproducible offline — the same window is in
arm (d) repeat 0's lesson blocks, where that repeat's `sum-39` answer does not
contain it at all. `leak_check.py` now subtracts the windows of the producer's
own vocabulary and prints **both** counts, so a reader can apply either.

**This is a defect in the instrument, found by running it**: ADR 0180's
12-character window property is a lower bound with a known false-positive mode,
and it fires the moment a lesson bullet and a summary share a common English
fragment. It was invisible while every lesson said "no failure signals".

## 5. What this says about raw retrieval, for the fifth time

(b) − (a) = **+0.0107**, inside (b)'s own repeat spread's order of magnitude
and far inside the negatives' spread. Fifth measurement of that comparison:
0.0000 (ADR 0155), +0.0235 (0175), −0.0117 (0184), −0.0156 (0193), **+0.0107**
here. The sign has changed three times and the magnitude has never cleared a
noise bar. And the reason is unchanged and visible: arm (b)'s lesson block at
every scenario is five bullets of `- [success] no failure signals: 0 error(s)
recorded, 0 tool call(s), none failed`, while seventeen real failure records
sit in the same store out-ranked by thirty near-identical successes.

## 6. The knob: the trigger fired and the default does not move

`prereg.txt`, committed before the first arm call, says:

> `knowledge_boost`'s shipped default moves from 0.0 to 16.0 ONLY IF (d) − (c)
> on the mean > BAR, and a test then pins the shipped value to the measured
> one.

**(d) − (c) = +0.0440 > 0.0191. The trigger fired. The default stays 0.0.**

That is a departure from what the pre-registration plainly intended, and
calling it anything else would be the substitution this repo's ADRs keep
catching. The reason is a fact the pre-registration could not have known,
because this run is what produced it:

**The value that engages the layer is not a constant of the system.** It was
8.0 for a store with one lesson (ADR 0193, chosen by the same worst-case rule
on the same agent and almost the same corpus) and it is 16.0 for a store with
three — because the ranking a boost has to overcome is set by how stale the
lessons are, and staleness grows with the store. A scalar default cannot mean
"engage the layer": at 16.0 an adopter with one fresh lesson over-boosts, and an
adopter whose lessons have gone quiet for fifty runs still gets nothing. ADR
0193 declined to ship 8.0 because it was tuned on one entry; shipping 16.0
because it was tuned on three would be the same error with a bigger number.

The second reason is §4's ranking table. The knob is a **switch**, not a
ranking control, so "what value should the boost have" is the wrong question
being asked of the wrong parameter. A default that engages the layer without
being tuned to a store size has to be expressed **relative to the record scores
the entries are competing with** — that is a code change, it is unmeasured, and
it is named here as the next increment rather than performed on the strength of
one corpus.

What an adopter can do today is unchanged and now has a measured number behind
it: ADR 0193 made all three knobs `aef.yaml` fields, and

```yaml
context:
  impl: memory
  knowledge_boost: 16.0     # ADR 0201's arm (d), on a three-entry store
```

is one line.
`tests/services/knowledge/test_ab_coverage.py::test_the_shipped_boost_default_is_the_measured_one`
and `tests/config/test_context_knobs.py` are untouched and still pass, and
`test_context_knobs.py` already asserts the shipped defaults against
`MemoryRetriever`'s own dataclass fields rather than against numbers typed in a
test, so there is exactly one copy of the default and this ADR did not add a
second.

## 6a. The test, and three mutations

No file under `aef/` was modified by this worker. What is added is one
regression guard, `tests/harness/test_corpus_failure_families.py` (+3), and
what it guards is the *capability*, not a number:

`tests/harness/test_corpus_negatives.py` asserts the corpus still has
negatives — ADR 0159's property. This asserts they fall into **more than one
recurring family**, which is a different thing and is the precondition for
every measurement in this ADR. A corpus that drifts back to one family
silently un-measures all of it, and the drift needs no bad intent: deleting a
scenario, widening the new rule until it always passes, or re-recording the
agent onto a model that happens to carry attributions would each do it, and
each reads as tidying in a diff. The assertions read recorded answers and the
owner's own checks — no graph, no model, 0.1 s.

| mutation | test that failed |
|---|---|
| delete the four regex-only train scenarios | `test_more_than_one_of_them_is_not_the_word_cap` (the joined family still recurs, so the count alone would not have caught it) |
| widen Rule A on every new train scenario so it always passes | `test_the_train_split_consolidates_more_than_one_lesson` **and** `test_more_than_one_of_them_is_not_the_word_cap` |
| drop Rule A from the two new validation negatives | `test_the_scored_split_carries_a_negative_that_is_not_a_word_cap_overrun` |

Three mutations, three caught. Every corpus file restored and verified: the
sha256 map over all **65** scenario files is identical before and after, and
the control passes on both sides of the run.

## 7. Consequences

- **Rubric: dimension 2 moves 14/20 → 17/20.** One row prepended; the heading
  is recomputed from the rows by `tests/test_rubric_arithmetic.py`.
- **ADR 0193's closing defect 4 is discharged.** The corpus produces three
  entries; ranking between entries has been measured; the answer is that the
  knob does not do it.
- **`knowledge_boost` stays 0.0**, with a third and different basis: not "the
  knob buys nothing" (ADR 0110, about coverage), not "the value is tuned to one
  entry" (ADR 0193), but "the value is a function of store size and staleness,
  and a scalar cannot express what the knob is for".
- **ADR 0180's excerpt scanner has a named false-positive mode** and an
  instrument that separates it.
- **ADR 0171's headline finding is retired**: *"on this task, at this cap
  range, this agent's one reproducible failure is length"* was true of one
  owner rule. `corpus/README.md` says so, and says what the second failure is.
- **ADR 0193's defects 1, 2 and 3 stand**, unfixed and unchanged by this
  worker: `run_scenario` still cannot express the arms and still builds its own
  throwaway memory with no retriever; the consolidation lag is still one
  scenario on the shipped path; and `render_retrieved_context(max_items=5)` is
  still the real budget rather than `context_budget_tokens` — 47 to 60 chunks
  were admitted under an 8000-token budget that never bound, and a constant
  five decided what the model saw. **Every number in this ADR is a number about
  that constant five, and with three lessons competing for it that is no longer
  a detail: at boost 16.0 the lessons take three of the five bullets and the
  raw records get two.**

## 8. Green bar

```
pytest -q                 3088 passed, 25 skipped, 1 xfailed
mypy aef examples         Success: no issues found in 135 source files
ruff check .              All checks passed!
ruff format --check aef tests examples docs/research/i12e   All checks passed
make measure-ci           (registered: i12e-seed, i12e-arms)
```

## 9. Quota preflight

ADR 0150's corrected argv, run first as the loop requires:

```
returncode 0  is_error=False  result='OK'  input_tokens=2
modelUsage keys: ['claude-opus-5[1m]']
```

**Calls: 120 of a budget of 140** — 1 preflight + 14 recordings + 21 (a) + 42
(b, two repeats) + 42 (d, two repeats). Arm (c) cost 0 because it is arm (b);
the rule screen, the seed, the static sweep, twenty-one dry arms, the leak scan
and the aggregation cost 0. **Twenty calls were left unspent**, and what they
could not buy is a third repeat: a third of each of (b) and (d) is 42.

## 10. Artifacts

- `docs/research/i12e/scenarios.py` — the fourteen passages, Rule A, the check
  derivation, the disclosure and the cap's two calibrations. Committed before
  the first recording.
- `docs/research/i12e/screen.py` — the six-candidate screen (§1).
- `docs/research/i12e/record_one.py` — one scenario per invocation, checks from
  `scenarios.py`, `--model` never on the argv.
- `docs/research/i12e/seed.py` — the train replay and the three entries.
- `docs/research/i12e/boost_sweep.py` — the static per-entry rank sweep.
- `docs/research/i12e/dry_identity.py` — twenty-one offline arms; (c)≡(b) and
  the choice of 16.0.
- `docs/research/i12e/arms.py` — one arm-repeat per invocation, derived
  negatives, per-signature ranks, a JSONL line per scenario as it lands.
- `docs/research/i12e/leak_check.py` — the excerpt property and its
  discriminator.
- `docs/research/i12e/aggregate.py` — every table above, from the raw JSON.
- `docs/research/i12e/prereg.txt` — the decision rule, committed first.
- `docs/research/i12e/results/` — `screen.json`, `seed.json`,
  `boost_sweep.json`, `dry/`, `{a,b,d}_r*.json` (live, with every rendered
  prompt), `arms.jsonl`.

## 11. Confidence

**High** that three lessons formed and that they are different signatures: the
seed is offline, deterministic, replayed from committed cassettes under
`on_miss="fail"`, and re-derivable by `make measure`.

**High** that (d) beat (b) here: four live arm-repeats, per-scenario scores
written as they landed, prompt hashes pinned, and the control arm's two repeats
byte-identical to each other and to the offline prediction.

**High** that (c) is (b): one sha256 over twenty-one rendered prompts, offline,
matched by the live run.

**High** on the mechanism: word-cap failures 8/8/6 → 0/0 is not a subtle
effect.

**Medium** on the size. `+0.0440` clears this rig's own bar by 2.30× and does
not clear S1b's 0.0857. **Two** repeats of each arm, not three — the budget
bought fourteen recordings instead — one corpus, one agent, two failure
families, and a scored split whose ten negatives are eight word-cap overruns
and two Rule A failures.

**Low** on generalisation of 16.0, and lower than ADR 0193's confidence in 8.0,
because this run is the evidence that the number moves with the store.

**None claimed** about whether a boost expressed relative to record scores
would behave better. It is named as the next increment and nothing here
measures it.
