# ADR 0092: Numbers nobody supplied

## Status
Accepted. Phase 3 round 4 continued — three declared surfaces with no
supplier, and one metric supplied by the wrong party.

## 1. G3's cost rule read a number the candidate writes

`cost_tokens` is `sum(p.token_cost for p in state.provenance)`, and
`Provenance` is emitted by **agent-authored nodes in their own
`StateDelta`**. Nothing else produces it. Reproduced:

```
reports 1000 tokens   -> cost_tokens=1000
reports 0             -> cost_tokens=0
emits NO provenance   -> cost_tokens=0
```

So a candidate that deletes `provenance=[...]` reports zero tokens, and G3's
cost-blow-up rule — `candidate.cost_tokens / incumbent_cost` — cannot bind.
Same shape as ADR 0080's `recovered` marker, on the cost axis: a number the
thing being measured gets to write about itself.

**Deleting the reporting is not a cheaper agent; it is an agent that stopped
saying.** An incumbent that reported and a candidate that does not is now a
cost violation rather than a free pass.

Note what this does *not* do, and the test says so explicitly: an agent that
**never** reported gives the rule nothing to compare against, and no gate
logic can invent it. ADR 0060 already established that cost gating is the
wrong instrument against reward hacking; this only stops the rule being
trivially switched off where it does apply.

## 2. `GateContext.tracer` had no injector

One production construction site (`loop.py`), passing neither `tracer` nor
`limits`. So `_run_traced`'s traced branch **never executed outside a test**
— the observability of the gate pipeline was unreachable by construction —
and G0's `max_changed_lines` / `max_changed_files` overrides could not be set
by any caller.

Both now come from `LoopConfig`. Verified by running a real gate: four spans
emitted, and `gate_limits={"max_changed_lines": 1}` makes G0 reject.

## 3. `domain_gates` is pluggable in code and not from config

`RuleBasedEvaluator.domain_gates` defaults to `{}` and **nothing in `aef/`
populates it**. `AgentConfig.evaluator.suites` is read by nothing. So
`record.domain_gates` is `{}` in every shipped path and `score_of`'s gate
branch does not fire.

The roadmap marked pluggable `domain_gates` as DONE. At the API level that is
true — you can pass them to the constructor. What was misleading is the
implication that the config surface reaches them. The roadmap now says which
is which, the same correction ADR 0083 made for the audit log.

## The thread, again

ADR 0090's four findings were "the system knew something and the operator did
not". These three are the mirror image: **the operator could declare
something and the system never read it.** A tracer with no injector, limits
with no supplier, config fields with no builder — each looks configurable and
is decorative.

That is the same defect class as ADR 0091's service drift, and it has now
appeared often enough to be worth naming: *a declared injection point with no
production caller is indistinguishable from a missing feature, and reads as a
present one.*

## Confidence
High on all three: each was reproduced by grepping for the supplier, finding
none, and then running the real path to confirm the consequence. Each fix was
verified by running — spans counted, limits binding, the cost rule failing a
provenance-dropping candidate while still passing an honest one within
budget.

**Not claimed:** that `evaluator.suites` now works. It does not; it is
documented as not working, which is the smaller and honest claim. Wiring a
named-gate registry is Phase 2 config work and a larger decision than this
ADR should make.
