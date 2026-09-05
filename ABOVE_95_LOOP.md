# Above-95 loop — close the reviewer's list, then pilot a cold-start repo

Input: `docs/research/upgrade-2026-09-04.md` (69/100, J0b) and the two blind
reviews' named gaps. Output: every gap closed on an artifact, a real repo
adopted, and **the number the rows sum to** — stated plainly whether or not
it reaches the target.

Every rule of `IMPROVE_LOOP.md` and the multi-agent protocol of
`ABOVE_90_LOOP.md` apply unchanged. HARD-STOP gates bind. Read `CLAUDE.md`
and `.claude/skills/reproduce-first/SKILL.md` first.

## The owner's answers, recorded

- **Live gating in `aef-core`: NO.** This repo's candidates are numeric-constant
  edits to Python graphs and replay from cassettes deterministically; live
  calls add no judgement, spend quota nightly, and widen the worker env on
  every gate run. `gates.live_model_calls` stays `false` here and goes `true`
  in the pilot repo, where candidates are prompt text that misses by
  construction. (Item 4 of the next-steps table, answered.)
- **Copilot (item 9) is DROPPED.** No CLI installed; this repo ships no guess.
- **The pilot repo is `peptideindex`** (item 3), and the owner authorised
  running it here rather than handing it back.
- **Target: above 95.** The measured ceiling is ~82 without a third party
  (report §4). Both statements go in the final report; **no increment
  manufactures a point to close the gap.** A dimension moves on an artifact
  or it does not move.

## What peptideindex is, measured before this file was written

`git -C /Users/raptor/peptideindex`: default branch **`master`**, HEAD
`5752fcf3e`, 2 untracked paths. **No `.claude/agents/`, no `CLAUDE.md`, no
`AGENTS.md`, no `.codex/`.** 2,482 `.ts`, 1,816 `.js`, 42 `.sql`, 21 `.py`,
**0 SDK call sites**. A `.claude/scheduled_tasks.lock` — Claude Code is used
there and no agent is committed.

**This is the COLD-START case and it is new.** Every repo tested on
2026-09-04 (marlin, keystone, datamining) already had prompt-file agents.
The question this pilot answers is what an adopter with *no agentic surface
at all* gets, on a repo whose default branch is not `main`.

## Safety, unchanged

`/Users/raptor/peptideindex` is a production repo (public site, pricing
data). All measurement runs on a CLONE in scratch. The real repo is touched
only by N7's final step: `aef adopt` on a **local branch**, committed,
**never pushed**, `master` untouched, one `git branch -D` to undo. Nothing
else under `/Users/raptor/` is written.

## Increments

| id | closes | claim | dim |
|---|---|---|---|
| N1 | next-steps #1 | a candidate proposed FROM harvested evidence — S7's unclaimed clause (b) | 7 |
| N2 | #2 | the four arms re-run on the one-model corpus (ADR 0184 withdrawn by 0191) | 2 |
| N3 | #6 | the adversarial rounds become a runnable suite, not a document | 4 |
| N4 | #7 | a halt channel: the digest may not print `Halt channel configured: NO` | 4 |
| N5 | #8 | `make measure` regenerates every committed table in CI | 5 |
| N6 | #10 | redaction covers this repo's own identifier shapes | 4 |
| N7 | #3 | **the cold-start pilot**: peptideindex, clone then a real local branch | 7 |
| N8 | J0b d6 | a stepping stone produces a better descendant, or it does not | 6 |
| N9 | J0b d1 | the nightly loop closes unattended — a real turn, in CI, from CI's own memory | 1 |
| N10 | J0b d8 | the Codex live path runs in CI, or the reason it cannot | 8 |

## Rules this loop adds

- **A cold-start repo has no personas.** N7 does not invent an agentic
  surface to make the tool look good: it reports what `adopt` gives a repo
  with none, and only then — as the owner's proxy, in writing — authors ONE
  persona for a job that repo actually has, and says so.
- **The pilot's real-repo step is a branch, never a push.**
- **Two measurement branches may not touch one corpus.** ADR 0191's lesson:
  check `git merge-base --is-ancestor` before trusting a row.
- Workers: own scratch subdir; `set -eo pipefail` and an explicit
  `rc=${pipestatus[N]}` check before any push; shasum-verified backups.

## Report

Append to `docs/research/upgrade-2026-09-04.md` as a second wave, and state
the final number beside the target with the ceiling argument intact.
