# ADR 0019: `StateDelta.plan` replaces, never merges — the shipped example was silently dropping `subgoals`/`reusable_key`

## Status
Accepted

## Context
Fresh logic read of `aef/state/delta.py` (not a field-audit — every field
there already has a real consumer; this is about correctness of the
*merge semantics* themselves). `StateDelta.apply()` treats `plan` as a
full replacement, not a merge, unlike `working_memory`/`scores` (shallow
dict merge) or the append-only list fields. That's a deliberate,
documented design choice — `Plan` is a single coherent object, not a
collection of independent keys — but it's also a real footgun: a node
that wants to change *one* field of an existing plan (its `status`, most
commonly) must reconstruct the entire `Plan`, and if it does so with
`Plan(goal=..., status="done")` instead of starting from the existing
plan, every other field — `subgoals`, `reusable_key` — silently reverts
to its default.

`examples/hello_agent`, the one example this repo ships, did exactly
that: `summarize_node` built `Plan(goal=prior_goal, status="done")` from
scratch. In `hello_agent`'s own graph this happened to be harmless — its
plan never has subgoals or a reusable_key set — but it demonstrated the
unsafe pattern as if it were normal, which is worse than not having an
example at all: a future node author copying this pattern into a graph
where the plan *does* accumulate subgoals would silently lose them with
no error, no test failure, nothing — exactly the "plausible-looking
function that lies" failure mode this whole night's work has been
hunting for, just found in documentation-by-example rather than in
production code.

## Decision
Fixed `summarize_node` to use `state.plan.model_copy(update={"status":
"done"})` when a plan already exists, falling back to constructing a
fresh `Plan` only when there was none to begin with. Added a comment at
the fix site and a comment on `StateDelta.plan`'s field declaration
cross-referencing each other, so the replace-not-merge semantic is
discoverable from either the interface or the example. Added a direct
unit test for `summarize_node` (not routed through the full graph, since
`draft_node` runs first and would overwrite any seeded subgoals before
`summarize_node` ever saw them) seeding a `Plan` with both `subgoals` and
`reusable_key` set, proving they survive.

## Consequences
- Anyone reading `examples/hello_agent` as a reference for "how to update
  a plan" now sees the safe pattern, not the lossy one.
- The fix required understanding `draft_node` always overwrites the
  initial plan (it runs first, unconditionally), which is why the
  regression test calls `summarize_node` directly rather than seeding
  `AEFState.plan` and running the full graph — a graph-level test would
  never have exercised the code path being fixed.

## Alternatives Considered
- **Make `StateDelta.plan` merge field-by-field like `working_memory`
  does.** Rejected: `Plan` is a nested structure (subgoals are themselves
  `Plan`s) with no obvious per-field merge semantics for the interesting
  case — is `subgoals` supposed to append, replace, or merge-by-index?
  None of those has an obviously correct answer, whereas "replace the
  whole object, and use `model_copy` if you only want to change one
  field" is unambiguous and matches ordinary pydantic/dataclass practice
  everywhere else in this codebase.
- **Only fix the example, skip documenting it on `StateDelta.plan`
  itself.** Rejected: the interface is where a node author looks first;
  the comment there is what actually prevents the next instance of this
  bug, the example fix only cleans up the one instance already shipped.

## Confidence
High — the bug was concretely reproducible (the unsafe reconstruction
pattern demonstrably drops fields any `Plan` with real subgoals would
have), the fix is small and tested with a case specifically designed to
fail against the old code, and the design alternative (field-level plan
merging) was considered and has no clean semantics to fall back on.
