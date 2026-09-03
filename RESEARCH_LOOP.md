# Research loop — compare this loop with the field, produce the worklist

Bounded. One pass = one dated report. Run it, read the report, then run
`IMPROVE_LOOP.md` on the worklist it emits. Do not improve anything here.

Read first: `CLAUDE.md`, `docs/autonomy/self-improving-loop.md` (HARD-STOP
gates §4 apply), `docs/research/self-learning-rubric.md` (the scale),
`docs/trust/promotion-trust-case.md` (what "safe" already means here).

## Rules

- **Evidence per dimension, or no score change.** A rubric dimension moves
  only when you cite what the field does *with a number* and what this repo
  does *with a file path*. "They seem better" is not a finding.
- **Reproduced and suspected stay separate.** If you can run a comparison
  (e.g. the I4 harness against a technique), run it and say so. If you only
  read about it, say that.
- **Constraint #7 is not on the table.** `aef/evolution/` stays disabled.
  A technique that requires runtime self-modification is recorded as
  "requires an owner decision the trust case currently recommends against",
  not proposed as an increment.
- **Search, don't recall.** Every source is a URL fetched this run. The
  field moves monthly; last year's survey is a starting point, not a source.
- Bounded: 8 dimensions × at most 4 sources each. Stop when the table is
  full.

## Procedure

1. **Search** — for each rubric dimension, `WebSearch` at least two queries
   (one naming the technique family, one asking for 2026 results/benchmarks).
   Fetch the primary source for anything you cite. Seed list, already
   confirmed live on 2026-09-03: DGM (arXiv 2505.22954, ICLR 2026), Karpathy
   autoresearch (github.com/karpathy/autoresearch), ACE (arXiv 2510.04618,
   ICLR 2026), WikiSkill (arXiv 2608.27454), Self-Evolving Coding Agents
   survey (arXiv 2608.03392), Live-SWE-agent (2511.13646), SICA, MOSS
   (2605.22794), AgentFactory (2603.18000), statistical limits (2510.04399).
2. **Locate** — for each technique, the file(s) in this repo that do the
   nearest thing, or the ADR that decided not to. `grep`, then read.
3. **Compare** — one row per technique: what they do; their measured
   result; what this repo does; the gap in one sentence; whether closing it
   crosses a HARD-STOP gate or constraint #7.
4. **Re-score** — fill the rubric table with the new evidence. A dimension
   that did not change keeps its baseline number and the reason.
5. **Emit the worklist** — for each gap, an increment shaped like the ones
   `WIKISKILL_LOOP.md` used: reproduce-first check, the change, the
   measurement that proves it, the ADR it needs. Order by
   (weight × gap) / cost. The first item is always the task metric if
   dimension 1 is below 15 — nothing else can be measured without it.
6. **Write** `docs/research/loop-comparison-<YYYY-MM-DD>.md` with the
   comparison table, the re-scored rubric, the worklist, and a
   "Sources" list of every URL used. Copy the worklist into
   `IMPROVE_LOOP.md` under "Current worklist", replacing the previous one.
7. Commit (`docs(research): ...`), push `origin main`. Stop.

## Report template

```
# Loop comparison — <date>
Score: <n>/100 (baseline 50, previous <n>)
## Comparison
| Technique | Source | Their result | This repo | Gap | Gate? |
## Rubric
<the 8-row table with evidence>
## Worklist for IMPROVE_LOOP.md
1. ...
## Sources
```
