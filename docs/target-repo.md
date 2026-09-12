# Integrate a target repo

Point AEF at an existing absolute directory, including a new repo or one that
already has agents. Run the skill from a coding-agent session in the AEF checkout:

| Harness | Command |
|---|---|
| Claude Code / Grok | `/target-repo "/absolute/path/to/your repo"` |
| Codex | `$target-repo "/absolute/path/to/your repo"` |

Codex CLI and IDE also support selection through `/skills`; other host interfaces
may expose a skill picker. Repository skills live in `.claude/skills`,
`.agents/skills`, and `.grok/skills`; the three copies share the same contract.
Restart the session if its skill list has not refreshed. The skill resolves the
AEF source from its own location, so the target is always the path you supply.

The command performs adoption and mechanical migration, then directs the
coding agent to complete and test the applicable integration **in the target**.
All target implementation, environments, reports and tests belong there. The
AEF checkout remains read-only throughout this invocation.

## Prepare AEF once

Use Python 3.11 or newer. Before starting a target invocation, prepare the source
checkout's environment in a separate setup step:

```sh
cd /absolute/path/to/aef-core
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

The target launcher uses the source's existing `.venv/bin/python`, or the
invoking Python when no source virtual environment exists. AEF's dependencies
must already be available; the launcher does not install them. If dependencies
are missing, stop that invocation and prepare the environment separately.

The target itself should use an **installed, pinned AEF wheel in its own
environment**, with the wheel hash and source revision recorded. Follow the
generated target guide for packaging and installation. An editable target
dependency pointing back to this AEF checkout does not provide isolation.

## Terminal entry point

The deterministic phase can run without a coding agent:

```sh
python3 -I -B /absolute/path/to/aef-core/scripts/target_repo.py '/absolute/path/to/your repo'
```

This prints generated/preserved paths, migration limitations and the next guide
to read. It does not perform semantic wiring, execute a target agent, install a
target runtime, or prove learning gains. A successful exit means the mechanical
phase and source comparison passed.

The default is `--profile offline`: explicit `model_provider: null`, providerless
graph onboarding and rule-based reflection, with no loop kit or scheduled
workflows. This supports deterministic and tool-only work. Migrated prompt
personas still need a real model provider before they can execute.

For a target that needs model execution, explicitly select the model profile:

```sh
python3 -I -B /absolute/path/to/aef-core/scripts/target_repo.py '/absolute/path/to/your repo' --profile model
```

Model configuration still needs owner wiring and authorized credentials. Live
gate evaluation remains disabled by default (`gates.live_model_calls: false`);
`--profile model` does not grant that permission. To generate the optional
workflow pair as well, add `--with-workflows` to the model command. Offline plus
workflows is rejected before writing. Review a workflow's credentials, corpus
and schedule before enabling it in the target.

The gate workflow prepares trusted dependencies before evaluating in Docker
with networking disabled. Existing workflows are preserved, so applying a
newer template requires an explicit review and update. A credentialed
self-hosted runner also needs GitHub access restrictions outside editable
workflow files; the main-push condition alone is not that boundary. See
[ADR 0211](adr/0211-prepare-workflows-before-isolated-evaluation.md).

Direct `aef adopt --dir /absolute/target` retains its model-profile default for
compatibility, but also omits workflows unless explicitly requested. Use
`--profile offline` with direct adoption when you want the launcher's default.

## New repos and existing agents

| Target contents | Mechanical result | Work still required |
|---|---|---|
| No agents yet | Configuration, onboarding guides and an adapter stub | Define the five agent surfaces and implement a real graph; the stub raises `NotImplementedError` |
| `.claude/agents/**/*.md` or `.grok/agents/**/*.md` | One graph per discovered Markdown persona | Wire a model provider and verify the persona's actual tool and task semantics |
| `.codex/agents/**/*.toml` | One graph per eligible TOML persona with nonempty `name`, `description`, and `developer_instructions` | Review unsupported settings and wire the provider and domain checks |
| Supported Python SDK call sites | Mechanical wrappers, with skipped or unresolved cases reported | Review state mapping, routing, complex functions and actual policy/model instrumentation |
| Existing skills and instruction files | Skills inventoried; AEF guidance added to managed instruction blocks | Skills remain native workflows; instruction prose is not automatically converted into executable nodes |

Native persona graphs run `retrieve -> prompt_agent -> reflect -> consolidate
-> END`. They read the persona at execution time. The default writable agent
root is `agents/`, so the original `.claude`, `.codex` and `.grok` personas are
not rewritten by migration. Widening a loop's writable root is a separate,
explicit choice with a larger blast radius.

Native capability settings are reported, not automatically granted or enforced
by AEF. Provider containment varies. A persona written to use tools must have a
real supported tool path or the mismatch must remain an unresolved limitation;
invented tool results are not evidence. See the
[integration contract](../AGENT_INTEGRATION.md) for provider-specific limits.

## Preservation and updates

AEF maintains signed blocks in `AGENTS.md`, `CLAUDE.md`, `GROK.md`,
`.github/copilot-instructions.md`, `.cursor/rules/aef.mdc` and `.gitignore`.
Owner text outside those blocks is preserved. Text inside an AEF block is
managed content and may be replaced on a rerun. The signature identifies the
managed content; it is not a security boundary. `GROK.md` is a portable guide:
load it explicitly unless your harness documents automatic discovery.

Existing configuration, guides, workflows and generated graphs are preserved,
including hand edits. Rerunning creates missing outputs and refreshes valid
managed instruction blocks. It **does not** force-upgrade the target's AEF
package, replace an existing graph, convert its profile, or disable an existing
schedule.

To update an integrated repo:

1. Update and prepare the AEF source in a separate session, then run
   `target-repo` with the same explicit target path.
2. Inspect the created, updated and preserved paths in the report. Review old
   config, guides and graphs against the current source guidance; apply needed
   changes in the target while retaining owner instructions and custom behavior.
3. Install the chosen pinned wheel in the target and record its hash and source
   revision. Test the target against that installed package.
4. Complete the target checklist and inspect the diff. Report the exact package,
   behavior checks and remaining limitations before treating the upgrade as done.

The same AEF checkout can serve multiple targets. Keep each target's dependency
pin, configuration, corpus, memory and reports separate. The command processes
one target per invocation; it is not a fleet updater.

## Verify the integration

Read the target's `AGENT_INTEGRATION.md`, `AUTONOMY.md`, `FIRST_DAY.md`, and
`AEF_MIGRATION_CHECKLIST.md`. Establish its existing tests, then prove the
applicable success and failure paths, policy denial/HITL behavior, checkpoints,
resume and deterministic replay. Use the target's domain checks instead of
assuming AEF's own source-tree tests exist there.

`aef doctor` checks setup. `aef run` executes a wired graph. `aef eval` scores
recorded execution, and `aef trace` inspects its provenance; trace display alone
is not deterministic replay. The generated guide explains the profile's path.

Record lessons with evidence and failure context. Keep proposed advice separate
from validated improvements. Passing integration tests does not prove that
reflection or prompt changes help a real task. Evolution and automatic candidate
promotion stay disabled; live model spending and publishing require authorization.

## Source integrity and failure behavior

An explicit existing absolute target is required. Source/target overlap and
shared source Git metadata are refused. Every generated write is checked for
symlinks, hard links, nonregular entries and paths escaping the target. Imports
run with `-I -B`: target Python is scanned, never executed, and the source gains
no bytecode. No install, branch change, commit, push or report write runs in the
source. Reports go to stdout; redirect them only to the target when desired.

The launcher snapshots every source entry before and after its child: root,
ignored files, file hashes, permissions, modification times and link targets.
It also covers external Git directories/common metadata for worktrees. It does
not follow arbitrary symlinks or compare access times changed by reads. A match
prints the entry count and manifest digest. Drift prints changed paths with
before/after metadata and forces a nonzero exit, even if the child also failed.
Unverifiable snapshots fail closed; no source restoration is attempted.

The manifest reads all regular source files, including ignored files, twice.
Large virtual environments and generated directories therefore add work in
proportion to their bytes; this is not a constant-time Git-status check.

These checks assume no concurrent process swaps filesystem paths. They are
not an OS sandbox for later agent edits or target test commands. The skill
keeps those actions within the target too and requires its own whole-invocation
baseline. A matching launcher snapshot proves the two observed states match,
not absence of intervening writes; drift does not identify its author.
On a refusal, earlier target outputs may remain; inspect them before retrying.
Existing files are not force-replaced, and the invocation is not transactional.

Native discovery references: [Claude skills](https://code.claude.com/docs/en/skills)
and [Codex skills](https://learn.chatgpt.com/docs/build-skills), checked
2026-09-11; Grok's local `~/.grok/README.md` Skills section documents `/skills`
and `/skill-name` shorthand (verified with CLI 1.0.5). These describe discovery,
not an end-to-end validation of each harness executing this integration.
