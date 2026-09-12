# Goal: repeatable repository integration and reviewed main release

Requested on 2026-09-11. Baseline: `6786c4a1d922f15ff1f1a398191ab9170838f51f`.
Include the existing, uncommitted September 8 review and offline integration
changes; preserve their evidence and verify them again before shipping.

## Executable prompt

Review the full AEF codebase and its integration boundaries. Make adoption
straightforward for both empty repositories and repositories with existing
Claude, Codex and Grok agents. Work from code and reproduced behavior. Audit
runtime/state/replay, security, providers, memory/reflection/evaluation,
adoption/migration, packaging, commands, documentation and CI. Use independent
reviewers for separable areas and reconcile their findings.

1. Read repository contracts, the handoff, roadmap and relevant ADRs. Inventory
   dirty work, Git refs/worktrees, package entry points and GitHub website setup.
2. Exercise fresh and mixed existing-agent repositories in disposable fixtures.
   Check preservation, reruns, unsupported formats, collisions, unsafe paths,
   offline operation, installed-wheel behavior and traversal at practical scale.
3. Reproduce defects before fixing them. Add focused regressions and verify
   important detectors against a planted fault in a disposable source copy.
   Fix integration-blocking defects; record remaining limitations honestly.
4. Make `/target-repo /absolute/path` discoverable in the GitHub README and
   linked guide, with the correct native Codex invocation and portable CLI
   equivalent. Explain existing-agent behavior, update semantics, setup,
   preservation and semantic work still needed after scaffolding.
5. Keep source read-only during a target-repo invocation. Keep all target
   integration writes within its explicitly selected directory. During this
   source review, do not modify any real external target repository.
6. Run the complete suite, strict mypy on `aef examples`, Ruff, formatting,
   measurement reproduction and disposable integration regressions. Record
   actual results and limitations in a dated review report.
7. Remove only verified stale branches whose commits are retained in main and
   clean, redundant worktrees. Preserve unmerged commits and dirty worktrees;
   report any such retained work. Avoid blanket clean/delete commands.
8. Commit the reviewed changes, fast-forward main and push to origin/main.
   Verify the remote commit and required GitHub CI. Finish with a clean
   checkout, current public docs, the review report and no remaining safe
   cleanup work. Stop when this finite list is complete.

## Acceptance and falsification

- Integration must not damage existing owner instructions, configuration,
  personas or workflows. Reruns must not duplicate generated agents or blocks.
- New and supported existing-agent fixtures must yield usable generated files;
  unsupported inputs must produce an explicit diagnostic.
- Offline integrations must run without constructing providers or making
  network/model calls. Source preservation must be checked, not assumed.
- Scalability claims require measured fixture size, elapsed time and bounded
  traversal behavior; no claim of unlimited repository size or concurrency.
- All existing tests remain represented. Required commands: `pytest -q`,
  `mypy --strict aef examples`, `ruff check .`,
  `ruff format --check aef tests examples`, and `make measure-ci`.
- Completion requires origin/main at the tested commit and passing CI, or an
  explicitly reported external blocker. Local green alone is not publication.

## Boundaries

The user explicitly authorizes this repository's main push and safe cleanup.
No paid live-model trials, external target edits, evolution enablement,
Tier-1 auto-merge, weaker policy/HITL controls or changed evaluation thresholds.
No fabricated model identity, execution results or learning gains. The
historical harmful-lesson result remains unresolved by infrastructure tests.
The GitHub website means the existing public repository entry point and docs;
do not invent a separate hosting deployment where none is configured.
