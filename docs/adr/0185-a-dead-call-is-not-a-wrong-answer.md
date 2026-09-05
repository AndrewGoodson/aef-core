# ADR 0185: A dead call is not a wrong answer, and the pairing the mean cannot do

## Status

Accepted. Worker S2b of the upgrade loop. Two increments, both "strengthen or
report": G3 becomes more able to judge honestly under live noise. **No
threshold is lowered.** The p95 rule, the cohort size, the zero-tolerance
rule, the cost ratio and the prose cohort's every constant (ADR 0170) are
byte-for-byte what they were.

> **Two errata, both from ADR 0191.** (1) `is_dead_call`'s second condition
> below is gated on the MODE STRING alone, and a mode string is a request
> rather than a fact: `--cassette-miss live` with no `--config` builds no
> provider, so every cassette miss raised `ModelProviderError: ... no live
> provider to fall through to` and **every scenario in the corpus** was
> classified dead, retried, and excluded from G3 — reproduced, with the same
> numbers giving `G3 FAIL` counted and `G3 PASS` excluded. The classifier now
> takes `live_provider_present` as a third condition and the unconfigured live
> run is refused before it starts. (2) Consequence 3's cost bound is per
> scenario execution, not per call — see the erratum on it below. Neither
> correction lowers a threshold.

Nothing here was measured with a live model call. Every number is either
ADR 0156's committed output (`docs/research/i13/*.json`) or a stub provider —
`impl: command` pointed at a shell script that exits non-zero on chosen
invocations, a real subprocess through the real `CommandProvider`, the same
substitution ADR 0181's offline tests use for `/bin/echo`.

## Context

ADR 0156 measured the live noise floor on `claude-opus-5[1m]`: **mean 0.7639,
spread 0.1666** over 3 repeats of 6 scenarios, and a planted prompt regression
that fell 0.0278 — six times smaller than the noise it had to be seen against.
It left two things for this increment, both stated in its own consequences:

1. *"A third of the floor's spread is transient live-call failure."* Repeat 3's
   `sum-13: 0.00` was a **failed call**, established from token accounting
   (370 tokens against ~465) because nothing in the harness said so. Both a
   provider that raises and a provider that returns `""` give exactly
   `score=0.0000, cost_tokens=0`.
2. *"Per-scenario, paired comparison beats the mean. … A sign test over paired
   scenarios would have flagged the regression where the mean could not. This
   is a change to how a live comparison is read, and it is not made here — it
   is offered to the S-thread with the data to support it."*

Under K1 (ADR 0181) `gates.live_model_calls: true` lets a gate pass execute
live. So every gate pass can now meet (1), and (2) is now about a real gate
rather than a research script.

## A — a dead call is not a wrong answer

### Reproduced

`tests/harness/test_dead_calls.py`, and before that as a script. Four
scenarios, one graph, `--cassette-miss live`, a provider that exits 7 on its
third invocation:

```
s1: score=1.0000 cost_tokens=0 failure=None
s2: score=1.0000 cost_tokens=0 failure=None
s3: score=0.0000 cost_tokens=0 failure='NodeEvaluationError: ModelProviderError:
                                        flaky.sh exited 7: provider fell over'
s4: score=1.0000 cost_tokens=0 failure=None

G3 fail: 1 previously-passing scenario(s) now score below 0.5
         (zero tolerance, regardless of the aggregate)
  evidence: s3
```

The `failure` string was computed and carried all the way to `VariantRun`, and
**nothing read it**. G3 rejected a candidate that answered every scenario it
was asked, for a scenario it was never asked.

### The rule

**Classification** (`scenario_runner.is_dead_call`) — a scenario is a dead
call when its failure chain names a `ModelProviderError` **and the run was
live**. The second condition is load-bearing and is the difference between
this being a strengthening and being a hole:

> Under `cassette_miss="fail"` — the default, and what every replayed gate pass
> uses — no call is ever attempted, so nothing can die. A `ModelProviderError`
> there is `CassetteProvider` reporting a **miss**, which is a *behavioural*
> difference and the strongest signal the replayed path has: ADR 0123 caught
> the very regression ADR 0156 could not see live, scoring it **0.0000 with 36
> misses**. Excusing that as a dead call would throw away the best evidence in
> the gates.

So every replayed run is byte-identical to before, and a test says so
(`test_a_replayed_run_classifies_no_dead_calls_at_all`, and the mutation that
removes the condition fails it).

**Retry once** (`isolated_suite.run_corpus_isolated`). Bounded at one, for two
reasons: an unbounded retry is an unbounded bill on somebody's quota, and the
*second* death is itself the signal — a transient failure usually does not
repeat, a candidate that deterministically kills the provider does. The retry
is counted (`ScenarioResult.retried`) and named in the evidence even when it
succeeded, because a silent extra call is how a bounded retry becomes an
unbounded one nobody notices.

**Exclude, symmetrically** (`CohortVerdict.without`, called by
`G3Improvement`). A scenario dead in **any** arm is dropped from the
candidate, the incumbent **and every control**.

**Refuse past a ceiling.** `MAX_DEAD_FRACTION = 0.25`. Above it G3 returns
`could not judge: N dead call(s) of M scenario(s) (X%)`, which is a FAIL and
therefore an escalation, exactly as an absent cohort is.

### Why excluding is not weakening

Three arguments, in order of how much work they do.

**1. A 0.0 there is a claim nobody measured.** The candidate's prompt was not
evaluated on that scenario. No answer was produced — not a wrong one, not an
empty one, none. Scoring it 0.0 asserts "this candidate fails here", which is
evidence that was never collected. It is not conservatism to enter fabricated
evidence against a candidate; it is the same category of error as entering
fabricated evidence for one, and ADR 0085/0088/0093 are this repo's history of
taking that seriously in the other direction.

**2. The commonest case is that exclusion RAISES the bar.** The threshold G3
gates on is p95 of the *cohort's* means. A cohort has five members and the
candidate has one, so most dead calls land in a control — and a control's dead
0.0 drags its mean down, drags p95 down, and **lowers** the bar the candidate
must clear. This is measured as a test, not asserted
(`test_excluding_a_dead_call_in_a_control_RAISES_the_bar`): the same candidate,
the same numbers, passes when the dead call is counted and fails when it is
excluded.

**3. Symmetry is what makes it a comparison at all.** Dropping a scenario from
the candidate alone would compute its mean over one scenario set and the
threshold it must beat over another. `without` drops from every arm, so the
comparison is like with like on strictly fewer scenarios — and `n=` in the
evidence says how many.

### Why the refusal floor exists

Because the argument above has a limit and the limit is gameable.

`is_dead_call` reads a string. A candidate running under `--cassette-miss live`
can raise `ModelProviderError` from its own node body, or spell the name into
another exception's message, and this function cannot tell that apart from a
provider that genuinely fell over. Nothing reading a string can. So a
candidate could in principle kill the provider on exactly the scenarios it
does badly on, and shrink the comparison until it wins.

Three things bound that, and only the third is a real stop:

- the retry (a deterministic killer still gets excluded, so this bounds nothing
  against a deliberate attacker — it bounds *noise*);
- the symmetry (killing a scenario removes it from the cohort too, so the gain
  is only the difference between what the candidate would have scored there and
  what the cohort scored — often zero, sometimes not);
- **the ceiling.** Past 25% there is no comparison left to win. A candidate that
  makes the provider die is not thereby cleared: it is escalated to a human,
  which is where a candidate whose evidence cannot be gathered belongs.

25% on the six-scenario summary corpus permits exactly one dead call — the
count ADR 0156 actually saw — and refuses at two. That is a choice, and the
honest statement of the residual is: **a candidate can still selectively kill
up to a quarter of the corpus**, and on a corpus this small that quarter is one
scenario. The fix for that is the same as ADR 0156's consequence 2 — more
scenarios — not a tighter fraction, because a tighter fraction on six scenarios
means refusing to judge any live pass at all.

`test_a_candidate_cannot_kill_the_corpus_down_to_a_pass` pins the stop.

### What a re-measured floor would be

Not measured — **re-aggregated** from ADR 0156's own committed per-scenario
data under this ADR's rule, with `sum-13` repeat 3 (the known dead call)
excluded from **both** arms:

| | floor repeats | mean of means | spread | fall vs the planted regression |
|---|---|---|---|---|
| as ADR 0156 reported | 0.8333 / 0.7917 / 0.6667 | **0.7639** | **0.1667** | 0.0278 = **0.17×** the spread |
| dead call excluded | 0.8333 / 0.7917 / 0.8000 | **0.8083** | **0.0417** | 0.0889 = **2.13×** the spread |

The regression arm moves too — 0.7361 → 0.7194 — because the exclusion is
symmetric: `sum-13` repeat 3 leaves both arms or neither. That is the rule
doing what it says, not a thumb on the scale.

> **The bar a future S2c should clear: floor mean 0.8083, spread 0.0417 (Opus,
> ADR 0156's data, dead calls excluded).**

And the consequence worth stating plainly: **under this rule ADR 0156's planted
regression would have been detectable by the mean** — 0.0889 against a 0.0417
spread, 4.0 standard deviations of the means.

Three caveats, because that is a strong claim from a weak sample. This is one
exclusion in three repeats, so removing the worst score of the worst repeat
mechanically raises the floor and shrinks the spread; a spread estimated from
three numbers is barely an estimate; and none of it is a re-run. **Nothing in
the rubric moves on a re-aggregation.** S2c should re-measure and either clear
0.8083/0.0417 or report why not.

## B — the paired statistic, reported beside p95

`paired_sign_test(candidate, incumbent)` runs a two-sided exact sign test over
the scenarios both arms were scored on (dead calls already excluded), and its
result is appended to G3's evidence on **every** verdict:

```
paired: 7 down / 3 up / 8 same (sign test p=0.3438)
paired: candidate scored lower on sum-17-clockmaker@r1, sum-17-clockmaker@r2, …
```

**The p95 rule decides exactly as before.** No branch in
`g3_improvement.py` reads `PairedComparison`, and
`test_the_paired_direction_changes_no_verdict` pins it: two candidates with the
same mean and opposite paired directions get the same outcome and the same
reason string.

### On ADR 0156's data

Pooled over all 18 (scenario, repeat) observations, candidate = the planted
regression arm, incumbent = the floor arm:

| | value |
|---|---|
| mean of means, floor → regression | 0.7639 → 0.7361, fall **0.0278** |
| floor spread | **0.1667** — the fall is 0.17× of it, invisible |
| paired | **7 down / 3 up / 8 same** |
| sign test p | **0.3438** |
| `sum-17-clockmaker` | down in **3 of 3** repeats |
| `sum-18-heron-rookery` | down in **3 of 3** repeats |

The direction is legible where the mean is not. **The significance is not**:
p=0.3438 does not reach 0.05, and per repeat — six pairs, which is what one
real G3 pass sees — the same data gives p = 0.625, 1.0, 1.0. Both facts are
asserted in tests so nobody can later read the line as a verdict.

### Where the two increments join

`sum-13` repeat 3 scored 0.00 because its call died. Paired against the
regression arm's 1.00, that reads as **the planted regression improving a
scenario**. Excluding it removes a false "up":

| | down / up / same | p |
|---|---|---|
| dead call counted | 7 / 3 / 8 | 0.3438 |
| dead call excluded | 7 / 2 / 8 | **0.1797** |

Increment A makes increment B sharper, not blunter. A dead call is not merely
noise in the mean; it is a wrong-signed paired observation.

## Should the paired test ever GATE? Argued, not implemented.

**The case for.** It detects what the mean provably cannot on this corpus.
ADR 0156's regression is real, it is invisible to a 0.0278-vs-0.1666
comparison, and it is visible as two scenarios falling in every repeat. G3's
whole design premise is that means have no power at this sample size — the
module docstring has said so since ADR 0051 — and a paired test is the standard
answer to exactly that, because it removes between-scenario variance, which is
the dominant term when scenarios differ in difficulty far more than arms differ
in quality.

**The case against, and it is the stronger one today.**

- *n is tiny where it counts.* A gate pass scores six scenarios once. Six
  paired observations cannot reach p<0.05 by a sign test even if every one
  moves the same way (2 × 0.5⁶ = 0.031 requires 6 of 6 with no ties — and ties
  are the majority here: 8 of 18). A gate whose statistic can only fire on a
  unanimous sweep is a gate that fires on nothing, or fires on noise if the
  threshold is loosened to compensate.
- *One scenario games it.* With six scenarios, 4-down-2-up and 2-down-4-up are
  one scenario apart. A candidate needs to flip a single scenario to move the
  paired verdict, and unlike the mean there is no magnitude term to make that
  expensive: a 0.05 improvement counts exactly as much as a 0.5 one. The p95
  rule is harder to game precisely because it is an aggregate against a cohort
  the candidate did not choose.
- *There is no cohort in it.* The p95 rule's power comes from comparing against
  **random mutations**, not against the incumbent — that is ADR 0051's whole
  point, and it is why "beats the incumbent" was never allowed to be the rule.
  A paired candidate-vs-incumbent test reintroduces exactly the comparison G3
  exists to refuse. A paired test against the *cohort* would be a different
  proposal and is not this one.
- *It has never disagreed with p95 on real data.* We have one dataset, and on
  it the paired test does not reach significance either. A gate justified by
  "it would have caught the one regression we planted" is justified by a
  statistic that, run properly, did not catch it.

**What would settle it.** A rig where p95 and the paired line **disagree**, run
twice:

1. Build a candidate whose per-scenario pattern is consistently-down-but-small
   (a real prompt change, not a synthetic score table) on a corpus of at least
   ~40 scenarios — ADR 0156 consequence 2's number, where the spread falls to
   about 0.06 and the sign test has room to fire.
2. Score it live, three repeats, alongside a true-null arm (an unchanged prompt
   scored twice, so the "regression" is known to be zero).
3. Record every case where p95 passes and paired flags, and where p95 fails and
   paired says all-same. **Run the whole thing twice**, because a single run
   cannot separate a disagreement from a repeat's noise, and ADR 0156's
   repeat-to-repeat spread is the reason.
4. Gate on the paired test only if the false-positive rate on the true-null arm
   is measured and small at whatever threshold is proposed — a number, with its
   basis, in the shape `docs/trust/promotion-trust-case.md` already uses.

Until then the line is evidence a human reads and the trust case can cite, and
that is all it is.

## Erratum on ADR 0156

ADR 0156's floor — **mean 0.7639, spread 0.1666** — includes a dead call. Its
own text identifies it (repeat 3's `sum-13: 0.00`, "a harness/model failure,
not a content failure") and then, deliberately, keeps it: *"that is a property
of live scoring, not an artefact to be excluded — a gate pass will meet it
too."*

That reasoning was right about the world and wrong about the gate. A gate pass
does meet transient call failure — which is why the gate now **retries it and,
if it repeats, declines to score it** rather than recording a 0.0 it did not
observe. With the rule this ADR adds, a gate pass no longer meets it in the
score. So the floor as published is the floor of a scorer that has since been
changed, and the number a live claim on this suite must clear is the
re-aggregated one above (0.8083 / 0.0417), not 0.7639 / 0.1666.

ADR 0156's verdict is untouched: dimension 1 did not move, and does not move
here either. What changes is which floor the next live measurement is compared
against.

ADR 0156's other reported-not-fixed findings are unaffected by this increment:
its D2 (the ReDoS word cap) and its reporting gap (a 0.0000 that means "the
provider died" being indistinguishable in `loop score --json`) were both closed
by ADR 0166; its third finding, `answered_by = next(iter(model_usage))`, by ADR
0169 — which replaced the guess with an explicit
`CompletionResult.model_attribution`.

## Consequences

1. **Every replayed gate pass is unchanged.** `is_dead_call` is False unless
   `cassette_miss == "live"`, `without(frozenset())` returns the very same
   object, and `tests/harness/test_g3_improvement.py` and
   `tests/harness/test_promotion_safety.py` are untouched and green.
2. **A live gate pass now says what it did not measure.** The evidence names
   every excluded scenario, every rescued retry and the paired comparison. ADR
   0156 had to infer a dead call from split-level token accounting; nobody has
   to do that again.
3. **The retry costs at most one extra call per dead scenario**, and the
   evidence says when it was spent. On the six-scenario corpus the worst case a
   pass can reach before refusing is 6 + 1 extra calls per arm.

   > **Erratum (ADR 0191, F7).** Wrong as written. The retry re-runs the whole
   > SCENARIO, and a scenario costs as many calls as its graph makes.
   > Reproduced on a two-call graph whose provider dies on its fourth
   > invocation: a clean two-scenario run costs 4 calls, the run with one death
   > cost **6** — two extra calls for one dead scenario. The true bound is
   > **one extra scenario EXECUTION**: up to K extra calls for a K-call
   > scenario, and at worst one extra full corpus pass per arm. Still bounded,
   > which is what the retry needed to be; just not this number. The
   > six-scenario figure above holds only because that corpus's graphs make one
   > call each. `test_the_retry_costs_one_extra_SCENARIO_not_one_extra_CALL`
   > pins the correction.
4. **The residual is stated:** a candidate can still kill up to a quarter of the
   corpus and have those scenarios excluded rather than counted against it. On
   six scenarios that is one. More scenarios is the fix, as it was for the
   floor.
5. **The paired line does not gate**, and the evidence that would justify
   changing that is written down above rather than left to judgement.

## Files

- `aef/harness/scenario_runner.py` — `is_dead_call`, `_error_type_chain`, and
  the `dead_call` key on the in-process failure payload.
- `aef/harness/isolated_suite.py` — `ScenarioResult.dead_call`/`.retried`, the
  classification, and the one bounded retry.
- `aef/harness/suite.py` — `VariantRun.dead`/`.retried`, and the union across
  candidate, incumbent and every control.
- `aef/harness/evaluation.py` — `CohortVerdict.dead_scenarios`,
  `.retried_scenarios`, `.without()`.
- `aef/harness/gates/g3_improvement.py` — the refusal floor, the exclusion, the
  paired sign test, the evidence lines.
- `tests/harness/test_dead_calls.py`, `tests/harness/test_g3_dead_calls_and_pairing.py`.

## Mutations

Byte backups, sha256-verified before and after; nothing restored with
`git checkout --`. Six planted, six caught.

| mutation | detected by |
|---|---|
| M1 score the dead call 0 again (drop the exclusion) | 2 failed |
| M2 drop the refusal floor | 2 failed |
| M3 drop the bounded retry | 2 failed |
| M4 classify a replayed cassette MISS as a dead call | 2 failed |
| M5 make the paired line always report all-same | 5 failed |
| M6 exclude from the candidate only (drop the symmetry) | 4 failed |

## Confidence

High that the defect was real and is closed: reproduced from a stub provider
that exits non-zero on a chosen call, fixed, and the mutation that restores the
old behaviour fails a test.

High that no replayed path changed: the classification is gated on the run's
mode, a test asserts it, and the two existing gate suites are untouched.

Medium on the refusal floor's *value* of 25%. It is chosen so that ADR 0156's
observed one-in-six passes and two-in-six refuses; no data says a candidate
attacking the ceiling is likelier at 25% than at 20% or 33%.

Medium-low on the re-aggregated floor. It is arithmetic on three repeats with
one exclusion, not a measurement, and it is labelled as such.

Low on any claim that the paired line generalises. One corpus, one model, one
night's data, one planted regression, and the statistic does not reach
significance on it.
