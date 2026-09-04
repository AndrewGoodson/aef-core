# Above-90 loop — multi-agent, autonomous, pushes to main

**Run of 2026-09-04: 79 → 84. Report: `docs/research/above-90-2026-09-04.md`.**
I10 (ADR 0122) and I11 (0123) landed; two fix waves (0125, 0126) closed
thirteen reproduced seams, four of which invalidated evidence an earlier
ADR had already claimed. I12 did not start — it is ~42 live model calls
and the harness quota is exhausted; its runner is written and dry-run
verified at `scratchpad/i12_ace_arms.py`. Resume there when quota returns.

Input: the rubric at 79 (`docs/research/self-learning-rubric.md`) and the
status block in `IMPROVE_LOOP.md`. Output: the three increments below, each
measured, merged to `main` by the orchestrator, pushed. Stop at ≥ 90 or
when the list is exhausted; then report the owner actions that remain.

Every rule of `IMPROVE_LOOP.md` applies unchanged: a score moves only on an
artifact; no green test without a mutation check; never weaken a control;
never enable `aef/evolution/`, never Tier-1 auto-merge; HARD-STOP gates
(`docs/autonomy/self-improving-loop.md` §4). Read `CLAUDE.md` first.

## Protocol — one orchestrator, N workers

- **Orchestrator** (the session that read this file): owns `main`. Never
  edits code itself while workers run. Launches workers, merges their
  branches, runs the green bar on the merged tree, resolves the append-only
  files, pushes. Runs one adversarial pass (seam-hunter) after each merge
  wave and turns findings into fixes before the next wave.
- **Worker**: one increment, one git worktree, one branch
  `improve/i<n>-<slug>` off current `main`. Follows `IMPROVE_LOOP.md`'s
  increment shape end to end — reproduce, change, measure, mutation, ADR,
  log entry — and **commits on its branch only. Never merges, never
  pushes, never touches `main`.** Returns: branch name, the measured
  numbers, the rubric claim, and anything it left undone.
- **Parallelism**: I10 and I11 are independent — run them together. I12
  depends on I11's suite — run it after I11 merges. Never two workers on the
  same increment.
- **Append-only files** (`IMPROVE_LOG.md`, `docs/adr/README.md`, the
  rubric's current table): workers append; the orchestrator resolves
  conflicts by keeping both entries in ADR-number order. ADR numbers:
  I10 → 0122, I11 → 0123, I12 → 0124. Do not renumber.
- **Green bar on the merged tree before every push**: `pytest -q`, `mypy
  aef examples`, `ruff check .`, `ruff format --check aef tests examples`.
  Test count grows or holds.
- **Live model calls** go through `impl: claude_code` (ADR 0112). They cost
  the session login's quota and ~10 s each. Budget them: a measurement is
  a few dozen calls, not a few thousand. Say how many were made.

## I10 — LLM proposer (rubric dim 6 → up to 9; dim 1 → up to 18; ADR 0122)

**Reproduce.** `RuleBasedProposer` emits numeric-constant steps and one
structural transformation. `run_loop(sample_parents=True)` on the flaky
fixture keeps one candidate and then duplicates (ADR 0121's measurement):
the archive has nothing to sample because the proposer has one idea.

**Change.** `aef/harness/llm_proposer.py`: `LLMProposer(provider, model)`
producing the same `Proposal` the rule-based one does. Input: the Zone A
source, `MemoryEvidence` (citations from **train only** — reuse
`_check_citations`; a proposal citing validation or holdout is refused, not
emitted), the failing nodes. The model returns the whole modified file in
one fenced block; code validates: parses (`ast`), same path, within G0's
line budget, no new imports outside the allowlist G0 enforces (reuse it —
do not write a second list), diff non-empty. Rationale = model prose +
computed citation list. Any failure → fall back to `RuleBasedProposer` and
say so in the rationale. Wire: `LoopConfig.proposer: "rule_based" | "llm"`
and `aef loop run --proposer llm`. **Off by default.** No gate changes.

**Measure** (live, claude_code): `run_loop` 4 turns on the flaky fixture
and on `agents/demo`, rule-based vs LLM: kept count, distinct kept trees,
gate pass rate, calls made. Falsification: LLM keeps ≤ rule-based → stays
off, and that is the result. Mutations: refuse validation citations;
refuse a file that does not parse; refuse a path outside Zone A; fallback
on provider error.

## I11 — A task suite a model can fail, gate-able (dim 1 → 20; dim 3 → 9; ADR 0123)

**Reproduce.** `aef loop score` on `corpus/`: every scenario fails only by
raising. `test_without_checks_a_clean_wrong_answer_scores_full_marks` is the
shape; the corpus has no content task.

**Change.**
1. `aef/providers/cassette_provider.py`: `CassetteProvider(inner, cassette,
   on_miss="fail"|"live")`. Key = stable hash of `CompletionRequest`
   (messages, model, max_tokens). Hit → recorded `CompletionResult`. Miss →
   `on_miss="live"` calls `inner` and records; `"fail"` raises
   `ModelProviderError` naming the miss. `Scenario` gains
   `model_calls: tuple[RecordedCall, ...]` (payload round-trip, legacy
   scenarios load with none). `record_run`/`aef loop record` capture calls;
   `scenario_runner` and `isolated_suite` build a cassette from the
   scenario and use `on_miss="fail"` by default — the gates stay
   deterministic — with `LoopConfig.cassette_miss="live"` as the opt-in
   that lets a prompt change be scored live (and reported as such).
2. `agents/summary/graph.py`: retrieve → draft (calls
   `services.require_model_provider()`) → reflect → consolidate. Task:
   summarise `working_memory["text"]` in ≤ N words mentioning required
   terms. Twenty scenarios recorded live via `aef loop record` with owner
   `checks` (`contains` the required terms, `regex` on length) and
   `budget_ms`; split 12 train / 6 validation / 2 holdout
   (`--i-am-spending-the-holdout`, deliberately, once). Texts are short and
   synthetic — no real data.
3. `aef loop score agents.summary.graph:build_graph --corpus corpus`
   works, deterministic under cassette (repeat spread 0).

**Measure.** Score with cassette: n, mean, CI, spread 0. A **planted prompt
regression** (drop "mention X" from the draft prompt) scored with
`cassette_miss="live"`: the score must fall, and the spread across
`--repeat 3` is reported as the live noise floor. LLM judge vs rule-based
judge agreement with checks on this corpus (I3's A/B re-run where content
varies): report the disagreement count. Calls made: state it. Mutations:
cassette miss under `"fail"` must raise; a hit must not call `inner`; a
scenario with calls must round-trip; a check on the summary must move the
score.

## I12 — The ACE measurement on the task metric (dim 2 → 19; ADR 0124)

**Depends on I11.** Reproduce: dim 2's evidence is coverage rigs, not task
outcomes. Change: nothing new in the runtime unless the measurement demands
it. Measure, on the summary corpus, four arms with the cassette off (live,
budgeted: ≤ 60 calls): (a) no retrieve node, (b) retrieve with raw records
only, (c) retrieve with the knowledge layer, (d) (c) + `reflection.impl:
llm`. Metric: `aef loop score` validation mean and repeat spread. Report
the table. Falsification: if (c) ≤ (b) the knowledge layer buys nothing on
the task metric and dim 2 does not move — record it. If (d) ≤ (c) the LLM
reflection stays off. Dim 2 moves only on a measured gain above the spread.

## After each merge wave

Launch `seam-hunter` on the diff of the wave. Every finding is reproduced
or dropped; reproduced ones are fixed in a `fix/` branch by a worker and
merged before the next wave. Six for six, every adversarial round in this
program found a defect. Assume this one will.

## Owner actions this loop cannot take

- Update the Codex CLI (`npm i -g @openai/codex@latest`) and run the
  smoke in `docs/model-checks/2026-09-03-claude-fable-5-1.md` — dim 8 +1.
- Point `harvest` at a real tenant's runs (ADR 0119 made it safe) — dim 7
  up to +5, and the trust case's own criterion.

## Report

`docs/model-checks/`-style: `docs/research/above-90-<date>.md` with the
rubric re-scored, every number, every knob's default and why, calls made,
and the owner actions. Then stop.
