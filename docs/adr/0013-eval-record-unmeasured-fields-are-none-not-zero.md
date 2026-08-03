# ADR 0013: `EvaluationRecord.cost_dollars`/`latency_ms` are `None` when unmeasured, not a silent `0.0`; `latency_ms` is now actually computed

## Status
Accepted

## Context
Continuing the field-audit pattern (ADR 0010–0012) into
`aef/services/eval/`: `EvaluationRecord.cost_dollars` and `.latency_ms`
were both typed `float = 0.0` and `RuleBasedEvaluator` — the only real
`Evaluator` in this codebase — never set either one, so every evaluated
run reported exactly `0.0` for both, indistinguishable from "this run
genuinely cost nothing and took no time." The CLI's `aef eval` command
didn't even print them, which is itself a symptom: nobody had reason to
surface numbers that were always zero.

This is the same shape of gap as `idempotency_key_fn` (ADR 0010) —
present in the schema, silently never populated — but the risk here is
misleading data rather than missing enforcement: `tool_call_accuracy` and
`trajectory_quality` already correctly model "not applicable/not
computed" as `None` (see `RuleBasedEvaluator._tool_call_accuracy`
returning `None` when no tools were called); `cost_dollars`/`latency_ms`
had no such escape hatch and defaulted to a number that looks measured.

## Decision
Both fields become `float | None = None`. `RuleBasedEvaluator`:
- `latency_ms` is now genuinely computed — the span between the earliest
  and latest `Provenance.ts` across `state.provenance` (the only timing
  data `AEFState` carries), using `min`/`max` rather than assuming
  provenance entries arrive in chronological order. `None` when fewer
  than two provenance entries exist (no span to compute).
- `cost_dollars` stays `None` deliberately — no pricing table exists
  anywhere in Phase 0/1 to convert `cost_tokens` into a dollar figure,
  and fabricating one (e.g. a hardcoded $/token constant) would be worse
  than an honest "unmeasured": it would silently misprice the moment a
  different model with different pricing is used.

`aef eval`'s CLI output now prints both fields.

## Consequences
- Any code reading `EvaluationRecord.cost_dollars`/`.latency_ms` and
  treating a falsy/zero value as "no cost/no time" will now see `None`
  instead — a `TypeError` on arithmetic is the correct failure mode here
  (forces the caller to handle "unmeasured" explicitly) rather than
  silently computing with a wrong zero.
- `latency_ms` is real for the first time; any Phase 2+ code that wants
  to reason about run duration (e.g., a future planner budgeting time,
  or the eventual evolution engine's cost/latency Pareto axis from
  report §11) now has a genuine number to read instead of always `0.0`.
- `cost_dollars` remains a gap, but an honestly-labeled one — a future
  fix (Phase 2+ token-optimizer or provider-cost-table work) has a clear
  `None` to replace, not a `0.0` to first prove is fake.

## Alternatives Considered
- **Hardcode a rough $/token constant so cost_dollars is "approximately
  right."** Rejected: an approximate number that looks precise is worse
  than an honest `None` — it would be silently wrong per-model (every
  provider/model has different pricing) with no signal that it's an
  estimate, not a measurement.
- **Leave both at `0.0` and just document the limitation in a docstring.**
  Rejected: matches the letter of "document what's not implemented" but
  a caller reading the value has no way to distinguish "documented as
  unmeasured" from "genuinely zero" without reading the docstring first —
  exactly the failure mode `None` exists to prevent.

## Confidence
High on `latency_ms` — directly computed from data already present, unit
tested against exact millisecond spans and against out-of-order
timestamps. High on the `cost_dollars=None` decision as the honest choice
for Phase 0/1; the eventual real fix (a pricing table) is Phase 2+ scope
this ADR doesn't attempt.
