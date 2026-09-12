# ADR 0207: Offline adoption and source integrity

Status: accepted. Owner-authorized source update after the parcel-repo trial.

## Evidence

The trial needed a spare graph step to reach END, a fake command provider for
tool-only work, manual removal of generated schedules, and a hand-built
installed-package regression. Its source comparison found Git-object timestamp
drift despite matching content. The author of that drift was not established.
These are integration defects and evidence gaps; no learning gain was measured.

## Decisions

1. `max_steps` counts executed nodes. END consumes no budget. A graph finishing
   on the last permitted node succeeds; an unfinished graph still fails before
   executing another node. Checkpoint and resume keep the same boundary.
2. `model_provider: null` explicitly selects a providerless runtime. Omitting the
   field is still invalid. Runtime construction, doctor and rule-based reflection
   work without creating a provider. LLM reflection and live gate calls reject a
   null provider. Existing provider configurations retain their behavior.
3. Adoption has `offline` and `model` profiles. Direct `aef adopt` retains the
   model default for compatibility; the target launcher defaults to offline.
   Both omit workflows unless `--with-workflows` is explicit, and offline plus
   workflows is rejected before writing. Offline onboarding omits loop/corpus
   bootstrap instructions and the model-login requirement. It includes the
   evidence-learning protocol and a portable GROK.md with explicit-load guidance.
   Existing files and workflows remain preserved: a profile selection does not
   convert an existing installation or disable existing schedules.
4. The target launcher takes full source manifests before and after the child,
   including ignored entries, permissions, modification times, link targets,
   hashes and external Git metadata. It runs no Git commands. Drift returns a
   nonzero status and prints changed paths with before/after metadata, even when
   the child also fails. Unverifiable snapshots fail closed. It never restores
   source files or writes a source report. Arbitrary links are not followed and
   access times are excluded. Two matching snapshots prove matching observed
   states, not absence of intervening writes or attribution of drift.
5. A disposable installed-wheel test exercises adoption, offline CLI execution,
   outcomes, provenance, policy denials/HITL, exact budgets, checkpoints, resume
   and deterministic replay. The test supplies the domain graph explicitly;
   adoption still emits a stub. It installs the wheel into an isolated package
   directory and verifies imports come from it. It uses the test interpreter's
   dependency environment, not a fresh dependency-resolution matrix. Network
   and model-provider construction have tripwires. `hatchling`, already the
   declared build backend, joins the dev extra to make this test reproducible;
   no runtime dependency was added.

## Validation and limits

Regressions restore the exact step-limit fault, reject inconsistent offline
settings, preserve existing installations, opt in to scheduled workflow tests,
and force source drift across content, mode, timestamp, new/deleted paths,
ignored files and Git metadata with successful and failing children. Policy
thresholds, HITL, evolution disablement and deterministic checks remain intact.

Validation results are recorded in
[the source update report](../model-checks/2026-09-08-offline-integration-update.md).
This update changes only aef-core and disposable fixtures. The existing parcel
integration and its pinned wheel are not refreshed by this work. No paid model
evaluation, release, deployment or learning-quality claim follows from these tests.
