# ADR 0087: History must not be editable by what it records

## Status
Accepted. Closes the three findings ADR 0086 recorded as open.

## 1. Replay never validated the state chain

`replay()` reassigned `state = record.delta.apply(record.input_state)` on
every iteration, so **the final state was decided entirely by the last
record.** `_validate_chain` (ADR 0023) checks that node ids and routes chain;
nothing checked that record N+1's input is record N's output.

A trace whose node ids chain perfectly and whose deterministic nodes
re-execute to matching deltas therefore replayed **clean** with forged
`scores`, `objective` and `checkpoint_seq` — precisely because no
deterministic node reads those fields:

```
live final   : scores={} objective='ship the trade'        seq=2
forged replay: scores={'sharpe': 3.4} objective='ship the trade (approved)' seq=4244
```

ADR 0023's stated goal was *"instead of silently producing a wrong final
state with no error"*. It was half-achieved: reordering by node id was
caught, state forgery was not, and the existing test only permuted node ids.

Replay now carries the chain forward from `trace[0].input_state` and refuses
any record whose declared input is not what the previous record produced.

One existing test failed on this change, and it was right to. It hand-built
two records from the *same* state — a trace that never chained. Its intent (a
partial trace not ending in `END` is legitimate) was correct; its fixture
described a run that never happened. The fixture was fixed, not the check.

## 2. `apply` was shallow-pure, and the record aliased live state

`model_copy(update=...)` rebuilds the top-level containers and shares every
nested object. Two consequences, both reproduced:

- The same `StateDelta` applied to two states leaked nested values between
  the results **and back into the delta itself**.
- `NodeExecutionRecord.input_state` aliased the live state, so a node
  mutating a nested structure in place **rewrote the record that is supposed
  to be the history of what it was given**.

Two fixes, because they are two different objects. `apply` deep-copies the
`Any`-typed payloads — that governs apply's *output*. The executor snapshots
the state *before* the node runs — that is apply's *input*, and it is what
the record holds. Fixing only the first left the second reproducing, which
the test caught.

The existing purity test asserted `state.working_memory == {}` and
`state.checkpoint_seq`. Both pass under full nested aliasing, while the test
name reads as if it pins deep purity.

## 3. The ADR 0022 guard stopped at `scores`

`scores` rejected non-finite floats. `working_memory` — the field
`AEFState`'s own docstring names as where per-agent data belongs — accepted
`NaN`, which the first `model_dump_json()` rewrites to `null`. That is
ADR 0022's exact corruption on a different field: the value comes back
looking merely absent, forever.

Now checked on `working_memory`, `retrieved_context`, `tool_results` and
`errors`, walked depth-first, with the error naming the path (`m.pf`,
`xs[1]`) rather than saying something somewhere is non-finite.

## The pattern

Every one of these three had a test that **read as if it pinned the property
and asserted something weaker**: node ids instead of state, top-level
containers instead of nested ones, one field instead of the field family.

That is the same shape as ADR 0078's `inspect.getsource` assertion and
ADR 0079's hand-repaired fixture. A test whose name states a property is a
claim; only its assertions are evidence.

## Consequences
- `apply` deep-copies its payloads and the executor deep-copies each recorded
  input. Both are per-node-execution costs on the `Any`-typed fields only,
  and the recording copy happens solely when `record_trace=True`.
- A hand-assembled trace that does not chain is now rejected. That is a
  behaviour change for anyone constructing traces by hand — which the replay
  module's own docstring already warned was possible and unguarded.

## Confidence
High: each was reproduced before the fix and re-run after, each has a control
asserting the honest path still works, and the incomplete first fix for
finding 2 was caught by its own test rather than by inspection.

**Not claimed:** that the trace is now tamper-evident. Nothing signs it. A
forger who rebuilds a *consistent* chain — recomputing each input from the
previous delta — replays clean, and should: that is a valid trace of a
different run. What is closed is silent corruption, not authorship.
