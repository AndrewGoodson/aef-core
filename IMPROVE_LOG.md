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
