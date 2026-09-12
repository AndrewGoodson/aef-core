# Codex review — 2026-09-08

**The inherited real-repository result is negative:** incumbent 0.6667,
learned lesson 0.4000, placebo 0.8667. This review does not turn the 92/100
machinery rubric into readiness or claim that new prompts improved live
answers. The incumbent was cassette-replayed; candidate and placebo each had
five live calls. Resampling alone moved the incumbent +0.2. The small
comparison warrants rejecting readiness, but does not precisely isolate
causality across all three arms. See [ADR 0204](../adr/0204-the-loop-on-a-repo-somebody-uses-and-the-bullet-that-made-it-worse.md).

The requested [goal prompt](../../MODEL_REVIEW_GOAL.md) was created and
executed by this Codex session, GPT-6 family; an exact provider model ID is
not available in this session. Baseline was clean `main` and `origin/main`
at `6786c4a1d922f15ff1f1a398191ab9170838f51f`. Changes are on
`codex/model-review-20260908`, uncommitted and unpushed. Work was confined to
aef-core and disposable fixtures. Historical handoff and measurement files
retain their original observations.

## Review coverage

This was repository-wide orientation, focused implementation review and the
full regression suite. It was not a claim to inspect every line or prove the
absence of security defects. The most consequential changes are specified in
[ADR 0205](../adr/0205-evidence-learning-and-cross-harness-replay.md).

| Surface | Review and result | Limit |
|---|---|---|
| Graph kernel, state, durability | Checked fixed node/Services contract, execution/replay boundaries and existing regression coverage; recorded missing service inputs | No new graph algorithm or fan-out implementation |
| Providers and prompt execution | Captured runtime request reproduces missing no-tools instruction; now explicit only when provider declares it | Instruction compliance and live model quality unmeasured |
| Memory, knowledge, corpus | Five sequential persistent-memory runs; tenant snapshots, consolidation, harvest and both replay paths exercised | Legacy missing inputs and arbitrary external stores cannot be recovered |
| Native adoption and migration | Claude/Grok Markdown and Codex TOML discovery, graph compilation, collisions, symlink refusal, scope reporting, preserved owner bytes and idempotence | Synthetic repo validation; Grok discovery additionally checked against local CLI 1.0.5 |
| Prompt learning and proposal | Shared evidence protocol; bounded TOML lesson edits preserve non-prompt configuration | Existing append-only proposer; no new optimizer or automatic forgetting |
| Gates, policy and isolation | Existing gate/security suite retained; nested vendor import mutation detected; recorded errors remain visible through fallback | No claim that in-process execution is a complete hostile-code boundary |
| Packaging and CI | Inspected `pyproject.toml` and three workflow definitions; ran local CI-equivalent green bar and published-measurement check | No fresh wheel-install matrix or hosted Actions run |
| Docs and harness contracts | Reconciled AGENTS/CLAUDE, tested equality and shipped protocol consistency; wrote goal, ADR and this audit | Historical dated measurements remain historical |

## All nine inherited findings

“Fixed” below means the reproduced mechanism is corrected locally. It does
not mean a fresh real-repository live pilot passed.

| Finding | Severity | Disposition and evidence |
|---|---|---|
| F-Q1-1: tool-using persona with tools off | High | **Fixed mechanism.** Captured-request regression was RED before the capability message; a mutation removing it fails. Unknown provider declarations do not claim no-tools containment. Live hallucination rate not remeasured. |
| F-N7-1: later memory-backed runs discarded | High | **Fixed for new FileMemoryStore recordings.** Original missing-input reproduction failed; five successive runs now harvest and replay with recorded pre-run context in ordinary and isolated execution, including reversed order; live memory bytes stay unchanged. Old recordings without snapshots remain limited. |
| F-Q1-3: archive graph-ID mismatch | High | **Partial.** Preflight recovery advice now includes the chosen archive namespace and warns to use the same ID throughout. The implicit `default` versus explicitly blessed ID mismatch is not automatically reconciled. |
| F-Q1-4: reused work directory | Medium | **Fixed.** Generated commands use a fresh `mktemp` parent and nonexistent child per invocation; restoring the fixed path fails the regression. |
| F-Q1-5: provider failure called agent regression | Medium | **Partial.** Synthetic provider failure routed through graph fallback now exposes its exception type in both runners; no secret error body is copied. The exact external unlaunchable-provider pilot and the G2 headline were not fully rerun/fixed. |
| F-N7-2: unmeasured scenario count printed as zero | Medium | **Partial.** Missing count is `unknown`, eliminating the false zero and its warning. Actual harvest-count instrumentation remains open. |
| F-N7-3: agentless entrypoint checklist | Low | **Fixed.** Generated checklist asks for a first objective when there is no legacy agent. |
| F-P1-2: doctor ignores committed halt configuration | Medium | **Fixed.** `doctor --config` uses the configured block without executing the command; legacy environment configuration remains supported. |
| F-P1-3: live candidate versus replayed incumbent | Unassigned | **Open.** Source and historical evidence confirm the asymmetry. No new paired live gate mode or paid remeasurement was introduced. The protocol explicitly rejects this comparison as sufficient improvement evidence. |

Additional reproduced defects corrected here: native definitions silently
omitted, suffix collisions, unsafe symlink discovery, TOML lesson editing,
mixed-directory Zone A reporting, provider-declaration loss in recording,
and root harness-contract drift. The full integration run also exposed a
test fixture leaking a temporary `agents` import across tests; teardown now
restores the import path and modules. A later full run caught changed wording
for a missing live provider; the production diagnostic was restored while the
existing scoring/no-retry assertions remained unchanged.

## Research translated into implementation

Sources were inspected on 2026-09-08. “Current” means the sources checked
here, not an exhaustive survey of every new paper or a claim to implement
their reported algorithms.

| Primary source | Applicable idea | What changed here |
|---|---|---|
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Execution durability depends on recorded state and replay inputs | Capture the memory/context actually available before a run, then replay from that snapshot |
| [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), 2025-09-29 | Deliberate, bounded context and explicit tool design | Capability message, scoped evidence cards and fallible retrieved lessons |
| [GEPA](https://arxiv.org/abs/2507.19457), July 2025 | Reflection over execution feedback can guide prompt search | Require failure provenance and falsifiable corrections; GEPA search itself not implemented |
| [ACE](https://arxiv.org/abs/2510.04618), October 2025 | Structured incremental context updates | Bounded lesson changes and explicit supersession guidance; existing proposer remains append-only |
| [Meta Context Engineering](https://arxiv.org/abs/2601.21557), January 2026 | Context-construction methods can themselves be evaluated | Pin prompt/context revisions and distinguish mechanism tests from outcome evidence; no meta-optimizer claimed |
| [Anthropic agent evaluations](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Outcomes, graders and repeated trials need deliberate design | Separate infrastructure failures, retain held-out tasks and require comparable live arms before improvement claims |
| [OpenAI subagent configuration](https://developers.openai.com/codex/subagents) and [AGENTS.md](https://developers.openai.com/codex/guides/agents-md) | Native instruction files and required TOML fields | Discover Codex definitions and edit only `developer_instructions`; preserve configuration without granting permissions |

Grok was verified locally, not inferred from a filename convention:
`/Users/raptor/.grok/bin/grok` resolved to CLI 1.0.5. An isolated initialized
repository inspected without model execution discovered root AGENTS/CLAUDE
and `.grok/agents/aef-probe.md`; root `GROK.md` and `.grok/GROK.md` were not
discovered. This is version-specific evidence, not a promise for future Grok
releases. Migration support does not certify Grok provider containment; the
prior provider limits still apply.

## Verification

Baseline: **3,177 passed, 8 skipped, 1 xfailed** in 196.74 seconds.
Final: **3,197 passed, 8 skipped, 1 xfailed** in 166.89 seconds.

The first integrated full run returned **1 failed, 3,195 passed, 8 skipped,
1 xfailed**. Its failure was the missing-live-provider wording regression
described above. No existing assertion was weakened to make it pass.

| Check | Result |
|---|---|
| `pytest -q` with a fresh explicit temporary directory | PASS: 3,197 passed, 8 skipped, 1 xfailed |
| `mypy --strict aef examples` | PASS, 137 source files |
| `ruff check .` | PASS |
| `ruff format --check aef tests examples` | PASS, 323 files |
| `make measure-ci` | PASS: 75 rows reproduce, 1 already-recorded expected drift, 0 unexplained; drift set unchanged |
| Production mutation checks | **19/19 detected**, all source bytes restored and SHA-256 checked |

The [mutation manifest](evidence/2026-09-08-mutations.json) names every
production edit, exact test, failure exit code and before/after hash. Mutations
ran sequentially with isolated bytecode caches and `finally` restoration.
They cover capabilities, memory snapshots, provider metadata, native
discovery, collisions, symlinks, TOML edits, unknown metrics, halt config,
archive guidance, work directories, agentless onboarding, fallback diagnosis,
scope reporting, protocol distribution, contract drift, vendor isolation,
missing-live-provider diagnosis and memory redaction. A mutation hash describes
its test checkpoint, not a release artifact hash.

Local raw logs remain under `/tmp/aef-review-*`; selected final evidence is
retained in the [validation log](evidence/2026-09-08-validation.txt). Earlier RED logs record the individual
reproductions; the full-suite and mutation failures above are included rather
than hidden by the final successful result. Remaining skips/xfail are reported
as unexecuted/expected limitations, not passing coverage.

## Follow-up: target-only integration command

The owner also requested an integration command that leaves this source
checkout unchanged when invoked. [ADR 0206](../adr/0206-target-repo-command.md)
records the implementation; the [usage guide](../target-repo.md) gives the
Claude/Grok slash command and Codex's native `$target-repo` skill invocation.

The launcher performs guarded adoption and mechanical migration; the skill
continues target-local semantic wiring and validation. Source/target overlap,
shared source Git metadata and linked output paths are refused. Python imports
run with bytecode writes disabled. Existing target instructions, configuration
and hand-edited graphs survive. Skill instructions require before/after source
manifests, including ignored files, in addition to Git status/diff.

The focused suite passed **224 tests**. Its first run had three environment
failures because subprocesses could not find `ruff`; activating the documented
virtual environment resolved them without code or assertion changes. The
final full suite passed **3,210 tests, with 8 skipped and 1 xfailed** in 184.50
seconds. Ruff, formatting (326 files), strict typing (138 files), and all three
skill validators passed. Published measurements remain **75 reproduced,
1 known drift, 0 unexplained**.

Both added production mutations were detected: removing hard-link protection
and enabling source bytecode writes. Original source bytes were restored and
SHA-256 verified. The [mutation evidence](evidence/2026-09-08-target-repo-mutations.json)
and [validation log](evidence/2026-09-08-target-repo-validation.txt) retain the
results. Temporary-repo manifests verify source contents, modes, modification
times, Git metadata and ignored/new paths across successful and refused runs.

No actual target repository was supplied for this command, so its semantic
integration workflow has not been executed against an owner's selected repo.
Later agent actions are governed by the skill; the launcher is not an OS
sandbox against concurrent path replacement or arbitrary target test code.

## Remaining owner decisions and stops

Choose an independent third-party adopting repository and its acceptance
tasks. Authorize any paid matched live incumbent/candidate/placebo run and
the provider's actual capability model. Select a personal halt destination.
These are external inputs, not work a model can substitute with fixtures.

The resulting scaffold is better at preserving evidence, explaining its
capabilities and ingesting native personas. Useful real-repository learning
is still unproven. Evolution, Tier-1 auto-merge, policy/HITL boundaries,
held-out ownership and per-repository Zone A selection remain in force.
