---
name: target-repo
description: Integrate AEF into an explicitly selected external repository. Use for /target-repo with an absolute directory, $target-repo with an absolute directory, or a request to integrate a target repo while keeping this AEF source checkout read-only.
---

# Target repo

Invoke `/target-repo /absolute/path/to/repo`. In Codex, select `target-repo`
through `/skills` or use `$target-repo /absolute/path/to/repo`.

The directory containing this skill is three levels below the AEF **source**
root. Resolve that location; do not infer the source from the current working
directory. The user's argument is the **target**. Require one explicit,
existing absolute directory. If absent or ambiguous, ask for that path only.
Never default to `.` or select a repository from memory.

## Execute

1. Treat the source checkout as read-only for this entire invocation. Keep
   every edit, generated artifact, log, cache, dependency install, test and
   integration report inside the target. Do not change source branches,
   commits, files, prompts, dependencies, or Git metadata. A source defect
   becomes a reported blocker; do not repair it during this command.
2. Read the target's existing agent instructions and inspect its worktree.
   Preserve existing work and owner policy. Record the source's initial
   status/diff using Git with `--no-optional-locks`. Also capture a source
   manifest covering the root, ignored files, new paths, regular-file hashes,
   modes, modification times, external Git metadata and symlink targets
   without following arbitrary links. Keep that
   baseline in memory or the target; store nothing in the source. Reject
   source/target overlap and source-linked worktrees. The launcher enforces
   these path boundaries too.
3. Run the bundled launcher, replacing both example paths with resolved paths:

   ```sh
   python3 -I -B /absolute/path/to/aef-core/scripts/target_repo.py /absolute/path/to/target
   ```

   Pass the target as one argument. Use an argv API or proper shell quoting
   for spaces and shell metacharacters; never evaluate the argument as code.
   The launcher uses the source's existing `.venv/bin/python`, falling back
   to its invoking interpreter. It installs nothing. It runs adoption plus
   mechanical migration with bytecode disabled and checks output paths.
   It defaults to the offline profile (`model_provider: null`) and adds no
   scheduled workflows. Use `--profile model` when the target needs a model;
   only add `--with-workflows` if scheduled loop workflows were requested.
   Existing config and workflows are preserved; a profile is not a conversion.
   The launcher takes full before/after source manifests around its child,
   prints a matching digest or the changed paths with before/after metadata,
   and returns nonzero for any detected drift or unverifiable snapshot. It
   never restores source files. This verifies the mechanical phase only;
   keep the whole-invocation baseline for the later semantic work too.
   On failure, inspect any target outputs before continuing; do not bypass
   a refusal with a direct `aef adopt`, `--force`, or a symlink.
4. Continue **semantic integration in the target**. Read its generated
   `AGENT_INTEGRATION.md`, `AUTONOMY.md`, `AEF_MIGRATION_CHECKLIST.md`, and the
   migration report. Inventory `.claude/agents`, `.codex/agents`, `.grok/agents`,
   existing skills and actual call sites. Complete applicable adapter, graph,
   provider and entrypoint wiring; preserve agent objectives and target
   behavior. A generated stub or wrapper is not proof of a working agent.
   Use target-local environments and dependencies. Never use an editable
   install, build, or test command that can write back into the source.
5. Apply the generated evidence-learning protocol: observed tool outcomes,
   explicit capabilities, bounded lessons, provenance and held-out controls.
   Keep target safety gates, HITL, denied scopes, Tier-1 protection and
   evolution disablement intact. Tool-enabled prompts require actual tools;
   do not substitute invented tool results. Do not claim learning gains from
   compilation, static checks, or a tools-disabled run.
6. Run the target's relevant local checks, fixing target-local integration
   defects. Keep caches and reports there. Inspect executable target code
   before running it; skip commands whose writes cannot stay in the target.
   Credentials, paid/live evaluations, deployment and external publication
   require applicable authorization; continue independent local work when
   one of those is unavailable. Do not start background self-modification.
7. Compare source status/diff and the complete manifest with the baseline.
   Do not claim source preservation if either differs; report the discrepancy
   without reverting concurrent owner work. Report the target,
   files changed there, checks actually run, unresolved semantic wiring or
   live-evaluation blockers, and source verification. Completion means the
   integration checks pass; if only scaffolding completed, say so. Stop when
   those checks pass or no further target-local work can resolve a blocker.
