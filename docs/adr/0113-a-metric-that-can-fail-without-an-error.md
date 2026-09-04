# ADR 0113: A task metric that can fail without an error

## Status
Accepted. Increment I1 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.

## Context

The rubric (`docs/research/self-learning-rubric.md`) scored dimension 1,
"closed measurement loop", at 8/20 and said nothing else could be measured
until it moved. The reason was narrower than "no benchmark": the corpus and
the gates *had* a scalar — `score_of(record)` is `task_completion` zeroed by
domain gates — but `RuleBasedEvaluator` set `task_completion` to 1.0 for
any run whose plan finished with no errors. The only way to score below 1.0
was to raise. A graph that ran cleanly and produced the wrong answer was
indistinguishable from one that produced the right one, so nothing the loop
learned could move the metric except "stop raising". autoresearch's whole
method is one scalar that can go down; this repo's could not.

Reproduced before the fix: `test_without_checks_a_clean_wrong_answer_scores_full_marks`.

## Decision

1. **A scenario carries owner-declared `checks`.** Each is a dotted path
   into the final `AEFState`, one of four operators (`equals`, `contains`,
   `regex`, `exists`), and a value. **Data, never code.** Scenarios are
   files a candidate can read, and the gates re-execute them against
   candidate code; a check that could execute would hand the candidate the
   judge. Malformed checks fail at load (`CheckError`), so a typo cannot
   silently score a corpus 0.
2. **With checks, `task_completion` is the fraction that hold**, still
   zeroed by an error (a right answer followed by a raise did not
   complete) and by a blown wall-clock budget. Without checks it is
   unchanged: a scenario that declares nothing about its answer makes no
   claim, and scoring it lower would invent one.
3. **A scenario may carry `budget_ms`, judged on the runner's stopwatch.**
   Under `fixed_clock` the recorded latency replays verbatim and says
   nothing about the candidate, so `EvaluationRecord.latency_ms` is the
   wrong quantity; the runner times the executor itself and passes
   `elapsed_ms` in.
4. **One scoring function, both paths.** `score_scenario()` is called by
   the in-process runner (`loop score`, tests) and by the isolated suite
   (the gates). Two constructions of a score drift and the drift reads as a
   regression (ADR 0091). A test runs a wrong-answer candidate through the
   isolated path and requires 0.0 there too.
5. **`aef loop score`** reads the metric directly: per split, n, mean,
   stdev, CI95, per-scenario scores, and under `--repeat N` the spread of
   the mean across identical runs — the noise floor an increment must
   clear. Holdout is refused without `--i-am-spending-the-holdout`, the
   recorder's existing rule.

## Evidence

Baseline on the demo corpus: train 0.5000 (n=6), validation 0.4000 (n=5),
repeat spread 0.000000 over three runs. Planted fault (demo success path
writes `scores.quality=0.0`): train 0.1667, validation 0.1000, and only the
five checked scenarios moved. Three mutations on the scorer each failed a
test. Full record in `IMPROVE_LOG.md`.

## Consequences

- G3 now gates on a metric that can see content. A candidate that "fixes"
  a scenario by making it stop raising while still answering wrong no
  longer improves.
- The metric is only as good as the owner's checks, and there are five.
  Recording a scenario without checks is still allowed and still means
  "this is what happened". `loop record` does not yet take `--check`; that
  is a small follow-up, not a design question.
- `expected` (a claim about the task: must pass / must fail) and `checks`
  (a claim about the answer) are deliberately separate fields. Folding one
  into the other is a decision this ADR does not make.
- Rubric dimension 1: 8 → 13. Not the +7 the worklist allowed: keep/revert
  on the metric (I2) is what makes it a *loop*.
- **`elapsed_ms` is not the same quantity on both paths** (added 2026-09-03,
  ADR 0125). One scoring function serves both runners, and it does — but the
  number handed to it differs by construction. `isolated_suite` starts its
  stopwatch in the parent and stops it after the executor returns, and
  between those two points every node body crossed a pipe to a worker
  process and back; the in-process runner has no such hop. Measured on the
  4-node fixture in `seam/repro_budget_isolated.py`, three runs each:
  in-process **0.082 / 0.119 / 0.125 ms**, isolated **0.715 / 0.767 /
  0.790 ms** — roughly 0.18 ms of IPC per node, about 6x the total on a
  graph this small. A `budget_ms` calibrated with `aef loop score` at 5x the
  in-process elapsed (0.417 ms) scores 1.0 in-process and 0.0 at the gate,
  on identical code. The stopwatch is deliberately NOT changed: timing only
  the executor's inner work would stop measuring what a candidate costs to
  run under the gate, and subtracting an estimate of IPC would be inventing
  a number. The fix is disclosure — `aef loop score --help` now says it, and
  a budget should be set from an isolated run, or with roughly 0.2 ms per
  node of headroom.

## Confidence

High on the mechanism; the corpus is small and demo-shaped, which the
number 13 is meant to say.
