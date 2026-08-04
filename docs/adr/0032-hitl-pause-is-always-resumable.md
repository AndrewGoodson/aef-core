# ADR 0032: A HITL pause always leaves the run resumable

## Status
Accepted

## Context
The 2026-08-04 architecture review (Finding 2, MEDIUM-HIGH) found that
`GraphExecutor._resolve_route` raises `HumanApprovalRequiredError` *after*
the node fn has already executed and *before* `save_checkpoint`/
`save_cursor` run for that super-step. Two consequences, both reproduced:

- **Reproduction A (unrecoverable run):** when the gated edge is the entry
  node's outgoing edge, the block happens before any checkpoint was ever
  written. `resume()` then raised `GraphExecutionError: no checkpoints
  found ... nothing to resume` — the operator could grant approval but had
  no way to continue the paused run; only a full re-`run()` from scratch
  worked.
- **Reproduction B (re-execution on resume):** with a checkpoint already on
  disk from a prior node, `resume()` after approval re-executes the node
  whose edge was gated (its side effect fired a second time).

External durable-execution research confirmed the framing: LangGraph's
`interrupt()` likewise re-executes pre-interrupt code, and Temporal
activities are explicitly at-least-once — so *re-execution* is the accepted
industry semantics, mitigated by idempotency keys. The unique defect was
Reproduction A: a paused run that cannot be resumed at all is strictly
worse than the peer behavior (both LangGraph and Temporal always persist
enough to resume).

## Decision
`_run_from` now captures the node's `input_state` and wraps the
`_resolve_route` call. When it raises `HumanApprovalRequiredError` and a
durability backend is configured, the executor persists — before re-raising
— a checkpoint of the node's **input** state plus a cursor pointing back at
the current node. On `resume()` after approval, the run reloads that
checkpoint and re-executes the gated node from the same input it originally
had, then proceeds through the now-approved edge.

This deliberately **keeps** at-least-once re-execution of the gated node
(Reproduction B is pinned as accepted behavior, not "fixed"). Making the
gated node *not* re-execute would require persisting mid-super-step pending
state and resuming *after* the gate — the same pending-writes machinery the
review recommended deferring until fan-out (ADR 0007) lands. Building it now
would be a checkpoint-format change nobody needs yet. The mitigation for
double-execution remains the node's `idempotency_key_fn` (required for any
non-pure node by the `Node` constructor), and the kernel still does **not**
itself dedupe on that key — unchanged from ADR 0010, cross-referenced here
so the at-least-once contract stays explicit rather than implied.

## Consequences
- A run gated before its first checkpoint is now resumable: a checkpoint +
  cursor exist at the block, and `resume()` with approval completes
  (Reproduction A fixed).
- The gated node re-executes on resume (Reproduction B), which is honest
  at-least-once semantics matching LangGraph/Temporal — documented, tested,
  and mitigated by idempotency keys, not silently changed.
- For a gate on a *later* node, the block-time persist is idempotent with
  what the prior super-step already wrote (same input-state checkpoint, same
  cursor) — no behavior change there, just a guarantee that holds uniformly.
- 293/293 tests (up from 291; two new: entry-node HITL block is resumable,
  and the gated node re-executes exactly once on resume), mypy --strict
  clean, ruff clean. The atomic-write work from ADR 0031 means this extra
  block-time checkpoint is also crash-consistent.

## Alternatives Considered
- **Resume *after* the gate without re-running the gated node.** Rejected
  for now: needs persisted mid-super-step pending state (pending-writes),
  which the review scoped to the fan-out phase — over-building it here
  contradicts "don't invent a checkpoint-format change nobody needs yet,"
  and the re-execution it would avoid is already an accepted, idempotency-
  mitigated pattern across LangGraph and Temporal.
- **Check approval at node *entry* (before running the node) instead of at
  route resolution.** Rejected: the approval gate is a property of an
  *edge* (`from_node -> to_node`), and which edge a node takes is only known
  *after* the node runs and returns its `Route` — a node can route to
  different targets, only some of which are gated. Checking at entry would
  require pre-computing the route, which is exactly what running the node
  does.
- **Have `_resolve_route` itself do the persist.** Rejected: durability
  sequencing is the executor loop's responsibility (`_resolve_route` is a
  pure routing decision with no durability handle); keeping the persist in
  `_run_from` keeps that separation intact.

## Confidence
High that Reproduction A is fixed (the entry-node HITL block now persists a
checkpoint + cursor and `resume()` completes — reproduced failing first,
then passing). High that keeping at-least-once re-execution is the right
call (it matches documented LangGraph/Temporal semantics and the review's
own analysis; the alternative is deferred infrastructure). The remaining
judgment — whether double-execution of the gated node is acceptable in
practice — rests entirely on node authors honoring the idempotency-key
contract, which is a pre-existing property (ADR 0010), not something this
change weakens.
