# ADR 0072: Three defects in the monitor path

## Status
Accepted. Found by `seam-hunter` on its first invocation (ADR 0071), each
reproduced against the real CLI and verified independently.

## Context
`aef loop monitor` composes with the archive and the ledger. Each component
is tested; the composed path is executed by **no test at all**, because the
only code that writes a `MERGED` ledger entry is the auto-merge branch, which
is unreachable while Tier-1 is off. Absence of a caller produced absence of
coverage.

## Defect 1 — the pre-merge baseline was fabricated

`gate()` wrote `{"baseline_pass_rate": 1.0}` into every `MERGED` entry. A
literal. **Nothing in the harness computes a pass rate** — `grep` returns
only the writer and the reader.

`evaluate_window` reads that as "the live pass rate this change must hold
against", so every merged change was judged against a claim that production
was at **100%** before it. Anything below 95% live reads as `REGRESSED`,
which sets `gated_rollback=True`, which **halts the loop permanently** — with
a message blaming the gates for a blind spot they do not have.

An ordinary 90%-pass agent would halt on its first monitored merge.

**Fixed:** no baseline is written. Absence now means *unmeasured*, and an
unmeasured window rolls back (rollback-by-default, ADR 0056) **without**
halting — reverting is right, blaming the gates is not.

## Defect 2 — the rollback restored the change it was reverting

`archive.rollback(root, gid, version, dest)` restores **that version's**
content; `tests/harness/test_archive.py` pins exactly that contract. `monitor`
passed `archive_version` — the version the merge **produced**. So the
rollback reinstated the regressing change, byte for byte.

Worse, there was no correct target to pass instead: `archive.record` is
called from exactly one place, the auto-merge branch, so **no pre-merge state
is ever archived**. `_blessed_baseline` takes `versions[0]`, which is the
first auto-merged candidate, not anything an owner blessed.

**Fixed:** roll back to `version - 1`, and **refuse** with an
`ArchiveError` when no predecessor exists. A rollback with nothing to return
to is a gap in the archive, not licence to reinstate the change.

## Defect 3 — observations were never connected

A deployment writes observations wherever it runs (`aef run --observations
<any path>`). The monitor reads a hardcoded `<state>/observations.jsonl`, and
`aef loop monitor` had **no flag to point it anywhere**. Nothing joined them.

An owner following `LOOP.md` exactly got zero observations, so every window
reported unobserved and **silently reverted every merge**, exit 0.

**Fixed:** `aef loop monitor --observations <path>` copies the deployment's
file into the state directory, and fails loudly if the path does not exist.

## Consequences
- 5 tests covering all three, including the two that matter most: a rollback
  restores the version **before** the merge, and an unmeasured baseline does
  **not** halt.
- **All three were latent.** None can fire while Tier-1 is off, because the
  `MERGED` writer is unreachable. That is precisely why they had no coverage,
  and precisely why they would have fired on the *first* real merge.
- This makes the case against enabling Tier-1 overwhelming rather than
  cautious: the first auto-merged change would have been judged against a
  fabricated baseline and, on regression, "rolled back" to itself.

## Still open
`aef loop` has **no `bless`/`archive` command**, so an owner cannot archive a
baseline even though `LOOP.md` obligation 5 tells them to. The refusal added
above makes the gap loud instead of silent, which is the honest interim, not
a fix.

## Confidence
High: each defect was reproduced against the real CLI by the agent, then
verified independently from source before being recorded. **Not claimed:**
that the monitor path is now sound. Three joins were examined and three were
broken; the remaining composed paths have not had the same treatment.
