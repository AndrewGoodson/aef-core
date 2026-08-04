# ADR 0056: Ambiguity rolls back; a rollback the gates missed halts the loop

## Status
Accepted. Implements M10, the final milestone of the self-rewiring program.

## Context
ADR 0045 removed the human from the merge path. It named four mechanisms
that had to replace them and made M10 **load-bearing rather than optional**:
until this exists, Tier-1 auto-merge stays off, because an auto-merge with
nothing watching afterwards is unobserved in both directions.

Three decisions here go against the comfortable option.

## Decision

**1. Ambiguity rolls back.** When the monitoring window closes without
enough observations — or with none at all — the change is **reverted**, not
held pending more data. Reverting a good change costs one re-proposal;
keeping a bad one compounds through every subsequent merge built on top of
it. "Wait and see" is the option that quietly accumulates risk, so it is not
offered. A window that closed with zero live runs is `AMBIGUOUS`, never
`HEALTHY`: absence of evidence is not health.

A regression is acted on **as soon as it is visible**, without waiting for
the window to fill. Waiting while a known regression runs live would be the
monitoring system choosing tidiness over the thing it exists for.

**2. A rollback triggered by a change every gate passed halts the loop.**
It means the gates have a blind spot, and continuing to merge through a
known blind spot is how a system with good local decisions ends up somewhere
bad. The halt turns one bad merge into a bounded incident. An *ambiguity*
rollback does **not** halt — insufficient evidence is not evidence the gates
were wrong.

**3. The kill switch is a file.** `touch <root>/HALTED`. The owner must be
able to stop the loop **without the loop's cooperation**, from a shell,
under stress, without reading documentation. `check()` raises rather than
returning a boolean, so no caller can proceed by ignoring a return value,
and nothing in the harness calls `release()` — a loop that can clear its own
halt has no halt.

**4. The digest reports whether the loop is worth running at all**, not only
whether it is safe. `05-approval-policy.md` §6 makes "no measurable benefit
over the owner editing code directly" a halt criterion, so a digest that
cannot say it is a status page rather than an oversight surface. Rollbacks
are netted out of the accepted count, and a loop that has done nothing
reports `None` rather than `True` — defaulting to true would make a loop
that achieves nothing look like a loop that is succeeding.

## Consequences
- 35 tests. Both headline behaviours are tested directly, including the
  asymmetry between a regression rollback (halts) and an ambiguity rollback
  (does not).
- All five halt criteria from `05-approval-policy.md` §6 are evaluated
  together and each names itself in the output.
- **Tier-1 auto-merge is now buildable, and is still off.** `decide()`
  (ADR 0055) takes `tier1_enabled` and every caller passes `False`.
  Enabling it is an owner action and remains a HARD-STOP — building the
  switch and throwing it are different acts, and only one is reversible
  without consequence.
- Owner defaults now settled with reversible values: Q-A2 monitoring window
  = 20 observations or 7 days; regression margin 0.05; Q-A4 digest cadence
  weekly.
- **Q-A5 (who is notified on a halt, and how) is NOT resolved here.** The
  kill switch and halt assessment produce the signal; delivering it to a
  person who is not watching a terminal needs a channel this repo has no
  configuration for. Left explicitly open rather than defaulted, because a
  notification that goes nowhere is worse than a known gap.
- **Q-A3 (cooling-off delay before a Tier-1 merge) is also not
  implemented.** It is moot while Tier-1 is off, and should be decided when
  it is turned on.

## Alternatives Considered
- **Hold ambiguous changes pending more data.** Rejected: it is the option
  that accumulates unverified merges, and each one makes the next
  attribution harder.
- **Roll back on any post-merge dip.** Rejected: at these sample sizes it
  would revert constantly on noise, and a mechanism that fires on everything
  is ignored, which is worse than one calibrated slightly loose.
- **Kill switch as an API call or config flag.** Rejected: it requires the
  loop to be running and cooperative, which is exactly the condition under
  which you most want to stop it.
- **Halt on every rollback.** Rejected: an ambiguity rollback is the system
  working as designed, and halting on it would make the safe default
  unusable.

## Confidence
High on the decision logic — every rule has a direct test, including the
cases where the safe answer differs from the comfortable one. Medium on the
thresholds (20 observations, 0.05 margin, 7 days), which are owner defaults
with no evidence behind them yet and should move on first real workload.
**Explicitly not claimed:** that post-merge monitoring is as good as a
competent human reviewing every change. ADR 0045 traded one for the other
knowingly, and this milestone builds the replacement — it does not close the
gap that trade opened. Also not claimed: that these four mechanisms are
sufficient to enable Tier-1. That remains an owner judgement, and the halt
criteria exist because it may turn out to be the wrong one.
