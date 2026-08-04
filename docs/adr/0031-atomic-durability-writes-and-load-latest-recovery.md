# ADR 0031: Durability writes are atomic, and `load_latest` recovers past a torn checkpoint

## Status
Accepted

## Context
The 2026-08-04 architecture review (docs/design/review-2026-08-04-
architecture-and-bug-hunt.md, Finding 1, HIGH) found the write side of
`FileDurabilityBackend` was never hardened, even though ADR 0026 hardened
the read side.

- `save_checkpoint` and `save_cursor` used plain `Path.write_text()`,
  which is **not atomic**: a process crash mid-write leaves a truncated
  file. For the newest checkpoint this bricked resume; for `cursor.json`
  — overwritten in place every super-step — a torn write corrupts the
  resume pointer itself.
- `load_latest` picked `max(list_checkpoints())` and called
  `load_checkpoint` on it with no recovery. Reproduced directly: two good
  checkpoints (seq 0, 1) plus a truncated `2.json` made `load_latest`
  raise `CorruptedCheckpointError`, permanently bricking `resume()` even
  though seq 0 and 1 sat intact on disk.

External durable-execution research (Temporal, LangGraph, POSIX crash-
consistency literature) confirmed the standard fix and that this was below
common practice: atomic file replace via temp-file + fsync + rename, with
the cursor as the priority target since it is the one file overwritten in
place.

## Decision
Added `_atomic_write_text(path, text)`: write to a temp file in the **same
directory** (same filesystem, so the rename is atomic on POSIX), `os.write`
+ `os.fsync` the data, `os.replace()` over the target, then `os.fsync` the
containing directory so the rename itself is durable. Both
`save_checkpoint` and `save_cursor` now use it. A crash at any point leaves
either the old file fully intact or the new file fully intact — never a
torn one.

`load_latest` now walks checkpoints newest-first and falls back past any
`CorruptedCheckpointError` to the highest *loadable* checkpoint. If every
checkpoint is corrupt, the last error propagates (returning `None` would be
indistinguishable from "this run never started"). This keeps ADR 0026's
"corruption is loud" contract while making a single torn file survivable
when an earlier good checkpoint exists.

## Consequences
- A crash mid-write no longer produces a torn file in the first place
  (atomic replace), and even a file corrupted by something outside this
  backend (disk fault, manual edit, a legacy pre-atomic-write crash) no
  longer bricks resume when an earlier good checkpoint exists.
- `load_latest`'s return contract is unchanged for the common paths
  (`None` when a run has no checkpoints at all; the newest state when the
  newest checkpoint is good). Only the torn-newest case changed: recover
  instead of raise, unless nothing is loadable.
- 291/291 tests (up from 288; three new: torn-final-recovers, all-corrupt-
  still-raises, save-is-atomic-no-temp-artifact), mypy --strict clean,
  ruff clean. No vendor SDK touched (constraint #3 intact).
- **Finding 5 (checkpoint-format versioning) resolved as already-covered:**
  verified that each checkpoint file carries `schema_version` (via
  `AEFState.model_dump_json`), and `load_state` already runs the migration
  registry on read — so the checkpoint format is versioned today. The one
  format that is *not* versioned is `cursor.json` (a trivial
  `{"next_node": ...}` single-field sidecar). That is fine now, but when
  fan-out lands (ADR 0007) the cursor becomes multiple pending cursors +
  pending-writes — the cursor sidecar is the file to add a version field to
  *at that point*. Flagged here, not pre-built (no format change is needed
  yet).

## Alternatives Considered
- **Keep `write_text` and only add `load_latest` recovery.** Rejected:
  recovery alone leaves the cursor-corruption case (a torn `cursor.json`
  has no earlier good version to fall back to — it is overwritten in
  place), and still litters the run dir with torn files. Atomic write is
  the actual fix; recovery is defense-in-depth on top of it.
- **`load_latest` returns `None` when all checkpoints are corrupt** (softer
  than raising). Rejected: `None` already means "no checkpoints exist," and
  conflating "never ran" with "everything is corrupt" is exactly the kind
  of silent-failure masking ADR 0026/0030 removed elsewhere.
- **fsync-free temp+rename.** Rejected: without fsyncing the file before
  rename, a crash can land the rename before the data reaches disk,
  reintroducing a torn file after reboot — the crash-consistency
  literature is explicit that the fsync is load-bearing.

## Confidence
High — the brick-on-torn-final-checkpoint bug was reproduced exactly as the
review documented before any fix, the fix was verified to recover to the
prior good checkpoint (and to still raise when nothing is loadable), and
the atomic-write pattern (temp + fsync + os.replace + dir fsync) is the
established POSIX crash-consistent recipe, not an ad-hoc invention.
