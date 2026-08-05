# ADR 0062: Unmeasurable size denies; the workspace ignores export attributes

## Status
Accepted. Two confirmed defects in the isolation boundary (ADR 0047),
reproduced by running against real repositories.

## Context
Phase 1b probed ADR 0047's claim under unusual git input. Two defects, both
in code with passing tests, both silent.

## Defect 1 — a change git will not size counted as zero

`_parse_numstat` read git's line counts with
`int(added) if added.isdigit() else 0`. Git reports `-` for anything it
declines to diff, including any file a `.gitattributes` marks `binary`.

**Measured:** a candidate committing `agents/.gitattributes` with `*.py binary`
alongside a 5,050-line rewrite reported **1 changed line**. G0's diff-size
budget — the control that rejects changes too large to verify — saw nothing.

The attribute trick only works when the driver runs with the candidate
checked out, because git reads attributes from the working tree; in CI the
checkout is `main` and the same diff reported 5,051 correctly. That
difference is itself the problem: **a safety control whose correctness
depends on which branch happens to be checked out is not a control.**

The deeper fault is the default. Genuinely binary files hit the same path,
with no attacker involved. **Unmeasurable size now denies**: `DiffEntry`
carries `size_unknown`, and G0 rejects rather than counting zero.

## Defect 2 — `git archive` honours `export-ignore`

`build_candidate_workspace` built the base tree with `git archive`, which
respects `export-ignore` in `.gitattributes`.

**Measured:** with `tests/ export-ignore` and `aef/ export-ignore` at the base
ref, the materialised workspace contained **neither the test suite nor the
harness**, and reported nothing wrong. G1 would then run a suite that no
longer contains the test that fails, and pass.

This needs no attacker. Excluding `tests/` from an sdist is ordinary, sensible
packaging hygiene, and any repo doing it would have had a vacuous G1 from the
moment it adopted the loop.

Fixed by enumerating with `git ls-tree -r -z` and writing each blob, which
reports the tree as committed and ignores export attributes. Only `100644`
and `100755` land — symlinks and gitlinks are refused for the same reason
`candidate.py` refuses them.

## Consequences
- Both defects have reproducing tests built from real repositories.
- The workspace now uses the same mechanism as `BaseRefHarness.materialize`:
  enumerate, then fetch each blob. One approach, verified per path, rather
  than two with different failure modes.
- A candidate containing a genuinely binary file (an image fixture, say) is
  now **rejected** rather than under-counted. That is the correct default and
  it is stricter than before; if binary assets in Zone A become a real need,
  the answer is an explicit allowance with its own budget, not a silent zero.
- `.gitattributes` under `agents/` is still Zone A and still writable. It can
  no longer hide a change's size, and it never could affect the base tree.

## Alternatives Considered
- **`git diff --attr-source=<base_sha>`** to pin attributes to the base ref.
  Correct in principle and tried first; the invocation was rejected by the
  local git and, more importantly, it only addresses the attribute route.
  Denying unmeasurable sizes covers genuinely binary files too, and works on
  every git version.
- **Counting an unmeasurable file as the size budget's maximum** rather than
  rejecting. Rejected: it silently converts "we cannot check this" into "this
  is exactly at the limit", which reads as a measurement.
- **`git archive --worktree-attributes`.** Rejected: still consults
  attributes, just a different set.

## Confidence
High. Both were reproduced by constructing the repository and observing the
wrong answer, and both fixes were verified against the same probe. What is
**not** claimed: that these are the last isolation defects. Both were found
by trying four things; the search was not exhaustive, and `.gitattributes`
has other verbs (`filter`, `diff`, `merge`) that were not probed.
