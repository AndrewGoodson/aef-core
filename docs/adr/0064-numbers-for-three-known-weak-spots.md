# ADR 0064: Numbers for three known-weak spots, and what they cost

## Status
Accepted. Phase 1d. Quantifies limitations previously stated only
qualitatively, and fixes three of the four.

## Context
Four weaknesses were documented but never measured. Measurement changed the
severity of two of them and reversed the priority.

## 1. Policy detection was ANTI-correlated — removed, not tuned

`outcome.py` inferred policy refusals by substring-matching error text
(`"policy"`, `"denied"`, `"requires_hitl"`, …).

| Input | Detected |
|---|---|
| `"tool call refused: scope web_search_rw not granted"` | **missed** |
| `"HITL gate blocked edge draft->publish"` | **missed** |
| `"guardrail rejected the request"` | **missed** |
| `{"code": "E_SCOPE", "detail": "scope not declared"}` | **missed** |
| `"PolicyDecision.REQUIRE_HITL"` | caught |
| `"connection denied by upstream DNS"` | **false positive** |
| `"the policy document could not be parsed"` | **false positive** |
| `"user denied the cookie banner"` | **false positive** |

**4 of 5 real refusals missed; 3 of 3 innocuous errors flagged.** It fired
more often on the wrong input than the right one — worse than no signal,
because a signal gets acted on. G2 treats a *new* policy denial as a
regression, so a candidate could be rejected for an unrelated DNS timeout.

Replaced with an explicit `policy_denied: True` key that the refused node
sets. Under-counting an unmarked refusal is a known, bounded gap;
mis-counting a timeout as one was neither.

## 2. Drift over-reported insertions by 100× — fixed

Position-wise line comparison treated an insertion as changing every line
after it:

| Change | Reported | True |
|---|---|---|
| insert 1 line at the top of 100 | **1.000** | 0.010 |
| insert 1 line in the middle | **0.505** | 0.010 |
| insert 1 line at the end | 0.020 | 0.010 |

At the default budget of 0.5, **any candidate adding an import to the top of
a file was rejected outright.** This was documented as "over-reports" without
a number, which badly understated it — it made the drift budget a de-facto
ban on insertions.

`difflib.SequenceMatcher` charges an insertion one line wherever it lands:
0.0099 at every position.

## 3. G4's name matching was evadable — fixed

`from aef.kernel import Edge as E` then
`E(..., requires_human_approval=False)` produced **zero findings**. A HITL
gate could be disabled by renaming an import. Aliases are now resolved
(`as` names, `module.Node(...)`, fully-qualified), all four forms tested.

## 4. p95 over 5 samples — measured, NOT a defect

Across 40 seeds against the demo agent: p95 threshold `min=0.4364
max=0.4545 stdev=0.0048`, converging to stdev 0 by cohort size 15. The same
candidate passed under **40/40 seeds**. Seed choice did not flip a decision.

**This is weak evidence and is not a clean bill of health.** The demo agent
has a coarse score space (11 scenarios, two constants, one mutated per cohort
member). A real agent with a continuous score space and many mutable
dimensions could behave differently, and nothing here says otherwise. No
change made; the measurement is recorded so the next person starts from data
rather than from this ADR's confidence.

## Consequences
- One test was updated rather than added: it *pinned* the anti-correlated
  substring behaviour. A test asserting a wrong behaviour is worse than no
  test, because it defends the defect during refactoring.
- `examples/hello_agent` now sets `policy_denied` on its refusal path. Any
  node that can be refused must, or the refusal goes uncounted — this is a
  convention on an untyped field, not a schema, and is therefore a real
  ongoing obligation rather than a solved problem.
- 13 new tests.

## Alternatives Considered
- **Tune the substring list.** Rejected: the false-positive set
  ("denied by DNS", "policy document") is not separable from the
  true-positive set by keywords, because they share the words.
- **A typed `PolicyDenial` error model on `AEFState`.** The right answer, and
  a kernel change touching the state schema and its migrations. Deliberately
  not made in a verification pass; the marker key is the honest interim.
- **Keep position-wise drift and raise the budget.** Rejected: it would hide
  the defect behind a threshold and make the budget meaningless for real
  changes.

## Confidence
High on all three fixes — each was measured before and after. Medium on the
p95 finding, which is one agent with a coarse score space and should not be
read as a general result.
