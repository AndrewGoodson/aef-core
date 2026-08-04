# ADR 0051: G3 requires a null-hypothesis control cohort

## Status
Accepted. Implements M5. Reverses the `03-roadmap.md` recommendation to
defer the null-hypothesis baseline (Q2).

## Context
G2 establishes a candidate broke nothing. G3 must establish it *helped* —
and the obvious rule, "score better than the incumbent", does not support
that conclusion.

Generate enough random variants of anything and some will score higher on a
fixed set of scenarios by chance. With n≈20 scenarios, the spread of random
mutations comfortably covers the effect sizes a real improvement produces.
"Beats the incumbent" therefore launders chance into evidence, and does so
most often precisely when a proposer is generating many candidates — which
is the operating regime.

The roadmap listed this as deferred (Q2: "accept R1 exposure knowingly").
ADR 0045 then made auto-merge the default path, which removes the human who
would have noticed a stream of plausible-but-worthless merges. Deferring is
no longer defensible.

## Decision
**A control cohort is mandatory. No cohort ⇒ FAIL, not pass.** Absence of a
null hypothesis means the gate has no signal, which is a Tier-2 escalation
(ADR 0045), never an endorsement. A cohort below `min_cohort_size` (5) also
fails: a percentile over three samples is not a threshold.

**The candidate must beat the 95th percentile of the cohort's means** — not
the incumbent. A candidate that beats the incumbent while sitting inside the
random cohort's spread is the null hypothesis holding, and the report says
so in those words rather than leaving a reader to infer it.

**Confidence intervals are reported, never gated on.** At this sample size
they overlap routinely; gating on means would convert noise into a decision
while looking rigorous. What G3 *gates* on is the percentile comparison plus
a deterministic per-scenario rule.

**Zero tolerance on previously-passing scenarios, checked before any
statistic.** A candidate whose aggregate improves while one previously-
passing scenario drops below threshold is rejected. This is the rule that
still binds when the sample is too small for the statistics to say anything
— which is most of the time. A scenario the candidate did not score at all
counts as regressed: a missing score is not a passing one.

**Cost blow-up is rejected** above 1.5× the incumbent's tokens. An
unmeasured (zero) incumbent cost is treated as "nothing to compare", not as
"free" — the same honesty rule as `EvaluationRecord.cost_dollars` staying
`None`.

## Consequences
- 22 tests, including the central one: a candidate beating the incumbent but
  inside the cohort spread is rejected, and the evidence names why.
- G3 cannot pass today, because nothing generates a control cohort. That is
  correct and deliberate — the gate refuses rather than degrades.
- **The cohort generator is not built here.** Producing random mutations
  requires the mutation machinery that M8 introduces. G3 defines the
  contract and the statistics; M8 supplies the cohort. Until then every
  candidate escalates, which is exactly the Tier-2 default ADR 0045
  specifies before M10.
- `score_of` zeroes a record whose domain gate failed rather than averaging
  it away, consistent with ADR 0038.

## Alternatives Considered
- **Defer the cohort (the roadmap's Q2 recommendation).** Rejected: it was
  premised on the owner reviewing every merge, which ADR 0045 removed.
- **Compare means with a t-test.** Rejected: it assumes a distribution the
  scores do not have (bounded, heavily massed at 0 and 1) and would still
  be underpowered at n≈20. The percentile comparison makes no distributional
  assumption.
- **Bootstrap confidence intervals instead of the normal approximation.**
  Deferred, and a genuine improvement — the current CI is reported, not
  gated on, so its imprecision costs nothing today. Revisit when it feeds a
  decision.
- **Let G3 pass when no cohort exists, and flag it.** Rejected: a flag on a
  passing result is not a control. Under auto-merge it would be the
  difference between "escalated" and "merged".

## Confidence
High that requiring a cohort is right, and high on the deterministic
zero-tolerance rule, which is directly tested against a case where the
aggregate improves. Medium on the specific thresholds — p95, cohort size 5,
cost ratio 1.5 — which are owner defaults chosen restrictively and are
reversible; none has evidence behind it yet. **Explicitly not claimed:**
that beating a random cohort proves an improvement generalises. It rejects
one specific null hypothesis on the scenarios measured. The owner-held
rotating holdout exists for the question this cannot answer.
