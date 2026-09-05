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

## Current — 2026-09-04, J0's base (ADR 0151) plus increments measured since — **70 / 100**

*The base is J0's independent score (68, ADR 0151). Every row above J0's is a
self-graded increment measured after it — each names its ADR and the artifact,
and each is exactly the kind of row a future J0 should re-check. A heading that
said "after J0" over a table containing such rows was mislabelled (second seam
hunt, S2).*

*Corrected 2026-09-04 (ADR 0127): every total in this file up to and
including this one was carried forward by hand as `previous + delta` and
was one point low, because the baseline's own rows summed to 51 against a
stated 50. **No dimension's score or evidence changes** — only the
addition. `tests/test_rubric_arithmetic.py` now recomputes the heading
from the rows, so a total nobody checked cannot recur.*

| # | Score | What moved and the artifact |
|---|---|---|
| 3 | 7/10 | S3b (ADR 0171): ADR 0159 could not grade a judge because the corpus had no true negatives — its only three were case-sensitive `contains` defects, and correcting them left it 20/20 pass, AUC 0.322. Corpus rebuilt: 3 case defects corrected, 57 more of the same shape found latent and corrected, 20 word caps moved to `max_words`+`min_words`, and 19 scenarios recorded live on `claude-opus-5[1m]` against inputs chosen to be handled badly (negation, superseded figure, similar names, dropped unit, conditionality, direction-of-change, caps 12–38). **7 fail an owner check, 4 of them in validation.** The A/B re-run on the enriched validation split, same script, same model, 34 calls: rule-based 4/17 (constant-fail), **LLM 16/17 against a 13/17 constant baseline, AUC 1.000** (every owner-fail state 0.275–0.635, every owner-pass state 0.850–0.910), position delta max 0.17. All three pre-registered conditions fired. Remaining: all 7 negatives are word-cap overruns, so AUC 1.000 is perfect separation of ONE failure family with n=4; no self-preference control (J0's third gap, still open) |
| 4 | 15/15 | S5 / J3 (ADR 0161): the 14 read "one point off: shadow containment is opt-in". Reproduced by running — on a box WITH docker and the worker image, `ShadowRunner(incumbent, candidate)` refused exactly as it does with neither, and the one-line way past it was `uncontained=True`; the escaping node's write landed on the host. `shadow_for` now resolves a runtime, verifies isolation both directions and returns a contained runner: same node, same box, no arguments, host marker **False**. `shadow.containment: auto` is the default and **refuses rather than falling back** (an automatic fallback would be weaker than ADR 0105's refusal); `fallback`/`off` are owner statements in `aef.yaml`, announced on stderr and written to the ledger as `EventKind.CONTAINMENT` with `security_event: True`, which `build_digest` counts. J0's deduction answered in both halves: the renamed `test_the_in_process_bypass_exists_only_when_an_owner_opts_out_and_is_logged` keeps proving the bypass real under opt-out and adds that the default cannot reach it, and the adversarial-round record's two BROKE-IT attacks are named at the tests that re-execute them. 5 mutations, 5 caught; +15 tests |
| 1 | 15/20 | J0 (ADR 0151): the repo's own scheduled `aef loop cycle` passes no `--memory` and exits 0 every night with `no memory store configured … no candidate`; the adopter's rendered workflow has no cycle step. Verified. "Automatically" is unmet |
| 2 | 12/20 | J0 (ADR 0151): `make_retrieve_node` writes `retrieved_context` and no prompt reads it — `draft_node` builds from `working_memory` alone; the knowledge A/B measures a retrieval-coverage proxy, never a task score. Verified. I12 as designed would have measured four identical arms |
| 3 | 6/10 | J0 (ADR 0151): the 3/18 vs 9/18 judge A/B exists as a docstring citing an ADR — no test, script or committed data; no judge scored against a real model in-repo; no self-preference control. Verified |
| 5 | 8/10 | J0 (ADR 0151): archive sampling, `reflection.impl: llm` and `proposer: llm` are "off by measurement" with the measurement in prose only — no runnable script, no committed data; nothing measures end-to-end benefit. Verified |
| 6 | 5/10 | J0 (ADR 0151): lineage archive is in-memory per `run_loop` call, no CLI flag (`grep sample_parents aef/cli/` empty), only kept candidates enter it, nothing persists across invocations. Verified |
| 7 | 4/10 | J0 (ADR 0151): no live signal has ever entered harvest; the cron's `--runs` is populated by no step; corpus is self-generated. Verified — one point below our own row |
| 8 | 4/5 | J0 (ADR 0151): the Codex path's live test is a skip from code alone; six manual obligations remain. J0 scored 4.5; rows are integers; the lower integer |
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
