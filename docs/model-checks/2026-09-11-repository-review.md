# Repository integration review — 2026-09-11

This review hardens integration and recovery mechanisms. It does **not** establish
that AEF's generated advice improves agents. The historical harmful-lesson
result remains: incumbent 0.6667, generated lesson 0.4000, placebo 0.8667
([ADR 0204](../adr/0204-the-loop-on-a-repo-somebody-uses-and-the-bullet-that-made-it-worse.md)).
Those arms used asymmetric live/replay execution and small samples; neither
that result nor infrastructure tests support a general learning-quality claim.

The owner requested a full review, fresh and existing-agent integration,
scalability checks, GitHub command documentation, safe cleanup and a main push.
The [executable goal](../../REPOSITORY_REVIEW_GOAL.md) records the finite scope.
Review began at `6786c4a1d922f15ff1f1a398191ab9170838f51f` and includes the
previously uncommitted September 8 review and offline integration work. Their
dated reports retain their original local-only status as historical evidence;
this report records the later release review.

## Review coverage and reproduced fixes

Five parallel reviews covered native integration, adoption/packaging, runtime
durability, GitHub documentation and independent change review. The primary
review reconciled contracts, code changes, regression evidence and release
checks. This is a repository-wide review, not a proof that every code path is
defect-free.

| Area | Reproduced defect and resulting behavior |
|---|---|
| Native graph identity | Adding an earlier-sorting duplicate persona could bind its reported graph to another agent. Migration now parses prior literal source/ID mappings without importing owner code, reserves existing identities and assigns unique new paths. |
| Migration scan | Python discovery entered excluded dependency trees and followed external file symlinks. It now prunes before traversal and skips/reports linked Python sources. |
| Native special files | Markdown/TOML persona FIFOs blocked before migration completed. Discovery now rejects nonregular sources before opening them; all three harness cases fail promptly without creating a config. |
| Forced native updates | `migrate --force` discarded edited native graph wrappers. It now preserves numbered, byte-exact backups, including non-UTF-8 owner edits. Ordinary reruns preserve wrappers. |
| Repeat adoption | Offline-generated instructions changed an unchanged target's framework classification on rerun. Detection now removes AEF's managed blocks while retaining owner text. |
| File boundaries | Adoption could mutate another pathname through a hardlinked instruction file, detect a framework from an external symlink, or block on special files. Linked owner instructions are preserved; scanning ignores links and nonregular files. |
| Checkpoint/cursor consistency | An interrupted cursor write could silently mark a run done or execute a node against its own output. Built-in backends bind cursors to checkpoint sequences and reject missing, stale, malformed or legacy unbound pairs. |
| Checkpoint identity | Replacing state at the same sequence left the old cursor valid; misplaced JSON could resume another run. Built-ins now allow identical retries but reject changed checkpoint identities, and file reads validate payload identity against its path. |
| Shadow persistence | Full-suite integration exposed candidates sharing the incumbent's completed checkpoint identities. Each shadow observation now uses fresh temporary durability, preserving the incumbent store and allowing differing candidate results to be compared. |
| Configured context replay | A valid one-token retrieval run was replayed using defaults and rejected. Recording now captures four typed retriever settings, and harvest plus both evaluation runners reconstruct them without importing provider/policy permissions. |
| Atomic writes | Short `os.write` results were ignored, installing truncated checkpoint JSON. Writes now consume the full payload before syncing/rename; zero progress raises without replacing the prior valid checkpoint. |
| Isolated workflow setup | The loop-gate job disabled networking before checkout, dependency installation and fetch. It now builds a trusted runtime first, fetches a validated branch name as quoted shell data and evaluates inside a separate network-disabled Docker container with read-only source. Core and adopter workflows share one renderer. |
| Live CI routing | Ordinary PRs could select a configured credentialed runner. The live job now runs only on main pushes; external runner access restrictions remain necessary because a PR author can edit workflow YAML. |

[ADR 0208](../adr/0208-repeatable-existing-agent-integration.md) records
integration decisions and [ADR 0209](../adr/0209-checkpoint-cursor-consistency.md)
records durability evidence and compatibility.
[ADR 0210](../adr/0210-recorded-retriever-configuration.md) records the retrieval
configuration binding and unbound-service limits.
[ADR 0211](../adr/0211-prepare-workflows-before-isolated-evaluation.md) records
workflow preparation, isolation and runner-policy limits. Focused tests failed
before the respective fixes, including injected first, intermediate and terminal cursor
commit failures and short writes.

Five targeted mutations were then planted only in disposable source copies.
Removing native special-file rejection failed all three harness regressions;
removing prior graph identity recovery failed both collision regressions.
Removing cursor sequence validation failed all three crash-boundary cases;
ignoring short writes failed the checkpoint JSON regression. Sharing the
incumbent checkpoint store again failed the new shadow isolation regression.
Every unmodified
control passed, and source input hashes remained unchanged. Retained
[integration results](evidence/2026-09-11-integration-mutations.json) and
[durability results](evidence/2026-09-11-durability-mutations.json) include exact
commands and original temporary log locations. The
[shadow result](evidence/2026-09-11-shadow-storage-mutations.json) records its
independent detector and the 205-test validation. Their scripts and copied logs
are adjacent in the evidence directory. The repeatable scripts require an
output directory outside the source checkout.

The prior changes included in this release are documented separately:
[cross-harness/evidence review](2026-09-08-codex-review.md),
[offline integration update](2026-09-08-offline-integration-update.md), and
ADRs 0205–0207. They include pre-run memory snapshots, explicit capability
messages, native TOML lesson editing, providerless configuration, exact graph
step budgets, target-source integrity checks and opt-in workflow generation.

The workflow correction also passed 188 focused regressions and an independent
real Docker smoke using the exact generated build, fetch, gate and report shell
steps. Trusted installation and fetch succeeded. Inside the candidate test,
network access was unavailable, execution was nonroot, source/runtime were
read-only, scratch/state were writable, and the planted host credential plus
Docker socket were absent. G0, G1 and G4 passed; G5 rejected the deliberately
missing blessed baseline. Status verified the ledger. This validates setup and
isolation, not a passing candidate evaluation. No GitHub dispatch, private
remote fetch, adopter dependency matrix or live model was tested. The newly
created image was removed. Retained [workflow results](evidence/2026-09-12-workflow-review.json)
include negative reproductions, and the [Docker report](evidence/2026-09-12-workflow-docker-smoke/report.json)
has adjacent logs, exact shell steps and the executed smoke script as text.

## Integration and scale evidence

Disposable fixtures cover fresh repositories and existing Claude/Grok Markdown
plus Codex TOML agents, mixed harnesses, duplicate names, owner-edited configs,
instructions and workflows, unsafe paths, reruns and installed package usage.
Existing native tool settings remain source data; migration does not grant the
runtime those tools or preserve arbitrary Python control flow automatically.

The installed-wheel test builds from a disposable source copy and installs
without dependency/network resolution into an isolated package directory.
It supplies and executes a domain graph with success and failure cases, checks
doctor/run/eval/trace, persisted outcomes, policy denial/HITL, checkpoints,
resume and deterministic replay. Provider/network tripwires stay armed.
The model-profile probe additionally verifies packaged skill/template resources
without running a model. This is not a new clean dependency-resolution matrix;
CI runs the suite on Python 3.11 and 3.13.

One local migration fixture used 1,000 native personas across the three harnesses,
nested teams, 257 repeating names and 1,000 excluded `.venv` Python files.
Initial generation took 0.211 seconds. Adding 20 earlier-sorting colliding
personas and rerunning took 0.409 seconds; an unchanged 1,020-persona rerun took
0.415 seconds. All original graph paths, IDs and bytes stayed unchanged; all
1,020 personas had unique correctly bound graph IDs. Filesystem audit events
confirmed that the excluded dependency tree was never entered. These are
single-machine disposable-fixture timings, not production throughput claims.
The [fixture script](evidence/2026-09-11-integration-scale.py) and
[measured output](evidence/2026-09-11-integration-scale.json) are retained. Run
`python -B docs/model-checks/evidence/2026-09-11-integration-scale.py /absolute/aef-source`
with the source environment to repeat it.

Framework detection collects up to 2,000 Python and 2,000 manifest files in one
sorted, pruned walk. SDK migration and native discovery have no file-count cap.
Neither parsing nor source hashing has a global byte budget. The target launcher
reads all regular source files twice, including ignored environments and build
outputs. Large owned trees and files still cost time and memory; concurrent
writers are not coordinated.

## Public command and update behavior

GitHub has no configured Pages site or separate website build. The repository
[README](../../README.md) and [target guide](../target-repo.md) are the public
entry point. They document:

```text
Claude Code / Grok: /target-repo "/absolute/path/to/repo"
Codex:              $target-repo "/absolute/path/to/repo"
```

Codex CLI/IDE also expose `/skills`; host interfaces can expose a skill picker.
Three native skill copies carry the same source-read-only contract. The launcher
defaults to offline scaffolding, preserves existing configuration and directs
semantic work into the selected target. It neither installs a runtime nor proves
target-agent behavior by itself. It checks source manifests and returns failure
on drift, but is not an OS sandbox or an atomic target transaction.

Repeat adoption updates managed AEF instruction blocks and creates missing
files. Existing owner files and wrappers are preserved. It is not a wholesale
upgrade command: refresh a target's pinned wheel and review template/adapter
changes explicitly. This review did not edit the actual parcel repository or
any other external target, refresh their installed wheels, or run paid models.

## Remaining limits and hard stops

- Legacy checkpoint state remains readable. An old cursor without a sequence
  binding cannot resume automatically; inspect history before recording a
  repaired cursor. Custom durability implementations must enforce the documented
  consistency contract. Existing run/sequence identities cannot be changed or
  silently repaired through `save_checkpoint`; identical retries remain valid.
  No transactional or exactly-once recovery is claimed.
- Unparseable owner graphs, legacy duplicate wrappers and arbitrary SDK control
  flow require inspection. Native harness command discovery is documented and
  fixtures pass; no end-to-end live Claude/Codex/Grok integration was measured.
- Replay cannot recover missing inputs in legacy recordings or arbitrary external
  services. Harvest still constructs default policy, and custom reflection,
  judge settings, external knowledge and custom retrievers remain unbound.
  See the earlier review for partial archive-namespace advice, provider
  error presentation and missing harvest-count instrumentation. The live-candidate
  versus replayed-incumbent comparison remains open.
- The earlier no-tools capability correction is a prompt mechanism, not proof
  that hallucinated tool outcomes are eliminated. A permitted third-party trial
  and matched live evaluation still require real external evidence.
- Evolution, Tier-1 protection, policy denial/HITL defaults and live-spend gates
  remain intact. No automatic self-modification or broader tool scope was added.

## Release validation

Local release checks completed on September 12:

| Check | Observed result |
|---|---|
| Full suite, Python 3.13 | 3,315 passed, 8 skipped, 1 expected failure; 216 warnings, 337.09 seconds. |
| Full suite, Python 3.11 | 3,310 passed, 9 skipped, 1 expected failure; 303.52 seconds, fresh CI dependency environment. |
| Ruff | Repository lint passed; all 332 checked Python files formatted. |
| Strict typing | `mypy --strict aef examples` passed for 139 files. |
| Measurement reproduction | 75 reproduced, 1 expected difference, 0 unexplained. |
| Mindgraph | 287 checks passed; self-test detected 24 planted tokens and 5 contract-gate faults, with no false positives. |
| Targeted fault detection | All five disposable mutations failed their regressions; unmodified controls passed. |
| Actual-source launcher | Fresh and mixed-agent targets each passed initial adoption and an exact rerun. All four source manifests matched across 16,402 entries. |

The mixed-agent fixture preserved nine owner files byte-for-byte and three
instruction prefixes, then verified three distinct graph IDs bound to the
correct Claude, Codex and Grok source files. Reruns preserved all target bytes,
modes and modification times. No actual external target was modified.
Retained evidence: [full suite](evidence/2026-09-12-full-suite.log),
[static checks](evidence/2026-09-12-static-validation.json),
[Python 3.11 validation](evidence/2026-09-12-python311/results.json),
[Python 3.11 final suite](evidence/2026-09-12-python311/pytest-full-final.log) and
[its retained artifacts](evidence/2026-09-12-python311/artifact-index.json),
[measurements](evidence/2026-09-12-measurements.log),
[Mindgraph verification](evidence/2026-09-12-mindgraph-verify.log),
[Mindgraph self-test](evidence/2026-09-12-mindgraph-self-test.log), and
[launcher results and adjacent logs](evidence/2026-09-12-launcher-release/launcher-release-check.json).

The Python 3.11 run used a disposable macOS ARM64 source snapshot and a fresh
`[dev,anthropic,mem0]` environment matching CI extras. Its lint, formatting,
strict typing, dependency consistency and measurement checks also passed. The
optional `mem0-integration` extra was absent, so five integration tests were
replaced by one module skip; this explains the count difference. These are
local checks, not evidence that GitHub Ubuntu runners completed. The
[final snapshot comparison](evidence/2026-09-12-python311/snapshot-current-comparison.json)
confirmed no code differences across 1,174 captured paths; only review reports
and retained evidence had changed.

Earlier full-suite failures exposed shared shadow storage and a removed literal
`green bar` documentation contract; both were corrected before the passing run.
The release fixture's first final assertion looked for persona graphs at the
wrong directory depth. Its corrected recursive check passed with explicit
source-to-graph binding assertions. These checker corrections are not additional
runtime fixes. Python 3.11 then exposed an existing exact-float fixture whose
means differed in the last bit across interpreter versions. The fixture now
uses exactly representable values while preserving paired directions and the
verdict; production scoring is unchanged. The final Python 3.13 fixture module
[passed all 17 tests](evidence/2026-09-12-python313-pairing-final.log) after its
full-suite run. The existing expected failure remains the widened-root
every-graph acceptance scan described by F-M5-1. Skips and synthetic fixtures
provide no live-harness or learning-quality evidence.

Cleanup removed 52 individually verified ignored cache/build directories.
After validation, it removed 20 verified cache/build directories recreated by
the checks. Git cleanup removed the merged local `codex/model-review-20260908` branch and the merged remote
`wikiskill/knowledge-layer` branch. Both branch tips were proven ancestors of
main before deletion; the remote deletion used an exact SHA lease. There were
no redundant worktrees. The active checkout, dependencies, `.claude/state`,
`.scratch` and all tracked files were preserved. See the
[cache audit](evidence/2026-09-12-cache-cleanup.json) and
[Git audit](evidence/2026-09-12-git-cleanup.json).

This report records pre-commit local evidence. Existing GitHub CI and monitor
[annotations](evidence/2026-09-12-github-runner-blocker.json) state that jobs could not start because recent account payments
failed or spending limits need adjustment. Local checks do not establish remote
CI success. Publication requires the release commit at `origin/main`; the
commit's [Actions run](https://github.com/AndrewGoodson/aef-core/actions/workflows/ci.yml)
is the source of truth for whether remote Python 3.11/3.13 jobs actually ran.
The final release response reports that exact commit and its CI outcome.
