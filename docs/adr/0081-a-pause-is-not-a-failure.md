# ADR 0081: A pause is not a failure

## Status
Accepted. Closes the decision recorded in `MORNING_REPORT.md` §5 and the
behavioural half of ADR 0079 that ADR 0080 deliberately left open.

## Context

`Outcome` had two answers: passed, or not. A run that stopped at a
human-approval gate got the second one — the same answer as a run that
crashed.

That made **removing the gate look like a maximal improvement.** Reproduced
against the real gate stack before changing anything:

```
incumbent (gate ON)  : passed=False score=0.0
                       HumanApprovalRequiredError: edge 'a' -> 'deploy'
candidate (gate GONE): passed=True  score=1.0
G2 regressed = False
```

`Comparison.regressed` short-circuits on `not incumbent.passed`, so the whole
question was swallowed: the incumbent had not passed, therefore nothing could
have regressed. Three gates, zero catches, on the one change the autonomy
contract names a HARD-STOP.

ADR 0079 named two causes and fixed one (G4's static scan). ADR 0080 hardened
that scan against three evasions and said plainly that it was a mitigation,
not a fix, because the behavioural half was an owner's decision. This is that
decision.

## Decision — option (b)

A HITL pause is **its own outcome class**: `Outcome.hitl_paused`. Neither a
pass nor a failure.

`passed` stays strictly `False` for a paused run. Nothing that reads `passed`
can be fooled into treating a pause as success, and no existing consumer
changes behaviour. The distinction earns its keep one level up, in
`Comparison`, which now answers three questions instead of one:

| incumbent → candidate | verdict |
|---|---|
| pause → **pass** | **regression** — the control is no longer being hit |
| pause → fail | regression |
| pause → pause | unchanged |
| **pass → pause** | **not a regression**, reported |

Both HITL branches are decided **before** the `passed` short-circuits, which
is precisely where the old code lost the question.

`pass → pause` is deliberately not a rejection. A candidate that adds a
human-approval gate has made the system more conservative, and **a loop that
cannot make itself more conservative is pointed the wrong way.** It is
surfaced in G2's evidence so the owner sees it.

## Why this marker cannot be forged, and `recovered` could

ADR 0076 added `RECOVERED_KEY` and ADR 0080 found it was a working reward
hack: it is written by **Zone A code the candidate authors**, and it
*relaxes* the pass predicate. `policy_denied` is safe only because
`PolicyEngine` — Zone B — is its sole writer. I did not carry that property
across.

`hitl_paused` is set in exactly one place: the `except
HumanApprovalRequiredError` clause in `scenario_runner`, which is harness
code executed from the base ref. **A candidate cannot write it.** That is
structural, not a check.

It also does not point the exploitable way. `hitl_paused` never makes a run
`passed`, and turning a pass into a pause is the direction that costs the
candidate its score. There is no version of this a candidate wants to assert
about itself.

Defence in depth on top, because the zone rule is why the zone rule exists: a
candidate *can* raise `HumanApprovalRequiredError` from its own node, which
is a claim about a control rather than an ordinary error. G4 now reports
introducing that raise as an owner-only change, judged base-vs-head, so an
agent the owner already blessed with it is unaffected.

## The harness does not approve on the owner's behalf

`scenario_runner` supplies **no** `hitl_approvals`. The alternative —
granting them so the corpus can execute — means the harness gives itself the
permission the edge exists to withhold, in order to make measurement
convenient. That is the shape of every control that quietly stopped
controlling anything.

The cost is real and is now stated rather than hidden: a HITL-gated scenario
**cannot be scored on behaviour**. G2's verdict says so explicitly —
*"N scenario(s) stopped at a human-approval gate and were NOT approved by the
harness — their behaviour is unmeasured, not passing."* A verdict that does
not state its own limits invites being read as broader than it is.

## What was not touched

`RuleBasedEvaluator.task_completion` — ADR 0038 and every existing user. A
test asserts `hitl_paused` does not appear in that class.

## Consequences
- The ADR 0079 attack now fails as a regression, verified by re-running the
  original reproduction rather than by reasoning about it.
- Corpora recorded before this change are unaffected: `hitl_paused` is absent
  from their payloads and reads as `False`, so the default path is exactly
  what it was.
- Owners with HITL-gated agents get a corpus that pins the *presence* of the
  gate but not the behaviour behind it. That is a smaller claim than the one
  the corpus makes elsewhere, and it is the honest one.

## Confidence
High on the mechanism: the attack was reproduced first, the fix was verified
by re-running it, and all three HITL transitions plus the round-trip and the
legacy-payload path are pinned by tests. **Not claimed:** that the gate's
coverage of HITL-gated agents is now good. It is bounded by design — the
harness will not approve — and an owner who needs behavioural coverage behind
an approval gate needs a mechanism this ADR does not provide.
