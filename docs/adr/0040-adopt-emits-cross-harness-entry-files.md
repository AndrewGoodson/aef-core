# ADR 0040: `aef adopt` emits a native entry file for every major coding-agent harness

## Status
Accepted

## Context
aef-core's *core* is already harness-agnostic: the `aef` package and CLI are
plain Python, so any coding agent that writes Python — Claude, OpenAI Codex,
Cursor, GitHub Copilot — can author nodes against it. But the *onboarding
layer* was Claude-shaped: `aef adopt` emitted `CLAUDE.md` (which only Claude /
Claude Code reads) plus `AGENT_INTEGRATION.md`/`AUTONOMY.md`, and the docs
said things like "a fresh Claude Code session." An adopted repo therefore
handed its scaffold contract to Claude but **not** to the other harnesses,
each of which reads a *different* instructions file:

- Claude / Claude Code → `CLAUDE.md`
- OpenAI Codex (and the emerging cross-tool convention) → `AGENTS.md`
- GitHub Copilot → `.github/copilot-instructions.md`
- Cursor → `.cursor/rules/*.mdc`

So on Codex/Copilot/Cursor, an adopted repo's agent would start with no
aef-core context at all — the scaffold read as Claude-only even though the
library isn't.

## Decision
`aef adopt` now emits a native entry file for each major harness, all
resolving to the one canonical guide so there's a single source of truth:

- **`AGENTS.md`** — written identical to the generated `CLAUDE.md` (the full
  scaffold contract). Codex and the cross-tool `AGENTS.md` convention read
  this; keeping it byte-identical to `CLAUDE.md` mirrors how the aef-core repo
  itself carries both.
- **`.github/copilot-instructions.md`** and **`.cursor/rules/aef.mdc`** — thin
  native pointers (a shared body) that name the two always-on invariants,
  the four-command green bar, and the HARD-STOP gates, then point at
  `AGENT_INTEGRATION.md`/`AUTONOMY.md` for the rest. The Cursor file carries
  the minimal `.mdc` frontmatter (`alwaysApply: true`). Thin pointers, not
  full copies, so the contract lives in one place and can't drift four ways.

`adopt`'s `_write_if_absent` now creates parent directories (for `.github/`,
`.cursor/rules/`), and all three new files are never-overwrite like the rest
(HARD-STOP gate #3 — the tool emitting the gates honors them). Claude-specific
phrasing in the shared docs and generated templates was neutralized to
"coding agent (Claude, Codex, Cursor, GitHub Copilot, …)", and
`AGENT_INTEGRATION.md` gained a harness→entry-file table plus a note that the
`/loop` bootstrap prompt is Claude Code's trigger and runs on any harness by
dropping the prefix.

## Consequences
- A repo adopted with `aef adopt` is usable from Claude, Codex, Copilot, or
  Cursor out of the box — each agent finds the scaffold in the file it
  natively reads. The library was already portable; the onboarding layer now
  is too.
- `aef adopt` writes nine files (was six); never-overwrite and idempotent
  second-run behavior hold for all of them (re-tested), and the new
  subdirectory files are created without clobbering an existing `.github/` or
  `.cursor/`.
- Single source of truth preserved: `AGENTS.md` duplicates `CLAUDE.md` by
  construction (same render), and the Copilot/Cursor pointers carry only the
  safety essentials + a link, so there is one contract to maintain, not four.
- 321/321 tests (three new: all-nine-artifacts, per-harness entry-file
  content, never-overwrite for the harness files; idempotency updated
  6→9), mypy --strict clean (incl. examples), ruff clean.

## Alternatives Considered
- **Emit full copies of the contract into all four files.** Rejected: four
  independently-maintained copies drift. `AGENTS.md` is a deliberate exact
  duplicate of `CLAUDE.md` (both are "full contract" filename conventions),
  but Copilot/Cursor get pointers so the body lives once in
  `AGENT_INTEGRATION.md`.
- **Emit only `AGENTS.md` and rely on every tool eventually reading it.**
  Rejected: Copilot and Cursor do not read `AGENTS.md` today — they read
  their own paths — so an `AGENTS.md`-only approach still leaves two of the
  four named harnesses with no entry point.
- **A single legacy `.cursorrules` file for Cursor.** Rejected in favor of
  the modern `.cursor/rules/*.mdc` format (the current Cursor convention),
  which supports the `alwaysApply` frontmatter so the rule is reliably in
  context.

## Confidence
High — the gap (adopt emitting Claude-only entry files) was verified
directly, the fix was confirmed end-to-end by running the real `aef adopt`
in a clean temp dir and inspecting all nine emitted files across the
`.github/` and `.cursor/rules/` subdirectories, and never-overwrite is
re-tested for the new harness files. The per-harness entry-file conventions
(`AGENTS.md`, `.github/copilot-instructions.md`, `.cursor/rules/*.mdc`) are
the documented ones for those tools as of 2026.
