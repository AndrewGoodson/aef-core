# ADR 0011: `Edge.requires_human_approval`, `requires_deterministic_fallback`, and `Node.telemetry_tags` are now wired up

## Status
Accepted

## Context
Following the same pattern that found the `idempotency_key_fn` gap (ADR
0010) — grep for every declared contract field and check whether anything
actually reads it — turned up three more: `Edge.requires_human_approval`,
`Edge.requires_deterministic_fallback`, and `Node.telemetry_tags` were all
declared, all part of the report/blueprint's node/edge contract, and all
completely inert. `GraphExecutor._resolve_route` matched routes against
declared edges but never inspected either boolean flag; span construction
never read `telemetry_tags`.

`requires_human_approval` is the most severe of the three: constraint #6
requires "irreversible actions require explicit HITL approval above a
configurable risk threshold," and the `PolicyEngine` already implements
exactly that discipline for tool calls (deny-by-default,
`REQUIRE_HITL` above a risk threshold). An `Edge` declaring
`requires_human_approval=True` with zero enforcement is a safety-relevant
gap in the same category, at the routing layer instead of the tool-call
layer — a node could route across a "requires approval" edge exactly as
freely as any other edge, with nothing surfacing that fact anywhere.

## Decision
**`requires_human_approval`:** `Services` gains `hitl_approvals:
frozenset[str]` — a set of pre-granted approvals, keyed by
`hitl_approval_key(from_node, to_node)`. `GraphExecutor._resolve_route`
now raises `HumanApprovalRequiredError` (a new, distinct exception, not
folded into `RoutingViolationError` — this is a deliberate refusal, not a
graph-definition bug) when a matched edge requires approval that hasn't
been granted. The error message includes the exact `Services(...)`
construction needed to grant it, so the caller's remediation is obvious.
Deny-by-default: an edge with no approval in `hitl_approvals` is refused,
consistent with `PolicyEngine`'s existing discipline.

**`requires_deterministic_fallback`:** per blueprint §2.2, this flag
exists so an LLM-decided route lacking a deterministic equivalent "must
say so explicitly and out loud." A boolean nobody reads doesn't say
anything out loud. `GraphExecutor` now emits a dedicated
`aef.edge.emergent_routing` marker span whenever such an edge is crossed
— a real, traced, "out loud" event instead of a silently-declared flag.

**`telemetry_tags`:** now included in the node's span attributes
(`aef.node.telemetry_tags`) whenever a node declares any — the most
mechanical of the three fixes, but the same category of gap (declared,
never surfaced).

**`cost_model`:** deliberately left unwired, and explicitly documented as
such (not silently left inert like the other three were). Its consumers —
the Phase 2 planner's resource budgeting, the Phase 4 evolution engine's
Pareto-aware selection — don't exist yet in this codebase, so there is
nothing for it to be wired *to*. Unlike the three fields above, it never
had a validation rule or safety claim attached that made its inertness
misleading.

## Consequences
- Any graph relying on `requires_human_approval` for safety must now
  explicitly grant approvals via `Services.hitl_approvals` before calling
  `run()`/`resume()` — a graph written against the old (inert) behavior
  that happened to declare `requires_human_approval=True` on an edge will
  now see `HumanApprovalRequiredError` where it previously saw silent
  success. This is the intended, safety-improving behavior change, but it
  is a behavior change worth calling out explicitly for anyone who wrote
  code against the field before it did anything.
- Emergent-routing marker spans add one extra span per crossing of a
  `requires_deterministic_fallback=True` edge — negligible overhead,
  matches the existing pattern of one span per node execution.

## Alternatives Considered
- **Route HITL approval through `PolicyEngine` instead of a new
  `Services.hitl_approvals` field.** Rejected: `PolicyEngine` evaluates
  *tool calls* (`Tool`/`ToolCall`), a different concern from *graph
  routing* (`Edge`s). Conflating them would mean either fabricating a fake
  `Tool` for every HITL-gated edge, or teaching `PolicyEngine` about graph
  topology it has no other reason to know about.
- **Silently allow `requires_human_approval` edges (leave it
  unenforced) and only fix `telemetry_tags`/`requires_deterministic_fallback`.**
  Rejected: this is the one field of the three with a direct constraint
  #6 safety claim attached; leaving it inert while calling Phase 0/1
  "real, tested code" would be the exact kind of "plausible-looking
  function that lies" the build task warned against for stubs, just
  smuggled into what's supposed to be finished code instead.

## Confidence
High on `requires_human_approval` and `telemetry_tags` — mechanically
verified fixes, "attribute lands where it should" is directly testable.
Medium-High on the `requires_deterministic_fallback` marker-span design
specifically: it's a reasonable interpretation of "explicitly and out
loud," but the blueprint doesn't prescribe exactly what "out loud" should
mean mechanically, so a future Phase 5 multi-agent coordination
implementation may want something richer (e.g., writing to a dedicated
audit log, not just a trace span).
