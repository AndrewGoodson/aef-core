# J0 — independent rubric score, aef-core

Scored blind: from the code, the tests, and commands I ran. I did not read
`IMPROVE_LOG.md`, `docs/adr/`, any `*_LOOP.md`, `docs/research/` beyond the
weights table and dimension definitions, `docs/model-checks/`, `docs/trust/`,
or git history. Baseline conditions I established myself:

- `pytest -q tests` → **1999 passed, 3 skipped** in 114s. The three skips are
  the live-CLI provider tests (`AEF_LIVE_HARNESS`), which I was told not to run.
- `aef loop score agents.summary.graph:build_graph --corpus corpus --splits train,validation --json`
  → real numbers (validation mean 0.9167, n=6, CI 0.8134..1.02, cost 457 tokens).
- The `@needs_container` containment tests **ran** on this box (not skipped):
  read-only rootfs, no network from inside the candidate, writable workspace control.

## Scores

| # | Dimension | Score / weight | Evidence (file, test) | What is missing for full marks |
|---|---|---|---|---|
| 1 | Closed measurement loop | **15 / 20** | `aef/harness/loop.py::run_loop` is autoresearch's shape — propose, gate, keep-or-revert, stop on turns/wall-clock — and `tests/harness/test_run_loop.py::test_improvements_stack_because_the_next_turn_proposes_from_kept` proves the metric-carrying branch advances while `main` never moves; the metric is one scalar (`aef/harness/evaluation.py::score_of`) over a real 32-scenario 3-way-split corpus I scored myself. | **Nothing runs it unattended.** `.github/workflows/loop-monitor.yml`'s daily `aef loop cycle` step passes no `--memory` and no `--entrypoint`, so by `aef/cli/loop.py::cmd_cycle` it takes the `memory=None` branch and prints "no memory store configured … no candidate", exit 0 — the repo's own scheduled loop is a no-op, and `render_loop_monitor_workflow` emits **no cycle step at all** to adopters. Also: one candidate per turn (nothing near autoresearch's ~100 runs/night), and the 2-scenario holdout is read by no automated comparison — only by `--i-am-spending-the-holdout` by hand. |
| 2 | What gets learned | **12 / 20** | Raw records → consolidated knowledge is real and measured against the level below on a pre-registered metric with pre-stated falsification conditions: `tests/services/knowledge/test_ab_coverage.py::test_unconsolidated_retrieval_degrades_as_experience_accumulates` builds its corpus from actual `GraphExecutor` runs and shows raw-only coverage falling 6→1 as recurrence rises while the wiki holds at 6. Code-level learning is real too (`aef/harness/proposer.py` + `transformations.py`, gated by G3). | **The experience→behaviour link is open.** `make_retrieve_node` writes lessons to `state.retrieved_context` and *nothing reads them*: `grep retrieved_context aef/ agents/` finds only writers, and `agents/summary/graph.py::draft_node` builds its prompt from `working_memory` alone. So the knowledge layer is measured on a retrieval-coverage **proxy** and never on a task score — ACE's actual claim (playbook in context lifts accuracy) is unproven here. The skill level is absent by design: `aef/harness/skills.py::propose_skills` writes drafts and refuses to write anywhere a harness loads them, so no test can show an installed skill changing anything. Two of three inter-level comparisons are unmeasured. |
| 3 | Reflection quality | **6 / 10** | `aef/reasoning/llm_reflection.py` is implemented, not a stub, and the bias controls are structural and tested: `tests/reasoning/test_llm_reflection.py::test_judge_presents_evidence_in_opposite_orders` / `::test_judge_averages_the_position_swapped_samples_and_reports_the_delta` (position swap, `position_delta` reported) and `::test_evidence_is_excerpted_so_bulk_cannot_read_as_quality` (verbosity clamp), plus anti-omission and rule-based fallback. The on-state is wired and tested (`::test_agent_services_wires_llm_reflection_when_asked`). | **The measurement against the rule-based baseline is a docstring.** `aef/reasoning/llm_reflection.py:20` states "the rule-based judge agreed with the owner's checks 3/18 and the LLM judge 9/18" and cites an ADR; `grep` finds no test, script or corpus run that reproduces it — the exact "asserted, not shown" case. No self-preference control at all. Every judge test uses a fake provider; no judge in this repo has ever been scored against a real model. |
| 4 | Safety, containment, governance | **14 / 15** | Deterministic replay that catches a lying node (`tests/kernel/test_replay.py::test_replay_catches_a_node_that_lies_about_being_deterministic`); deny-by-default with HITL at any positive risk (`tests/security/test_tool.py::test_default_hitl_threshold_is_zero_so_any_positive_risk_requires_approval`); six gates that always ESCALATE (`tests/harness/test_loop_driver.py::test_a_fully_passing_candidate_escalates_and_does_not_merge`); hash-chained ledger that refuses to append onto damage; kill switch checked before anything else; and containment **demonstrated, not claimed** — `tests/harness/test_container_sandbox.py::test_a_candidate_inside_the_container_cannot_reach_the_network` and `::test_the_root_filesystem_is_read_only` executed on this machine. Zone policy survives traversal, case, backslash and null-byte probes (`tests/harness/test_zones.py`). | The adversarial-round record is a **prose assertion about a document**: `tests/harness/test_trust_case.py::test_the_adversarial_section_reports_failures_not_only_successes` greps the trust case's text rather than re-running any adversarial candidate. `test_the_in_process_shadow_bypass_is_still_real_when_opted_into` concedes an uncontained path still exists when opted into. |
| 5 | Evidence and honesty | **8 / 10** | Negative results ship as executable tests, not prose: `tests/services/knowledge/test_ab_coverage.py::test_the_boost_buys_no_coverage_at_any_setting` and `::test_the_llm_summariser_costs_coverage_at_tight_budgets` (an owned loss), the half-life sweep in `tests/services/knowledge/test_ab_curation.py::test_the_half_life_sweep`, and `::test_the_shipped_default_is_the_measured_one` which pins a default so raising it forces a re-measurement. Limits are stated in the code that has them (`g3_improvement.py::_check_cost` says outright that cost is self-reported and the rule cannot bind against an agent that never reported). | Three shipped defaults — archive sampling off, `reflection.impl: llm` off, `proposer: llm` off — carry their justification only in ADRs, with no test or runnable script behind any of them (`grep` for a measurement of the archive or the proposer finds none). And nothing measures the loop's own end-to-end benefit, i.e. whether it beats an owner editing code, which is the claim the whole apparatus exists to support. |
| 6 | Open-endedness / archive | **5 / 10** | DGM's rule in miniature is present and its **on-state is tested**: `aef/harness/loop.py::_parent_weight` (sigmoid fitness ÷ 1+children) with `tests/harness/test_run_loop.py::test_sampling_records_lineage_and_points_kept_at_the_best_score` and `::test_sampling_can_revisit_an_earlier_parent`. A separate durable archive stores accepted content with digests and restores it without git (`aef/harness/archive.py`, `tests/harness/test_archive.py`). | The lineage archive is **in-memory inside one `run_loop` call**, has no CLI flag (`grep sample_parents aef/cli/` → nothing, so `aef loop run` cannot enable it), defaults off, and **only kept candidates enter it** — rejected candidates are dropped after one duplicate check, so the stepping stones DGM keeps do not survive at all. Nothing carries an archive between invocations. |
| 7 | Real-signal ingestion | **4 / 10** | The ingestion path is real and well-tested: `aef run --record-runs` writes `RecordedRun`s and `aef/harness/harvest.py` re-executes each before admitting it, promotes failures to `train` only with no flag to reach validation or holdout, redacts, and rate-limits by source — `tests/harness/test_harvest.py::test_a_run_that_does_not_reproduce_is_rejected` and `::test_a_model_calling_run_harvests_and_re_executes_from_its_cassette`. | **No live signal has ever entered it.** Nothing in the repo or in the emitted workflows writes runs or `observations.jsonl`: the cron passes `--runs ~/.aef-loop-state/runs` that no step populates, and `aef/cli/loop.py:987`'s help says the observations file is "the observations JSONL **your deployment** wrote". The entire corpus is self-generated from two in-repo demo agents through a cassette provider (`tests/harness/test_evidence_loop.py::test_the_seed_corpus_is_recorded_not_hand_authored`), so no live traffic and no real tenant has closed this loop. Telemetry (`aef/observability/`) feeds traces, not the metric. |
| 8 | Adoptability / harness-native | **4.5 / 5** | `aef/providers/harness_provider.py` makes the coding agent's own login the credential — one headless `claude -p` / `codex exec`, no key, argv pinned by `tests/providers/test_harness_provider.py::test_claude_argv_is_a_toolless_single_turn_under_the_session_login` and `::test_claude_argv_does_not_inherit_the_operators_session`. Adoption is verified against a generated repo rather than asserted: `tests/cli/test_pristine_adoption.py::test_every_emitted_aef_command_is_one_the_cli_accepts` and `::test_loop_doctor_reports_all_six_and_exits_nonzero`, with cross-tool entry files covered by `tests/cli/test_adopt.py::test_run_adopt_emits_native_entry_file_for_each_harness`. | The `codex` path is never exercised against the real CLI (its only live test is one of the three skips), and adoption still leaves six manual obligations before the loop can approve anything — the scaffold's own docs say each unmet one makes `aef loop cycle` exit 0 having done nothing. |

## Total

**68.5 / 100**

(15 + 12 + 6 + 14 + 8 + 5 + 4 + 4.5)

## The two hardest to score

**Dimension 2 (what gets learned)** was hardest, because the repo is honest and
well-instrumented about a link it has not actually closed, and the honesty is
easy to mistake for the closure. Every artifact points the right way — records
are written by a reflect node, consolidated into entries that require two
distinct runs, retrieved under a real token budget, tallied helpful/harmful by
what was in context — and the A/B is a genuinely good measurement: metric fixed
first, falsification conditions stated first, corpus built from real executor
runs, an R=1 control against a rigged rig, and a knob killed by its own sweep.
But the chain stops one node short of behaviour. `make_retrieve_node` puts
lessons on state and the only agent with a retrieve node ignores them when it
builds its prompt. So the measured quantity is how many distinct lessons fit in
a budget, which is a property of the retriever, not of the agent — and the
field reference (ACE) is specifically a *task-accuracy* claim. I could not
score the knowledge layer as changing behaviour when no test anywhere shows a
task score moving because a lesson was retrieved, and I could not score it low
either, because the layer is real, wired, and measured on the ruler it declared.

**Dimension 1 (closed measurement loop)** was hard for the opposite reason: the
machinery is close to complete and the operational wiring around it is not, and
the two are in different files. `run_loop` is the real thing — keep/revert,
wall-clock budget, lineage, refusal to move `main`, refusal to run while HEAD is
the branch it advances — and `aef loop score` produced honest numbers on a real
corpus in seconds. Judged on the code alone this is close to full marks.
Judged on what actually executes without a person typing the command, it is a
scheduled job that reaches `cmd_cycle` with `args.memory` unset and returns
"nothing to learn from" every night, and an adopter workflow with no cycle step
at all. I weighted the second, because the rubric's word is "automatically" and
because a loop that exits 0 having done nothing is the specific failure this
repo elsewhere reproduces and documents at length — it just still has one.

## Files read

Code and config:
- `aef/harness/loop.py`, `corpus.py`, `evaluation.py`, `archive.py`, `harvest.py`,
  `monitoring.py`, `proposer.py`, `transformations.py`, `llm_proposer.py`,
  `skills.py`, `bootstrap.py`, `ledger.py` (EventKind only), `gates/g3_improvement.py`
- `aef/cli/loop.py`, `aef/cli/adopt_loop.py` (workflow renderers + kit prose)
- `aef/reasoning/llm_reflection.py`, `aef/reasoning/nodes.py`
- `aef/providers/harness_provider.py`
- `agents/summary/graph.py`, `agents/demo/graph.py`
- `corpus/README.md`, `corpus/manifest.json`, split directory listings
- `.github/workflows/ci.yml`, `loop-gate.yml`, `loop-monitor.yml`
- `CLAUDE.md` (project instructions, supplied in context)

Tests (read in full or by test-name listing + selected bodies):
- `tests/harness/test_run_loop.py`, `test_evidence_loop.py`, `test_harvest.py`,
  `test_loop_driver.py`, `test_cycle_and_halt.py`, `test_llm_proposer.py`,
  `test_promotion_safety.py`, `test_trust_case.py`, `test_container_sandbox.py`,
  `test_zones.py`, `test_archive.py` (listing only)
- `tests/services/knowledge/test_ab_coverage.py`, `test_ab_curation.py` (listing)
- `tests/reasoning/test_llm_reflection.py`, `test_retrieve_node.py`
- `tests/security/test_tool.py`, `tests/kernel/test_replay.py`,
  `tests/test_phase2_5_stubs.py`, `tests/providers/test_harness_provider.py`
- `tests/cli/test_adopt.py`, `test_pristine_adoption.py`, `test_adoption_sequence.py` (listings)

Rubric: `docs/research/self-learning-rubric.md` — **only** the header paragraph
and the weights/definitions table, extracted with the prescribed `sed` command.
I stopped there and did not open the Current or Baseline score tables.

Deliberately not read, to avoid contaminating the score:
`tests/test_rubric_arithmetic.py` (would likely restate the current score table),
plus everything on the exclusion list. I opened no excluded file by accident.
