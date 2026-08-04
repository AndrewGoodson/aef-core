# ADR 0036: A node's `fallback_node_id` routes unconditionally, bypassing edge resolution

## Status
Accepted

## Context
Round-1 line-by-line kernel audit found a swallowed-exception defect (rated
High). When a node raises and declares a `fallback_node_id`,
`_execute_node` returned `(error_delta, fallback_node_id)`, which then flowed
through `_resolve_route` — the *normal* routing path, which requires a
declared `Edge` from the node to the target whose `condition` is currently
true. `Graph.validate()` only checks that `fallback_node_id` is a declared
*node*, never that a usable edge to it exists.

So a graph that validates cleanly can have a fallback the executor cannot
reach: with no edge (or an edge whose condition is `False`), routing the
fallback raised `RoutingViolationError` — masking the original exception with
a misleading routing error, and the fallback handler never ran. Reproduced
directly (both the no-edge and false-condition variants) — the original
`ValueError` was recorded in `state.errors` but the run aborted with a
routing error instead of reaching the handler. Every existing fallback test
happened to declare the edge, so this path was untested.

A `fallback_node_id` is an **error handler**. Making it depend on edge
conditions defeats its purpose: the point of "if I fail, go here" is that it
fires *regardless* of the normal routing logic.

## Decision
`_execute_node` now returns `(delta, route, fallback_target)`, where
`fallback_target` is the fallback node id when the node raised and declared
one, else `None`. When `fallback_target` is set, `_run_from` routes to it
**directly**, bypassing `_resolve_route` (and therefore edge-condition
evaluation), checkpoints/cursors the post-node state, and continues. The
target is still validated as a real node by the executor's own per-iteration
node lookup (`no such node` guard) and by `Graph.validate()`'s existing
`fallback_node_id`-is-a-declared-node check. The original exception remains
recorded in `state.errors` and on the node's span (`record_exception`),
unchanged.

## Consequences
- A declared fallback now fires on exception whether or not a declared edge
  to it exists or its condition is true — matching the intent of an error
  handler. Reproduced: both the no-edge and false-condition cases now reach
  the handler and complete.
- No edge is required to a fallback anymore; existing graphs that *do*
  declare a `boom -> safe` edge are unaffected (the edge is simply no longer
  load-bearing for the error path).
- The original exception is preserved in `state.errors`/the span exactly as
  before — this fixes the control-flow masking, not the error recording.
- 305/305 tests (two new: fallback fires with no edge, and with a
  false-condition edge), mypy --strict clean, ruff clean.

## Alternatives Considered
- **Make `Graph.validate()` require a declared edge to the fallback.**
  Rejected: an edge can have a `False` condition and still "exist," so a
  declared-edge check doesn't guarantee reachability at runtime — and more
  fundamentally, an error handler shouldn't be gated by routing conditions at
  all. Requiring the edge would keep the wrong model.
- **Preserve/chain the original exception into the RoutingViolationError.**
  Rejected as insufficient: it improves the error message but still fails to
  run the handler — the fallback would remain unreachable, which is the
  actual defect.
- **Leave fallback going through `_resolve_route`, document the edge
  requirement.** Rejected: documenting a fragile requirement ("your error
  handler needs a true-condition edge or it silently won't run") is worse
  than removing the requirement; it's a footgun either way.

## Confidence
High — the swallow/mask was reproduced before the fix (both variants), the
fix was verified to reach the handler in both, and routing an error handler
unconditionally is the standard, intent-matching semantics. The change is
scoped to the exception path; the normal routing path and its tests are
untouched.
