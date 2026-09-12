# ADR 0206: Target-only integration command

Status: accepted.

## Request

Allow `/target-repo <directory>` to integrate AEF into a selected external
repository without changing this source checkout when the command runs.

## Decision

Ship equivalent Claude, Codex and Grok repository skills backed by
`scripts/target_repo.py`. Codex's native explicit invocation is `$target-repo`
or `/skills`; do not claim an identical custom-slash API across harnesses.

The launcher accepts an explicit absolute directory and starts trusted AEF
imports with Python `-I -B`, with the target as the working directory. It uses
an existing interpreter and installs nothing. Target code is only parsed.
The entrypoint rejects overlapping trees and shared source Git metadata.

Adoption and migration accept an optional write guard so this command can
enforce target-only writes without changing their default APIs or existing
preservation behavior. The guard rejects path traversal, linked output paths,
hard-linked files and nonregular destinations. Migration destinations are
preflighted before adoption. No force option is exposed.

The launcher reports mechanical completion explicitly. The skill continues
semantic wiring and target-local validation, carries the evidence-learning
and safety contracts, and reports remaining runtime blockers. Generated
graphs are not a claim of functional equivalence or learning improvement.

## Evidence and limits

`tests/cli/test_target_repo.py` exercises the real launcher against independent
temporary source and target trees. Full source manifests include Git metadata,
ignored files, modification times and new paths. The successful test migrates
all three native formats, preserves owner CRLF bytes, compiles generated graphs,
and reruns without changing either tree. Hostile fixtures cover overlap,
links, shared metadata and import shadowing.

There is no filesystem sandbox against concurrent path replacement, and later
agent-driven edits/tests are governed by the skill, not intercepted by the
launcher. A failed operation can leave earlier outputs inside the target.
The command remains useful for non-Git directories; it never initializes Git.

Usage and discovery references: [target-repo guide](../target-repo.md).
