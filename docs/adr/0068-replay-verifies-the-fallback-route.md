# ADR 0068: Replay verifies the fallback route; recovery is invisible to the loop

## Status
Accepted. Phase A — graph-engineering audit. Fixes one defect and records a
second as an open limitation.

## A1 — the node contract holds

Every node function in the repo was AST-scanned for environment reads, direct
clock reads, randomness, and self-constructed clients. **Five node functions,
zero violations** (`agents/demo`, three in `examples/hello_agent`,
`aef/reasoning/nodes.py`).

The scanner was first verified against a deliberately-violating node and
caught three of three planted faults — a detector that cannot detect is not a
detector, and "no violations found" from an unverified scanner means nothing.

## A2 — DEFECT: replay trusted a fallback record's route

ADR 0039 established that a fallback record is **trusted, not re-executed**,
because re-running the function would raise the original exception again and
make the trace unreplayable. That is sound for the *delta*.

It was silently extended to the *route*, which is checkable without running
anything.

**Measured:** a trace recorded against a graph whose `work` node falls back to
`safe` was replayed against a graph whose `work` node falls back to `risky` —
both handlers present, both deterministic. **Replay passed.** A live run of
the same graph produced `handled_by=RISKY` and two errors, against the
recording's `SAFE` and one.

The fallback target is part of a node's declared behaviour, and re-executing
the node can never reveal a change to it — the node raises by construction.
Replay now compares `record.route` against the node's current
`fallback_node_id` and raises `DeterminismViolationError` on a mismatch. The
ADR 0039 property is preserved and tested: the raising node is still not
re-executed.

## A3 — composition: three documented behaviours, one real blind spot

Confirmed working as designed, and worth knowing:
- `StateDelta.plan` **replaces**, so a node reconstructing `Plan(...)` drops
  subgoals and `reusable_key` silently. Documented in `delta.py`;
  `hello_agent` uses the safe `model_copy` pattern.
- `working_memory` is last-writer-wins with no record of the overwritten
  value.
- Provenance is append-ordered by execution, not by timestamp.
  `_latency_ms` uses max−min and is therefore order-insensitive.

**The blind spot — a recovered run is indistinguishable from a failed one.**

| | `Outcome.passed` | `task_completion` | `EvaluationRecord.passed` |
|---|---|---|---|
| plan **done**, one transient error retried successfully | False | 0.0 | False |
| plan **failed**, gave up | False | 0.0 | False |

Identical on every axis the loop scores, because `RuleBasedEvaluator` zeroes
`task_completion` whenever `state.errors` is non-empty, and `Outcome.passed`
requires `error_count == 0`.

**Consequence for the loop:** a candidate that makes the agent *recover* from
a transient failure scores exactly like one that changed nothing. Graceful
recovery is unrewardable, so the objective the loop optimises cannot express
one of the more valuable things an agent can learn. `RecordedRun.failed` also
classifies recovered runs as failures, so harvest promotes runs that actually
succeeded.

**Not fixed here.** The fix needs an error entry to say whether it was
recovered from — the same untyped-`AEFState.errors` problem that produced the
`policy_denied` marker (ADR 0064), and changing `task_completion` semantics
touches ADR 0038 and every existing user of `RuleBasedEvaluator`. Recorded as
an open limitation rather than changed inside an audit.

## A4 — fan-out fails loudly

A graph returning a tuple `Route` raises `NotImplementedError` naming ADR
0007, rather than silently taking the first target. Correct as designed.

## Consequences
- 3 tests. The retargeted-fallback case is the reproduction; two controls
  pin that an unchanged fallback still replays and that the raising node is
  still not re-executed.
- **This is the first defect found in the kernel** rather than the harness.
  Six previous ones were all in `aef/harness/`, which had started to read as
  evidence the kernel was sound; it was evidence nobody had looked.

## Confidence
High on A1, A2 and A4 — each measured, and A1's scanner was itself verified.
High that A3's blind spot is real; medium on its severity, which depends on
how often recovery matters for a given agent and cannot be settled from this
repo's demo. **Not claimed:** that the composition audit was exhaustive. Four
interactions were probed out of a much larger space.
