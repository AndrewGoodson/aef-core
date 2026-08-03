# ADR 0016: `aef adopt`'s framework detection also scans dependency manifests, not just `.py` imports

## Status
Accepted

## Context
`detect_framework` only ever scanned `.py` files for `import`/`from`
statements. This misses a real, common moment in the adoption path this
command exists for: a repo where `langgraph` (or `crewai`, or
`openai`/`anthropic`) is already declared in `requirements.txt` or
`pyproject.toml` — someone just ran `pip install langgraph` and is about
to start writing code — but no `.py` file imports it yet. `aef adopt` run
at exactly that moment reported `"none"`, generating a `none`-flavored
`CLAUDE.md`/checklist ("no agent framework... detected. Start from
scratch") for a repo that's about to be a LangGraph repo. The build task
named this command "the part I care most about" — detection quality here
matters more than in most other places this session touched.

## Decision
`detect_framework` now scans two signal sources and combines them, not
one-source-then-the-other: `.py` files (unchanged, `import`/`from`
anchored) and dependency manifests — `requirements*.txt`, `pyproject.toml`,
`Pipfile` — found anywhere in the tree (not just repo root, so a monorepo
with the framework declared under `services/agent/requirements.txt` is
still caught), matched with a looser word-boundary regex since manifest
files don't have import syntax to anchor on. The same priority order
(langgraph > crewai > raw_sdk > none) applies across the combined signal
set, not per-source — a `crewai` import alongside a `langgraph` manifest
entry still resolves to `langgraph`, tested explicitly so a future change
to either source's precedence is a visible decision, not an accidental
regression.

Also added regression tests for two behaviors that existed before this
change but had no test locking them in: multiple frameworks genuinely
present (no objectively "correct" tie-break exists; the current
deterministic order is now explicit and tested) and manifest files inside
ignored directories (`.venv`, etc.) correctly not counting.

## Consequences
- `aef adopt` run immediately after `pip install <framework>` and before
  writing meaningful code now detects correctly, generating the right
  migration checklist instead of the "none" fallback.
- Manifest scanning is a pure word-boundary match (`\blanggraph\b`) —
  broader than the import-anchored code regex, so a comment or a
  false-positive string mention in a manifest-adjacent file *could*
  theoretically trigger a false positive. Accepted: manifest files are
  structured dependency declarations, not free-form text, so this risk is
  low, and a false positive here costs a slightly-wrong migration
  checklist, not an incorrect production behavior.

## Alternatives Considered
- **Parse `pyproject.toml`/`requirements.txt` properly (TOML parser, line-based
  requirement parser) instead of a regex over raw file text.** Rejected as
  disproportionate: the signal needed is "is this package name mentioned
  at all," not a structured dependency graph — a regex answers that
  correctly for every realistic manifest shape without a parsing
  dependency (`tomllib` is stdlib in 3.11+ and would work, but adds
  format-specific code for marginal precision gain over a word-boundary
  match).
- **Only check repo-root manifests, not the whole tree.** Rejected: the
  build task explicitly cares about the adoption path working well, and
  monorepos with the actual agent code (and its manifest) in a
  subdirectory are a realistic shape `aef adopt` should still get right.

## Confidence
High — directly reproduces and fixes a concrete, plausible false-negative
in the command the build task most cares about getting right, verified
against real temp-directory fixtures for every new scenario (manifest-only,
subdirectory, variant filename, mixed code+manifest signals, ignored-dir
exclusion), not just reasoned about.
