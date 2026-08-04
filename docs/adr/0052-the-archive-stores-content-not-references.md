# ADR 0052: The archive stores content, not references

## Status
Accepted. Implements M6.

## Context
`03-roadmap.md` M6 specified "rollback restores an exact prior manifest".
The three-reviewer audit found the flaw (04 §1.9): **a palette ref is a
name.** An archive recording "version 7 used `agents.planner:build`" pins
the *name*, and the code behind that name changes under ordinary human PRs.
Rolling back would restore a version whose meaning had silently changed —
the worst kind of failure, because the rollback reports success.

A second failure mode is quieter: an archive that stores git shas and
nothing else stops working after `git gc`, a force-push, or a branch
deletion, and does so long after anyone would connect the two events.

## Decision
**Store bytes and a SHA-256 per file.** Every entry holds the actual content
of every Zone A file. `read_files` verifies each digest and **raises** on
mismatch rather than returning content that differs from what was accepted.

**Do not depend on git.** Git shas are recorded as provenance, but the
archive is self-contained and its tests run with no repository present at
all.

**Append-only, monotonic versions.** `record()` never overwrites. A
**rollback is itself archived as a new version**, and the version rolled
back *from* is left in place — erasing it would hide the very thing the
rollback is evidence about.

**The entry file is written last, and atomically**, using the kernel's
existing `_atomic_write_text` (temp file same-dir → `fsync` → `os.replace` →
directory `fsync`, ADR 0031) rather than a second implementation that would
need proving separately. The entry is what makes a version real, so a crash
mid-write leaves a directory with no entry rather than an entry describing
files that are not all there.

## Consequences
- 21 tests. The central one tampers with an archived file and asserts the
  read fails: an archive that hands back altered content is worse than none,
  because a rollback from it restores something other than what was
  accepted.
- Rollback from a tampered version refuses outright rather than restoring
  best-effort.
- Disk cost is the full content of every accepted version. Deliberate: Zone A
  diffs are budget-capped at 200 lines / 3 files (ADR 0049), so the archive
  grows slowly, and correctness here is worth more than bytes.
- **Not implemented: pruning or retention.** The archive grows without
  bound. A retention policy is a real future need and is *not* a silent
  default — deleting history is exactly what `check_never_shrinks` exists to
  catch, so any future pruning must be an explicit owner action.

## Alternatives Considered
- **Store refs/manifests only.** Rejected — this is the flaw the audit
  found.
- **Store git blob shas and read content back with `git cat-file`.**
  Rejected: smaller, but reintroduces the dependency on git never garbage-
  collecting, and an archive with a liveness requirement on another system's
  housekeeping is not durable.
- **Delete the rolled-back-from version.** Rejected: it makes the history
  read as though the bad change never happened, which is precisely the
  record a post-merge investigation needs.
- **Compress or deduplicate stored content.** Deferred; premature while
  diffs are capped this small, and it would put a codec between the archive
  and the bytes it exists to preserve.

## Confidence
High. Every property is directly tested against a real filesystem, including
tampering, deletion, path escape, and the never-shrinks check. The one
untested property is crash-atomicity of the entry write, which is inherited
from `_atomic_write_text` and covered by ADR 0031's own tests rather than
re-proved here.
