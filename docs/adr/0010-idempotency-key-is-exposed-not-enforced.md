# ADR 0010: The kernel computes and exposes `idempotency_key`; it does not enforce idempotency itself

## Status
Accepted

## Context
`Node.__post_init__` (constraint from blueprint §2.1) already required an
`idempotency_key_fn` on any node with `side_effects != pure`. But nothing
in `GraphExecutor` ever called it — the computed key was architecturally
unreachable from inside a node's own `fn` body, since `idempotency_key_fn`
is a sibling field on `Node`, not something passed into the function. A
node wanting to use its own declared idempotency key had no way to get it.

This surfaced while investigating a related, more concrete risk: after
`GraphExecutor.resume()` was added (ADR 0009) to correctly continue a
crashed run from its saved cursor, a node that raises partway through —
*after* it already performed a real side effect (e.g., a successful
external API call followed by a failure parsing the response) — will be
re-invoked by a subsequent `resume()`, because the cursor still points at
that node (the failing super-step was never checkpointed past). Nothing
stops that node's `fn` from firing the same side effect a second time.

The obvious next question was whether the kernel could prevent this
automatically — e.g., a claim-before-execute ledger keyed by
`idempotency_key`, blocking a second invocation. On inspection this
doesn't actually work as a general kernel-level guarantee:
- **Claim before executing `fn`:** blocks *any* retry of that node,
  including one where the first attempt failed before doing anything
  real (e.g., an input-validation error thrown before the API call) —
  over-broad, breaks legitimate retry-after-transient-failure.
- **Claim only after `fn` returns successfully:** doesn't protect the
  exact case that matters — a node that fails *after* its side effect
  already fired never reaches the "mark as done" step, so the key is
  never claimed, and the next retry re-fires the same side effect anyway.

This is not a gap unique to AEF: it's why Temporal's own idempotency model
puts the burden on the Activity to pass its idempotency key to whatever
external system it calls (a payment API, a ticket-creation endpoint,
etc.) — the *external system* is what actually has to dedupe, because
only it knows whether the effect already landed. An orchestrator that
never talks to that system directly cannot make that call reliably on the
node's behalf.

## Decision
`Context` gains an `idempotency_key: str | None` field.
`GraphExecutor._run_from` computes it — `node.idempotency_key_fn(state)`
if the node declares one, else `None` — before calling `node.fn`, so the
node has direct access to its own idempotency key without recomputing it
or reaching into `Node` (which it doesn't have access to). The kernel's
job stops there: it does not maintain a dedup ledger, does not block a
retried invocation, and does not guarantee an at-most-once call to
whatever the node does internally. Making a specific side effect
idempotent is the node author's responsibility, by threading
`ctx.idempotency_key` into the downstream call (a header, a request
field, whatever the target API's own idempotency mechanism expects) —
demonstrated in `examples/hello_agent/graph.py`'s `search_node`.

## Consequences
- A node whose `fn` fails after a real side effect has already fired, and
  is later retried via `resume()`, can still duplicate that side effect —
  this ADR does not close that risk, it clarifies whose responsibility
  closing it is (the node, via the external system's own idempotency
  support) and gives the node the tool it needs (`ctx.idempotency_key`) to
  do so, which didn't exist before.
- `Node.__post_init__`'s existing requirement (an `idempotency_key_fn` on
  any non-pure node) now has a real consumer, not just a validation rule
  nothing reads.
- A node author who keys `idempotency_key_fn` off something too coarse
  (e.g. `lambda state: state.run_id` for a node that legitimately calls
  the same tool multiple times per run with different arguments) will get
  a key that collides across those distinct calls — that's a node-authoring
  mistake this ADR doesn't prevent; the key must capture what makes each
  attempt distinct, same discipline Temporal requires of its Activities.

## Alternatives Considered
- **Kernel-level claim-before-execute ledger.** Rejected: blocks
  legitimate retries of failures that occurred before any real side
  effect, for a guarantee it doesn't actually provide in the case that
  matters most (see Context above).
- **Kernel-level claim-after-execute ledger.** Rejected: provides no
  protection in the exact failure mode motivating this — a side effect
  that fired but whose node then failed before returning.
- **Leave `idempotency_key_fn` as validation-only, undocumented as
  inert.** Rejected: matches the letter of constraint #2's contract but
  ships a field that looks load-bearing and isn't, which is exactly the
  kind of "plausible-looking but doesn't do anything" surface the build
  task's stub guidance warns against for a different reason (stubs) but
  applies here too (a real field, quietly disconnected).

## Confidence
High on the "kernel can't generically guarantee this" architectural
conclusion (it mirrors Temporal's own well-established model). Medium on
whether `Context.idempotency_key` is the complete right shape long-term —
Phase 2+ durability work (a real Postgres/Temporal backend) may want a
richer per-attempt context (attempt count tied to idempotency key,
previous-attempt outcome) that this minimal version doesn't carry yet.
