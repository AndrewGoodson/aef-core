# ADR 0208: Preserve identity and owner files during repeat integration

Status: accepted, 2026-09-11. Owner-authorized repository review and release.

## Reproduced failures

Adding an earlier-sorting persona with the same name caused migration to reuse
an existing graph for the wrong source persona. Filtering `rglob` results also
walked excluded dependency trees before discarding their files, and Python
source symlinks could make the scanner read outside the selected repository.
An explicit `migrate --force` replaced edited native prompt wrappers without
preserving their contents.

Adoption separately changed its own framework detection on an unchanged offline
rerun: generated instruction files were mistaken for pre-existing agents. Its
instruction writer could mutate another pathname through a hard link, and its
framework detector could follow external file links or block on special files.
Native discovery also blocked on Markdown/TOML persona FIFOs in all three
harness directories. Each failure received a failing regression before its fix.

## Decision

Recover generated graph identity from literal `AGENT_FILE` and `GRAPH_ID`
assignments parsed with the AST. Never import an adopting repository to inspect
its graphs. Keep prior source-to-graph mappings and reserve occupied identities,
including legacy duplicate graphs. New collisions receive distinct paths and
IDs. Ordinary reruns preserve existing wrappers. An explicit forced replacement
backs up edited native wrappers byte for byte to a previously unused path and
reports it.

Prune excluded directories before traversal. Framework detection uses one
sorted walk, separately collecting at most 2,000 Python and 2,000 manifest
files. It skips symlinks and nonregular files. SDK migration scans all eligible
Python files, skips external file links and reports the skipped modules.
Native persona discovery remains recursive across Claude, Codex and Grok,
and refuses nonregular persona files before reading them. Native config files
that are not discovery inputs remain untouched.

Adoption excludes its own managed instruction blocks from existing-agent
detection, while retaining owner text in the classification. Linked instruction
files are preserved and reported rather than updated through another pathname.
The stricter target command refuses unsafe output paths before writing them.

The source command defaults to offline adoption, preserves existing configs,
and leaves semantic integration to the coding agent in the selected target.
The portable entry point and native harness syntax are documented in
[the target guide](../target-repo.md). It verifies source manifests, including
ignored files and external Git metadata; it is not a filesystem sandbox.

## Evidence and limits

Installed-wheel tests exercise offline and model-profile template generation
with provider and network tripwires. Mixed-harness regression fixtures cover
owner-file preservation, duplicate names, legacy graph identity, reruns, path
boundaries and edited wrapper backups. The dated
[review report](../model-checks/2026-09-11-repository-review.md) records measured
scale, final checks and remaining gaps.

Framework sampling does not prove discovery of every framework in a large
repository. SDK migration and persona discovery have no file-count ceiling;
source manifests read all regular source bytes twice. Large-file parsing and
concurrent filesystem mutation remain limits. Unparseable owner graphs and
legacy duplicates are preserved for inspection, not silently repaired or
deleted. Scaffold generation is not automatic migration of arbitrary Python
control flow, native tool grants, or proof that learned advice improves work.
