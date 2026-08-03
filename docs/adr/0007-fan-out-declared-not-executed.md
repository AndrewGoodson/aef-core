# ADR 0007: Fan-out is part of the Edge/Route contract but not executed by the Phase 0/1 GraphExecutor

## Status
Accepted

## Context
The blueprint's Edge contract declares `to_node: str | list[str]`
explicitly to support fan-out. Executing fan-out correctly requires
BSP-style super-step semantics (LangGraph's Pregel-inspired model: run all
of a super-step's parallel branches, then merge/join before advancing) —
real concurrency, a defined state-merge policy for concurrent writers, and
barrier synchronization. Implementing a partial or sequential-only version
of this and calling it "fan-out" would be a half-finished implementation
that looks correct in a demo and produces silently wrong results (or
silently serializes what should be parallel) under real use — worse than
not having it.

## Decision
`Edge.to_node` and the `Route` type both accept multiple targets
(`tuple[str, ...]`), so the *data contract* matches the blueprint
verbatim and no future schema change is needed to support fan-out. The
`GraphExecutor._resolve_route` method, however, raises `NotImplementedError`
the moment it sees a multi-target route, with a message pointing at this
ADR and the roadmap. There is no code path that silently does something
plausible-but-wrong with a fan-out route.

## Consequences
- Every node written against AEF today must route to exactly one node (or
  `END`). Any graph design requiring parallel branches must wait for a
  Phase 2 executor upgrade.
- When BSP-style execution is built, it is purely an addition to
  `GraphExecutor` — no change to `Node`, `Edge`, `Graph`, or `AEFState` is
  required, since the contract already anticipates it.

## Alternatives Considered
- **Implement fan-out as sequential branch execution (run each target in
  turn, threading state through).** Rejected: this is not fan-out, it's
  relabeled sequential execution, and would misrepresent what the graph
  actually does under the hood — exactly the "plausible-looking function
  that lies" the build task explicitly warned against for stubs.
- **Drop fan-out from the contract entirely until Phase 2.** Rejected:
  would require a breaking schema change to `Edge`/`Route` later, when
  simply declaring-but-not-executing costs nothing today.

## Confidence
High.
