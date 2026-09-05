# ADR 0171: A corpus that can tell two judges apart

## Status

Accepted. Worker S3b of `UPGRADE_LOOP.md`, executing the last sentence of ADR
0159 and the open consequence of ADR 0166. Record in `IMPROVE_LOG.md`.
**Rubric dimension 3 moves 6 → 7** (heading 69 → 70), against three
conditions pre-registered before a single judge call was made.

Model, everywhere in this document: **`claude-opus-5[1m]`** — the harness
session's own default. The recording config passes `model: ""`, so no
`--model` flag reaches the CLI, and `run_i14.py` is invoked without `--model`
for the same reason. Recording and judging on different models would not be a
comparison.

## Context

ADR 0159 built the judge A/B as a committed artifact and then found that the
artifact could not answer the question it was built for:

> So the summary corpus cannot grade a judge. Its three negatives are
> check-authoring defects rather than content failures, and once they are
> corrected there are none left. […] The next increment for dimension 3 is
> not a better judge — it is **a corpus with true content negatives**.

Its numbers: the corpus was 15/18 pass, so a judge answering "pass" to
everything scored 15/18; the LLM judge scored exactly 15/18; the AUC over the
45 pass/fail pairs was **0.322**, below the 0.5 of no information at all.

ADR 0166 left a second thing for "whoever next re-records the corpus": the
twenty word caps still carried a regex, because migrating them to
`max_words` + `min_words: 1` would add a fifth check to a four-check scenario
and move every recorded score from 0.75 to 0.80.

This increment is both, in that order, plus one thing neither ADR knew about.

## Decision and evidence

### Part 1(a) — the three case-sensitivity defects, corrected

`aef loop score --json`'s `attribution` (ADR 0166) names them without a guess:

```
train      sum-07-signal-box   3/4  working_memory.summary contains 'volunteers':
                                    got "Volunteers restored Ashcombe station's …"
validation sum-14-quarry-lake  3/4  working_memory.summary contains 'swimming':
                                    got 'Swimming will be permitted at Ketley …'
validation sum-16-cliff-path   3/4  working_memory.summary contains 'landslip':
                                    got 'Landslip after heavy rain removed …'
```

All three summaries mention the term. `contains` is case-sensitive, the model
capitalised at the start of a sentence, and `checks.py` has **no
case-insensitive op** — `aef/` is not this worker's to change, and adding one
would have been a reasonable request to make and a bad thing to do quietly.

So the corrected form is the one already blessed in this repo:
`docs/research/i14/run_i14.py`'s `_case_insensitive` oracle rewrites a
`contains` as `regex` with an inline `(?i)`. That transformation is now on
disk. One check object per file moves; every other top-level key is asserted
byte-identical per file, by a JSON diff over every key.

| | before | after |
|---|---|---|
| train | mean **0.9792**, n=12, `sum-07` 0.75 | mean **1.0000**, n=12 |
| validation | mean **0.9167**, n=6, `sum-14`/`sum-16` 0.75 | mean **1.0000**, n=6 |
| holdout | 1.0, n=2 | 1.0, n=2 |
| `attribution` | 3 entries | **empty** |

That is the honest baseline and it is the problem: **20/20 pass, no negatives
at all.** Exactly what ADR 0159 predicted.

### Part 1(b) — the twenty word caps

ADR 0166's two objections to `max_words` + `min_words: 1`, and what happened
to them:

- *A bare `max_words` accepts an empty summary, retiring the 0.0000-vs-0.25
  signal ADR 0156 used.* Answered by keeping `min_words: 1`, which restores
  the predicate exactly.
- *The fifth check moves every recorded score, 0.75 → 0.80, and the metric
  stops being the one ADR 0123 recorded.* Answered by (a): after the case
  defects are corrected there are no 0.75s left, so the count moving 4 → 5
  changes **no score at all**. `loop score --json` before and after this
  migration is identical, byte for byte — diffed, not eyeballed.

**The scale did move and that is fine, stated plainly:** a per-scenario score
is now `k/5` rather than `k/4`, so one failed check costs 0.20 instead of
0.25. Checks are the owner's data (ADR 0113) and the owner changed them on
purpose; no cassette was touched, so nothing about what the agent *did* has
been re-recorded; and `tests/test_rubric_arithmetic.py` reads the rubric, not
the corpus.

The cap regex was the last check in all twenty files, so the rewrite is a
suffix replacement: nothing else moves, and each new `max_words` value is
asserted equal both to the pattern's `N+1` and to the scenario's own
`working_memory.max_words`.

**Ordering.** (b) is verdict-neutral — it changes no check from pass to fail
or back — so it cannot make v1 and v2 incomparable and it landed *before* the
judge run, in its own commit. What does make v1 and v2 different is (a) and
part 2, deliberately: that is the increment.

### Part 1(c) — the same defect, 57 more times

Not planned. `tests/harness/test_corpus_negatives.py` was written to assert
"no case-sensitive `contains` on a summary" as a tripwire against the fixed
defect returning, and it went red on the first run naming **57 checks in 20
files** — `Kestrel`, `otters`, `copper`, `planning`, `Tuesday`, `1874` — every
one of which passes today only because the model happened not to open a
sentence with that term.

A check that is correct by luck reports a content failure on the day the luck
runs out, which is the entire story of ADR 0123's three 0.75s. All 57 are now
`(?i)` regexes over `re.escape(value)`. Score before and after: identical,
byte for byte.

### Part 2 — nineteen recordings, seven true negatives

**How they were obtained.** `sum-21`…`sum-28` through `aef loop bootstrap
--inputs … --config …` (train only — that is a rule in `bootstrap.py`, not a
default, and there is no flag to override it); `sum-29`…`sum-39` through `aef
loop record --split validation --check …`, one invocation each, because
bootstrap cannot write validation. **Every check was written before its run**,
in the inputs file or on the command line — the strongest available order,
since a check authored after reading the answer can be shaped to fail it.
No scenario carries an `expected` label: these are not tripwires, and
`record_run`'s MUST_FAIL guard was never engaged.

The recording config is `docs/research/i13/aef.measurement.yaml` with one line
changed — `model: claude-opus-5` becomes `model: ""` — because
`ClaudeCodeProvider` appends `--model` only when the string is non-empty, and
the session default is what the judge answers on.

The inputs were chosen to be handled badly, one family per scenario: a finding
stated by negation; a superseded figure the passage opens with; two
similarly-named entities with opposite outcomes; a measurement whose unit
competes with four other numbers; a permission worthless without its
conditions; a rate that fell while the count rose; a proper name that could be
confused with a second site; and caps from 12 to 38 words.

**Seven fail an owner check** — 3 in train, 4 in validation:

| id | split | cap | words | what fails | owner's one-sentence justification |
|---|---|---|---|---|---|
| `sum-22-marlowe-street` | train | 30 | 31 | `max_words` | the owner asked for at most 30 words and the summary is 31 |
| `sum-25-hollin-bridge` | train | 25 | 26 | `max_words` | at most 25 words, delivered 26 |
| `sum-26-netherby-clinic` | train | 30 | 31 | `max_words` | at most 30 words, delivered 31 |
| `sum-30-ganister-tarn` | validation | 28 | 30 | `max_words` | at most 28 words, delivered 30 |
| `sum-33-cotterdale-bus` | validation | 25 | 26 | `max_words` | at most 25 words, delivered 26 |
| `sum-35-priory-gatehouse` | validation | 28 | 30 | `max_words` | at most 28 words, delivered 30 |
| `sum-36-larkfield-quarry` | validation | 38 | 41 | `max_words` | at most 38 words, delivered 41; the cap was deliberately roomy so that length would not be the failure, and it was anyway |

The twelve that pass are positives and are kept as positives; a corpus needs
both sides.

**Three checks were widened before anything was called a negative**, and this
is the part a reader should be most sceptical of, so each is stated with the
text that provoked it:

| id | check as written | what the model wrote | why the check was wrong |
|---|---|---|---|
| `sum-21-ardvey-ferry` | `(?i)not overloaded` | "…rejects the operator's claims, finding **no overloading**…" | the inquiry's central finding, correctly stated in other words |
| `sum-22-marlowe-street` | `(?i)divers` | "**diverted** traffic uses nearby Marlow Street" | `divers` does not occur in `diverted`; the diversion is conveyed |
| `sum-29-brindle-viaduct` | `3\.1 million\|3,?100,?000` | "nine months and **£3.1m**" | £3.1m is the revised figure, in the notation the model chose |

Widening a check so a correct answer passes and widening a check so a failure
disappears look identical in a diff. What separates them is that the first
three moved from FAIL to pass and the count of negatives after all the
widening is still 7. `test_corpus_negatives.py` asserts that floor.

**The finding that matters more than the count: all seven negatives are word-
cap overruns.** Every content trap was handled correctly. Negation survived,
superseded figures survived, similar names survived, the unit survived, the
conditions survived, the direction-of-change survived. The three apparent
content failures were my checks, not the model's answers — ADR 0159's lesson
repeating itself inside the increment that exists because of it. On this task,
at this cap range, this agent's one reproducible failure is length.

Score after part 2 (replayed from cassettes, 37 hits, 0 misses):

```
train      mean 0.9675  n=20   3 negatives
validation mean 0.9529  n=17   4 negatives
```

### Part 3 — the judge A/B, re-run

**Pre-registered before any call** (`prereg-v2.txt`, this worker's scratch):
dimension 3 moves 6 → 7 only if (1) part 2 landed with ≥ 6 negatives and ≥ 2
in validation, (2) the LLM judge's AUC on the enriched validation split is
**≥ 0.70**, and (3) the position delta stays **≤ 0.20**. And, stated in
advance because it changes how a 0.5 should be read: all four validation
negatives fail on word count, `LLMJudge` is asked for a "quality" score, and
an AUC near 0.5 would have been evidence that the judge does not measure what
the owner's checks measure — a more useful finding than 0159's, and still +0.

`docs/research/i14/run_i14.py` unchanged (it already accepts `--corpus` and
`--out`). The enriched **validation** split is selected by pointing `--corpus`
at a directory with an empty `train/` and a symlink to the real `validation/`;
`--report` runs against the real `corpus/` and reproduces every table below
from `results-v2.jsonl` alone. Raw judgments in
`docs/research/i14/results-v2.jsonl`, rendered report in `report-v2.txt`;
S3's `results.jsonl` and `report.txt` are untouched.

17 states, **34 live calls**, three foreground batches, 0 fallbacks, every
`stop_reason` `end_turn`, mean 9.7 s per judgment (max 14.4 s).

#### Agreement — both arms, same 17 states, same model

| arm | agrees with the checks | scores observed |
|---|---|---|
| rule-based (`RuleBasedJudge`, no model call) | **4/17** | 0.000 on all 17 |
| LLM (`LLMJudge`, `working_memory` in evidence) | **16/17** | 0.275 – 0.910 |

The split is 13/17 pass, so a constant "pass" scores 13/17. **16/17 beats
that**, which 0159's 15/18-against-a-15/18-baseline did not. Agreement by
threshold: rule 4 at every cut; LLM 13 / 16 / 16 / 16 / 17 at 0.25 / 0.4 /
0.5 / 0.6 / 0.75 — the headline does not rest on where the line is drawn, and
at 0.75 it is unanimous.

#### The 2×2

| | LLM pass | LLM fail |
|---|---|---|
| **rule pass** | 0 | 0 |
| **rule fail** | **14** (13 of them owner-pass) | **3** (0 owner-pass) |

The rule-based arm is still a constant — it answers "fail" to everything,
because this agent writes no `state.scores` and its weighted score is 0.0
everywhere. The LLM arm is **not** a constant any more, which is the whole
difference from ADR 0159.

#### The measurement that decides it: AUC 1.000

| | states | LLM score |
|---|---|---|
| owner-**pass** | 13 | 0.850 – 0.910 |
| owner-**fail** | 4 | 0.275 – 0.635 |

**AUC over all 52 pass/fail pairs: 1.000** — perfect separation, against
0.322 in ADR 0159. The margin is 0.215 (lowest pass 0.850, highest fail
0.635), not a hairline. And the ordering *within* the failures tracks the size
of the overrun rather than being noise:

| id | over cap by | LLM score |
|---|---|---|
| `sum-33-cotterdale-bus` | 1 word | 0.635 |
| `sum-30-ganister-tarn` | 2 words | 0.375 |
| `sum-35-priory-gatehouse` | 2 words | 0.325 |
| `sum-36-larkfield-quarry` | 3 words | 0.275 |

The mechanism is visible and worth naming: the judged state is the reflect
node's `input_state`, whose `working_memory` carries `max_words` alongside the
summary (ADR 0126 put it there). The judge can see the cap and is evidently
counting against it. The scenarios at cap score high — `sum-34` 30/30 → 0.900,
`sum-39` 38/38 → 0.875, `sum-13` 35/35 → 0.850 — so it is not simply
penalising length.

#### Position swap

Max delta **0.17**, mean 0.0424, non-zero on 13/17. Inside the 0.20 threshold
set before running; larger than ADR 0159's 0.06, and the maximum is
`sum-33` — the one-word overrun, the single state the judge got wrong at
threshold 0.5. The judge is least stable exactly where it is least certain,
which is the direction one would want and is stated rather than smoothed.

#### The second oracle is now redundant, and that is the point

`_case_insensitive` (oracle B) exists because the corpus's `contains` checks
were wrong. After parts 1(a) and 1(c) they are all `(?i)` regexes already, so
B rewrites nothing and reports identical numbers to A: 13/17 pass, rule 4/17,
LLM 16/17, AUC 1.000. The defect the second oracle was built to route around
is gone from the data rather than corrected in the report.

## Falsifications, stated before running and how each fired

- **(1) the corpus has real negatives — HELD.** 7 overall, 4 in validation,
  recorded not authored, cassettes pinned, checks written before the runs.
- **(2) AUC ≥ 0.70 — HELD, at 1.000.** Two independent readings agree: the
  agreement count (16/17 against a 13/17 constant) and the separation (no
  owner-fail state scores above any owner-pass state).
- **(3) position delta ≤ 0.20 — HELD.** Max 0.17.

All three fired. **Claim: +1. Dimension 3 moves 6 → 7.**

**Why 7 and not 8.** Two of J0's three named gaps for this row are closed —
the A/B is a script with committed data (ADR 0159) and a judge is now scored
against a real model *on a corpus that can tell judges apart* — but the third,
a **self-preference control**, is untouched and is S6's. And the honest
limitation of this measurement is that AUC 1.000 is perfect separation of
**one failure family with n = 4**: every negative is a word-cap overrun, so
what has been shown is that this judge detects that failure, not that it
detects failure. A corpus whose negatives include a term the model dropped or
a fact it inverted would test something this one does not, and nothing here
should be cited as if it had.

## Defects found and not fixed (reported, per this worker's scope)

1. **`answering_model`'s rule 3 misattributed one call again.** 33 of 34
   judge calls resolved to `claude-opus-5[1m]`; **one** (`sum-17-clockmaker`)
   resolved to `claude-haiku-4-5-20251001`. This is ADR 0159's defect 1
   reproducing at almost the same rate (1/36 there, 1/34 here): `LLMJudge`
   asks for JSON only, the answering model sometimes writes ~12 output
   tokens, and the CLI's own helper model writes more, so "the key that
   produced the most output tokens" picks the helper. Provenance only; both
   samples for that state parsed and scored normally. Still unfixed in
   `aef/providers/`.
2. **`aef loop bootstrap` reports "0 of 8 recorded run(s) failed" on a batch
   that produced three content negatives.** Its failure notion is `classify`
   — the outcome class the gates read — and none of these runs raised. The
   message it then prints is the one about a corpus where everything passes
   demonstrating nothing, which is precisely wrong here: the owner's checks
   are in the same inputs file, and the command has them. Not a wrong
   computation, but the report is misleading at the one moment an adopter is
   deciding whether their inputs were good enough. `aef/` is not this
   worker's; recorded for whoever owns it.
3. **`tests/harness/test_cassette_replay.py` pinned the corpus's size**
   (`report["train"]["n"] == 12 and report["validation"]["n"] == 6`) inside a
   test whose subject is "no live call was made". Growing the corpus turned it
   red for a reason unrelated to what it asserts. Fixed here rather than
   reported, because it is a test file and it blocked the green bar: it now
   reads the split sizes off the corpus.

## Mutations

Each performed for real against `tests/harness/test_corpus_negatives.py`,
which is this increment's own tripwire; perturb, run, restore from a
shasum-verified byte backup.

| # | mutation | result |
|---|---|---|
| M1 | widen one negative's `max_words` until it passes (`sum-36` 38 → 45) | 1 failed |
| M2 | widen three validation negatives, leaving one | 3 failed |
| M3 | restore one `contains` on a summary (`sum-01` `Kestrel`) | 1 failed |
| M4 | drop `min_words` from one scenario | 1 failed |
| M5 | set one `max_words` check to disagree with the run's own cap | 1 failed |

5 of 5 caught; the control is green before and after; every restore proved by
sha256 equality with a byte backup taken before the perturbation. M2 trips
three assertions rather than two — the negative floor, the validation floor,
**and** the cap-agreement check, because widening a cap in the check without
touching the run's own `max_words` is exactly what that third assertion is
for.

## Green bar

```
pytest -q                      2251 passed, 5 skipped   (from 2178; +73)
mypy aef examples              Success: no issues found in 132 source files
ruff check .                   All checks passed!
ruff format --check            257 files already formatted
```

`tests/harness/test_container_sandbox.py::test_a_timed_out_container_is_actually_dead`
failed once during an intermediate full-suite run and passes in isolation and
in the final bar; it is a docker-timing flake, unrelated to anything here, and
noted so the next reader does not attribute it to this increment.

## Live budget

**54 calls of the 70 allowed**: 1 quota preflight (ADR 0150's corrected argv —
`is_error false`, `result "OK"`, `input_tokens 2`), 8 bootstrap, 11 record,
34 judge. No call was retried and none was wasted on a malformed invocation —
`aef loop record` parses `--check` before it runs anything, so a bad check
costs nothing.

## Confidence

High on the corpus work: every edit is asserted key-by-key against a byte
backup, the score is diffed before and after each step, and the two
score-neutral migrations are proved neutral rather than assumed.

High on the A/B's numbers: 34 committed calls, regenerable by
`run_i14.py --report`, two statistics agreeing.

**Medium on what the A/B means.** AUC 1.000 over 13 × 4 pairs is a small
sample of one failure family, and the judge's advantage may rest on a
mechanism as narrow as counting words against a cap it can see in the
evidence. The number is solid; its generality is not, and the row's
"Remaining" says so.
