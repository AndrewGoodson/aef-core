# ADR 0063: A floor that moves with the thing it floors is not a floor

## Status
Accepted. Corrects a claim in ADR 0051 that the code did not deliver.
Records the Phase 1c doc-vs-code audit.

## Context
ADR 0051 states: *"A cohort below `min_cohort_size` (5) also fails: a
percentile over three samples is not a threshold."*

The audit checked that claim against the driver rather than against the gate
in isolation, and it was false.

## The defect
`_gates_with_evidence` constructed the gate as

```python
G3Improvement(verdict=cohort_verdict, min_cohort_size=config.cohort_size)
```

while `CohortBuilder` generates **exactly** `cohort_size` members and raises
if it cannot. So `len(verdict.cohort) < self.min_cohort_size` compares a
number against itself and is **never true**. The guard was dead code from the
moment it was wired.

**Measured:** with the driver's wiring, a two-member cohort passes G3, and
p95 is computed over two samples. With G3's own default floor of 5, the same
cohort fails with the reason ADR 0051 describes.

The gate was correct. Its own unit tests passed, because they constructed
`G3Improvement()` directly and never exercised the driver's wiring. **The
defect lived entirely in the seam between two correct components** — which is
why a doc-vs-code audit that checks claims against the *assembled system*
found it and neither component's tests did.

## Decision
- The driver no longer passes `min_cohort_size`. G3's default (5) stands
  independently of how many members were actually generated.
- `LoopConfig.__post_init__` rejects a `cohort_size` below that floor at
  construction. Otherwise every candidate would be rejected for an undersized
  cohort, discovered one gate run at a time.
- A regression test asserts the driver's source does not reintroduce the
  wiring. Source-text assertions are usually a smell; here the property is
  about how two components are connected, which no behavioural test of either
  component can see.

## Consequences
- ADR 0051's claim is now true as implemented.
- ADR 0053's status is amended: its file-level drift decision was corrected
  by ADR 0058, and the status said nothing about it. A superseded ADR that
  does not say so is worse than a wrong one, because it reads as current.
- 18 of 19 audited claims were accurate; the audit script itself had a false
  negative on this very claim (a non-greedy regex matched the wrong
  `G3Improvement(` call), and it was caught only by reading the source
  afterwards. **An audit tool needs auditing too**, and a claim that comes
  back clean from one imprecise check is not verified.

## Alternatives Considered
- **Make `min_cohort_size` a ratio of the requested size.** Rejected: same
  defect in a more sophisticated costume — it would still move with the thing
  it constrains.
- **Drop the floor entirely** and rely on `cohort_size`'s default. Rejected:
  the floor exists so that a *misconfiguration* fails loudly, and deleting it
  removes the only thing that would notice.
- **Assert on behaviour rather than source text.** Preferred in general, and
  it would need a full pipeline run with a deliberately-undersized cohort —
  which construction now forbids. The source assertion is the cheaper guard
  against the specific regression.

## Confidence
High on the defect and the fix, both measured. Medium on the audit's
coverage: 19 claims across 17 ADRs is not every claim, and it favoured ones
expressible as a one-line assertion. Claims about *rationale* — whether a
design choice was the right one — are not checkable this way and were not
checked.
