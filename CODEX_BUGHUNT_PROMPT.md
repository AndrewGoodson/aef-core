# Codex goal — 10-round adversarial bug hunt on aef-core

**Repo:** `/Users/raptor/aef-core` (Python 3.13, 107 modules under `aef/`, 79 test files, 109 ADRs)

## Your goal

Find and fix real defects in `aef-core` across **10 adversarial rounds**, working
entirely on a new branch. The owner will review your diff afterward. You are not
here to add features, tidy style, or raise coverage for its own sake — you are
here to find things that are **wrong**.

## Branch discipline — absolute

```bash
git checkout -b codex/bughunt-10x
```

**You must never commit to `main`, never push to `main`, and never force-push
anything.** Every commit goes on `codex/bughunt-10x`. Do not open a PR, do not
merge, do not rebase onto main. When you finish, leave the branch checked out
with a clean tree and a summary written to `CODEX_BUGHUNT_REPORT.md`.

Do not push to any repository other than this one.

## Setup

```bash
cd /Users/raptor/aef-core
python -m venv .venv && source .venv/bin/activate   # if .venv is absent
pip install -e ".[dev,anthropic,mem0]"
```

## The green bar — must be clean before AND after every round

```bash
pytest -q
mypy --strict aef
ruff check .
ruff format --check aef tests examples
```

`mypy --strict` must stay clean across the whole `aef/` package. If a round
leaves any of these red, that round is not finished.

There is also a second, independent suite for the dashboard sub-project:

```bash
cd mindgraph && python tools/verify && python tools/verify --self-test
```

Currently 287 checks and 29 self-test detections. Keep both green.

## Method — this is not optional

**Reproduce first.** For every candidate defect: construct the failing case and
**RUN it**. Watch it fail. Then fix it. Then watch it pass. An argument that
something is broken is not a finding; a transcript is. Assert that every patch
actually applied — do not trust that an edit landed.

**An exit code alone is not evidence.** Run probes visibly and read the error
text to confirm it names the thing you think it names. When planting a fault to
test a check, clear `__pycache__` first and use clean temp state — stale bytecode
has produced false greens in this repo before.

**Hunt the seams.** In this program's history, defects clustered in the *joins*
between components that were each individually correct and individually tested.
Prioritise: node→graph wiring, config→factory→services construction, adapter
boundaries, checkpoint/replay round-trips, CLI→library edges, and anywhere two
modules agree on a contract that neither one enforces.

**Never weaken a control to make something pass.** If a gate, zone rule, budget,
or test is wrong, propose *replacing* it and explain why — ADR 0093 is the
precedent for doing that properly. Deleting an assertion to get green is the one
failure mode that would make this whole exercise negative-value.

## Round structure — repeat 10 times

Each round is a complete cycle. Do not batch rounds.

1. **Pick a lens** — a different one each round. Suggested, in no fixed order:
   *(1)* replay determinism and checkpoint round-trips; *(2)* the security policy
   engine's deny-by-default behaviour and HITL routing; *(3)* provider fallback
   and error paths; *(4)* concurrency, ordering, and shared mutable state;
   *(5)* the seams listed above; *(6)* boundary values — empty, null, zero, one,
   huge, unicode, negative, NaN; *(7)* error handling and what gets swallowed;
   *(8)* the CLI (`aef adopt`, `aef doctor`) against hostile/odd repos;
   *(9)* resource lifecycle — files, handles, temp dirs, cleanup on failure;
   *(10)* the gap between what docstrings/ADRs promise and what the code does.
2. **Hunt.** Read code, form specific hypotheses, write failing cases.
3. **Verify each finding** by reproducing it. Discard anything you cannot
   reproduce — record it as "suspected, not reproduced" rather than fixing it.
4. **Fix** what you confirmed. Small, focused diffs. Write the test alongside the
   fix, not after, especially in `kernel/` and `state/` where replay determinism
   and checkpoint round-trips are the actual safety properties.
5. **Re-run the full green bar** plus the mindgraph verifier.
6. **Commit** with a conventional-commit message stating the defect, the
   reproduction, and the fix. One commit per defect where practical.
7. **Append to `CODEX_BUGHUNT_REPORT.md`**: round number, lens, what you looked
   at, what you found, what you fixed, what you ruled out, and anything
   suspicious you could not reproduce.

**A round that finds nothing is a valid result** — record it as dry and move to a
different lens. Do not manufacture a finding to fill a round. The honest signal
this exercise produces is *where* the defects are, and inflating the count
destroys it.

## Hard stops — do not do these under any circumstances

1. **Do not enable Tier-1 auto-merge.** Not on any evidence you generate.
   `docs/trust/promotion-trust-case.md` recommends against it; that is the
   owner's decision, not yours.
2. **Do not enable `aef/evolution/` or weaken either disablement layer.**
   `EvolutionConfig(enabled=True)` and `AgentConfig`'s `evolution.enabled: true`
   both raise, deliberately.
3. **Do not weaken a gate, zone rule, or budget to make something pass.**
4. **Do not add a secret or a write permission to any GitHub workflow.**
5. **Do not push to any repo other than this one, and never to `main`.**
6. **Do not change `RuleBasedEvaluator.task_completion` semantics** (ADR 0038).
7. **Do not alter routing into a HITL-gated edge.**

## Deliberate design — these are NOT bugs, do not "fix" them

- **`NotImplementedError` bodies** in `aef/reasoning/reflection.py`,
  `aef/services/optimizers/`, `aef/coordination/`, and parts of
  `aef/services/*/base.py`. These are Phase 3/5 typed interfaces, deferred on
  purpose. See `docs/roadmap.md`.
- **`aef/evolution/` being disabled.** Constraint #7.
- **The policy engine denying by default**, including a `Tool` with no declared
  scopes, and routing any positive-risk call to `REQUIRE_HITL`. Constraint #6.
- **Vendor SDK imports confined to `aef/providers/` and
  `aef/services/*/adapters/`.** Enforced by `tests/test_vendor_isolation.py`. If
  you need a vendor import elsewhere, you have the wrong design, not a lint
  problem.
- **The five-things rule:** only Knowledge, Policies, Tools, Objectives, and
  Evaluation Metrics may differ per agent. An agent-specific branch anywhere
  else is a design defect — flag it, do not accommodate it.
- **`mindgraph/` deliberately does not offer** control charts, state timelines,
  a loop-vs-human comparison, a difference map, or a scrubber. Each absence is
  argued in `mindgraph/DECISIONS.md` from the data. They are not missing
  features.

## Two known-stale items — confirm and fix, cheaply

Both were found but not fixed, so they are free wins and a calibration check:

1. `aef/config/schema.py:152` — the rejection message for
   `evolution.enabled=True` says *"none of the Phase 4 gate criteria are
   implemented yet"*. All seven are now implemented; what they lack is
   **evidence from live traffic**. The disablement is correct; the explanation
   misleads. Fix the wording, keep the behaviour.
2. `aef doctor` reports the generated `aef_adapter.py` as `[OK]` while its own
   text says *"still the generated stub, not wired yet"*. Green status on
   unwired code reads as done at a glance. Consider `[WARN]`.

If you disagree with either, say so with reasoning rather than complying.

## Context worth reading before round 1

- `CLAUDE.md` — the scaffold contract and the prime directive.
- `docs/roadmap.md` — the authoritative real-vs-stubbed answer.
- `docs/adr/README.md` — index of 109 decisions. Check here before assuming a
  design choice was arbitrary; it probably has a written rationale.
- `docs/trust/promotion-trust-case.md` — why the loop does not self-merge.
- `.claude/skills/reproduce-first/` — the verification method above, in full.
- `.claude/agents/seam-hunter.md` — the seam-hunting brief.

## What "done" looks like

- 10 rounds completed and recorded, including any dry ones.
- Green bar clean: `pytest -q`, `mypy --strict aef`, `ruff check .`,
  `ruff format --check aef tests examples`.
- `mindgraph/tools/verify` and `--self-test` still green.
- Every fix has a test that fails without it and passes with it.
- `CODEX_BUGHUNT_REPORT.md` written, with a final section listing: confirmed
  defects fixed, suspected-but-unreproduced, deliberate designs you probed and
  found sound, and anything you would recommend the owner change but did not
  touch because it needed a human decision.
- Branch `codex/bughunt-10x`, clean tree, **nothing merged to main**.

A short report of real findings beats a long one padded with style nits. If you
found three genuine defects in ten rounds, say three.
