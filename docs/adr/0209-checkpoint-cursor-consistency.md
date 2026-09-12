# ADR 0209: Refuse an inconsistent checkpoint/cursor pair

Status: accepted. Runtime review during the owner-authorized integration audit.

## Evidence

Checkpoint files and `cursor.json` each use an atomic write, but the two writes
are not one transaction. Fault injection that raises immediately before the
first cursor write left a checkpoint after node A. A fresh executor treated the
missing cursor as END and returned success without running B or C. Interruption
before the second cursor write paired state after B with the old cursor for B:
resume produced visits A, B, B, C. The final cursor write has the same defect.

This is different from the documented at-least-once retry of a node with its
original input. Here B ran against its own output, changing state and potentially
its idempotency key. Three regression cases failed before the fix.

A separate write fault exposed that `_atomic_write_text` ignored the byte count
returned by `os.write`. A short write returned success, then atomically installed
truncated JSON. The short-write regression failed with `CorruptedCheckpointError`
before the fix. Atomic rename alone does not establish a complete payload.

Cross-review found that sequence binding alone was insufficient: a public
`save_checkpoint` call could replace sequence 1 after its cursor was committed.
The unchanged cursor then resumed B against state that already included B.
Another reproduction placed valid JSON with a different `run_id` or sequence
inside `r1/1.json`; reads accepted the foreign identity. Seven additional
regression cases failed before these follow-up fixes.

## Decision

Built-in durability backends bind each cursor to a checkpoint sequence. Loading
a cursor rejects a missing, stale, malformed or unbound cursor when checkpoints
exist. A null next-node value establishes completion only when the binding
matches the latest checkpoint. The file backend records the sequence in its
existing atomic cursor sidecar; checkpoint payloads and public method signatures
are unchanged. The in-memory and internal ephemeral backends enforce the same
contract. Normal file writes remember the just-written sequence instead of
enumerating the growing checkpoint directory after every node.

Run/sequence identities are now immutable through `save_checkpoint`: an
identical retry succeeds without rewriting the file, and a changed checkpoint
raises before replacing any evidence. File reads also require the payload's
run id and sequence to match the requested identity. This closes the two ways
an unchanged sequence binding could refer to different state through the
backend API or an accidentally copied file.

Shadow comparisons use a fresh ephemeral checkpoint store for each candidate
observation. The incumbent retains the configured store, and both arms retain
the supplied input identity. Reusing the live store had allowed shadow outputs
to replace incumbent checkpoints; immutability exposed this as three comparison
failures in the full suite. Candidate state is now compared and discarded without
reading or replacing the incumbent's checkpoint history. This changes no tool
policy, HITL approval handling or container boundary; memory and knowledge store
sharing retain the explicit limits documented by the shadow harness.

Atomic file writes now consume the entire encoded payload before syncing and
renaming it. A zero-byte write raises instead of looping indefinitely or
replacing the previous valid checkpoint with incomplete data.

The executor still refuses a newer corrupt checkpoint instead of combining a
rewound state with a live cursor (ADR 0086). Neither check deletes checkpoints,
rewrites evidence, retries a node, or claims successful recovery.

## Compatibility and limits

Old checkpoint state remains readable through `load_checkpoint` and
`load_latest`. Legacy cursor JSON without `checkpoint_seq` cannot prove which
checkpoint it belongs to and therefore cannot resume automatically when state
exists. After inspecting the state and execution history, the owner can record
the correct next node through a fresh backend's `save_cursor`; the backend then
writes the binding.
Do not infer the correct next node merely from the old cursor.

Code that previously replaced state at an existing run/sequence must instead
advance the sequence or use a new run identity. Resaving unchanged input after
a node failure remains supported. A corrupt existing file cannot be silently
repaired by `save_checkpoint`, because the backend cannot establish whether
its cursor would describe the replacement. It preserves the corrupt bytes for
inspection; explicit repair lies outside the checkpoint-saving API. Existing
read-only `load_latest` fallback and unsafe-rewind refusal remain unchanged.

External `DurabilityBackend` implementations keep the same signatures, but must
implement immutable checkpoint identities, binding and consistency checks
themselves. The typed
Postgres and Temporal stubs remain unimplemented. Concurrent workers writing the
same run are not coordinated by this change. Exactly-once side effects,
transactional checkpoint/cursor commits and automatic crash recovery are not
claimed. A crash in this window now stops with an explicit error rather than
inventing a final state.

## Validation

Fault injection covers interruption before the first, intermediate and terminal
cursor commit, then reopens a file backend to simulate a new process. Each case
refuses resume and preserves its last state. Backend tests cover missing/stale
bindings, legacy cursors, malformed sequence types, successful cursor reload and
the absence of per-step checkpoint-directory scans. Existing completed, paused,
HITL and budget-limited resume tests continue to pass.
Short-write injection verifies complete checkpoint and cursor payloads; a
zero-byte write verifies that the previous checkpoint remains readable.
Follow-up tests reject changed identities in all built-in backends, allow
identical retries including a reopened file backend, preserve corrupt files
on attempted overwrite, and reject payload identities inconsistent with their
file paths. Existing failure retry and corruption fallback tests still pass.
The shadow integration regression verifies repeated observations preserve the
incumbent's persisted state and completed cursor while giving each candidate an
empty checkpoint history. Restoring the shared-store assignment in a disposable
copy makes the regression fail; existing contained comparison and suppression
tests pass with the separate store.
