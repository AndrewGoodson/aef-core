# ADR 0034: `aef adopt` emits an onboarding kit (integration guide + autonomy contract)

## Status
Accepted

## Context
`aef adopt` already wrote four never-overwrite artifacts into a target repo
(`CLAUDE.md`, `aef.yaml`, `aef_adapter.py`, `AEF_MIGRATION_CHECKLIST.md`).
The onboarding-prep loop (Phase C) needed adopt to also scale the
*autonomy* practice to new repos: a fresh agent in an adopted repo should
be able to ingest aef-core and start the self-improving loop from files in
its own repo, and — critically — should inherit the same **safety contract**
(the HARD-STOP gates) that makes unattended running acceptable, not just the
mechanics.

ADR 0033 codified that contract as `docs/autonomy/self-improving-loop.md` in
aef-core. But `docs/` does not ship in the pip package (ADR 0024), and an
adopted repo is a different repo entirely — so a pointer alone is not enough
for a zero-context start. The adopted repo needs a self-contained guide plus
the gates inlined locally.

## Decision
`aef adopt` now emits two more never-overwrite files:

- **`AGENT_INTEGRATION.md`** — the self-contained ingest-and-start guide:
  what the agent inherits and the five per-agent surfaces, the two always-on
  invariants (two-plane determinism, vendor isolation), a 5-step start
  (`pip install` → `aef doctor` → fill `aef.yaml` → write one node → `aef
  run`/`eval`/`trace`), the node contract, and the guardrails.
- **`AUTONOMY.md`** — the autonomy safety contract inlined into the adopted
  repo: the four-command green bar, the reproduce-first rule, the HARD-STOP
  gates verbatim, the self-learning-is-not-evolution boundary, and the
  bounded-work-list rule — with a pointer to aef-core's canonical
  `docs/autonomy/self-improving-loop.md` for the full spec.

Both go through the same `_write_if_absent` path as the existing four, so
adopt stays never-overwrite (HARD-STOP gate #3 honored by the tool that
emits the gates). The repo `CLAUDE.md`'s adoption section was updated to
enumerate the new files.

## Consequences
- A newly-adopted repo now inherits both the how (integration guide) and the
  safety contract (autonomy gates) as local, self-contained files — a
  zero-context agent can start without reaching into an aef-core source
  checkout it may not have.
- The safety gates are now issued *from the scaffold* into every adopted
  repo, not re-stated per session — the same one-source-of-truth property
  ADR 0033 established for aef-core itself, extended to adopters.
- `aef adopt` now writes six files (was four); the never-overwrite guarantee
  and idempotent second-run behavior are unchanged and re-tested for the two
  new files.
- 298/298 tests (up from 296; three new: all-six-artifacts, onboarding-kit
  content assertions, never-overwrite for the kit — the idempotency test
  updated 4→6), mypy --strict clean, ruff clean. Verified end-to-end in a
  clean base-only venv: real `aef adopt` into a throwaway repo emits all six,
  `aef doctor` then passes.

## Alternatives Considered
- **Only emit a pointer to aef-core's docs, no inlined content.** Rejected:
  `docs/` doesn't ship in the pip package (ADR 0024) and the adopted repo is
  a separate repo — a pointer to a file that may not exist on disk is exactly
  the dead-reference bug ADR 0024 fixed. The gates must be inlined locally.
- **Fold everything into the generated `CLAUDE.md` instead of separate
  files.** Rejected: the integration guide and the autonomy contract have
  distinct audiences and lifecycles (one is start-here onboarding, one is an
  operating-rules contract an unattended agent re-reads), and keeping
  `AUTONOMY.md` a discrete file makes the safety contract easy to locate and
  cite. The generated `CLAUDE.md` links to both.
- **Generate the kit only via a new `aef onboard` command.** Rejected:
  adoption is already the moment a repo joins aef-core; emitting the kit
  there means no extra step to forget. A separate command would be a second
  path to the same files.

## Confidence
High — the emit + never-overwrite behavior was reproduced-first (tests
failing, then passing), the content assertions check the load-bearing pieces
(HARD-STOP gates and the evolution boundary in `AUTONOMY.md`, the node
signature and `aef doctor` step in `AGENT_INTEGRATION.md`), and the whole
adopt flow was exercised end-to-end in a clean base-only venv, not just unit-
tested.
