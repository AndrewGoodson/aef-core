# ADR 0127: The scoreboard is under test

## Status
Accepted. Increment I0 of `TO_90_LOOP.md`; record in `IMPROVE_LOG.md`.
Corrects an arithmetic error; **no dimension's score or evidence changes.**

## Context

`docs/research/self-learning-rubric.md` opens with a rule: *a dimension's
score changes only with a cited artifact — never with a sentence saying it
improved. A self-graded number is exactly the failure the trust case warns
about.* The per-dimension rows have honoured that rule for eleven
increments. The **headline total** never did. It was carried forward by
hand as `previous + delta` at each increment and nothing ever recomputed it
from the rows.

The baseline's rows summed to 51 against a stated 50. Every total after it
inherited the point, through nine increments and two nights of work,
including the totals quoted in ADRs, in `IMPROVE_LOG.md`, in
`IMPROVE_LOOP.md`'s status block, and in the report
`docs/research/above-90-2026-09-04.md`.

It surfaced because that report printed a per-dimension breakdown next to
the total for the first time, and the two disagreed.

## Decision

1. **Correct the totals**: baseline 50 → 51, current 84 → 85. Each carries
   a note in the file saying it is a correction to the addition, not a
   re-scoring. No row moves.
2. **`tests/test_rubric_arithmetic.py` recomputes the heading from the
   rows** on every run, and asserts the shape the table actually has: it is
   prepend-ordered history, so the first row for a dimension is its current
   score, and a dimension that has never moved has no row in "Current" at
   all and carries its baseline value (dimensions 4 and 8 today). It also
   asserts every weighted dimension is scored, no score exceeds its weight,
   the row's weight matches the weights table, the weights still sum to 100,
   and each scored section is internally consistent — including the
   baseline, because that is the number every later delta was taken from.
3. **Downstream documents are left as written.** ADRs and log entries are
   dated records of what was believed at the time; rewriting them would
   erase the error rather than record it. This ADR is the correction, and
   the rubric points at it.

## Evidence

```
before: heading 84, rows 19+17+8+14+10+8+5+4 = 85   (dims 4 and 8 carried from baseline)
        baseline heading 50, rows 8+8+3+14+9+3+2+4 = 51
guard against the uncorrected file: 3 failed, 3 passed
after correction:                   6 passed
mutations, each reverted:
  M1 heading one point high              2 failed
  M2 a dimension scores above its weight 3 failed
  M3 a dimension that is not weighted    4 failed
  M4 baseline restored to its old error  1 failed
pytest -q  1820 passed (from 1814; +6, none removed)
mypy aef examples 127 files clean · ruff check/format clean
```

## Consequences

- **The score is 85, not 84**, and 90 is therefore five points away rather
  than six: I12 (+2), the live noise floor (+1), the judge A/B re-run (+1),
  and the Codex smoke (+1). Dimension 7's five points and dimension 4's
  last point remain unclaimed and are not needed to reach 90.
- No dimension's evidence is affected. Every measurement in this programme
  stands exactly as recorded.
- The failure mode is the one this repo keeps finding — a number nobody
  recomputes, two records of one fact drifting (ADR 0091) — this time in
  the document that exists to prevent it. The guard makes the scoreboard
  the same kind of artifact it demands of everything else.

## Confidence

High. The correction is arithmetic and the guard reproduces it.
