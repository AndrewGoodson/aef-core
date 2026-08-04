# ADR 0053: Drift is distance from the baseline; rebaselining is rate-limited

## Status
Accepted. Implements M7 (gate G5).

## Context
Every other gate judges one candidate in isolation. A system that accepts
individually-defensible changes forever still ends up somewhere nobody
chose, so G5 asks about the *sequence*.

Two design points needed deciding, and the obvious answer is wrong on both.

## Decision

**1. Drift is distance from the blessed baseline, not the sum of steps.**
Summing per-change diff sizes makes an A→B→A round trip look like two
changes' worth of drift while the system sits exactly where it started.
Measuring the current state against the baseline correctly reports zero.
The metric is the fraction of files in `union(baseline, current)` whose
content differs — a file changed and changed back contributes nothing.

**But churn still consumes the rate budget.** Net displacement of zero does
not make the work free: each change was reviewed, merged, and carried
whatever risk it carried. Rate and drift measure different costs, so they
are counted separately.

**2. Rebaselining is rate-limited, not merely owner-only.** The superseded
G5 spec made rebaselining an owner decision and stopped there. That leaves a
standing-pressure hole (04 §1.9): once the drift budget binds, *every*
subsequent proposal is blocked until someone rebaselines, so the pressure to
rebaseline never lets up. A budget that reliably produces a request to raise
it is not a budget. The rate limit is what makes it one.

An agent-proposed rebaseline is refused as a **security event**, not an
ordinary rejection — it is a proposal about the rules rather than about the
code.

**3. The gate reports its numbers on pass as well as fail.** A budget nobody
can see approaching only ever announces itself by blocking something.

**4. An unreachable budget is refused at construction.** `max_drift` of 0
blocks every change; above 1 can never trip. Neither is a budget, and both
are the kind of misconfiguration that looks like a working control.

## Consequences
- 22 tests, including all three roadmap acceptance cases: accumulated small
  changes hard-stop, A→B→A nets zero drift but consumes rate, and an
  agent-proposed rebaseline is refused.
- G5 escalates rather than passing when there is no blessed baseline — same
  no-signal rule as G2's empty corpus and G3's missing cohort.
- **The drift metric is coarse: file-level, not line-level.** A one-character
  change and a full rewrite of the same file are equal drift. This is
  deliberate for v1 — a line-level metric invites gaming by spreading a
  change thinly across many files, which is the *worse* failure. Revisit
  with evidence.
- Budget values (3 changes / 7 days, 0.5 drift, 1 rebaseline / 7 days) are
  owner defaults chosen restrictively and are reversible. None has evidence
  behind it yet.

## Alternatives Considered
- **Cumulative sum of per-change diff sizes.** Rejected: it charges for
  churn twice (once as rate, once as drift) and misreports a round trip as
  maximal drift.
- **Line-level or AST-level drift.** Deferred: finer, but it rewards
  spreading a change across many files to keep each one small, and the whole
  point of the gate is to catch accumulation.
- **Owner-only rebaselining with no rate limit** (the superseded spec).
  Rejected — the standing-pressure hole above.
- **Auto-rebaseline when the budget binds.** Rejected outright: that is the
  budget deleting itself, which is indistinguishable from having no budget
  while looking like a control.

## Confidence
High on the distance-not-sum decision and on the rate limit; both have
direct tests, including the round-trip case that motivated the first.
Medium on the file-level granularity, which is a known coarseness rather
than a considered optimum. Low confidence in the specific numbers — they are
placeholders with a defensible shape, and the first real workload should
move them.
