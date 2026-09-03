# ADR 0111: A model release is a scheduled audit, not a surprise

## Status
Accepted. Ships `/new-model-check` and the result of its first run
(`docs/model-checks/2026-09-03-claude-fable-5-1.md`).

## Context

The self-improving loop in this repo is not a Python program that calls a
model. `aef/harness/` (9.5k lines) makes no model call at all. The loop is a
coding agent — Claude Code, today Fable 5.1 — reading prompt surfaces:
`CLAUDE.md`, the loop prompts, `.claude/agents/*`, `.claude/skills/*`, and
the templates `aef adopt` writes into other repos. The Python provider
(`aef/providers/anthropic_provider.py`) is the only SDK call site and is
dormant on the box that runs the loop; it matters because `adopt` ships it.

Every model release changes both surfaces, and nothing re-checked either:

- The provider sent `temperature` on every call. Every current Anthropic
  model rejects sampling parameters with a 400. It could not talk to any of
  them, and no test noticed because the fake client accepted anything.
- Every example config and both scaffold templates declared
  `model: claude-sonnet`, which is not a model ID.
- The vendor guide for Fable 5.1 says prompts written for prior models are
  often too prescriptive, names text to remove, and provides blocks to add
  for unattended runs. The loop contract had none of the latter.
- `.claude/` was gitignored in full. `reproduce-first` and `seam-hunter`,
  which `CLAUDE.md` calls the verification method and the dev pod, existed on
  one machine. A clone had neither — the same defect shape the previous
  commit (8948d6a) closed at the onboarding layer, one level down.

## Decision

1. **A skill, not a scanner.** `/new-model-check <model-id>` is a procedure
   in `SKILL.md`. It carries **no per-model facts** — a fact table or a
   capability pin here rots the day the next model ships, which is the
   defect being fixed. It loads facts each run from the bundled `claude-api`
   skill (updated with every Claude Code release), falls back to the public
   migration guide, and stops if neither loads. Auditing from memory is the
   failure mode, not a fallback.
2. **Reproduce-first applies to the audit itself.** The inventory grep is
   verified against a planted fault before "nothing found" is believed;
   every `[BLOCKS]` fix gets a failing-first test and a mutation check;
   findings are reported as *reproduced* or *suspected*, never blurred. A
   box without a credential reports every API finding as suspected.
3. **Remove before add, and keep verification.** `[TUNE]` edits follow the
   guide's order — delete text the new model over-obeys, then add its
   blocks — and never remove an instruction to test or check work. Every
   prompt edit's commit quotes before/after and the motivating shift, so a
   reviewer can disagree with one line without reverting the rest.
4. **Shipped by `adopt`, pinned by a test.** The template under
   `aef/cli/templates/` is the source of truth; `adopt` writes it
   never-overwrite; this repo's own copy is asserted byte-identical. Two
   drifting copies is how the skill that ships and the skill that was tested
   stop being the same document.
5. **The dev pod is tracked.** `.gitignore` narrows from `.claude/` to
   `.claude/*` with `skills/` and `agents/` re-included; harness state
   (`state/`, `worktrees/`, the lock) stays ignored.

## Consequences

- The provider adapter changes behaviour on three inputs: sampling
  parameters are no longer forwarded (the vendor-neutral field stays);
  `role="tool"` is refused by name before the network; `stop_reason ==
  "refusal"` raises `ModelProviderError`, which is the repo's own fallback
  mechanism — `FallbackProvider` catches it and tries the next provider, a
  lone provider fails loudly instead of returning `""`. `max_tokens`
  defaults to 16000, because on current models it caps thinking plus reply.
- `LLMSummariser.temperature` is now inert for the Anthropic adapter. Left
  in place: it is a vendor-neutral request field, and removing it is a
  separate decision about the summariser, not this check's.
- Shipped `AUTONOMY.md` and the loop contract carry ~400 words of
  model-dated prompt text with a section header saying which run added it
  and that the next run edits there. That is the cost of the guide's
  finding that placement and exact wording matter; paraphrase was
  deliberately not used.
- The first run found no text to remove. That is a result, not a skipped
  step: the remove-first scan (anti-narration, anti-formatting, caps
  escalation, dated idioms, retired model names) was run and its five hits
  were all verification/safety rules on the guide's keep list.

## What the first run did not do, stated so nobody infers it did

- No live call was made. This box has no credential. Every API finding is
  documented in the loaded guide and **not reproduced**.
- No effort or sub-agent tuning: agent definitions declare neither, and the
  guide is explicit only where they do.
- No A/B of the prompt surface with prior-model scaffolding removed. The
  guide recommends one; this repo has no prompt eval to run it against.
  Follow-up, not done.
- Server-side `fallbacks` were not adopted. `FallbackProvider` is the
  repo's mechanism and the refusal path now feeds it.

## Adversarial notes from the run

Three of five test-side steps had a hole in the test, not the code, which
is the ratio the handoff predicted:

- A patch anchor matched two sites; the second edit landed in the symlink
  test and read as a detection. Caught because the wrong test failed.
- The escape-depth assertion for the shipped `\#` was itself one level
  wrong; it failed against correct output.
- Wrapping the blockquotes for ruff split an asserted phrase across lines;
  the test was comparing raw lines where the rendered form joins them.

All three were fixed in the test. None weakened a control.

## Confidence

High on the mechanism and the provider fixes; moderate on the prompt
blocks, which are the vendor's measured recommendation applied without a
local measurement.
