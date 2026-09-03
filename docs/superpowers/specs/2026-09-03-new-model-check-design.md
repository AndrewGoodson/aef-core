# `/new-model-check` — design

Date: 2026-09-03. Status: approved (owner chose approach 2, apply-everything
mode, shipped by `aef adopt`).

## Problem

The self-improving loop in this repo is not a Python program that calls a
model. It is a coding agent (Claude Code, today Fable 5.1) reading prompt
surfaces: `CLAUDE.md`/`AGENTS.md`, the loop prompts, `.claude/agents/*`,
`.claude/skills/*`, and the templates `aef adopt` writes into other repos.
Every model release changes what those prompts should say — Fable 5.1's
guide, for one, says prompts written for prior models are often too
prescriptive and reduce output quality — and nothing re-checks them. The
dormant Python provider has the same problem at the API level: it sends
`temperature` on every call, which current models reject with a 400.

## Goal

A slash command, `/new-model-check [model-id]`, that a person runs once per
model release. It re-audits every model-facing surface against that
model's documented breaking changes and behavioral guidance, applies the
fixes, proves them, commits per step, and stops. It must work in a repo it
has never seen, because `aef adopt` ships it.

## Non-goals

- A Python scanner or a pinned capability table. Both rot per release.
- Auto-running on model change. A person invokes it.
- Choosing a model for the user. The target is the argument, else the
  session's own model.

## Design

### Where model knowledge comes from

The skill carries no per-model facts. It gets them, in order:

1. The bundled `claude-api` skill (`Skill(claude-api)`), whose
   `shared/model-migration.md` ships with every Claude Code release and has
   a `[BLOCKS]`/`[TUNE]` checklist per target model.
2. Fallback for harnesses without it: `WebFetch` of the public migration
   guide at `https://docs.claude.com/en/docs/about-claude/models/migration-guide`.
3. If neither is reachable: stop and say so. Do not audit from memory.

### Procedure (what `SKILL.md` says)

0. **Target.** `$ARGUMENTS` if given, else the model named in the session
   prompt. Record it. Run `git status`; a dirty tree is a stop.
1. **Model facts.** Load per above. Extract the `[BLOCKS]` list (API
   rejections) and the `[TUNE]` list (behavioral guidance). Note what the
   guide says to *keep* — for Fable 5.1, verification instructions stay.
2. **Inventory.** Two surfaces, found by glob, never by a hardcoded path:
   - *API surface*: files importing a vendor SDK or naming a model ID.
   - *Prompt surface*: `CLAUDE.md`, `AGENTS.md`, `AUTONOMY.md`,
     `AGENT_INTEGRATION.md`, `*_LOOP*.md`, `.claude/agents/*.md`,
     `.claude/skills/*/SKILL.md`, `.github/copilot-instructions.md`,
     `.cursor/rules/*`, and any code that *renders* those (templates).
   Before trusting the grep: plant a known-bad token in a scratch file,
   confirm the grep finds it, delete the file. A detector that has not
   caught a planted fault has not been shown to detect.
3. **Classify and apply.** For each `[BLOCKS]` hit: fix, with a test that
   fails before and passes after, then a mutation check (perturb the
   production value, confirm the test fails, revert). For each `[TUNE]`
   item: apply to the prompt surface — remove text the guide says to remove
   before adding text it says to add; add the autonomy, scope and
   test-sprawl blocks to any surface that governs unattended runs; do not
   remove verification instructions. Every prompt edit is quoted
   before/after in the commit body with the behavioral shift that motivates
   it — prompt edits are judgment calls and must be reviewable as such.
4. **Runtime spot-check.** If a vendor credential is available, one
   minimal call against the target model asserting `response.model`
   starts with it. If not, say "not run: no credential" — never imply it
   ran.
5. **Green bar** after every step: the repo's own test/type/lint commands
   (this repo: `pytest -q; mypy aef examples; ruff check .; ruff format
   --check aef tests examples`). Test count grows or holds.
6. **Record.** `docs/model-checks/<date>-<model>.md`: target, source of
   facts, every finding as *reproduced* or *suspected* (never blurred),
   what changed, what was deliberately left. An ADR if a public contract
   changed. Commit per step; push to `origin main` of the current repo is
   allowed by the loop contract and nothing further is.
7. **Bound.** When the two checklists are exhausted, stop. Do not
   manufacture findings to keep running.

HARD-STOP gates (`docs/autonomy/self-improving-loop.md` §4) apply unchanged:
external publish, weakening a security control, overwriting a user file in
an adopted repo, or an uncertain public-contract break each require a
human.

### Shipping

Source of truth: `aef/cli/templates/skills/new-model-check/SKILL.md`
(package data — hatchling ships everything under `aef/`). `aef adopt` writes
it to `.claude/skills/new-model-check/SKILL.md` via `_write_if_absent`, same
never-overwrite rule as every other scaffold file. This repo's own
`.claude/skills/new-model-check/SKILL.md` is a copy, pinned byte-identical
to the template by a test — the same mechanism that pins `AGENTS.md` to
`CLAUDE.md`.

### Testing

- `tests/cli/test_adopt.py`: adopt writes the skill; never overwrites an
  existing one; the template and this repo's copy are identical.
- Provider fixes each get a failing-first test plus a mutation check,
  recorded in the model-check report.
- The skill's own detector is checked against a planted fault on every run
  (procedure step 2), not once at authoring time.

## First run

The skill's first run is on this repo against `claude-fable-5-1`, and that
run *is* the requested Fable 5.1 system review. Its report is
`docs/model-checks/2026-09-03-claude-fable-5-1.md`.
