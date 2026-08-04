# ADR 0058: Drift is line-level; the control cohort mutates the incumbent

## Status
Accepted. Implements M12. **Corrects ADR 0053** (drift granularity) and
**corrects the cohort construction implied by ADR 0054**.

## Context
Every gate was built and tested, and the pipeline still could not pass
anything — not for want of a corpus. `G3Improvement()` was constructed with
no `CohortVerdict`, so it returned FAIL on every run, and `G5RateAndDrift()`
was given no blessed baseline. The gates had no caller feeding them.

Wiring that up and running the whole pipeline against a real single-file
Zone A agent surfaced two defects that inspection had not, and both were in
decisions previously recorded as settled.

## Decision

### 1. Drift is measured in lines, not files. (Corrects ADR 0053.)

ADR 0053 counted the fraction of *files* that differ, reasoning that a
line-level metric "invites spreading a change thinly across many files".

**That reasoning was wrong.** Spreading defeats a *file-count* budget — where
a file counts once however small the change — not a line-count one, whose
denominator is the same however the change is distributed. G0's
`max_changed_files` (ADR 0049) already covers spreading directly.

Worse, file-level granularity is **degenerate for a small agent**. A two-line
change to a one-file agent scored `1.0` — identical to a total rewrite — so
no budget below 1.0 could admit anything at all. The demo agent hit this
immediately: every candidate was rejected by G5 as if it had rewritten the
whole thing.

Drift is now differing lines over the larger of the two line counts,
position-wise. `0.0` unchanged, `1.0` fully rewritten, and a two-line change
to a sixty-line file is `0.033`.

### 2. The control cohort mutates the INCUMBENT, not the candidate.

`CohortBuilder` originally drew its random mutations from the candidate's
source. That asks: *would random further changes to this candidate match it?*

The question G3 exists to ask is: **would a random change to the incumbent
have done as well as this reasoned change to the incumbent?** The cohort must
start where the candidate started.

The difference is not academic and not conservative — it is **backwards**.
Perturbing an already-improved variant frequently preserves the improvement,
so the cohort's scores rise to meet the candidate and the p95 threshold
becomes unbeatable. A candidate that plainly should pass — improving every
previously-failing scenario without breaking one — was rejected as "the null
hypothesis". The gate was not merely mis-calibrated; it could not accept
anything.

A file that does not exist at the base ref now raises rather than falling
back to the candidate: a new file has no incumbent version to mutate, and
pretending otherwise reintroduces the same wrong question.

### 3. One execution answers both G2 and G3.

Materialising a variant and loading its graph is the expensive step, so
`scenario_runner` emits the outcome *and* the score from a single pass, and
the driver hands G2 the candidate outcomes the cohort run already produced.

### 4. The corpus is recorded, never hand-authored.

`aef loop record` promotes a real run into a scenario. A hand-written
scenario encodes what someone *believed* the graph does; a recorded one
encodes what it did, and the difference is exactly the case a corpus exists
to catch. Writing to `holdout` requires `--i-am-spending-the-holdout`;
overwriting an existing scenario is refused outright.

## Consequences
- **The pipeline can now pass a candidate**, proven end to end: a coherent
  change to two constants passes all six gates against a recorded corpus in a
  real git repository, and a change a single random mutation could have
  matched is rejected by G3 with "null hypothesis" in the reason.
- A full G3 evaluation costs **N+2 corpus passes** in subprocesses (7 passes
  × 9 scenarios = 63 scenario executions at the default cohort size). That is
  the price of the claim G3 makes, and `CohortPlan.describe()` reports it into
  the ledger rather than hiding it.
- `aef run --observations` writes the file the monitor reads. Before this,
  nothing wrote it, so every monitoring window reported unobserved — which,
  correctly, rolled everything back. Monitoring with no input is a very
  expensive way to revert.
- The demo agent has **two** tunable constants deliberately. The cohort
  mutates one constant per member, so a single-constant improvement is
  matchable by chance and correctly fails; a coherent two-constant change is
  not. That is the actual claim — reasoned change beats random change because
  it is *coherent*, not because it is larger.

## Alternatives Considered
- **Keep file-level drift and raise the budget.** Rejected: it papers over a
  metric that cannot distinguish a typo fix from a rewrite.
- **Max of file-fraction and line-fraction.** Rejected: strictly more
  conservative, which makes the degenerate single-file case worse, not better.
- **Make the demo agent multi-file so file-level drift works.** Rejected
  outright — that is changing the evidence to fit the instrument.
- **Draw the cohort from previously-rejected candidates.** Rejected (already,
  in ADR 0054): they are selected for having failed, which biases the
  threshold down.

## Confidence
High on both corrections: each was found by running the full pipeline, each
has a direct test, and the cohort fix turned a gate that could accept nothing
into one that accepts and rejects the right things. Medium on the line-level
metric's calibration — it is plainly better than file-level, but position-wise
line comparison treats an inserted line as changing everything after it, so a
pure insertion over-reports. A real diff would be exact; this is not, and the
default budget (0.5) is loose enough that it has not mattered yet.
**Not claimed:** that the seed corpus is adequate for anything but proving
the pipeline runs. It covers no model calls, no tools, no policy denials, and
no multi-node routing.
