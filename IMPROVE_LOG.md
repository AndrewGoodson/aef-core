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
