# ADR 0114: Keep on a branch, never on main

## Status
Accepted. Increment I2 of `IMPROVE_LOOP.md`; record in `IMPROVE_LOG.md`.

## Context

autoresearch's method is one loop: propose, measure, keep if the metric
improved, revert if not, repeat until the budget is spent. Its result came
from *stacking* — twenty kept changes out of seven hundred tries.

This repo had every piece except the stacking. `cycle()` proposes one
candidate from `base_ref`, gates it (G3 now on the task metric of ADR 0113,
with zero per-scenario regression and a null-cohort percentile), and records
the verdict. Then nothing. A candidate every gate passed got
`Disposition.ESCALATE` — correctly, because Tier-1 auto-merge is off on the
trust case's recommendation — and the next cycle proposed from the same
base again. `test_successive_cycles_do_not_compound` pinned that as a
property, and it is one: nothing may compound *into main* unattended.

But "nothing compounds into main" and "nothing compounds" are different
claims, and the loop was living under the second.

## Decision

1. **`run_loop` keeps on a local branch.** `loop/kept` is created from
   `base_ref` if absent. Each turn calls `cycle` with `base_ref` set to the
   kept branch, so the proposal is made from the kept state. If every gate
   passes — `ESCALATE` or `AUTO_MERGE`, the two dispositions that mean
   that — the kept branch is fast-forwarded to the candidate with
   `update-ref` guarded by the expected old value, and a `KEPT` ledger
   event records it. Otherwise the branch does not move.
2. **`main` never moves.** The driver asserts it at the end and raises if
   it did. `decide()` is untouched; `tier1_enabled` is untouched; the merge
   path is untouched. A person reviews `loop/kept` and merges it — the
   loop's gain is that they review ten stacked improvements, not ten
   proposals of the same first one.
3. **Bounded four ways.** Turn count; wall-clock budget checked before
   each turn; a halt from the gates; a turn that produces no candidate.
   Plus a fifth that the field's loops do not need and this one does: **a
   candidate whose tree matches one already rejected in this run stops the
   loop.** The proposer is deterministic from its evidence, and after a
   rejection the base is unchanged, so it would propose the identical diff
   forever and each re-gate costs N+2 corpus passes to learn nothing.
4. **`KEPT` is its own ledger event**, deliberately not `MERGED`: the
   monitor rolls merged versions back to their predecessor, and a kept
   candidate never reached the place it would roll back from.

## Erratum (2026-09-04, ADR 0122)

The evidence below reads turn 2's rejection as G3's. It was G1's: `run_loop` reused one `workdir` for every turn and `trust._prepare_empty_destination` refuses a non-empty workspace, so every turn after the first was rejected with `TrustBoundaryError` before any behavioural gate ran. Found by the I10 worker, fixed with per-turn `workdir/turn-<n>` in the driver; the acceptance test now asserts every gated candidate reached G3. The keep/stack/stop mechanics stand; the specific claim about *why* turn 2 was rejected does not.

## Evidence

Through the real cycle and real gates on the flaky-agent fixture: turn 1
proposed the structural retry from memory, every gate passed, the kept
branch advanced and main did not; turn 2 proposed a numeric tweak *from the
kept state* and G3 rejected it; turn 3 re-proposed the identical tree and
the driver stopped. Kept 1, reverted 1, ledger shows `KEPT` and no
`MERGED`. Nine driver tests against a fake cycle pin keep/revert/stack and
each stop condition; four driver mutations (never advance, propose from
main, ignore the repeated tree, ignore the budget) each failed tests.

## Consequences

- Rubric dimension 1: 13 → 17. What remains is the corpus (eleven demo
  scenarios) and the proposer's range (numeric constants and one
  structural transformation) — the loop can now stack, and has little to
  stack.
- `aef loop run --turns N --budget-minutes M` is the unattended entry
  point. It exits 0 on a bounded stop and non-zero only on a halt, because
  "spent the budget and kept two" is a successful run.
- The kept branch is local state the owner can delete; a second run
  resumes from it. That is the same shape as autoresearch's git history
  and the same shape as this repo's candidate branches, which `cycle`
  already leaves behind.

## Confidence

High on the driver; the number 17 says the loop is complete and the
material it works on is thin.
