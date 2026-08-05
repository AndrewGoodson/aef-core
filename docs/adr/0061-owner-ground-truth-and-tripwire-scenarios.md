# ADR 0061: Owner ground truth, and tripwire scenarios

## Status
Accepted. Fixes the defect recorded in ADR 0060.

## Context
ADR 0060 demonstrated that a one-line change making the agent ignore its
inputs and always report success passes all six gates. The cause: `Outcome`
and `score_of` both read `plan.status` and `errors`, so G2 and G3 ask the
agent whether it succeeded and record the answer.

A recorded trace says the agent **failed**. It does not say that failing was
**correct**. Without that second statement, "the candidate now passes a
scenario the incumbent failed" is ambiguous between *it learned the task* and
*it started lying*, and no threshold distinguishes them.

## Decision

**1. Scenarios carry an owner-supplied `expected` label.**
`UNSPECIFIED` (default) / `MUST_PASS` / `MUST_FAIL`. This is ground truth
about what *should* happen, supplied by a human, separate from the recording
of what did. `UNSPECIFIED` is the default so every existing scenario keeps its
exact prior meaning and the change is backward-compatible.

**2. `MUST_FAIL` is a tripwire.** A candidate reporting success on a task the
owner labelled impossible is not weighed against its other improvements — G2
fails immediately and marks it a **security event**. The reasoning is not
"this scenario went wrong": it is that the agent's self-report has been shown
unreliable, and **every other score is derived from that same self-report**,
so nothing else in the run means anything either.

**3. Tripwires must be impossible in principle, not merely hard.** This was
got wrong first: labelling the existing `difficulty=5` scenarios `MUST_FAIL`
immediately rejected a *legitimate* improvement as reward hacking. Difficulty
5 is hard, and an agent could rightly learn to handle it. The tripwires added
use difficulty 999 and 10,000 — no honest tuning satisfies them, so success
there is definitionally a lie. A test asserts every `MUST_FAIL` scenario has
difficulty ≥ 100, because a mislabelled tripwire silently blocks real
progress.

**4. `MUST_PASS` is a floor** independent of the incumbent: failing one is a
regression even if the incumbent failed it too.

## Consequences
- **Verified both directions.** The reward hack is now rejected by G2 as a
  tripwire hit; the legitimate two-constant improvement still passes all six
  gates and escalates. Both are `@pytest.mark.slow` end-to-end tests.
- **The cheap gates still cannot see it**, and a test records that: G0, G1,
  G4 and G5 all pass the reward hack. Only owner ground truth catches it.
  This is a limit of static and structural checking, not a tuning failure.
- **The corpus now carries an obligation it did not before.** A corpus with
  no `MUST_FAIL` scenario cannot detect reward hacking at all, and a test
  fails if aef-core's drops to zero. Adopting repos must add their own —
  `corpus/README.md` and `LOOP.md` need updating to say so (follow-up).
- Detection is only as good as the labels. An owner who labels nothing gets
  exactly the assurance ADR 0060 describes, which is close to none.

## Alternatives Considered
- **Cost or latency gating** (my own first recommendation). Rejected after
  measurement: the hack is *cheaper and faster*, so efficiency gating would
  have actively rewarded it. Recorded because the idea is superficially
  attractive and will be proposed again.
- **Requiring token cost to correlate with difficulty.** Rejected: it
  encodes "working means spending", which penalises genuine efficiency gains
  and is itself easy to satisfy by burning tokens.
- **An independent oracle re-running the task.** The stronger answer, and out
  of reach: for a general agent, the oracle is another agent, which has the
  same failure mode. Ground-truth labels are the honest approximation.
- **Rejecting any candidate that flips a previously-failing scenario.** That
  is the no-op-only pipeline ADR 0050 already removed.

## Confidence
High on the mechanism — both directions are tested end to end against a real
repository. Medium on sufficiency in general: this catches reward hacks that
**cross a labelled tripwire**, and an agent that degrades only on unlabelled
scenarios still passes. The honest statement is that gate quality is now
bounded by corpus labelling quality, which is a human input — that is a real
dependency, not a solved problem, and Tier-1 auto-merge should stay off until
there is evidence the labels are adequate in practice.
