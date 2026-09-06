# ADR 0202: The judge, on a set a word count cannot grade

## Status

Accepted. Worker **P3** of `TO_95_LOOP.md`; record in `IMPROVE_LOG.md`.
**Rubric dimension 3 moves 8 → 10.**

The headline first, because ADR 0159's discipline is that the most
interesting possible outcome gets the first paragraph: **the judge is not a
constant function and not a word counter.** On twelve cases built so that
"answer pass to everything", "answer fail to everything" and "count the words
against the cap" each score exactly 6/12, `LLMJudge` on the session default
agrees with the owner's labels **12/12**, separates the classes with **AUC
1.000**, and scores the correct summary above the corrupted one in **6 of 6
matched pairs**. The corpus's own regex checks — the non-model instrument a
judge would be replacing — score **9/12** on the same set.

Model, everywhere: **`claude-opus-5[1m]`** (the session default, `model: ""`,
no `--model` flag) as writer and judge A, and **`claude-sonnet-5`** (`--model
sonnet`) as the disinterested judge, reused from ADR 0162 so that two
measurements share one third party. Both quota preflights on ADR 0150's
corrected argv: `is_error false`, `result "OK"`, `input_tokens 2`, raw at
`docs/research/i14b/preflight.json` and `preflight-sonnet.json`.

Pre-registration: `docs/research/i14b/prereg.txt`, written before the first
preflight, not amended.

## Context

Two prior measurements of this judge, and what each is worth:

- **ADR 0159**: the summary corpus was 15/18 pass, so a judge answering
  "pass" to everything scored 15/18. `LLMJudge` scored exactly 15/18. **AUC
  0.322** — below the 0.5 of no information at all. Its conclusion was that
  the corpus could not grade a judge, and that the next increment needed a
  corpus with true content negatives.
- **ADR 0171**: seven true negatives were recorded, AUC went to **1.000**, and
  dimension 3 moved 6 → 7. Its own closing paragraph is why this ADR exists:

  > AUC 1.000 is perfect separation of **one failure family with n = 4**:
  > every negative is a word-cap overrun, so what has been shown is that this
  > judge detects that failure, not that it detects failure.

`len(summary.split()) > cap` detects a word-cap overrun. On ADR 0171's
validation split that instrument scores 16/17 — **the same as the judge**. So
the +1 taken there is, on the evidence in that document, consistent with the
judge being a word counter, and nothing since has distinguished the two.

## The hard set

Six passages from `corpus/` (train and validation, all recorded on
`claude-opus-5[1m]`), each contributing a **matched pair**: the agent's own
recorded summary verbatim from the cassette, and that same summary with **one
minimal owner-authored edit** that makes it wrong about the passage. Twelve
cases; six owner-pass, six owner-fail.

The judged state is the real scenario's `reflect` `input_state` with
`working_memory.summary` replaced and **nothing else touched** — so within a
pair the passage, the objective, the cap and the must-mention terms are
byte-identical and the summary is the only variable. `run_i14b.py --build`
asserts, rather than states, that each edit's span occurs exactly once in the
recorded summary.

| passage | family | the edit | the owner's label, in short |
|---|---|---|---|
| `sum-31-quernmore-kiln` | wrong unit | `340mm` → `340cm` | the survey says 340 **millimetres** out of plumb; 340 centimetres is ten times the lean |
| `sum-29-brindle-viaduct` | superseded figure | `£2.4m … £3.1m` → `£3.1m … £2.4m` | 2.4m was the first assessment and 3.1m the revised scheme; the summary says the work got cheaper when it got dearer |
| `sum-32-hessle-mills` | swapped entities | `Low` ⇄ `High` | the grant went to Hessle **Low** Mill and was refused to Hessle **High** Mill; every fact is attached to the wrong mill |
| `sum-21-ardvey-ferry` | fabricated reason | `an unapplied … chart correction` → `a steering gear failure reported twice before` | the conclusions survive; the cause is invented and appears nowhere in the passage |
| `sum-38-bewick-refusals` | dropped condition | the rate-fall clause removed | the rate fell 9% → 6% and the count rose only because applications almost doubled; every word left is true and the story is reversed |
| `sum-28-kellet-branch` | unsupported claim | `delayed indefinitely` → `reopens in September` | the passage says the September date already slipped and there is now no confirmed date |

**The control that makes it a fair test, and it is a computed number rather
than an argument: every one of the twelve summaries is within its own word
cap.** `--build` refuses to write the file otherwise, and
`tests/reasoning/test_i14b_hardset.py` asserts it. So the instrument ADR
0171's AUC actually measured scores 6/12 here — chance.

**The negatives are AUTHORED, not observed, and that is this artifact's real
weakness rather than a footnote.** ADR 0171 recorded nineteen runs against
deliberately trappy passages precisely to obtain content negatives and got
none: *"every content trap was handled correctly."* A set of content negatives
cannot be recorded from this agent at this cap range; it has to be written.
The consequence is exact: **this set grades the judge, and no number in it is
a statement about how often this agent fails.**

## Evidence

48 grading calls (12 cases × 2 judges × 2 position-swapped samples), 6
foreground batches, 0 fallbacks, every `stop_reason` `end_turn`. Answering
models: `claude-opus-5[1m]` ×24 and `claude-sonnet-5` ×24 — **no
misattribution this time**, against ADR 0159's 1-in-36 and ADR 0171's 1-in-34.

### The trivial baselines, computed from the same file

| instrument | agrees with the owner's labels |
|---|---|
| answer "pass" to everything | **6**/12 |
| answer "fail" to everything | **6**/12 |
| word count against the cap only | **6**/12 |
| the corpus's own inherited regex checks | **9**/12 |
| rule-based `RuleBasedJudge` (no model call) | **6**/12 (constant 0.000) |

The rule-based arm is constant-fail exactly as in ADRs 0159 and 0171: this
agent writes no `state.scores`, so its weighted score is 0.0 everywhere.

### The arms

| arm | agree | AUC | paired | max position delta | scores |
|---|---|---|---|---|---|
| `llm-opus` (session default) | **12**/12 | **1.000** | **6**/6 | **0.100** | 0.065 – 0.885 |
| `llm-sonnet` (disinterested) | **11**/12 | **1.000** | **6**/6 | **0.550** | 0.100 – 0.910 |

`paired` is the statistic this design exists for: on how many of the six
matched pairs does the judge score the correct summary above the corrupted
one. It controls for passage difficulty completely, because the two members of
a pair differ by one span.

Agreement by threshold — the headline does not rest on where the line is
drawn:

```
llm-opus     0.25:11/12  0.40:12/12  0.50:12/12  0.60:12/12  0.75:12/12
llm-sonnet   0.25: 8/12  0.40:10/12  0.50:11/12  0.60:11/12  0.75:11/12
```

Per case, with the two non-model instruments beside them:

| case | owner | checks | rule | opus | sonnet |
|---|---|---|---|---|---|
| `sum-21-ardvey-ferry:correct` | PASS | pass | 0.000 | 0.885 | 0.660 |
| `sum-21-ardvey-ferry:corrupt` | FAIL | pass | 0.000 | 0.150 | 0.100 |
| `sum-28-kellet-branch:correct` | PASS | pass | 0.000 | 0.885 | 0.900 |
| `sum-28-kellet-branch:corrupt` | FAIL | FAIL | 0.000 | 0.100 | 0.275 |
| `sum-29-brindle-viaduct:correct` | PASS | pass | 0.000 | 0.885 | 0.910 |
| `sum-29-brindle-viaduct:corrupt` | FAIL | pass | 0.000 | 0.175 | 0.325 |
| `sum-31-quernmore-kiln:correct` | PASS | pass | 0.000 | 0.885 | 0.900 |
| `sum-31-quernmore-kiln:corrupt` | FAIL | FAIL | 0.000 | 0.325 | 0.625 |
| `sum-32-hessle-mills:correct` | PASS | pass | 0.000 | 0.880 | 0.910 |
| `sum-32-hessle-mills:corrupt` | FAIL | pass | 0.000 | 0.065 | 0.125 |
| `sum-38-bewick-refusals:correct` | PASS | pass | 0.000 | 0.885 | 0.875 |
| `sum-38-bewick-refusals:corrupt` | FAIL | FAIL | 0.000 | 0.175 | 0.425 |

**Three of the six content failures are invisible to the corpus's own
checks** — the swapped mills, the fabricated cause and the swapped costs all
satisfy every `TaskCheck` in their scenario, because the required terms and
the required figure are all still present, in the wrong places. The judge
scores those three 0.065, 0.150 and 0.175. That is the concrete answer to
"what does a judge buy over a regex", on this set: three cases out of twelve,
and they are the three where the answer looks most correct.

### The 2×2 (rule-based versus the model judge)

| | opus pass | opus fail |
|---|---|---|
| **rule pass** | 0 | 0 |
| **rule fail** | **6** (all 6 owner-pass) | **6** (all 6 owner-fail) |

Against ADR 0159's version of this table, where one cell held all 18: the rule
arm is still a constant, and the model arm is now split exactly along the
owner's labels.

### The self-preference control, on the grading path

`claude-opus-5[1m]` wrote every positive and is the source text of every
negative, so `llm-opus` is grading its own writing and `llm-sonnet` wrote none
of it. ADR 0162's control is on the *comparing* path; this is the same
question on the path the loop's reflect node actually uses.

    mean(opus − sonnet) over all 12 cases                      -0.0613
    mean(opus − sonnet) over the 6 the Opus judge wrote        +0.0250

**+0.025 is indistinguishable from none**, against ADR 0162's +0.260 on the
comparing path. Two readings, both worth having: grading one item at a time
does not seem to invite the bias that choosing between two does, and ADR
0162's effect may be specific to the comparative frame rather than a property
of the model.

### The choosing-path control

ADR 0162's own "why 8 and not 9" is the request this answers:

> Nothing in the loop calls `PairwiseRanker` yet. It is a capability with a
> control, not a wire … dimension 3's remaining points want the control
> exercised where candidates are actually chosen.

**The loop's choosing act is `proposal = proposals[0]` in `cycle`
(`aef/harness/loop.py`), which is another worker's file this wave and was not
touched.** What was measured instead is the same shipped object performing a
choice whose outcome is scored: for each of the six pairs, choose which
summary to keep.

| judge | chose the correct summary | position-inconsistent |
|---|---|---|
| `claude-opus-5[1m]` | **6**/6 | **0**/6 |
| `claude-sonnet-5` | **6**/6 | **0**/6 |

And the shipped guard, exercised on that act with both candidates carrying
`model="claude-opus-5[1m]"`:

| how the judge model is given | calls spent | result |
|---|---|---|
| declared (`model="claude-opus-5"`) | **0** | `SelfRankingError`, before the call |
| empty (`model=""`, **this repo's default**) | **1** | `SelfRankingError`, from the model that answered |

Both fire, including through the `[1m]` suffix normalisation. The second row
is the honest cost the class docstring already stated: with the repo's own
default configuration a self-ranking attempt costs one call to detect.

**Choosing was the steadier instrument.** On the grading path the disinterested
judge made its one error (`sum-31:corrupt` at 0.625) and had two position
deltas above 0.5; on the choosing path it was 6/6 with no inconsistency at
all. That is a finding about where to put a judge, and it is n=6.

## Falsifications, as pre-registered and how each fired

- **(F1) the judge beats the trivial baselines, on all three statistics —
  HELD.** Agreement 12/12 (bar: ≥ 9/12), AUC 1.000 (bar: ≥ 0.75), paired 6/6
  (bar: ≥ 5/6). All three, deliberately, because ADR 0159's lesson is that one
  agreement count can be a constant function in disguise.
- **(F2) position sensitivity stays small (max delta ≤ 0.20) — HELD FOR THE
  JUDGE UNDER TEST, and BREACHED by the control.** `llm-opus`, the arm the
  repo ships and the one this row rests on: **0.100**. `llm-sonnet`: **0.550**,
  on two cases, and one of them (`sum-31:corrupt`) is the single case that arm
  got wrong.

  **The pre-registration did not say which arm, and that ambiguity is
  disclosed rather than resolved silently.** The reading applied here is that
  F2 governs the judge whose quality the rubric point is about — `LLMJudge` on
  the session default, which is what `reflection.impl: llm` runs. Under the
  stricter reading (any arm), F2 fires and this ADR claims **+1, not +2**.
  Both numbers are above; a reader who prefers the stricter reading can
  overrule this in one line.
- **(F3) the self-preference effect is absent, or present-and-mitigated —
  HELD on the first branch.** +0.025 on the grading path, measured against a
  disinterested judge on identical cases. The mitigation from ADR 0162 is
  unchanged and was re-exercised on the choosing act.
- **The fourth outcome, named in advance so it could not be hidden: "the judge
  beats the trivial baselines and still loses to the corpus's own regex
  checks" — DID NOT FIRE.** 12/12 against 9/12.

**Claim: +2. Dimension 3 moves 8 → 10.**

## Why 10 and not 9, and what a 10 here does not mean

The row's full-marks text is *"LLM critic + judge over recorded signals with
position/verbosity/self-preference bias controls, measured against the
rule-based baseline"*. Every clause now has a measurement behind it on a set
where the trivial instruments score chance: the judge against the rule-based
baseline (12/12 vs 6/12) and against the regex baseline (12/12 vs 9/12), the
position control (0.100, reported per case), the verbosity control (structural
— `MAX_EXCERPT_CHARS`/`MAX_ANSWER_CHARS`, and on this set the corrupted
summary is longer than the correct one in one pair and shorter in another), and
the self-preference control on both the comparing path (ADR 0162) and the
grading and choosing paths (here).

What a 10 does **not** mean, stated as plainly as the result:

1. **The negatives are authored.** They are the failure modes a reader would
   worry about, drawn from this corpus's own passages, but this agent does not
   make them. Nothing here measures the agent.
2. **n = 12, six pairs, one task family.** 25–40-word summaries of synthetic
   local-news passages, as in every measurement of this judge so far.
3. **The disinterested judge is position-unstable on this set** (0.550 max
   against ADR 0162's 0/11 inconsistency on the comparing path), and its one
   error is that instability. If a future increment moves the default judge to
   a cheaper model on the strength of ADR 0162, this set says re-measure first.
4. **Nothing in `run_loop` calls `PairwiseRanker`.** See below for exactly what
   that would take; the measurement here is on the shape, not on the wire.
5. **The set is small enough to be memorised.** It is committed, so a model
   trained on this repository later would have seen it. That is a real limit on
   re-running these numbers in a year, and the runner regenerates the set from
   the corpus so a replacement can be built the same way.

## What wiring the ranker into the choosing path would take

Recorded because P3 could not do it: `aef/harness/loop.py` is another worker's
file this wave.

`cycle` currently ends its proposal step with one line:

```python
proposal = proposals[0]  # at most one candidate per cycle, deliberately
```

`RuleBasedProposer.propose_from_memory` returns structural proposals followed
by one per numeric constant, so `proposals[0]` is a fixed function of the
source. Replacing that with a judged choice needs four things, and the fourth
is the one that would be easy to get wrong:

1. **A task string both candidates were written against.** `PairwiseRanker`
   takes the writers' instructions verbatim; a proposal's equivalent is the
   grounding citation plus the diff, and something has to render it.
2. **`Candidate.model` populated honestly.** For a rule-based proposal there is
   no writer model, so it is `""` and the guard cannot fire — which is correct
   (nothing wrote it) but means a mixed field of rule-based and LLM proposals
   is only half-guarded. That asymmetry should be stated wherever it is wired.
3. **A refusal path.** With `config.proposer == "llm"` and the repo's default
   `model: ""`, the guard fires **after one call** and raises. `cycle` must
   decide whether that is a turn that produced no candidate or an error, and
   the answer has to be written down before it is coded.
4. **The measurement, not the wire.** Choosing among proposals is not the same
   act as choosing among summaries: proposals are compared on a *predicted*
   effect, and this rig measured a judge choosing between two texts whose
   quality is directly readable. Wiring the ranker into `cycle` on the strength
   of a 6/6 measured on summaries would be exactly the "measured the wrong
   thing" defect this programme keeps finding. The honest next step is a
   ranking rig over real proposals scored against what the gates later said.

## Defects and findings outside this worker's files — reported, not fixed

1. **`MAX_ANSWER_CHARS = 600` truncates the source passage.** The judge's
   evidence includes `working_memory` strings sorted by key, so on the summary
   task it gets `summary` and then `text` — the passage the summary is being
   checked against. All six passages here are 265–468 characters, so nothing
   was truncated; a passage over 600 characters would be cut, and the judge
   would be asked whether a claim is supported by a source it can only see two
   thirds of, with nothing in the rationale saying so. This measurement
   selected around it rather than hitting it, which is the reason it is worth
   writing down.
2. **`max_words` never reaches the judge's evidence.** `_evidence` admits
   `working_memory` values only when `isinstance(value, str)`, and `max_words`
   is an int. ADR 0171 attributed its AUC 1.000 partly to the judge "counting
   against the cap it can see in the evidence" — the cap is visible, but
   through `state.objective` ("summarise … in at most 28 words"), not through
   working memory. Nothing in ADR 0171's numbers changes; the mechanism
   sentence does.
3. **A judge scored a wrong answer 0.625.** `sum-31:corrupt` — a kiln leaning
   340 **centimetres** instead of 340 millimetres — passed `claude-sonnet-5`'s
   0.5 threshold. Unit errors are the family this judge is weakest on in both
   arms (opus 0.325, its highest failing score), which is worth knowing before
   anyone points a judge at numerical work.

## Mutations

Each performed for real against `tests/reasoning/test_i14b_hardset.py`, this
increment's own tripwire: perturb, RUN, restore from a sha256-verified byte
backup. The control is green before and after.

| # | mutation | result |
|---|---|---|
| M1 | push one negative over its cap (`sum-38` corrupt padded past 36 words) | **5 failed** — CAUGHT |
| M2 | relabel one negative `owner_pass: true` (unbalancing the set) | **2 failed** — CAUGHT |
| M3 | replace a positive with something that is not the recorded summary | **2 failed** — CAUGHT |
| M4 | change an edit's `old` span so it no longer occurs in the summary | **2 failed** — CAUGHT |
| M5 | copy an inherited-check verdict forward instead of recomputing it | **2 failed** — CAUGHT |

5 of 5. M1 trips five assertions rather than two — the cap floor, the balance
of the trivial baselines, the builder-equality check and both parametrised
per-case rows — because a case going over its cap breaks every property that
makes the set a fair test at once, which is what those assertions are for.

## Green bar

Recorded in `IMPROVE_LOG.md` with P4's, since the two increments share one
branch and one bar.

## Live budget

**75 calls of the 90 allowed**: 2 quota preflights (session default and
`sonnet`), 48 grading, 24 choosing, 1 to show the self-ranking guard firing on
this repo's own `model: ""` default. No call was retried, none failed, every
`stop_reason` was `end_turn`. The 15 unspent were the retry reserve the
pre-registration set aside; no case was added to the set after seeing a
result.

## Confidence

**High on the numbers.** 75 committed judgments, two judges, the same twelve
cases, a report that regenerates every table from the JSONL alone, and a
tripwire test that re-derives the set from the corpus so the committed file
cannot drift from the scenarios it came from.

**High on the negative claim** — that this judge is not a word counter and not
a constant function. Three independent readings agree: the agreement count
against three baselines that all score 6/12, the AUC over 36 pass/fail pairs,
and the paired statistic which controls for passage difficulty exactly.

**Medium on generality**, and the five numbered limits above are the reason.
Six pairs of local-news summaries is a small window on "does this judge detect
failure", and the honest summary of three increments is: on word-cap overruns
it is perfect (ADR 0171), on six kinds of content error it is perfect here,
and on anything else nobody has looked.
