# ADR 0026: `FileDurabilityBackend` no longer crashes on stray files or corrupted checkpoints

## Status
Accepted

## Context
Adversarial-construction pass on `aef/kernel/durability.py` (same technique
as ADR 0023: hand-build the malformed input, actually call the code
against it, don't just read the source) — write checkpoint files by hand
into a `FileDurabilityBackend`'s directory and call
`load_checkpoint`/`load_latest`/`list_checkpoints` against them, covering:
a corrupted/truncated checkpoint file, a zero-byte checkpoint file, a
stray non-numeric-stem `.json` file sharing a run's directory, and (via
`aef/state/migrations.py`, read but not modified) a checkpoint written by
an unknown/future `schema_version` — the last of these was already handled
correctly (`NoMigrationPathError`, cycle detection via
`MigrationCycleError`), so no fix was needed there.

Two real bugs, both reproduced directly before any fix:

1. **`list_checkpoints` crashed on any non-numeric-stem `.json` file.**
   It filtered out exactly the literal name `"cursor"` and otherwise called
   `int(p.stem)` unconditionally on every `*.json` match. A single stray
   file in a run's checkpoint directory — a backup, a future sidecar file,
   any name that isn't a bare integer — raised `ValueError: invalid
   literal for int()`. Because `load_latest` calls `list_checkpoints`
   internally, this didn't just fail on the stray file: it bricked
   checkpoint access (and therefore `GraphExecutor.resume()`) for the
   *entire run_id*, including checkpoints that were themselves perfectly
   fine.
2. **`load_checkpoint` raised a bare `json.JSONDecodeError` on a corrupted
   or empty file**, with no indication of which run_id, checkpoint_seq, or
   file path was actually corrupted — a debugging dead end for exactly the
   scenario (a crash mid-`write_text`, since writes here aren't atomic)
   this backend's own docstring already anticipates as a real risk profile
   for a file-based checkpointer.

## Decision
- `list_checkpoints` now only treats a file as a checkpoint if its stem is
  purely digits (`p.stem.isdigit()`), which naturally excludes
  `cursor.json` and any other non-checkpoint file without needing a
  hardcoded name exception — the actual membership test is "is this a
  checkpoint," not "is this not literally called cursor."
- Added `CorruptedCheckpointError(RuntimeError)`, raised by
  `load_checkpoint` when `json.loads` fails, naming the exact path,
  run_id, and checkpoint_seq, with the original `JSONDecodeError` chained
  via `raise ... from exc` so the underlying parse failure is still
  visible.
- Exported both the new error and the pre-existing `MalformedTraceError`
  (ADR 0023) from `aef.kernel`'s top-level `__init__.py` — `MalformedTraceError`
  was added in that ADR but never added to `__all__`/the top-level import,
  an inconsistency with every sibling error (`DeterminismViolationError`,
  `GraphExecutionError`, etc.), all of which are re-exported there. Fixed
  as part of this same pass rather than filing a separate one-line ADR for
  an omission this small.

## Consequences
- A stray file sharing a checkpoint directory can no longer take down an
  entire run's checkpoint history — it's silently ignored, exactly like
  `cursor.json` already was, rather than a special case.
- A genuinely corrupted checkpoint still fails loudly (this is correct —
  matches ADR 0022/0023/0025's established stance that corruption must
  never be silently swallowed), but now with a diagnosable error naming
  the exact file instead of a bare `JSONDecodeError`.
- `aef.kernel.MalformedTraceError` and `CorruptedCheckpointError` are now
  both importable from `aef.kernel` directly, matching how every other
  kernel-level exception is exposed.
- 274/274 tests (up from 271/271), mypy --strict clean, ruff clean. No
  existing call site needed changes — pure hardening.
- `aef/kernel/executor.py` was also swept adversarially in the same pass
  (hand-built graphs: a real self-loop cycle, a zero-node graph and a
  missing entry_node reached by bypassing `Graph.compile()`/`validate()`
  via direct `CompiledGraph(graph=...)` construction, duplicate edges
  between the same two nodes) and came back clean — `max_steps` correctly
  bounds cycles with a named `GraphExecutionError`, an unvalidated
  zero-node/bad-entry-node graph still fails with a clear error even
  without going through `compile()`, and duplicate edges are harmless
  (first declared match wins, per the existing documented tie-break). No
  executor.py changes were needed.

## Alternatives Considered
- **Raise a clear error (instead of skipping) on an unrecognized `.json`
  file in the checkpoint directory**, on the theory that an unexpected
  file might itself indicate a problem worth surfacing. Rejected: the
  backend doesn't own that directory exclusively in any way it currently
  enforces, and treating "a file that isn't a checkpoint" as an error
  condition is a worse default than simply not mistaking it for one —
  consistent with `cursor.json` already being silently excluded rather
  than treated as an anomaly.
- **Wrap `load_state`'s `AEFState.model_validate` failures in the same
  `CorruptedCheckpointError`** (a structurally-valid-JSON-but-wrong-shape
  file). Deferred: `load_state`'s migration path already raises
  `NoMigrationPathError`/`MigrationCycleError`/pydantic's own
  `ValidationError` with reasonably specific messages for that case — the
  `json.loads` failure was the one with zero context, so that's the one
  this pass fixed; revisit if a similarly opaque failure is found there.

## Confidence
High — both bugs were reproduced directly (hand-written stray files and a
hand-corrupted checkpoint against a real `FileDurabilityBackend`, not
inferred from reading the source), the fixes were verified to resolve the
exact reproduction, and the `executor.py` adversarial pass found genuinely
correct existing behavior rather than an absence of testing — confirmed
each case actually reaches the code path being asserted on, not just that
no exception happened to occur.
