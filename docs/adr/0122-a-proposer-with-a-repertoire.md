# ADR 0122: A proposer with a repertoire

## Status
Accepted. Increment I10 of `ABOVE_90_LOOP.md`; record in `IMPROVE_LOG.md`.
`LLMProposer` is implemented, measured live, and **off by default**
(`LoopConfig.proposer = "rule_based"`; `aef loop run --proposer llm` turns it on).

## Context

ADR 0121 built DGM's archive and measured zero diversity gain, because
`RuleBasedProposer` is deterministic from its evidence: one structural
transformation and a numeric step. Reproduced at the start of this increment
(`.scratch/i10_reproduce.py`, RUN): from the root of the flaky fixture the
proposer emits one candidate; from the kept state, one other; identical across
three calls; **two reachable trees in total**. The archive had nothing to
sample. Dimension 6 sat at 6/10 with "a proposer with a repertoire" named as
what was missing.

The model path exists without a key (ADR 0112) and two model-in-the-loop
slices already state the rule this one follows: the model writes prose, code
computes every counted field (ADR 0110, 0115).

## Decision

1. **`aef/harness/llm_proposer.py`: `LLMProposer(provider, model)`** with the
   same `propose_from_memory(evidence, *, proposal_id, path, source)` contract
   as the rule-based one, producing the same `Proposal`. The model sees the
   Zone A source, the train-admissible memory records and the nodes they
   blame, and returns prose plus the whole modified file in one fenced block.
2. **Citations are computed, never claimed.** `grounded_in` is
   `MemoryEvidence.citations()`; the explicit `propose(...)` path runs the
   rule-based `_check_citations`, so a validation or holdout citation is
   refused before any model call. The zone check runs before the call too: a
   model is not asked to write outside Zone A.
3. **Validation in code, reusing the gates' own rules.** Exactly one fenced
   block; parses (`ast`); if the fence names a path it must be this one; the
   diff is non-empty and within G0's line budget (`DEFAULT_MAX_CHANGED_LINES`,
   overridable from `gate_limits`); no finding G0's `scan_source` would raise
   on the reply that the incumbent did not already carry (the allowlist is
   IMPORTED from G0 — a test asserts the module holds no set literal of its
   own); no owner-only declaration touched (G4's `OWNER_ONLY_FIELDS`, through
   the catalogue's `_assert_controls_untouched`). None of this is a second
   copy of the gates; every candidate is still gated. It is the proposer
   declining to spend N+2 corpus passes on a reply G0 would reject in
   milliseconds — and, for G4, declining to emit what would HALT the loop as
   a security event.
4. **Any failure falls back to `RuleBasedProposer` and says so** in the
   rationale (`[llm proposer fell back to rule-based: <reason>]`), and the
   cycle line repeats the reason. A model outage is a rule-based proposal with
   a note, not a lost turn.
5. **Wiring.** `LoopConfig.proposer: "rule_based" | "llm"` plus
   `proposer_provider`/`proposer_model`, refused at construction if `llm` is
   named without both. `cycle` builds the proposer from config; `run_loop`
   inherits it; the GATED ledger event records which proposer produced the
   candidate. `aef loop run|cycle --proposer llm --proposer-model <id>` builds
   `ClaudeCodeProvider` through the config factory. No model id is hardcoded.
6. **Off by default, by measurement** (below). Zone policy and every gate are
   unchanged.

## Evidence

Live, `ClaudeCodeProvider(default_model="claude-fable-5-1")`, `run_loop`
4 turns, rule-based vs LLM (2 reps), through the real six-gate pipeline.
**26 model calls** in total: 1 smoke, 9 under the defective driver (next
section, discarded), 16 measured.

| fixture | proposer | kept | distinct kept trees | gate pass | calls | stopped |
|---|---|---|---|---|---|---|
| flaky | rule_based | 1 | 1 | 1/3 | 0 | turn 3 re-proposed a rejected tree |
| flaky | llm rep 0 | 1 | 1 | 1/4 | 4 (92 s) | turn budget |
| flaky | llm rep 1 | 1 | 1 | 1/4 | 4 (102 s) | **halted** turn 4: G5 drift exhausted twice |
| demo | rule_based | 0 | 0 | 0/2 | 0 | turn 2 re-proposed a rejected tree |
| demo | llm rep 0 | 1 | 1 | 1/4 | 4 (134 s) | turn budget |
| demo | llm rep 1 | 1 | 1 | 1/4 | 4 (98 s) | turn budget |

- **16/16 replies validated; 0 fallbacks.** Every LLM run produced four
  distinct candidates and never re-proposed a rejected tree; the rule-based
  proposer stopped for want of ideas on both fixtures.
- **Flaky:** turn 1 the model wrote an in-node bounded retry (28 and 26
  lines) that passed every gate — the same repair the catalogue has, in its
  own shape. Turns 2-3 widened the retry (catch `Exception`, degrade instead
  of raising) and G3 rejected them against the null cohort. **G5 then
  rejected turns 3-4 of rep 1 for cumulative drift 0.542 / 0.506 > 0.5 and
  halted the loop** (criterion 3). A proposer that writes 20-35-line diffs
  spends the drift budget one kept change after blessing; the rule-based
  one never reaches it.
- **Demo:** the rule-based proposer keeps nothing (a single-constant step
  never beats the cohort — the null hypothesis by construction). The model
  raised `RETRY_BUDGET` and `QUALITY_THRESHOLD` 3→9 **together**, citing the
  run that failed on quality alone at difficulty 1, and it passed every gate
  in both reps: the exact "coherent change beats random change" claim the
  demo agent's docstring was written to test, made for the first time by a
  proposer rather than a hand-written fixture. Turns 2-4 the model said in
  its own prose that the current constants already accept every recorded
  input and proposed anyway; G3 rejected all of them.
- **Prediction recorded as wrong:** the expectation was distinct kept trees
  > 1 on at least one fixture. It is 1 in every arm. The repertoire exists
  (4/4 distinct candidates per run); the *kept* diversity did not move,
  because after one kept change the gates reject the rest. That is the gates
  working, and it is why the archive still has one member to sample.

**Why off.** The falsification rule was "LLM keeps ≤ rule-based → stays
off". The result is mixed: equal on flaky (1 = 1, at 0 calls for the rule
base), strictly better on demo (1 > 0). Off by default because the gain is
one kept candidate on the one agent the catalogue cannot reach, at ~100 s a
turn, and because the LLM arm is the only one that halted the loop.
`--proposer llm` is the owner's call for agents whose failures the catalogue
has no entry for — which the demo measurement says is real.

**Mutations** (`.scratch/i10_mutations.py`, each applied with an anchor
assertion, tests run, file restored byte-for-byte): M39 citation check
dropped, M40 parse check dropped, M41 zone check dropped, M42 provider error
not caught, M43 G0 scan dropped, M44 G4 check dropped, M45 line budget
dropped, M46 `config.proposer` ignored, M47 citation list dropped from the
rationale — **9/9 detected**. Plus M48 below.

## A defect found by running the measurement

The first live run rejected every turn after the first, in every arm, with
`G1: gate raised TrustBoundaryError: scratch destination .../work/workspace
must be empty`. `run_loop` handed every turn the same `workdir`; G1
materialises the candidate into `workdir/workspace` and
`trust._prepare_empty_destination` refuses a non-empty one. So **no real
`run_loop` had ever gated a second candidate behaviourally**: ADR 0114's
"turn 2 numeric tweak rejected" and ADR 0121's measurement were this, not
G3. Both tests asserted a rejection without asking which gate. Fixed in the
driver (a scratch dir per turn, `workdir/turn-<n>`), with a driver test and
an acceptance-test assertion that every gated candidate ran G3 and no gate
raised; mutation M48 (shared workdir reinstated) fails both. Gates unchanged.
The seventh adversarial-round-shaped finding in this program, and the first
found by a measurement rather than a review.

## Consequences

- Rubric dimension 6: 6 → 8. A repertoire exists and is measured (four
  distinct, gate-legal candidates per run, zero fallbacks); parents remain
  un-diverse because kept diversity is still 1 — stated, not claimed.
- Rubric dimension 1: 17 → 18. The loop's turns 2+ are real for the first
  time, and on `agents/demo` the loop keeps a candidate it could not before.
- `LoopRun.distinct_kept_trees` stays the measurement surface; the next
  question is whether G5's drift budget, sized for two-line diffs, is the
  right budget for a proposer that writes twenty — a decision for an owner,
  not a threshold to raise here.
- The harness chatter observed once in the model's prose ("Using no skill —
  proposer task…") lands in the rationale, capped at 600 characters. Cosmetic.

## Confidence

High on the mechanism and the validation (9 mutations, 39 tests including
the six-gate seam test with a fake provider). Medium on the measurement's
generality: two fixtures, two reps, one model; the direction on demo was the
same in both reps and the halt on flaky happened in one of two.
