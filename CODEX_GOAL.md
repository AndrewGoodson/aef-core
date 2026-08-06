# Codex goal (paste this)

Read `CODEX_BUGHUNT_PROMPT.md` in the repo root and execute it in full. It is
your brief — the round structure, the method, the hard stops, and the
not-a-bug list are all there. Read it completely before you touch any code.

**Goal:** find and fix real defects in `aef-core` across 10 adversarial rounds.
Not features, not style, not coverage for its own sake. Things that are wrong.

**Branch, non-negotiable:**
```bash
git checkout -b codex/bughunt-10x
```
Never commit to `main`. Never push to `main`. No PR, no merge, no rebase onto
main, no force-push, no pushing to any other repo. Every commit lands on
`codex/bughunt-10x`. The owner reviews the diff afterward.

**Green bar, clean before and after every round:**
```bash
pytest -q ; mypy --strict aef ; ruff check . ; ruff format --check aef tests examples
cd mindgraph && python tools/verify && python tools/verify --self-test
```

**Method:** reproduce first. Construct the failing case and RUN it, watch it
fail, fix it, watch it pass. An argument is not a finding; a transcript is. An
exit code alone is not evidence — read the error text.

**Never weaken a control to make something pass.** If a gate or test is wrong,
propose replacing it and say why.

**A round that finds nothing is a valid result.** Record it as dry and change
lens. Do not manufacture findings to fill rounds — if you found three defects in
ten rounds, say three.

**Done:** 10 rounds recorded (including dry ones), green bar clean on both
suites, every fix carrying a test that fails without it, `CODEX_BUGHUNT_REPORT.md`
written, branch `codex/bughunt-10x` with a clean tree, nothing merged to main.
