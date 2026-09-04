# ADR 0121: An archive, not a ladder

## Status
Accepted. Increment I6 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.
`sample_parents` is implemented, measured, and **off by default**.

## Context

`run_loop` (ADR 0114) keeps on a local branch and proposes the next turn
from the latest kept state: a ladder. The Darwin Gödel Machine's result
came from an *archive*: every kept agent stays, parents are sampled by
score and against how many children they already have, and stepping
stones that scored worse than the leader can still be built on. The rubric
scored dimension 6 at 3/10: lineage linear, no diversity pressure.

## Decision

1. **G3's scores reach the driver.** `GateRun` and `CycleRun` carry the
   candidate's and the incumbent's task-metric means when the behavioural
   gates ran; `None` when a cheap gate rejected first. The KEPT ledger event
   records score, parent, candidate ref.
2. **An archive of kept members with lineage.** Root plus every kept
   candidate, each with its score, its parent, and a children count.
3. **`sample_parents`** chooses the next parent by DGM's rule in
   miniature — a sigmoid of the score, divided by `1 + children` — with a
   seeded RNG so a run is reproducible. The kept branch then points at the
   *best-scoring* member, not the newest. Off, the driver is the ladder it
   was.
4. **A candidate whose tree matches a kept member is a duplicate**: neither
   kept nor counted as reverted, and the loop continues, because a
   different parent may produce something new. A tree matching a rejected
   one still stops the loop (ADR 0114).
5. **Off by default, by measurement.** On the flaky-agent fixture through
   the real cycle and gates, greedy and sampled both keep exactly one
   candidate and one distinct tree; sampling re-draws the root, the
   deterministic proposer re-emits the same structural change, and it is
   skipped as a duplicate. No diversity was gained because the proposer has
   nothing diverse to offer. The knob stays off until a proposer with a
   wider repertoire gives the archive something to sample.

## Evidence

Thirteen driver tests plus the weight test: greedy unchanged by the
archive; lineage recorded and the kept branch on the best score; a
non-greedy parent choice observed under seed 3 (as a duplicate); duplicates
neither kept nor reverted. Four mutations: sampling silently greedy, kept
branch not the best member, duplicates treated as new — each failed tests;
**the novelty term dropped passed every test** until a direct test of
`_parent_weight` was added, and is recorded here as the fourth test-side
hole this program has found in six increments.

## Consequences

- Rubric dimension 6: 3 → 6. The archive, lineage, sampling rule and
  duplicate handling exist and are tested; diversity pressure is measured
  to buy nothing on the current proposer, and the number says that.
- `LoopRun.archive` and `distinct_kept_trees` are the measurement surface
  for whoever widens the proposer.

## Confidence

High on the mechanism; the measured gain is zero and stated.
