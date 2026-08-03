# ADR 0002: Phase 0/1 durability backends are InMemory + File(JSON); Postgres/Temporal are typed stubs

## Status
Accepted

## Context
The blueprint specifies a two-tier durability model: a Postgres-backed
"fast path" `StateSnapshot` per super-step, plus a Temporal-wrapped "tier
2" guarantee for cross-worker crash recovery. The report is more
conditional: a Postgres checkpointer "suffices" until a run needs to
survive worker restarts or exceed roughly an hour of wall-clock time (see
ADR 0001). Phase 0/1's own mandate is "working, tested code" for
checkpointing and replay, runnable without standing up external
infrastructure — the `examples/` directory is explicitly scoped to
in-memory backends only.

## Decision
Ship two real, fully-tested `DurabilityBackend` implementations:
- `InMemoryDurabilityBackend` — round-trips every checkpoint through JSON
  serialization (not just Python object references), so the schema
  migration path (`aef.state.load_state`) is genuinely exercised on every
  read, exactly as an out-of-process backend would behave.
- `FileDurabilityBackend` — one JSON file per `(run_id, checkpoint_seq)`
  under a configurable root directory. Survives process restart with zero
  external services, standing in for "a Postgres checkpointer suffices."

`PostgresDurabilityBackend` and `TemporalDurabilityBackend` exist as
classes implementing the same interface, but every method raises
`NotImplementedError` with a pointer to the roadmap. Neither imports
`psycopg`/`psycopg2` nor `temporalio` — since nothing is implemented yet,
nothing vendor-specific needs importing, so these stubs don't create a
vendor-isolation problem for `kernel/` (constraint #3).

## Consequences
- CI and `examples/` need zero external services to exercise checkpointing
  and replay.
- `FileDurabilityBackend` is not safe for concurrent multi-process writers
  (no file locking) — acceptable for Phase 0/1's single-process execution
  model; would need to be addressed before any multi-worker use.
- The moment a real Postgres or Temporal backend is implemented, no caller
  code changes: `Services.durability` already takes any
  `DurabilityBackend`.

## Alternatives Considered
- **Implement `PostgresDurabilityBackend` now, since it's "the honest
  minimum" per the report.** Rejected: doing so would require a live
  Postgres instance in every dev/CI environment for something Phase 0/1
  doesn't functionally need yet (no run here approaches the report's own
  ~1hr/restart threshold). Revisit when a real long-running or
  crash-sensitive workload exists.
- **Implement `TemporalDurabilityBackend` now, per the blueprint's literal
  spec.** Rejected for the same infrastructure-proportionality reason,
  compounded by ADR 0001's decision not to marry Temporal as the default
  substrate.

## Confidence
High for the "don't require infra we don't need yet" reasoning; Medium on
exact Postgres/Temporal adapter shape when it's eventually built, since
that depends on whichever ORM/driver and Temporal SDK version are current
at that time.
