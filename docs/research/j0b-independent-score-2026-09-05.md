# Independent rubric score — aef-core @ main, 2026-09-05

Scored blind from code, tests, corpus data and commands I ran. I did not read
`IMPROVE_LOG.md`, any `*_LOOP.md`, `docs/adr/**`, `docs/trust/**`,
`docs/model-checks/**`, git history, or any `docs/research/**` file except the
rubric's weights table (`sed`-clipped before the first score table). I listed
`docs/research/**` filenames only.

Full suite as run by me: **2720 passed, 7 skipped, 1 xfailed** (151s). All 7
skips are live-model tests correctly gated behind `AEF_LIVE_HARNESS`. Docker was
available, so the container-containment tests actually executed (64 passed), they
did not skip.

## Scores

| # | Dim | Score/Weight | Evidence (file : test / command I ran) | Missing for full marks |
|---|---|---|---|---|
| 1 | Closed measurement loop | **13**/20 | I ran `aef loop run --turns 3 --budget-minutes 8` in a scratch clone: it proposed on a local branch, built a random control cohort, printed `G3 rejected it: candidate does not beat the p95 of the random control cohort`, reverted, and archived the stepping stone with score 0.3846 — `aef/harness/loop.py` + `tests/harness/test_run_loop.py::test_keep_advances_the_kept_branch_and_never_main`. Metric read directly: `aef loop score agents.summary.graph` → train mean 0.9675 (n=20), validation 0.9529 (n=17), `repeat_spread` reported as the noise floor; holdout refused without `--i-am-spending-the-holdout`. | It has never closed unattended. **I reproduced a live defect**: the shipped nightly command in `.github/workflows/loop-monitor.yml` omits `--graph-id`, and against this repo's own two-graph corpus it exits **1** — which that workflow's own `case` statement calls "REJECTED by a gate — the system working, not a broken job" and keeps green. `cycles.jsonl` records `error (GraphIdError)`. Even fixed, `--memory` is empty: nothing in either workflow writes runs. `aef loop digest` (I ran it) says `Production runs recorded: 0`. |
| 2 | What gets learned | **12**/20 | Three levels are real and wired: records (`aef/harness/memory_store.py`), consolidated entries with ACE-style helpful/harmful provenance tallies (`aef/services/knowledge/consolidate.py::_tally`, `tests/services/knowledge/test_consolidate.py`), and persona bullets with a matched-length placebo null (`aef/harness/prose_cohort.py`, `tests/harness/test_prose_gate_path.py::test_a_prompt_candidate_reaches_an_accept_verdict`). Retrieval reaches the prompt on the adopter path, not just a fixture: `tests/reasoning/test_prompt_agent.py::test_retrieved_lessons_go_in_the_user_turn_after_the_objective`. | **No level has been shown to beat the one below on the task metric.** `tests/services/knowledge/test_ab_coverage.py` (l.43) records arm (c) 0.9059 against arm (b) 0.9176 — consolidation *lost* to raw records on the task; the coverage A/Bs measure a proxy that is explicitly stated not to predict task outcome. The one lesson that ever moved a scenario carried the literal check string (`prose_cohort.py` design-3 rationale) — teaching to the test, now designed out. Skills are proposal-only (`aef loop skills --out <proposals dir>`, never installed) = absent at that level; harness code is Zone B and unreachable by design. |
| 3 | Reflection quality | **8**/10 | `aef/reasoning/llm_reflection.py`: LLM critic+judge over recorded signals, position-swap averaged with `position_delta` reported, per-item excerpt caps as a verbosity control, and a deny-by-default self-preference guard measured across three judge models / 66 committed position-swapped judgments (`docs/research/j4/rankings.jsonl`, listed not read). Pinned by `tests/reasoning/test_pairwise_ranker.py::test_the_system_prompt_is_byte_identical_to_the_one_adr_0162_measured` and `::test_neither_the_label_nor_the_writer_model_reaches_the_prompt`. On-state works: `tests/reasoning/test_llm_reflection.py` l.250 exercises `agent_services(reflection="llm")`. | Default is `rule_based` (`aef/config/schema.py::ReflectionConfig`). The comparison against the rule-based baseline is agreement-with-owner-checks over 3–5 discriminating items — n far too small. The corpus's seven real negatives are *all word-cap overruns* (corpus/README.md), one failure mode, so no judge here has been discriminated on diverse negatives. |
| 4 | Safety, containment, governance | **13**/15 | Containment is per-run evidence, not a docstring: I ran `tests/harness/test_container_sandbox.py` + `test_contained_shadow.py` with a real Docker 29.4 daemon — 64 passed, including `test_a_candidate_inside_the_container_cannot_reach_the_network`, `test_the_root_filesystem_is_read_only`, `test_a_candidate_cannot_write_to_the_host_outside_the_workspace`, `test_a_timed_out_container_is_actually_dead`. Plus `aef/harness/zones.py` (Zone B non-configurable), `tests/harness/test_evidence_loop.py::test_a_reward_hack_is_rejected_by_the_tripwire` with its companion `::test_the_cheap_gates_still_wave_the_reward_hack_through`, `tests/harness/test_workflows.py` (no `pull_request_target`), `tests/harness/test_trust_case.py::test_a_fully_passing_candidate_still_escalates`, `tests/kernel/test_replay.py`, `aef/security/tool.py` REQUIRE_HITL. | No live traffic, no real tenants — the trust case's own stated gaps. Adversarial rounds exist as a document I was not allowed to read, not as an executable red-team suite. And a shipped hole the system admits itself: `aef loop digest` printed `Halt channel configured: NO` — if the loop halts, nothing pages anyone. |
| 5 | Evidence and honesty | **9**/10 | Defaults are pinned to measurements *by tests*, not prose: `tests/services/knowledge/test_ab_coverage.py::test_the_boost_buys_no_coverage_at_any_setting`, `::test_the_shipped_default_is_the_measured_one`, `::test_the_llm_summariser_costs_coverage_at_tight_budgets`. Negative results are first-class (corpus README documents that correcting three case-sensitivity defects left the corpus with *zero* negatives, and `tests/harness/test_corpus_negatives.py` refuses a silent return to zero). Measurement scripts + raw judgments are committed (`docs/research/i12, i12b, i13, i14, j2, j4` — I enumerated the filenames). The digest reports its own emptiness. | I could not verify the committed artifacts against the claims (out of read scope), so several headline numbers reach a reader as docstring prose with the data one directory away and no re-runner (`make measure`) that regenerates the tables in CI. |
| 6 | Open-endedness / archive | **7**/10 | Two stores, deliberately separate (`aef/harness/archive.py`): a content-addressed, append-only, digest-verified version archive (`tests/harness/test_archive.py::test_the_archive_stores_content_not_a_reference`, `::test_a_tampered_archive_file_is_detected`) and a hash-chained per-graph lineage store keeping kept **and** rejected members with DGM's `sigmoid(score)/(1+children)` weight (`::test_parent_weight_prefers_score_and_penalises_children`, `::test_the_lineage_persists_and_a_second_run_samples_a_parent_the_first_kept`). Reachable and persistent from the CLI — my `aef loop run` printed `lineage: resumed 0 member(s) from …/lineage/demo_agent.jsonl` and `archive: 3 member(s) … 1 distinct gated tree(s); sampling off`. | `--sample-parents` is **off by default** and the repo's own position is that the archive buys nothing on this proposer; the on-state exists only under fake proposers in `tests/harness/test_run_loop.py`, never in a measured run. No owner-facing `aef loop lineage list` — only a counts line. No evidence any stepping stone ever produced a better descendant. |
| 7 | Real-signal ingestion | **3**/10 | The mechanism is real and careful: `aef run --record-runs` → `aef/harness/harvest.py` (redacts, re-executes to prove reproduction, rate-limits per day, writes `train` only, never labels `expected`), `tests/harness/test_harvest.py::test_a_run_that_does_not_reproduce_is_rejected`, `::test_harvest_offers_no_way_to_choose_a_split`. | **No live signal has entered the corpus.** I counted every scenario's provenance: `source` = 11 `record`, 8 `bootstrap`, 31 unspecified, **0 `harvest`**; every summary scenario's note reads "synthetic passage; recorded live via claude_code". Live *model calls* on author-written inputs is not live traffic and is not a real tenant. Neither shipped workflow writes runs, and the emitted adoptee `loop-monitor.yml` passes no `--runs` at all, so harvest never fires there either. `aef loop digest`: `Production runs recorded: 0 … the corpus cannot grow and the gates keep measuring what the agent used to do.` |
| 8 | Adoptability / harness-native | **4**/5 | I ran it: `aef adopt --dir .` then `aef migrate --dir .` in a fresh git repo containing one `.claude/agents/helper.md`, and `agents/migrated/helper/graph.py` imports and builds `['consolidate','prompt_agent','reflect','retrieve']`. Cross-tool entries emitted (`AGENTS.md`, `.cursor/rules/aef.mdc`, `.github/copilot-instructions.md`); no API key (`model_provider.impl: claude_code`); emitted commands are asserted parseable against the real parser in `tests/harness/test_adopter_runtime.py::test_every_emitted_command_parses`; migrate prints an explicit blast-radius report and refuses to migrate skills. | The persona `.md` is Zone C by default, so the loop may rewrite the generated graph but not the prompt without an opt-in `--agent-root` widen. The adopter must record their own corpus (bootstrap needs live calls) before any gate means anything. And the emitted nightly workflow carries the same `--graph-id`-omission class I reproduced upstream, plus no `--runs`. |

**Total: 69 / 100.**

## The two hardest dimensions

**Dimension 1** was hard because the machinery and the operation of the
machinery point in opposite directions, and only running it separates them. The
parts a rubric asks for are all present and I verified each one by hand: a fixed
corpus with three splits enforced at load time, one scalar per split with a
confidence interval and a repeat-spread noise floor, a wall-clock budget, and a
keep-or-revert decision taken against a *random control cohort* rather than
against the incumbent — which is a stricter null than autoresearch itself uses.
G3 refusing to answer at all without a cohort is better engineering than most
published loops. But the rubric's word is "automatically", and the automatic path
is broken today: the nightly `aef loop cycle` in the repo's own workflow exits 1
on the repo's own corpus for want of a `--graph-id`, and that workflow classifies
exit 1 as healthy. The system has an unusually good defence against exactly this
— `cycles.jsonl` journals the error verdict and `aef loop monitor` printed
`WARNING: SCHEDULED CYCLE PRODUCING NOTHING` when I ran it after three empty
turns — so it would be *caught*, eventually, by a human reading a monitor line.
That is a loop with an excellent alarm on a wire that is not connected. I scored
the wire, not the alarm; the alarm is why it is 13 and not 9.

**Dimension 2** was hard because the honest thing and the high-scoring thing
diverge here, and the repo consistently chooses the honest one. The levels are
built — records, consolidated entries with real ACE-style helpful/harmful
provenance derived from `retrieved_signatures`, persona bullets gated against a
token-matched placebo — and, unusually, the retrieval genuinely reaches a model
prompt on the *adopter* path, which I confirmed by generating a repo and
importing its graph rather than by reading a claim. What is absent is the payoff.
The one A/B that measured the task metric rather than a proxy found consolidation
*losing* (0.9059 vs 0.9176), a second measurement found a lesson making two
at-cap runs longer and breaking the very check it described, and the single
historical case of a lesson moving a score turned out to be the lesson carrying
the answer string. All three are recorded in test docstrings and asserted, not
buried — which is why dimension 5 scores 9. But a rubric that pays for "each
level measured against the one below" cannot pay for measurements that came back
negative, however well recorded. Twelve is what a fully-built, fully-wired,
un-validated learning stack is worth.

## Files read

Rubric (header only): `docs/research/self-learning-rubric.md` (via `sed`, stopped
before the first score table).

Repo docs: `CLAUDE.md`, `corpus/README.md`, `corpus/manifest.json`,
`.github/workflows/ci.yml`, `.github/workflows/loop-gate.yml`,
`.github/workflows/loop-monitor.yml`.

Code: `aef/cli/loop.py` (partial: header, `cmd_score`, `cmd_cycle`, `cmd_run`
parser, archive/graph-id sections), `aef/cli/migrate.py` (generated-graph
template region), `aef/cli/run.py` (grep), `aef/config/schema.py` (reflection /
evolution config), `aef/services/runtime.py` (grep), `aef/harness/archive.py`
(header + lineage), `aef/harness/check_memory.py` (header),
`aef/harness/harvest.py` (grep), `aef/harness/loop.py` (exit codes, proposer
registry, harvest wiring), `aef/harness/memory_store.py`,
`aef/harness/proposer.py` (header + `MemoryEvidence`),
`aef/harness/prose_cohort.py` (header), `aef/harness/zones.py` (header),
`aef/harness/gates/g3_improvement.py` (header), `aef/reasoning/llm_reflection.py`
(header + `PairwiseRanker`), `aef/providers/*.py` (grep for `isolation`),
`agents/demo/graph.py`, `agents/summary/graph.py`, `corpus/train/sum-21-ardvey-ferry.json`.

Tests: `tests/harness/test_adopter_runtime.py` (header + names),
`tests/harness/test_archive.py` (names), `tests/harness/test_container_sandbox.py`
(header + names), `tests/harness/test_contained_shadow.py` (names),
`tests/harness/test_evidence_loop.py` (names), `tests/harness/test_harvest.py`
(names), `tests/harness/test_promotion_safety.py` (names),
`tests/harness/test_prose_gate_path.py` (names), `tests/harness/test_run_loop.py`
(names), `tests/harness/test_trust_case.py` (names),
`tests/reasoning/test_pairwise_ranker.py`, `tests/reasoning/test_prompt_agent.py`
(names + three bodies), `tests/services/knowledge/test_ab_coverage.py` (header +
names), `tests/services/knowledge/test_ab_curation.py` (header + names).

Directory listings only (not read): `docs/research/{i12,i12b,i13,i14,j2,j4}/`,
`docs/`, `aef/harness/`, `aef/cli/`, `tests/`, `tests/harness/`, `agents/`,
`examples/`, `corpus/{train,validation,holdout}/`.

Generated by me under the scratchpad and read there: the `aef adopt` /
`aef migrate` output in `w/s0b/adoptee/` (including its emitted
`.github/workflows/loop-monitor.yml`).

## Commands I ran

- `pytest -q` (full suite, and `-rs` on the live-gated subset)
- `pytest tests/harness/test_container_sandbox.py tests/harness/test_contained_shadow.py`
- `aef loop score agents.demo.graph` and `aef loop score agents.summary.graph`
- `aef loop cycle` (with and without `--graph-id`; exit code captured)
- `aef loop bootstrap`, `aef loop bless`, `aef loop run` (2 and 3 turns), `aef loop monitor`, `aef loop digest`
- `aef adopt --dir .` and `aef migrate --dir .` in a fresh scratch repo, then imported the generated graph
- No live model calls. `AEF_LIVE_HARNESS` was never set; `claude`, `codex`, `grok` were never invoked.
