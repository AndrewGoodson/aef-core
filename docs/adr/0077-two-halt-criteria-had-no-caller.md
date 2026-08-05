# ADR 0077: Two halt criteria had no caller

## Status
Accepted. Closes the remaining wire-level finding recorded in ADR 0074.

## Context

`assess_halt` implements the five halt criteria from
`05-approval-policy.md` §6. It is called from exactly two places, and
**neither ever computed criteria 3 or 4**:

```python
assess_halt(zone_violation=True)          # loop.py, the gate
assess_halt(gated_rollback=gated_rollback)  # loop.py, the monitor
```

`drift_exhausted_twice` and `consecutive_escalation_rejections` were dead
parameters. Reproduced: two consecutive candidates exhausting the drift
budget left `kill switch engaged: False`.

This is ADR 0065's shape — a correct function with nothing supplying its
input — and the ledger held the evidence for both criteria the whole time.
Two of five safety criteria were decorative.

## Decision

Both are now computed from the ledger and acted on, in the gate, after this
run's own entry is appended so the current candidate counts.

- **Criterion 3** reads the two most recent gated verdicts. A proposer that
  exhausts the drift budget, is told so, and immediately does it again is not
  responding to the signal — which is what "in quick succession" means here.
  An intervening pass resets it.
- **Criterion 4** counts escalations the owner resolved by rejecting,
  backwards from the tail, so one acceptance resets the run. The criterion is
  about a proposer working outside its evidence base, not a lifetime total.

## The near-miss, which is the real content of this ADR

The first implementation matched `"drift" in reason`. G5's *other* failure
message is:

> no owner-blessed baseline to measure **drift** against

— the state **every fresh adopter starts in**. So the criterion would have
halted the loop on the second run of every new repo, for a reason that has
nothing to do with drift.

My own planted-fault check missed it, because I wrote the fault with a
shortened version of the message that happened not to contain the word. The
test caught it only because it used the real string.

The fix is not a better substring. G5 now exports `DRIFT_EXHAUSTED` and the
criterion keys on that marker, so the halt condition no longer depends on
prose that anyone may reword. This is the same move as `POLICY_DENIED_KEY`
and `RECOVERED_KEY` (ADR 0064, ADR 0076): **a control that reads free text is
a control that breaks when someone improves the wording.**

That makes three separate occasions in this program where a detector passed
its own verification and was wrong (ADR 0063, ADR 0073, and this one). The
`reproduce-first` rule "verify a detector against a planted fault" now needs
its own corollary: *plant the fault with the real value, not a paraphrase of
it.*

## Consequences
- The loop can now halt for two reasons it previously only documented. Both
  make it more conservative, never less.
- G5's drift-exhaustion message is keyed by constant; rewording the prose
  after the marker is safe, changing the marker is a deliberate act.

## Confidence
High: each detector is exercised in both directions against planted faults,
including the false-positive case that nearly shipped. **Not claimed:** that
"the two most recent gated verdicts" is the right reading of "in quick
succession" — it is *a* defensible reading of an underspecified phrase in the
approval policy, and an owner who wants a time window rather than a count
should say so.
