# ADR 0009: Resuming a run requires a persisted "cursor," not just the checkpointed state

## Status
Accepted

## Context
This wasn't a design decision made up front — it was a real bug found by
testing, not theorizing about, the claim that checkpointing supports
crash recovery and human-in-the-loop pause/resume (report §2.3 tier 1,
blueprint §2.3: "sub-second time-travel debugging and human-in-the-loop
pause/resume").

`GraphExecutor.run()` always starts execution at `graph.entry_node`. The
original assumption was that "resuming" a crashed or paused run meant
loading its latest checkpoint (`DurabilityBackend.load_latest(run_id)`)
and calling `run()` again with that state. Testing this directly
(a 3-node linear graph, crashed after 2 of 3 nodes via a capped
`max_steps`, then "resumed") showed it does not work: `run()` restarts at
`entry_node` and re-executes every node again against the already-advanced
state, because `AEFState` has no field recording which node was about to
execute next. Concretely, `working_memory["visited"]` ended up
`["a", "b", "a", "b", "c"]` instead of `["a", "b", "c"]` — nodes `a` and
`b` ran twice. For any node with real side effects (a tool call, a write
to an external system), that's a duplicated action, not just cosmetically
wrong state.

## Decision
Track a small per-run "cursor" — the id of the node that should run next,
or `None` once the run has reached `END` — as a first-class part of what
`DurabilityBackend` persists, saved alongside every checkpoint:

```python
def save_cursor(self, run_id: str, next_node: str | None) -> None: ...
def load_cursor(self, run_id: str) -> str | None: ...
```

`GraphExecutor.run()`'s loop body was factored into a shared `_run_from(state,
start_node)` helper. `run()` calls it starting at `graph.entry_node`, as
before. A new `GraphExecutor.resume(run_id)` loads the latest checkpoint
*and* the saved cursor, and calls `_run_from(state, cursor)` — genuinely
continuing from wherever the run left off. Resuming an already-completed
run (cursor is `None`) is a safe no-op that returns the final state
unchanged; resuming an unknown `run_id` raises a clear `GraphExecutionError`
rather than silently starting a "new" run.

The cursor deliberately lives in the durability backend, not in
`AEFState` itself — it's control-plane bookkeeping (which node is next),
not domain state a node would ever want to read or reason about, and
keeping it out of `AEFState` avoids another schema-migration surface for
something that's purely an execution-engine concern.

## Consequences
- `DurabilityBackend` gained two abstract methods; both `InMemoryDurabilityBackend`
  and `FileDurabilityBackend` implement them (in-memory dict / a `cursor.json`
  sidecar file, respectively). `PostgresDurabilityBackend`/`TemporalDurabilityBackend`
  stubs gained two more `NotImplementedError` methods, consistent with
  everything else on those classes.
- `run()`'s restart-from-entry-node behavior when handed a loaded checkpoint
  is now *documented* as a known footgun (module docstring in
  `aef/kernel/executor.py`) and pinned down by a dedicated regression test
  (`test_run_does_not_resume_it_restarts_and_duplicates_side_effects`) —
  the wrong behavior is now a deliberate, visible contract rather than an
  undocumented trap someone discovers in production.
- Any future `DurabilityBackend` implementation must implement
  `save_cursor`/`load_cursor` correctly for `resume()` to work — this is
  now part of the interface, not optional.

## Alternatives Considered
- **Add a `next_node` field to `AEFState`.** Rejected: conflates
  control-plane execution bookkeeping with the domain state schema nodes
  read and write, and would mean every schema migration going forward has
  to think about an execution-engine-internal field alongside the fields
  agents actually care about.
- **Encode the cursor as a reserved key in `working_memory`.** Rejected:
  `working_memory` is meant to be a node-owned bounded scratchpad (report
  §5); leaking executor internals into it is exactly the kind of
  control-plane/reasoning-plane conflation the two-plane architecture
  (constraint #1) exists to prevent.
- **Leave `run()`'s restart-from-scratch behavior as the only option, and
  just document "don't do that."** Rejected: crash recovery and HITL
  pause/resume are explicitly claimed capabilities of the checkpointing
  system in both source documents; shipping checkpointing without a way to
  actually resume correctly would be building the "plausible-looking
  function that lies" the build task explicitly warned against, just at
  the system level instead of the function level.

## Confidence
High. This was found and fixed by direct testing against a concrete
before/after reproduction, not inferred from reading the code.
