# ADR 0043: Separation of powers — a proposal may not modify its own judge

## Status
Accepted (planning decision; no implementation yet)

## Context
The self-rewiring pipeline judges each proposed wiring against two
standards: the golden-scenario corpus (gate G2) and the evaluation suite
(gate G3). Both are data that lives in the repository alongside the wiring
manifests the proposer edits.

An optimisation process pointed at a metric will, by default, find the
cheapest way to move that metric. If the process can also modify the
metric's definition or the evidence it is measured against, the cheapest
path is to weaken the standard — and the resulting change passes every
gate honestly, because the gates have been redefined. This is reward
hacking in its most direct form, and it is the expected outcome absent a
structural prohibition rather than an exotic risk (`02-risks.md` R1).

## Decision
**A proposal may not modify the standard by which it is judged, in the same
change.** A `WiringCandidate` is rejected outright if its diff touches: the
golden-scenario corpus; the eval suite (`domain_gates` definitions, the
functions they reference, evaluator configuration); the gate pipeline or any
gate's thresholds; `deterministic`/`side_effects` declarations; the removal
of an existing `requires_human_approval=True` edge flag; or anything under
`aef/`.

This is gate **G4**. It is **inviolable**: no configuration flag disables
it, and it runs **before** the expensive gates, so a proposal attempting to
edit its own tests is rejected before it can run them.

The qualifier *"in the same change"* is load-bearing and deliberate. The
corpus and suite **must** be able to evolve — a frozen test suite rots
(`02-risks.md` R4). What is prohibited is the *entity proposing a
behavioural change* simultaneously changing the *standard that judges it*.
Owners may add scenarios, retighten gates, or retire stale cases in
standalone, human-authored commits carrying no wiring change, where "are we
weakening our tests?" is the only question on the table and cannot be
smuggled in beside an attractive-looking improvement.

Agents may **nominate** corpus or suite changes in prose (a rationale
arguing a scenario is wrong is legitimate and useful); the owner decides.
**Nomination is not modification.**

## Consequences
- The most direct reward-hacking path is structurally closed, not merely
  discouraged.
- A G4 violation is treated as a **category signal**, not an ordinary gate
  failure: it means the proposer attempted to alter its judge. Violations
  are reported to the owner even though the candidate is never surfaced,
  and repeated violations are a halt-the-program trigger.
- Test-suite evolution remains possible, preserving the system's ability to
  improve its own standards over time — through the human, deliberately.
- `deterministic`/`side_effects` becoming owner-only closes a subtler
  escape: relabelling a node would let a proposal route around replay
  enforcement and the idempotency contract (`contracts.py:204-210`).
- **Known residual — the split attack.** A proposer could in principle
  weaken the standard in one change and exploit it in a later one. Mitigated
  because corpus/suite edits cannot be agent-proposed at all, by G5's
  cross-proposal drift monitoring, and by invalidating in-flight candidates
  when the standard changes (Q-G4-2).
- **Known residual — indirect goalpost movement.** A `domain_gate` that
  reads a proposer-writable `params` value could be influenced without
  touching the gate's code. Recorded as **Q-G4-1**: audit for this and close
  it, either by requiring gates to be pure functions of state or by making
  the relevant params owner-only.
- **Honest limitation:** G4 is a **scope** control, not an **intent**
  control. It guarantees a proposal cannot rewrite its own tests; it does
  not guarantee the proposal is a good idea. That residual is why the
  owner's diff review is load-bearing (ADR 0042, `02-risks.md` R3).

## Alternatives Considered
- **Allow suite edits if they pass review.** Rejected: it puts the
  weakening of a test in the same diff as an attractive improvement, which
  is exactly the cognitive setting where a reviewer is most likely to wave
  it through. Separating the commits separates the questions.
- **Freeze the corpus and suite permanently.** Rejected: guarantees
  corpus rot (R4) and caps the system's usefulness at whatever the initial
  authors imagined.
- **Rely on the owner's review to catch suite tampering.** Rejected as the
  *primary* control: it is precisely the thing that should not depend on a
  human noticing. Review remains the backstop; the structural rule is the
  front line.

## Confidence
High. The rule is simple, mechanically checkable, and cheap, and the
"in the same change" formulation resolves the real tension (suites must
evolve) without weakening the prohibition. The two named residuals — the
split attack and indirect goalpost movement via params — are recorded as
open questions rather than claimed solved.
