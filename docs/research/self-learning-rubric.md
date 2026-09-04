# Self-learning loop rubric — and the baseline score

A score is only honest if the scale is written down before the scoring and
each dimension moves only on evidence. This is that scale. `RESEARCH_LOOP.md`
re-scores it against the external field; `IMPROVE_LOOP.md` works the gaps.

**A dimension's score changes only with a cited artifact** — a test, a
measured A/B, an ADR, a file — never with a sentence saying it improved.
A self-graded number is exactly the failure the trust case warns about.

| # | Dimension | Weight | What full marks means | Field reference |
|---|---|---|---|---|
| 1 | Closed measurement loop | 20 | A fixed task benchmark, one scalar metric, a time budget; every change is kept or reverted on the metric, automatically, with holdout separation | autoresearch (keep/revert on one metric, ~100 runs/night); DGM (SWE-bench 20→50%); SICA |
| 2 | What gets learned | 20 | Experience changes behaviour at the strongest safe level: raw records → consolidated knowledge/playbook → skills/tools → harness code. Each level measured against the one below | ACE (+10.6% agents, playbook not summary); WikiSkill (wiki ablation load-bearing); Voyager/AgentFactory (skill library); DGM/MOSS (code) |
| 3 | Reflection quality | 10 | LLM critic + judge over recorded signals with position/verbosity/self-preference bias controls, measured against the rule-based baseline | Reflexion; ExpeL; ACE reflector/curator |
| 4 | Safety, containment, governance | 15 | Deterministic replay, deny-by-default policy, HITL, gated promotion, containment, adversarial rounds, an owner-readable trust case | Almost no research loop has any of this |
| 5 | Evidence and honesty | 10 | Every claim of improvement has a measurement; every knob's default has a reason; negative results recorded | Statistical limits of self-improvement (2510.04399) |
| 6 | Open-endedness / archive | 10 | Candidate lineage kept; parents sampled for diversity, not just the current best; stepping stones survive | DGM archive; SWE-Exp |
| 7 | Real-signal ingestion | 10 | Learns from live runs and real tenants, not a synthetic corpus; telemetry closes the loop | Arize "closing the loop"; Live-SWE-agent (on-the-fly) |
| 8 | Adoptability / harness-native | 5 | Drops into a repo whose agents are coding-agent sessions; no key; cross-tool | — |

## Current — 2026-09-03 after I7 — **70 / 100**

| # | Score | What moved and the artifact |
|---|---|---|
| 2 | 15/20 | I7 (ADR 0117): `aef loop skills` drafts one SKILL.md per well-evidenced entry under a proposals dir; refuses harness dirs, never overwrites, every field computed; 11 tests, 3 mutations detected. Remaining: no measurement that an adopted skill helps; no retrieved→outcome signal |
| 2 (I4) | 12/20 | I4 (ADR 0116): `runs_since_last_seen` recomputed per consolidation; retriever demotes stale entries by half-life, deletes nothing; live-lesson coverage 2→3 of 3 at budget 400, 6/6 at 2000; default 5 by sweep. Remaining: no retrieved→outcome signal (no retrieval node), no curation of lesson text, no skill layer |
| 3 | 7/10 | I3 (ADR 0115): `LLMCritic`/`LLMJudge` on `impl: claude_code`; citations, arithmetic, omission=0, clamping and the position-swap control all in code; live A/B 11/11 agreement, delta 0.0, ~10 s/judgment; off by default (parity on this corpus). Remaining: no corpus where the judges disagree; no self-preference control (nothing compares model outputs yet) |
| 1 | 17/20 | I2 (ADR 0114): `run_loop` keeps on a local branch, never main; proposes from the kept state so improvements stack; bounded by turns, budget, halt, no-candidate, repeated-rejected-tree. Real cycle: kept 1, reverted 1, stopped on its own evidence. Remaining: corpus is 11 demo scenarios; proposer knows numeric constants + one structural transform |
| 1 (I1) | 13/20 | I1 (ADR 0113): owner-declared `checks` + `budget_ms` on scenarios, one `score_scenario()` in both scoring paths, `aef loop score` with CI and repeat-spread. Planted clean-run-wrong-content fault moved train 0.5000→0.1667. Still missing: keep/revert on the metric (I2); corpus is 11 demo scenarios, 5 checked |

Other dimensions unchanged from baseline.

## Baseline — 2026-09-03 — **50 / 100**

| # | Score | Evidence for the number |
|---|---|---|
| 1 | 8/20 | G3 improvement gate vs a null cohort exists (`aef/harness/gates/g3_improvement.py`, ADR 0051) and train/val/holdout separation is enforced in `proposer.py`. But the corpus is synthetic scenarios, there is no task benchmark an agent is scored on, and nothing is kept automatically — Tier-1 auto-merge is off on the trust case's recommendation |
| 2 | 8/20 | Consolidated knowledge exists and is measured (ADR 0110, I4 A/B: coverage 6 vs 1 under budget). Retrieval is lexical overlap. No playbook curation, no skill layer (`aef/evolution/` hard-disabled, constraint #7), no harness self-modification by design |
| 3 | 3/10 | `RuleBasedCritic`/`RuleBasedJudge` only (ADR 0046). `Critic`/`Judge` LLM interfaces raise `NotImplementedError`. Runnable now via `impl: claude_code` (ADR 0112) but not implemented |
| 4 | 14/15 | Checkpoint/replay (ADR 0023/0031), deny-by-default `PolicyEngine`, HITL (ADR 0032), G0–G5, container (ADR 0105), canary with keyed tenant hash (ADR 0106), six adversarial rounds, `docs/trust/promotion-trust-case.md`. One point off: shadow containment is opt-in |
| 5 | 9/10 | I4 A/B, `knowledge_boost=0.0` swept and left off, LLM summariser measured and left off, ADR per decision, planted-fault detector checks. One off: no prompt eval exists, so prompt changes are unmeasured |
| 6 | 3/10 | `ledger.py` records candidates; lineage is linear; no archive sampling, no diversity pressure |
| 7 | 2/10 | Trust case §: criteria 1 and 6 "have never run against the live traffic and real tenants their text names". Corpus built from `GraphExecutor` runs of shipped examples |
| 8 | 4/5 | `aef adopt` scaffold, cross-tool entry files (ADR 0040), harness provider with no key (ADR 0112). One off: Codex path unconfirmed |

**Reading the number.** As a governed harness this is ~90. As a *learner* it is
~35: the machinery to judge a change is stronger than the machinery to
produce one, and nothing it learns yet moves a task metric. The field's
strongest loops (DGM, autoresearch) are the mirror image — strong learning,
no governance. The gap to 90 is dimensions 1, 2, 3, 6, 7, and every one of
them needs a task metric first, because without one the rest cannot be
measured and would be scored on vibes.
