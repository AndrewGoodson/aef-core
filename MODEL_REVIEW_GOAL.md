# Goal: evidence-backed cross-harness AEF review

Requested by the owner on 2026-09-08. Baseline: `6786c4a1d922f15ff1f1a398191ab9170838f51f`.
Executor: this Codex session (GPT-6 family); do not invent a provider model ID
or claim cross-model/live validation from local tests.

## Objective

Review the inherited implementation and measurements, then improve AEF as an
ingestible graph runtime and bounded prompt-learning scaffold for repositories
using Claude, Codex, and Grok. The real-repository negative result in ADR 0204
remains the baseline; the 92/100 machinery rubric is not readiness evidence.

## Execute this finite work list

1. Read HANDOFF.md, repository contracts, roadmap, research programme and ADR
   index. Inventory runtime, providers, prompts, ingestion, learning, gates,
   tests, packaging and CI. Run the existing verification baseline.
2. Fetch current primary sources for graph durability, context/prompt learning,
   and the actual harness instruction formats. Record dates, links, supported
   mechanisms and limitations. Do not import a technique merely for novelty.
3. Reproduce each of the nine handoff findings or explicitly record why it
   cannot be reproduced locally. Fix safe, reproduced defects. Resolve F-Q1-1
   with an ADR: make the runtime capabilities explicit to the persona without
   granting tools or treating instructions as a sandbox. Preserve opt-in for
   live gate calls. Treat paired live scoring as a separate owner/cost decision.
4. Exercise adoption/migration on isolated synthetic repositories containing
   `.claude`, `.codex`, and `.grok` definitions and existing owner instructions.
   Preserve every byte outside managed blocks; test idempotency, unsafe paths,
   name collisions, graph compilation and the emitted command sequence.
   Support only verified file formats; diagnose unsupported definitions clearly.
5. Improve learning prompts using provenance, explicit capability boundaries,
   task-scoped evidence and bounded incremental changes. Distinguish missing
   observations from negative observations, infrastructure failures from agent
   regressions, and historical replay from new prompt-quality measurements.
6. Reconcile AGENTS.md/CLAUDE.md and shipped instructions with executable
   behavior. Add a regression preventing renewed contract drift. Record
   behavior changes in ADRs and the implementation report.
7. For each fix, run its failing case before the patch, then a passing regression
   and a mutation that restores the fault. Verify restoration by SHA-256 and
   isolate bytecode caches. Run the full green bar and measure-ci after integration.
8. Produce `docs/model-checks/2026-09-08-codex-review.md` with the audit matrix,
   sources, reproduced/suspected/open findings, changes, actual test evidence,
   mutation results, and remaining owner decisions. Stop when this list is done.

## Falsification and acceptance

- Capability fix fails if a captured request still invites fabricated tool
  results, claims containment the provider lacks, or grants persona tools.
- Harvest fix fails if a later run with persistent memory cannot re-execute
  using its recorded pre-run context, or if unrecorded context is guessed.
- Integration fails if an eligible supported definition is silently omitted,
  an emitted graph does not compile, or existing user bytes change.
- Learning improvement is a mechanism claim until held-out, comparable live
  trials demonstrate outcome improvement. No score increases from prose.
- All existing tests must remain represented. Required final checks:
  `pytest -q`, `mypy --strict aef examples`, `ruff check .`,
  `ruff format --check aef tests examples`, and `make measure-ci`.

## Boundaries

Work only in aef-core and disposable scratch directories. Do not modify or
push marlin, peptideindex, or any other owner's repository. Do not enable
evolution or Tier-1 auto-merge; do not weaken policy, HITL, verdicts or
thresholds. Candidates stay in Zone A. No new dependency without evidence.
Stage only named files. No new live-model spend or external deployment is
required for this review. Leave changes reviewable on the task branch;
the current request does not explicitly ask to commit or push.

Third-party repository acceptance, live paired remeasurement and a personal
halt notification destination remain explicit external decisions. They must
be reported as unverified, never substituted with fixtures or a rubric score.

## Follow-up: target-only integration command

Create `/target-repo` for Claude/Grok and the native `$target-repo` skill for
Codex. Require an explicit existing absolute target directory. Invocation
must keep this AEF source checkout unchanged, including ignored files and Git
metadata; all integration edits, environments, caches and reports belong in
the target. Preserve existing target work and reject overlap, source-linked
worktrees and output paths that redirect writes outside the target.

Back the skill with a deterministic adoption/migration launcher, then direct
the coding agent to finish semantic wiring and verification in the target.
Do not equate generated scaffolding with a working or improved agent. Prove
source preservation and repeatability using temporary repositories, exercise
all three native agent formats, and demonstrate that tests catch removed
write safeguards. Record usage, actual validation and remaining limitations.

## Approved follow-up: defects learned from the parcel integration

Update aef-core with five bounded changes: exact graph step budgets, explicit
providerless configuration, offline adoption with opt-in workflows, automated
before/after source verification, and a disposable installed-wheel regression
covering adoption, policy, replay and recorded outcomes. Preserve prior dirty
work and leave the actual parcel target unchanged. Use reproduced failures,
focused regressions, copy-isolated mutations and the full green bar. Document
behavior and limitations in ADR 0207 and the source update report. No commit,
push, deployment or live-model spend is part of this follow-up.
