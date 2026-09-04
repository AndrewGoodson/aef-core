# Improve loop — work the research worklist until the rubric reads ≥ 90

Input: the "Current worklist" below, written by `RESEARCH_LOOP.md`. Output:
increments, each measured, each an ADR if it changes a contract. Re-score
after every increment. Stop at ≥ 90 on
`docs/research/self-learning-rubric.md`, or when the worklist is empty —
then run `RESEARCH_LOOP.md` again, not this file.

Read first: `CLAUDE.md`, `docs/autonomy/self-improving-loop.md` (§2 green
bar, §3 reproduce-first, §4 HARD-STOP gates, §9 unattended-run blocks),
`.claude/skills/reproduce-first/SKILL.md`, `docs/trust/promotion-trust-case.md`.

## Rules

- **A score moves only on an artifact.** Each increment names, before it
  starts, the measurement that will move a rubric dimension and by how
  much it may claim. If the measurement does not move, the score does not
  move, and that is recorded as a result (the I4 pattern: a knob swept and
  left off is a finding).
- **Metric before mechanism.** If dimension 1 is below 15, the only
  admissible increment is the task metric. Everything downstream is scored
  on it.
- **No green test without a mutation check.** Perturb the production value,
  see the test fail, revert.
- **Never weaken a control.** Never enable `aef/evolution/`, never loosen
  `PolicyEngine`, never remove a HITL gate, never turn on Tier-1 auto-merge.
  An increment that needs any of those stops and asks — HARD-STOP gate 2.
- **Every learned thing must be replayable.** Anything that writes to
  memory/knowledge writes at a node boundary through `Services`; a
  non-deterministic node is declared so. `ReplayEngine` tests must still pass.
- **One commit per increment**, green bar before each, `WIKISKILL_LOG.md`
  style entry in `IMPROVE_LOG.md`: what was planted, what was measured,
  what changed, the number.
- Bounded: the worklist below, nothing manufactured.

## Increment shape

```
### I<n> — <name> (rubric dim <k>, claims up to +<m>)
Reproduce: <the failing case or the measurement showing the gap, RUN>
Change: <files>
Measure: <command + the number, before and after>
Mutation: <what was perturbed, that the test failed>
ADR: <number or "none: no contract change">
Score: dim <k> <before> -> <after>, total <before> -> <after>
```

## Status after the 2026-09-03 run — 79 / 100

Done, each with an ADR and a measured entry in `IMPROVE_LOG.md`: I1 task
metric (0113), I2 keep/revert (0114), I3 LLM critic/judge (0115), I4
curation (0116), I5 redaction (0119), I6 archive (0121), I7 skill proposals
(0117), I8 prompt-surface test (0120), plus I9 retrieve node + A1 (0118),
added mid-run. Two knobs shipped off by measurement (LLM reflection,
archive sampling), one on (staleness half-life 5).

What separates 79 from 90, and none of it is code this loop can write:
dimension 7's last five points need a real tenant (owner decision, trust
case §4); dimension 1's last three need a corpus of real tasks the demo
graph cannot supply; dimension 6's last four need a proposer with a
repertoire; dimension 8's last point needs a Codex CLI that can parse its
server's catalog. The next `RESEARCH_LOOP.md` pass should re-score with
that in front of it rather than manufacture increments.

## Original worklist (seeded 2026-09-03 from the baseline; RESEARCH_LOOP.md replaces this)

1. **Task metric** (dim 1, up to +7). A fixed suite of graph tasks with a
   scalar score and a wall-clock budget, run by `aef eval`, holdout split
   never cited by a proposer (the rule `proposer.py` already enforces).
   Start from the eval harness in `aef/services/eval/` and the corpus in
   `aef/harness/corpus.py`; the tasks must be things the shipped graphs can
   actually fail at. Measure: the suite runs, scores are stable across
   three identical runs (variance stated), and a deliberately broken node
   moves the score.
2. **Keep/revert on the metric** (dim 1, up to +5). autoresearch's shape,
   inside the existing gates: a candidate is kept only if G3 beats the null
   cohort *and* the task metric does not regress on validation; kept means
   "promoted to the candidate ledger", never auto-merged (Tier-1 stays off).
   Measure: N proposals, the ledger keeps only the ones the metric supports.
3. **LLM critic and judge** (dim 3, up to +5). Implement `Critic`/`Judge`
   on `impl: claude_code` (ADR 0112) with position-swap and length controls;
   A/B against `RuleBasedCritic` on the task metric and on the I4 coverage
   harness. Off by default until the A/B says otherwise — same rule as the
   summariser.
4. **Playbook curation** (dim 2, up to +6). ACE's grow-and-refine over
   `KnowledgeEntry`: entries carry a helpful/harmful tally from the judge,
   retrieval ranks on it, stale entries are demoted not deleted. Measure on
   the I4 harness and the task metric; the ADR 0110 rule that the model
   never owns provenance holds.
5. **Real-signal ingestion** (dim 7, up to +5). Reflection reads real run
   provenance from adopted repos' `aef run` traces (the `dash/memory.py`
   accumulation already derives edges from `Provenance`); a corpus builder
   that turns real failed runs into scenarios with tenant tags redacted.
   Measure: corpus size from real runs > 0 and G3 runs on it.
6. **Archive sampling** (dim 6, up to +4). DGM's archive over the candidate
   ledger: parents sampled by score and novelty, lineage kept, stepping
   stones not pruned. Measure: diversity of kept candidates vs greedy.
7. **Skill proposals as reviewed PRs** (dim 2, up to +4). WikiSkill's third
   layer without self-modification: the consolidator emits a proposed skill
   file as a PR for a human, never applied at runtime. Constraint #7 untouched.
8. **Prompt eval** (dim 5, up to +1). A small eval so prompt-surface edits
   (`/new-model-check`) are measured, not asserted.

Expected if all land as claimed: 50 → 87. The last three points come from
dimension 7 running against a real tenant, which is an owner decision — say
so rather than inventing them.
