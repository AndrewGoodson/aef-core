# ADR 0212: `model_provider.effort`, and Claude Opus 5.5 as the shipped default

Status: accepted 2026-09-23, from the `/new-model-check claude-opus-5-5` run
(`docs/model-checks/2026-09-23-claude-opus-5-5.md`).

## Context

The bundled `claude-api` skill (2.1.280, `shared/model-migration.md`,
"Migrating to Claude Opus 5.5") names two things that touch this repo:

- Thinking can no longer be disabled; `{type: "disabled"}` and
  `budget_tokens` return 400 at every effort level. "Effort is now the
  control for how much the model thinks, and therefore for latency and cost."
- "The API default is `medium` (Claude Opus 5 and earlier Opus models
  default to `high`) … **Set `effort` explicitly**."

Neither adapter that can reach Opus 5.5 (`anthropic`, `claude_code`) sends
`thinking`, `tool_choice` or `tools`, so nothing here 400s. But neither could
set effort either: an owner who wanted Opus 5's depth had no way to ask.

## Decision

1. `ModelProviderConfig.effort: low | medium | high | xhigh | max`, optional.
   `anthropic` forwards it as `output_config.effort`; `claude_code` as the
   CLI's own `--effort` flag. **Unset sends nothing**, so every existing
   request, argv and cassette key is unchanged and each model keeps its own
   default.
2. Effort on an impl that would ignore it (`codex`, `grok`, `command`,
   primary or fallback) is a validation error — the same present-but-ignored
   rule as the `command:` block (ADR 0154).
3. The four shipped defaults (two example configs, the `aef adopt` and
   `aef init` templates) move from `claude-opus-5` to `claude-opus-5-5`, by
   owner decision. A test now requires the four to agree.
4. The prompt-surface test forbids think-suppression and
   reasoning-extraction text, which the guide says to delete. None exists.

## Not decided

No default effort is set. The guide says `medium` on Opus 5.5 "exceeds
Claude Opus 5 at `high`" on coding evals; this repo has not measured that on
its own corpus, and choosing a value without a measurement is the shape
ADR 0193 warns about. An owner who wants one sets it.

## Evidence

- One live call through `claude_code` with `--model claude-opus-5-5
  --effort low`: returned model `claude-opus-5-5`, content `ok`. Reproduced.
- `anthropic` with `output_config.effort`: fake-client tests only; no API
  key on this box. Suspected-correct from the guide, not run.
