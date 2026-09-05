# ADR 0162: The two signals, and which one came apart

## Status

Accepted. Worker **S6** of `UPGRADE_LOOP.md` (= `BEYOND_90_LOOP.md`'s **J4**).
Two rigs were asked for, each worth one rubric point, under one rule quoted
here because it decided half of this document:

> If the rig cannot be built honestly, **leave both points unclaimed.** A +1
> taken on a rig designed to produce it is worth less than nothing.

**Dimension 3 moves 7 → 8** (heading 70 → 71). **Dimension 2 stays 12**, and
the second half of this ADR is the record of why, with the inputs tried.

**Models, named once and used consistently after.** Everything here ran
through `ClaudeCodeProvider` on this box's own login, no API key:

| role | how it was addressed | what `modelUsage` reported answered |
|---|---|---|
| writer A / judge A | `model=""` — no `--model` flag, the session default | `claude-opus-5[1m]` |
| writer B / judge B | `--model claude-haiku-4-5-20251001` | `claude-haiku-4-5-20251001` |
| judge C (disinterested) | `--model sonnet` | `claude-sonnet-5` |

**90 live calls of the 90 allowed**, itemised at the end. Pre-registration:
`docs/research/j4/prereg.txt`, written before the first measurement call and
amended twice, each amendment before the calls it governs and each stating
what provoked it.

---

## Rig A — the self-preference control (dimension 3: 7 → 8)

### Why it did not exist

ADR 0115 said "no self-preference control (nothing compares model outputs
yet)". ADR 0123 repeated it. ADR 0171 closed with it as the reason dimension 3
was 7 and not 8. The obstruction was structural rather than neglect:
`LLMJudge.judge(state)` grades **one** state against a rubric, so a judge could
not prefer its own writing even in principle. A self-preference control needs a
judge choosing between two candidates, and nothing in `aef/` did that.

### The rig

Eleven pairs of summaries — same passage, same instructions, two models:

- **A-written**: the summary already in the cassette, verbatim.
- **B-written**: the *same recorded request*, byte-identical system and user
  messages, replayed through Haiku. 11 live calls.

Only the model differs. The judge is then shown the instructions and both
candidates and asked which better satisfies them, twice, in opposite
positions, and is told **nothing about authorship** — no model name, and not
even the caller's labels, which are stripped in favour of positional "A"/"B".
That is a property of the committed prompt, not an intention:
`tests/reasoning/test_pairwise_ranker.py::test_neither_the_label_nor_the_writer_model_reaches_the_prompt`
asserts it against the requests the ranker actually issues.

**A judge prefers a writer only if it names that writer in BOTH orders.** A
judge that flips with position expresses no preference and is counted
`inconsistent` — that is the position control, at the pair level, and it is
reported rather than averaged away.

**The owner's checks score both candidates independently**, which gives the
comparison a ground truth: on 5 of the 11 pairs the checks discriminate (B
better on 3, A better on 2), and on 6 they do not.

### Amendment 1 — six of the corpus's twenty are not Opus recordings

Found by the dry run, which prints the answering model per pair, before any
measurement call: **only `sum-21`…`sum-39` were recorded on
`claude-opus-5[1m]`.** The corpus's original twenty (`sum-01`…`sum-18`) were
recorded on **`claude-fable-5-1`**, the model of the earlier increments. ADR
0171 states nothing false — its nineteen *new* recordings are all Opus — but
its judge A/B ran over 17 validation states of which 6 are Fable's, which
matters not at all for "does this judge agree with the checks" and totally
here: on a Fable-written summary the Opus judge is not looking at its own
output, and that is the entire variable.

So rig A uses the eleven Opus-recorded validation scenarios (`sum-29`…`sum-39`,
containing all four owner-check negatives), and `load_pairs` now **refuses** a
pair whose recording is not writer A's — the guard that would have caught this
before it cost anything. The same fault would have hit rig B, whose probes were
re-picked from Opus recordings for the same reason.

### The result — 55 calls

| judge | wrote a candidate? | prefers the A-written summary | agrees with the owner checks | position-inconsistent |
|---|---|---|---|---|
| `claude-opus-5[1m]` | yes (A) | **0.714** (5 of 7 consistent pairs) | 2/3 | **4/11** |
| `claude-haiku-4-5-20251001` | yes (B) | 0.444 (4 of 9) | 5/5 | 2/11 |

    self_pref = P(judge A prefers A) - P(judge B prefers A) = +0.270
    |agreement difference| = |0.667 - 1.000| = 0.333

Both outside the 0.20 threshold set before running. **The effect is measured
PRESENT**, so the pre-registered consequence is +0 unless a mitigation is
implemented and re-measured.

### Amendment 2 — a difference-in-differences cannot say whose bias it is

Written before the arm it adds. Both judges wrote one of the two candidates,
so `+0.270` is a symmetric statistic: it says the two judges differ, not which
one is biased, and it assumes the two biases are equal and opposite. A judge
that wrote **neither** candidate fixes that, and `claude --help` documents
three aliases on this box. One preflight call resolved `sonnet` to
`claude-sonnet-5` (`preflight-sonnet.json`, `is_error false`). Same 11 pairs,
same prompt, same swap, 22 calls.

| judge | wrote one? | prefers A | agrees with the checks | position-inconsistent |
|---|---|---|---|---|
| `claude-opus-5[1m]` | yes (A) | 0.714 | 2/3 | 4/11 |
| `claude-haiku-4-5-20251001` | yes (B) | 0.444 | 5/5 | 2/11 |
| **`claude-sonnet-5`** | **no** | **0.455** | **5/5** | **0/11** |

    opus  self-preference = P(opus prefers A)   - P(sonnet prefers A) = +0.260
    haiku self-preference = P(sonnet prefers A) - P(haiku prefers A)  = +0.010

**The effect is one judge's, not the design's.** Haiku's self-preference is
+0.010 — indistinguishable from none. Opus's is +0.260, and the two routes to
it agree (the difference-in-differences gave +0.270 precisely because Haiku's
bias is ~0, which is what makes the symmetric statistic accidentally right).
The disinterested judge is also the one that never flipped with position
(0/11 against 4/11) and never disagreed with the owner's checks (5/5 against
2/3). Three statistics, one direction.

### The mitigation, implemented

`PairwiseRanker` in `aef/reasoning/llm_reflection.py` — the missing capability
and the control in one object, with the control **on by default**:

- `allow_self_ranking=False`. A ranker whose judge model wrote one of the
  candidates **refuses** (`SelfRankingError`) rather than warning or falling
  back, on ADR 0105's reasoning: an automatic fallback is weaker than a
  refusal, and a bias control reachable by accident is not a control. An owner
  who wants it says so in one field, and the error message carries the numbers
  above so the choice is made against evidence.
- **The guard fires twice**, because this repo's own default is `model: ""` —
  the harness session's model answers and its name is not known before the
  call. So: once on the declared judge model, and once on
  `CompletionResult.model` after the first call. The second costs one call to
  detect, and the class docstring says so rather than implying the guard is
  free.
- Names are normalised: `claude-opus-5[1m]` and `claude-opus-5` are one model
  (the harness reports both spellings — ADR 0169). A guard defeated by a
  suffix is not a guard, and `M3` below is that mutation.
- The candidates are presented positionally. Neither `Candidate.label` nor
  `Candidate.model` reaches the prompt.
- Code owns the tally: the model returns one letter per sample; `winner`,
  `consistent` and `verdicts` are computed. A sample that fails to parse, or a
  provider outage, is `None` — never a verdict — so a ranking cannot be
  half-observed and reported whole.

**The shipped prompt is the prompt that was measured**, and this is proved
rather than asserted: the 66 judgments were issued by `run_j4_selfpref.py`'s
own inline strings; `PairwiseRanker` was written afterwards and the two
renderings compared before the local copies were deleted — identical, sha256
`9a04e625…3501efb` (system) and `d8607c65…42be0bad` (the `sum-29` user turn),
now pinned in the test file so they cannot drift, with the runner importing
the shipped prompt and the shipped parser instead of holding copies.

### Falsifications, as pre-registered and how each fired

- **(1) the control exists as a committed runner + committed raw data —
  HELD.** `docs/research/j4/run_j4_selfpref.py`, `candidates.jsonl` (11),
  `rankings.jsonl` (66), `report-selfpref.txt` regenerable by `--report`.
- **(2) the effect is absent, OR present-and-mitigated — HELD on the second
  branch.** Present (+0.270 / 0.333, both outside 0.20). Mitigated: a
  disinterested judge was measured and is better on all three statistics, and
  the refusal is implemented with tests and its default set by that
  measurement. Amendment 2's own out — "if the disinterested judge agrees with
  the owner's checks no better than the self-interested one, the mitigation is
  not a mitigation and this is +0" — did not fire: 5/5 against 2/3.

**Claim: +1. Dimension 3 moves 7 → 8.**

### Why 8 and not 9, stated as plainly as the result

- **n is small and the discriminating subset is smaller.** 11 pairs; the
  checks discriminate on 5; the Opus judge is position-consistent on only 3 of
  those 5, so `2/3` is n = 3. The preference rates rest on 7, 9 and 11
  consistent pairs respectively.
- **One task family, one writer pair.** Everything is 25–38-word summaries of
  synthetic local-news passages. Whether Opus favours its own longer answers
  in general is not established by this and nothing here should be cited as if
  it were.
- **The disinterested arm was added after seeing the first result.** It was
  pre-registered before its own calls (amendment 2) and it did not move the
  bar, but it is adaptive and a reader should weigh it as such.
- **Position-inconsistency and self-preference are confounded here.** The
  Opus judge is the least stable AND the most self-preferring, and this rig
  cannot separate "prefers its own text" from "is noisier, and noise on a pair
  whose candidates differ in length favours the longer one".
- **Nothing in the loop calls `PairwiseRanker` yet.** It is a capability with
  a control, not a wire: `run_loop` still ranks candidates by gate outcome and
  score, not by a judge. Dimension 3's remaining points want the control
  exercised where candidates are actually chosen.

---

## Rig B — a lesson that is harmful AND resolved (dimension 2: stays 12)

### What was asked, and what "harmful" means today

ADR 0118 surfaced `helpful`/`harmful` per entry and deliberately did not rank
on them: *"on every rig so far harmful and live coincide"*. `_tally`
(`aef/services/knowledge/consolidate.py`) counts a run **harmful** when it had
the lesson in context and **reproduced that same failure** — so "harmful" and
"still worth showing" are one fact. J4 asked for the corpus that separates
them: a lesson that is retrieved and makes a later run fail *differently*.

### The lesson, built from records and not by hand

The corpus's seven owner-check negatives are all `max_words` overruns (ADR
0171). Each became one `MemoryRecord` whose verbal feedback is the **real**
`RuleBasedCritic` over a derived state carrying that check failure as
`state.errors[0]` — ADR 0157's method, used because the harness producer that
would write these in a run (M4b, ADR 0174) is on a branch that had not landed
on `main` within this worker's window, and depending on an unmerged branch is
not available to it. The signature is ADR 0174's own
(`failure:check:<path>:<op>`), so the object is the one the repo will have.
Synthetic in origin, real in shape, and said out loud.

The **shipped** `RuleBasedConsolidator` then folds the seven into one entry —
`failure:check:working_memory.summary:max_words`, occurrence_count 7,
confidence 0.636 — and the **shipped** `MemoryRetriever` +
`render_retrieved_context` put it in the prompt, one 330-character bullet
before the passage:

```
Lessons from this agent's earlier runs (most relevant first):
- [failure:check:working_memory.summary:max_words] 1 error(s) recorded; 0/0 tool
  call(s) failed. errors[0]: working_memory.summary max_words 38: got 'The
  Larkfield quarry extension won conditional permission on Tuesday: …
```

The rig asserts, per scenario, that the prompt it builds **with no lesson** is
the cassette's recorded prompt byte for byte, so a behaviour change cannot be
an artefact of rebuilding the prompt.

### The two arms — 10 calls, all `claude-opus-5[1m]`

**Harm probes**: five Opus-recorded scenarios that pass every owner check in
the baseline, whose summary sits at or within two words of the cap, with
multi-word `must_mention` terms — the conditions under which "be shorter" has
somewhere to cut.

| id | cap | baseline | with lesson | newly failed |
|---|---|---|---|---|
| `sum-24-pellow-mill` | 12 | 11 w, 4/4 | 11 w, 4/4 | — |
| `sum-23-cransley-cut` | 25 | 23 w, 5/5 | **28 w**, 4/5 | `max_words` |
| `sum-31-quernmore-kiln` | 26 | 25 w, 5/5 | 24 w, 5/5 | — |
| `sum-34-alder-carr` | 30 | 30 w, 5/5 | 30 w, 5/5 | — |
| `sum-39-coldbeck-society` | 38 | 38 w, 5/5 | **41 w**, 4/5 | `max_words` |

**The lesson made two runs LONGER and broke the very check it is about.**
Zero content checks flipped. So the pre-registered condition — "at least one
harm probe flips a NON-cap check from pass to fail" — **did not fire**. On the
harm arm the lesson is harmful and *live*: exactly the coincidence ADR 0118
described, arriving by a mechanism nobody predicted (adding ~50 words of
prior-failure text before the passage, including a 38-word example summary,
appears to raise the length the model writes rather than lower it).

**Help probes**: five of the seven cap negatives, same lesson.

| id | cap | baseline | with lesson | newly passed | newly failed |
|---|---|---|---|---|---|
| `sum-22-marlowe-street` | 30 | 31 w, 4/5 | 29 w, 5/5 | `max_words` | — |
| `sum-30-ganister-tarn` | 28 | 30 w, 4/5 | 28 w, 5/5 | `max_words` | — |
| `sum-33-cotterdale-bus` | 25 | 26 w, 4/5 | 21 w, 5/5 | `max_words` | — |
| `sum-35-priory-gatehouse` | 28 | 30 w, 4/5 | 28 w, 4/5 | `max_words` | **`regex`** |
| `sum-36-larkfield-quarry` | 38 | 41 w, 4/5 | 39 w, 4/5 | — | — |

`sum-35-priory-gatehouse` is the shape J4 asked for, and it turned up in the
arm that was not looking for it: the cap failure was **resolved** (30 → 28
words) and a different check **broke** in the same run.

### Why it is still +0, for two independent reasons

**Reason 1 — the one instance is a check-authoring narrowness, not a content
loss.** The check is
`(?i)(remains? open|stays open|open throughout|open to visitors)`. The
baseline wrote *"which **stays open** except for two April weeks"*; the
shortened version wrote *"**staying open** except two April weeks"*. The
meaning survives; the regex does not admit the participle. Under ADR 0171's
own standard — three checks were widened there because *"a correct answer
passes"* — this check would be widened, and the instance would disappear. A
rubric point resting on one run whose failure is a missing alternation in a
regex is a point taken on a rig that produced it.

**Reason 2 — the shipped tally cannot see it, and is inverted on exactly this
case.** Not reasoned about: run, by writing the ten runs back as the
`MemoryRecord`s a real reflect+consolidate pass would have written and letting
the shipped `RuleBasedConsolidator` compute the tally
(`run_j4_harm.py --tally`, output committed):

```
failure:check:working_memory.summary:max_words   x10   helpful=7  harmful=3
```

The three `harmful` are `sum-23`, `sum-39`, `sum-36` — the runs that
reproduced the *cap* failure. **`sum-35`, the one genuinely harmful run, is
counted `helpful`**, because `_tally`'s definition of harm is "reproduced this
signature" and `sum-35` produced `failure:check:working_memory.summary:regex`,
a different string that `_is_subsequence` cannot match. The lesson is credited
for the failure it caused.

So a `harm_penalty` term in `MemoryRetriever` would be ranking on a signal
this repo does not compute — worse, on one that moves the wrong way as harm
increases. `memory_retriever.py` is untouched, and the falsification's
condition (2) is the reason.

### The blocker, named for whoever takes dimension 2 next

`_tally` needs a second notion beside "reproduced": a run that had the lesson
in context and produced a failure signature **different from** the lesson's.
Today both branches of its `if` are `helpful`/`harmful` around
`_reproduced()`; the missing third outcome has no name. That is a change to
`aef/services/knowledge/consolidate.py`, which is not this worker's file, and
it should arrive with the corpus this rig could not build: content checks
written wide enough that shortening loses *meaning* rather than *grammar*, and
more than one instance of it.

### Falsifications, as pre-registered and how each fired

- **(1) a harm probe flips a non-cap check — DID NOT FIRE.** 0 of 5; the two
  flips were the cap check itself, in the wrong direction. One instance of the
  shape appeared in the help arm (`sum-35`), n = 1, and is fragile for reason 1.
- **(2) the shipped pipeline produces a readable `harmful` tally — DID NOT
  FIRE.** `helpful=7 harmful=3`, with the harmful run counted helpful.
- **(3) ranking on the tally recovers the flipped check — NOT REACHED**, and
  deliberately not attempted: measuring a knob against a signal that reads
  backwards would produce a number, and the number would mean nothing.

**Claim: +0. Dimension 2 stays 12.** The inputs tried are the two tables
above.

---

## Defects and findings outside this worker's files — reported, not fixed

1. **Six corpus scenarios are `claude-fable-5-1` recordings** (`sum-01`…
   `sum-18`; `sum-13`…`sum-18` are in validation). Nothing states this
   anywhere — `corpus/README.md` and ADR 0123 do not name the model, and ADR
   0171's "model, everywhere in this document: `claude-opus-5[1m]`" is true of
   its own recordings and reads, in a document about that corpus, as though it
   were true of all of them. Any future measurement that treats the
   validation split as one model's output is wrong by 6/17, and the quota for
   `claude-fable-5-1` is exhausted, so they cannot be re-recorded. **This
   worker's `load_pairs` refuses them; nothing else does.**
2. **A retrieved lesson made the failure it describes MORE likely.** Two of
   five at-cap runs went over the cap only when shown a lesson about going
   over the cap (23 → 28 words against a cap of 25; 38 → 41 against 38). The
   bullet is 330 characters of prior-failure prose containing a 38-word
   example summary, inserted between the instructions and the passage by
   `render_retrieved_context`. This is a property of the ACE-style layer as
   wired, not of this rig, and no measurement in this repo has looked for it:
   ADR 0110's A/B scored *retrieval coverage*, and ADR 0155's four arms
   compared prompts, not outcomes. Whoever next measures the knowledge layer
   on a task metric should expect the lesson to be able to cost score.
3. **`_tally`'s inversion**, above — `aef/services/knowledge/consolidate.py`.

## Mutations

Against `tests/reasoning/test_pairwise_ranker.py`, this increment's own
tripwire. Perturb, RUN, restore from a shasum-verified byte backup; the
control is green before and after and the file's sha256 is proved unchanged at
the end.

| # | mutation | result |
|---|---|---|
| M1 | default `allow_self_ranking` to `True` | 3 failed — CAUGHT |
| M2 | drop the post-call guard (the alias / `model=""` path) | 1 failed — CAUGHT |
| M3 | stop normalising the `[1m]` context-window suffix | 2 failed — CAUGHT |
| M4 | let a sample that produced no verdict still yield a winner | 1 failed — CAUGHT |
| M5 | put the writer's label into the prompt | 2 failed — CAUGHT |

5 of 5.

## Green bar

```
pytest -q                 2423 passed, 6 skipped   (from 2408; +15)
mypy aef examples         Success: no issues found in 132 source files
ruff check .              All checks passed!
ruff format --check aef tests examples docs/research/j4   267 files already formatted
```

`tests/harness/test_container_sandbox.py::test_a_timed_out_container_is_actually_dead`
failed on a later full-suite run and passes in isolation (25 passed). It is the
same docker-timing flake ADR 0171 recorded, on the same test, and is noted here
so the next reader does not attribute it to this increment — nothing here goes
near the container path.

## Live budget

**90 of the 90 allowed** — the cap exactly, with nothing left for a retry,
which amendment 2 said in advance:

| what | calls |
|---|---|
| quota preflight, ADR 0150's argv, session default | 1 |
| quota preflight, `--model claude-haiku-4-5-20251001` | 1 |
| quota preflight, `--model sonnet` | 1 |
| rig A — 11 Haiku candidate summaries | 11 |
| rig A — judge `claude-opus-5[1m]`, 11 pairs × 2 orders | 22 |
| rig A — judge `claude-haiku-4-5-20251001` | 22 |
| rig A — judge `claude-sonnet-5` (disinterested) | 22 |
| rig B — 5 harm probes | 5 |
| rig B — 5 help probes | 5 |

No call was retried, none failed, and every `stop_reason` was `end_turn`. The
three preflights are recorded raw as `preflight.json`,
`preflight-claude-haiku-4-5-20251001.json` and `preflight-sonnet.json`.

## Confidence

**High on rig A's mechanics**: 77 committed judgments, three judges, the same
eleven pairs, a report that regenerates every table from the JSONL alone, and
the shipped prompt proved byte-identical to the measured one.

**Medium on what rig A means.** The self-preference number is one judge's on
one task family with n = 11, the discriminating subset is n = 5, and
self-preference is confounded with position instability in a design that
cannot separate them. What is solid is the direction and its triple agreement;
what is not established is a magnitude anyone should quote.

**High on rig B's negative result**, and it is the part of this document most
worth reading: the ten runs are real, the lesson came out of shipped code over
recorded failures, the one instance of the shape J4 wanted is a regex that
does not admit "staying open", and the tally that would have to carry the
signal was RUN and reads backwards. Two independent reasons for +0, either of
which would be enough.
