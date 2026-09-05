# ADR 0159: The judge A/B is an artifact now, and it says the corpus cannot grade a judge

## Status

Accepted. Increment S3 of `UPGRADE_LOOP.md` (= I14 of `TO_90_LOOP.md`);
record in `IMPROVE_LOG.md`. **Rubric dimension 3 does not move — +0.** The
artifact exists; the judge was not shown to improve.

## Context

ADR 0123 (I11) reported a judge A/B on the 18 summary states: the rule-based
judge agreed with the owner's checks 3/18 and the LLM judge 9/18. ADR 0126
then found the cause — neither judge's evidence contained the answer — and put
`working_memory` into `_evidence`, but did **not** re-run the A/B. Its own
consequences section says so in a sentence this increment exists to honour:

> **The judge A/B must be re-run before anyone cites 3/18 or 9/18 again.**

J0's independent score (ADR 0151) deducted dimension 3 from 8 to 6 for three
reasons: the A/B "exists only as a docstring citing an ADR — no test, script
or committed data"; "no judge scored against a real model in-repo"; "no
self-preference control". The first two are this increment's; the third is
not (S6's).

I11's numbers were measured on `claude-fable-5-1`, whose quota is exhausted.
A comparison across models is not a comparison, so **both** arms are
re-measured here on the session default.

## Decision

**The measurement is a committed script over committed data.**
`docs/research/i14/run_i14.py` is the whole A/B: `--dry-run` prints the 18
states and the calls it would make and spends nothing, `--live` makes them
and appends one JSON object per state to `results.jsonl` as each judgment
lands, `--report` recomputes every table below from that file alone. The
raw judgments (`results.jsonl`), the quota preflight (`preflight.json`) and
both rendered outputs (`dry-run.txt`, `report.txt`) are in the repo. Nothing
in this ADR is a number only its author saw.

Three choices the script makes, stated because I11 committed no data to read
them off and a reader would otherwise have to guess:

1. **The 18 states** are every `summary_agent` scenario in `corpus/train`
   and `corpus/validation` (`sum-01` … `sum-18`), sorted by id. The two
   holdout scenarios are excluded.
2. **The judged state** is the state the reflect node actually sees in
   production: the `input_state` of the trace record whose `node_id` is
   `reflect`. It is not reconstructed by hand — scenarios load through
   `load_scenario`, checks evaluate through `evaluate_checks`.
3. **Agreement** binarises both sides: the owner's verdict is "pass" iff
   every check holds; a judge's verdict is "pass" iff its score is
   >= 0.5. The definition is checkable rather than asserted — under it the
   rule-based arm can only ever agree on states whose checks fail, because
   this agent writes no `state.scores` and its weighted score is 0.0
   everywhere, and that reproduces I11's 3/18 exactly. `--report` also
   sweeps the threshold, so the headline does not rest on one cut.

**`aef/reasoning/llm_reflection.py`'s docstring no longer carries the
numbers**, only a pointer to `docs/research/i14/`. That is the only change
to code in this increment, and it changes no logic.

## Evidence

Model: **`claude-opus-5[1m]`** (the session default; no `--model` is passed,
so the CLI uses it). Preflight per ADR 0150's corrected argv — `is_error:
false`, `result: "OK"`, `usage.input_tokens: 2`. **36 live calls** (18
states x 2 position-swapped samples), 3 foreground batches of 6 judgments,
mean 9.3 s per judgment (max 11.4 s), 0 fallbacks to rule-based, every
`stop_reason` `end_turn`.

### Agreement with the owner checks — both arms, same 18 states, same model

| arm | agrees with the checks | scores observed |
|---|---|---|
| rule-based (`RuleBasedJudge`, no model call) | **3/18** | 0.000 on all 18 |
| LLM (`LLMJudge`, `working_memory` in evidence) | **15/18** | 0.820 – 0.900 |

The two judges agree with **each other on 0/18**. Agreement is flat across
thresholds 0.25 / 0.4 / 0.5 / 0.6 / 0.75 — 3 and 15 at every cut, so neither
number is an artifact of where the line was drawn.

### The 2x2

| | LLM pass | LLM fail |
|---|---|---|
| **rule pass** | 0 | 0 |
| **rule fail** | **18** (15 of them owner-pass) | 0 |

Every cell but one is empty, and that is the finding. The rule-based judge
answers "fail" to all 18; the LLM judge answers "pass" to all 18. Both arms
are **constant functions** on this corpus.

### Position swap

Max delta **0.06**, mean 0.0228, non-zero on 12/18 — comfortably inside the
0.2 threshold set before running, and down from I11's "0.05–0.2 on 9 of 18".

### The measurement that decides the point: does the LLM judge discriminate?

The corpus is 15/18 pass, so **a judge that answers "pass" to everything
scores 15/18** without reading anything. Two statistics separate a judge from
that constant:

- **AUC (a random owner-pass state scoring above a random owner-fail one),
  45 pairs: 0.322.** 0.5 is no separation; below 0.5 is separation the wrong
  way. The three check-failing states score a mean 0.880 against the passing
  states' 0.864.
- **The second oracle.** ADR 0123 already recorded what the corpus's only
  three failures are: a required term capitalised at the start of a sentence
  meeting a case-sensitive `contains` — `Volunteers`/`volunteers` (sum-07),
  `Swimming`/`swimming` (sum-14), `Landslip`/`landslip` (sum-16). All three
  summaries do mention the term. Re-run with `contains` made
  case-insensitive (`_case_insensitive`, no extra calls), the corpus is
  **18/18 pass and has no negatives at all**: rule-based agrees 0/18, LLM
  18/18, and no judge of any quality can be distinguished from any other.

So the summary corpus cannot grade a judge. Its three negatives are
check-authoring defects rather than content failures, and once they are
corrected there are none left. **This retroactively applies to I11's
9/18 as well**, which was computed against the same oracle.

### What did change, and it is real

With the answer in evidence (`evidence_has_answer` is `true` on all 18
states, confirming ADR 0126's change reaches this path), the LLM judge's
scores moved from I11's blind 0.23–0.50 to **0.82–0.90**, and the position
delta collapsed from up to 0.2 to at most 0.06. The judge's behaviour
changed, measurably and in the direction ADR 0126 predicted. What is absent
is any instrument here that says whether the new behaviour is *better*.

## Falsifications, stated before running and how each fired

- **(a) the measurement is an artifact — HELD.** Script, raw judgments,
  preflight and rendered report are committed; `--report` reproduces every
  table from `results.jsonl` alone.
- **(c) position delta stays small (max <= 0.2) — HELD.** Max 0.06.
- **(b) the LLM judge agrees with the checks materially more often — held in
  the letter, FIRED in substance.** 15/18 against 3/18 is a large
  difference, and if that were the whole story dimension 3 would move. It is
  not: 15/18 is exactly the score of answering "pass" to everything, the AUC
  is 0.322, and correcting the three defective checks leaves the corpus with
  no negatives. Taking a rubric point for a judge measured to be a constant
  function would be the "measured the wrong thing" defect this programme
  keeps finding, applied to its own scoreboard.

**Claim: +0. The artifact exists; the judge did not improve — or rather,
nothing here could have shown it if it had.** Dimension 3 stays at 6/10.
Two of J0's three named gaps for that row are now closed in the repo (the
A/B is a script with data; a judge has been scored against a real model),
and the row can be revisited by whoever builds the corpus that makes them
worth a point. The data is committed, so that decision needs no re-run.

The next increment for dimension 3 is not a better judge — it is **a corpus
with true content negatives**: scenarios whose summary genuinely omits a
required term, contradicts the passage, or exceeds the word cap, with checks
that are right. Until then, and independently, the self-preference control
J0 named is still missing (S6's).

## Defects found and not fixed (reported, per this worker's scope)

1. **`answering_model`'s rule 3 misattributes a terse answer.** 35 of 36
   calls resolved to `claude-opus-5[1m]`; **one** (`sum-13-cider-press`,
   forward sample) resolved to `claude-haiku-4-5-20251001`. When the caller
   passes no model, rules 1 and 2 cannot apply and rule 3 picks "the key
   that produced the most output tokens". `LLMJudge` asks for JSON only, so
   the answering model sometimes writes ~12 output tokens and the CLI's own
   helper model writes more. The docstring's premise — "the helper writes a
   handful, the answering model writes the answer" — is false precisely for
   the judge, the call whose provenance ADR 0154 cared about. It is a
   provenance defect, not a scoring one: both samples for that state parsed
   and scored normally.
2. **The provider records `usage.input_tokens` only, which is 2.** The 72
   input tokens in `report.txt` are not the prompt's cost: the preflight
   shows the same call carrying 935 `cache_creation` and 2,365 `cache_read`
   tokens that `CompletionResult` has no field for. Any future claim about
   per-call cost through `ClaudeCodeProvider` needs those fields first —
   ADR 0126's 4,684-vs-211,470 figures are on a field this code does not
   keep.

## Consequences

- The claim J0 called "asserted, not shown" is now runnable from the repo by
  anyone, in three commands, with the raw data to check it against.
- Nobody should cite 3/18, 9/18 **or 15/18** as evidence about judge quality
  again. The right sentence is: on the summary corpus the rule-based judge
  is constant-fail, the LLM judge is constant-pass, and the corpus has no
  true negatives to tell them apart.
- `agents/summary`'s three "content failures" are re-labelled as check
  defects. Left in place deliberately: they are the corpus's only negatives,
  ADR 0123 already recorded the lesson, and silently editing the scenarios a
  candidate is scored on is a change to the metric, not to this measurement.

## Confidence

High on the numbers — 36 calls, committed, regenerable. High on the
non-discrimination finding: two independent statistics (AUC, the corrected
oracle) say the same thing. Medium on the rubric decision, which is a
judgement call about a pre-registered criterion met in the letter and not in
the spirit; the reasoning and the data are both here so it can be overruled
in one line.
