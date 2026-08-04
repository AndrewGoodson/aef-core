# ADR 0024: `aef adopt`'s generated CLAUDE.md no longer points at a doc that doesn't ship with the package

## Status
Accepted

## Context
End-to-end human-readability check of `aef adopt`'s output: ran `aef adopt`
inside a throwaway repo (a small LangChain+OpenAI agent, simulating a real
adoption target unrelated to aef-core), then read the four generated files
(`CLAUDE.md`, `aef.yaml`, `aef_adapter.py`, `AEF_MIGRATION_CHECKLIST.md`) as
a human picking up the migration would, then chained `aef doctor` against
the result (per the checklist's own step 9).

`aef_adapter.py`, `aef.yaml`, and `AEF_MIGRATION_CHECKLIST.md` all checked
out — internally consistent, and `aef doctor` reported all three checks
`[OK]` against the generated `aef.yaml`/`CLAUDE.md`.

`CLAUDE.md`'s "Where to look in aef-core" section did not: it listed bare
paths — `aef/kernel/`, `aef/state/`, `docs/roadmap.md`, etc. — with no
indication these live in a *different* repository/package than the one
this file is dropped into, and `pyproject.toml` (`packages = ["aef"]`)
confirms `docs/` is never included in the pip-installed distribution.
Confirmed directly: `pip install aef-core` (or any non-source-checkout
install) leaves the adopting repo with a `CLAUDE.md` telling a future,
context-free Claude Code session to read `docs/roadmap.md` — a file that,
for that install method, does not exist anywhere on disk.

## Decision
Reworded the section to state explicitly that these paths belong to the
`aef-core` package/repo, not the repo the file was generated into; added
the `python -c "import aef; print(aef.__path__[0])"` one-liner for locating
an installed copy; and marked the `docs/roadmap.md` line "(source checkout
only)" so a pip-only adopter isn't sent looking for a file their install
method never provided.

## Consequences
- A future context-free Claude Code session reading the generated
  `CLAUDE.md` in a pip-installed adoption target now gets an accurate
  instruction instead of a dead file reference.
- No test coupled to the old wording (grepped `tests/` for both the
  section header and `roadmap.md` — zero matches), so no test changes were
  needed; full suite (263/263), mypy --strict, and ruff all stay clean.
- Verified by regenerating `CLAUDE.md` in a second fresh throwaway repo and
  reading the rendered section directly, not just the template source.

## Alternatives Considered
- **Bundle `docs/` into the pip package** (add it to `packages`/package
  data in `pyproject.toml`). Rejected for this pass: a bigger packaging
  change than the bug warrants, and `docs/` includes files (this ADR
  index, research reports) with no reason to ship inside every installed
  agent's dependency tree.
- **Drop the `docs/roadmap.md` line entirely.** Rejected: source-checkout
  adopters (anyone developing against aef-core directly, which is the
  common case for an early-stage internal scaffold like this one) still
  benefit from the pointer — caveating it is more useful than deleting it.

## Confidence
High — reproduced by actually running `aef adopt` against a realistic
throwaway target repo and reading every generated file as an adopter
would (not just reading `adopt.py`'s source), confirmed the specific
`packages = ["aef"]` line that makes `docs/` unshipped, and reproduced the
fixed wording rendering correctly in a second fresh run.
