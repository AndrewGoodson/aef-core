# ADR 0066: Harvest promotes failures, to train only, and rejects what will not reproduce

## Status
Accepted. Implements Phase 2b. Discharges the documentation follow-up owed by
ADR 0061.

## Context
A static corpus stops binding as behaviour moves. Every gate is measured
against it, so a corpus that never grows quietly becomes a test of what the
agent *used to* do.

Harvesting needs whole runs — initial state **and** trace. Nothing persisted
them: `--observations` records only pass/fail, which is enough to monitor a
merge and nowhere near enough to rebuild a run as a test case. So
`aef run --record-runs <dir>` is part of this milestone, and tracing is
enabled only when recording is requested, since a trace costs memory
proportional to the run.

## Decision

**1. Failures are promoted automatically; successes only on request.**
Failures carry the information. Auto-promoting successes inflates the pass
rate the gates measure against, drifting the corpus toward "everything
passes" — and a corpus where everything already passes cannot demonstrate an
improvement.

**2. Always TRAIN. No parameter offers otherwise.** If production could write
to validation, the set that gates candidates would be shaped by the same
system being gated. A test asserts `harvest()` has no `split` parameter,
because a flag that exists gets used.

**3. A run that does not re-execute identically is REJECTED, not recorded.**
One admitted flake poisons every future comparison: the cost is not one bad
scenario, it is a corpus nobody can trust. Verification re-runs from the
recorded initial state with the recorded clock and compares the serialised
trace byte for byte.

**4. Rate-limited, counting what already landed today** rather than per
invocation. One bad deploy can produce thousands of failing runs; without a
cap the corpus fills with a single incident and the gates start measuring
that incident instead of the agent.

**5. Harvested scenarios carry `expected=UNSPECIFIED`, always.** Only a human
can say a task *should* have failed. A `MUST_FAIL` the system invented would
be a tripwire it set for itself, which is not ground truth — it is the same
self-report ADR 0060 showed cannot be trusted.

**6. The tripwire obligation is now documented** where it will be read:
`corpus/README.md`, the adopt-emitted corpus README, and `LOOP.md`. All three
state plainly that a corpus with no `MUST_FAIL` scenario cannot detect reward
hacking, and that tripwires must be impossible in principle rather than
merely hard.

## Consequences
- 15 tests, each recording real runs through a real `GraphExecutor` and
  harvesting them.
- The rate limit spans invocations, tested by harvesting twice.
- **The corpus can now grow without a human**, which is what makes the loop
  self-sustaining — and it grows only in the split that cannot influence the
  gates. Validation and holdout remain entirely hand-curated.
- **Nothing writes the runs directory unless a deployment opts in.** Same
  shape as observations: the loop reads what production emits, and emits
  nothing itself. A repo that never passes `--record-runs` gets a corpus that
  never grows, silently — the digest does not yet report that, and it should.

## Alternatives Considered
- **Harvest from checkpoints.** Rejected: `FileDurabilityBackend` persists
  the latest state and a cursor, not the initial state and trace, so a
  scenario cannot be rebuilt from one.
- **Promote everything and let the gates sort it out.** Rejected: the gates
  are measured *against* the corpus, so a corpus polluted by one incident
  makes every subsequent gate result about that incident.
- **Let harvest label obvious failures `MUST_FAIL`.** Rejected on exactly the
  grounds of ADR 0060 — that is the system deciding what should have
  happened from its own record of what did.
- **Sample rather than rate-limit** (take every Nth failure). Deferred: a
  cap is easier to reason about, and sampling under a burst still admits the
  burst's character.

## Confidence
High on the mechanism, all paths tested against real runs. Medium on the
defaults: 5 promotions/day is a guess with a defensible shape and no
evidence. **Not claimed:** that harvested scenarios are *good* scenarios.
They are real failures that reproduce, which is a floor, not a standard — a
corpus grown entirely by harvest would be a record of what broke, with no
coverage of what should never be claimed. The tripwires that catch reward
hacking still have to come from a person.
