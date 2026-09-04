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

## Current — 2026-09-04 after I15 — **86 / 100**

*Corrected 2026-09-04 (ADR 0127): every total in this file up to and
including this one was carried forward by hand as `previous + delta` and
was one point low, because the baseline's own rows summed to 51 against a
stated 50. **No dimension's score or evidence changes** — only the
addition. `tests/test_rubric_arithmetic.py` now recomputes the heading
from the rows, so a total nobody checked cannot recur.*

| # | Score | What moved and the artifact |
|---|---|---|
| 8 | 5/5 | I15 (ADR 0131): the Codex CLI was 18 versions behind and could not parse its own server's catalogue; upgraded, `CodexProvider` answered UNMODIFIED on the first live attempt (argv, `--output-last-message` reply, `turn.completed` usage in 19,975 / out 26). `tests/providers/test_codex_live.py` keeps it runnable, opt-in. Two backends measured, none assumed |
| 1 | 19/20 | I11 (ADR 0123): a content task a model can fail — `agents/summary`, 20 recorded scenarios with owner checks (12/6/2), `CassetteProvider` replays every pinned model call with no credential, miss FAILS by default; cassette score train 0.9792 / validation 0.9167, repeat spread 0; three real content failures (0.75); planted prompt regression → 0.0000 under the default with no live call. Remaining: the live noise floor did not get measured (three attempts past a ten-minute wall); no turn kept/reverted on this suite yet (I12) |
| 1 (I10) | 18/20 | I10 (ADR 0122): `run_loop` gave every turn one workdir and G1 refuses a non-empty one, so no real loop had ever gated a second candidate behaviourally — fixed per turn, asserted in the acceptance test (M48); on `agents/demo` the loop now keeps a coherent two-constant change the rule-based proposer could not make. Remaining: a corpus of real tasks (I11) |
| 3 | 8/10 | I11 (ADR 0123): I3's judge A/B re-run on the 18 summary states (36 calls): rule 3/18, LLM 9/18 agreement with the checks, disagree with each other on 10/18, position delta up to 0.2 — the corpus where the judges disagree now exists, and it shows neither judge's evidence contains the answer. Remaining: a judge that reads `working_memory`; self-preference control |
| 6 | 8/10 | I10 (ADR 0122): `LLMProposer` — model writes prose + whole file, code computes citations (train only, via `_check_citations`) and validates against G0's imported allowlist/line budget and G4's owner-only fields, falls back to rule-based with the reason; `LoopConfig.proposer`, `--proposer llm`. Live (26 calls): 4/4 distinct candidates per run, 16/16 validated, demo kept 1 vs 0, flaky 1 = 1; kept diversity still 1 everywhere; one G5 halt → off by default. Remaining: kept diversity > 1 needs an agent with more than one repairable failure |
| 6 | 6/10 | I6 (ADR 0121): G3 scores reach the driver; archive of kept members with lineage; `sample_parents` by sigmoid(score)/(1+children), seeded; kept branch = best member; duplicates skipped. Measured on the real cycle: zero diversity gain (deterministic proposer) → off by default. Remaining: a proposer with a repertoire |
| 5 | 10/10 | I8 (ADR 0120): `tests/test_prompt_surface.py` pins required blocks, forbidden text, kept verification lines; every detector proved against a planted fault; found a broken regex and a missing reproduce-first line in the shipped CLAUDE.md |
| 7 | 5/10 | I5 (ADR 0119): harvest redacts the input, re-executes, admits only if behaviour is unchanged, scans the output; on by default; 4 mutations detected. Remaining: has never run against a real tenant — owner decision |
| 2 | 17/20 | I9 (ADR 0118): `make_retrieve_node` — the retriever's first production caller, budget enforced in a real run; `retrieved_signatures` on reflection; helpful/harmful tallies per entry, agent-scoped, surfaced in metadata + drafts; A1 closed. Remaining: ranking on the tally (no rig where harmful ≠ live); text curation |
| 2 (I7) | 15/20 | I7 (ADR 0117): `aef loop skills` drafts one SKILL.md per well-evidenced entry under a proposals dir; refuses harness dirs, never overwrites, every field computed; 11 tests, 3 mutations detected. Remaining: no measurement that an adopted skill helps; no retrieved→outcome signal |
| 2 (I4) | 12/20 | I4 (ADR 0116): `runs_since_last_seen` recomputed per consolidation; retriever demotes stale entries by half-life, deletes nothing; live-lesson coverage 2→3 of 3 at budget 400, 6/6 at 2000; default 5 by sweep. Remaining: no retrieved→outcome signal (no retrieval node), no curation of lesson text, no skill layer |
| 3 | 7/10 | I3 (ADR 0115): `LLMCritic`/`LLMJudge` on `impl: claude_code`; citations, arithmetic, omission=0, clamping and the position-swap control all in code; live A/B 11/11 agreement, delta 0.0, ~10 s/judgment; off by default (parity on this corpus). Remaining: no corpus where the judges disagree; no self-preference control (nothing compares model outputs yet) |
| 1 | 17/20 | I2 (ADR 0114): `run_loop` keeps on a local branch, never main; proposes from the kept state so improvements stack; bounded by turns, budget, halt, no-candidate, repeated-rejected-tree. Real cycle: kept 1, reverted 1, stopped on its own evidence. Remaining: corpus is 11 demo scenarios; proposer knows numeric constants + one structural transform |
| 1 (I1) | 13/20 | I1 (ADR 0113): owner-declared `checks` + `budget_ms` on scenarios, one `score_scenario()` in both scoring paths, `aef loop score` with CI and repeat-spread. Planted clean-run-wrong-content fault moved train 0.5000→0.1667. Still missing: keep/revert on the metric (I2); corpus is 11 demo scenarios, 5 checked |

Other dimensions unchanged from baseline.

## Baseline — 2026-09-03 — **51 / 100**

*Corrected from 50 (ADR 0127): the rows below always summed to 51. Every
increment's delta was taken from the wrong base, which is how one point
travelled through nine increments in the document whose first rule is that
a self-graded number is the failure the trust case warns about.*

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

**Reading the number** (written at the baseline, when the corrected total
was 51). As a governed harness this is ~90. As a *learner* it is
~35: the machinery to judge a change is stronger than the machinery to
produce one, and nothing it learns yet moves a task metric. The field's
strongest loops (DGM, autoresearch) are the mirror image — strong learning,
no governance. The gap to 90 is dimensions 1, 2, 3, 6, 7, and every one of
them needs a task metric first, because without one the rest cannot be
measured and would be scored on vibes.
