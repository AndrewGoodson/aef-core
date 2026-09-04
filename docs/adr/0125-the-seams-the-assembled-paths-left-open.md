# ADR 0125: The seams the assembled paths left open

## Status
Accepted. Fix wave A of `ABOVE_90_LOOP.md`'s post-merge adversarial pass
(branch `fix/seams-a`); record in `IMPROVE_LOG.md`.

## Context

`ABOVE_90_LOOP.md` says every merge wave gets a `seam-hunter` pass and that
six for six of this program's adversarial rounds found a defect. This one
found six, and five of them are the same shape: **a component that is
correct, tested, and never handed what it needs by the thing that assembles
it.** Three of the ten defects this repo has recorded lived in seams
(`.claude/skills/reproduce-first/SKILL.md`); this wave makes it eight of
sixteen.

Every finding below was REPRODUCED by running it before anything was
changed. The reproductions live in the seam-hunter's scratch dir; the
commands and the numbers are in the Evidence section, and each one is now a
committed regression test.

Two of the six were **pre-existing**, not introduced by the I10/I11 wave:
F3 has been live since ADR 0094 moved node bodies into a worker, and the
`loop score` policy gap has been live since ADR 0113 added the command.

## Decision

### 1. `aef run` rebuilds the knowledge store from durable memory (F1)

`run_graph_module` built a fresh `InMemoryKnowledgeStore()` per process, and
a graph's retrieve node runs *before* its consolidate node. So across CLI
runs no consolidated lesson was ever in context: `retrieved_signatures` was
`[]` in every run, ADR 0118's helpful/harmful tally had no producer on the
assembled path, and that ADR's "A1 is closed on the way" was true only for a
caller who constructs `Services` by hand.

When `memory_path` is given, `RuleBasedConsolidator().consolidate(memory,
knowledge, agent_id=agent_id)` runs at run start. **Recompute, not a
file-backed knowledge store**: the consolidator is a stateless function of
the memory store by design (ADR 0110's "stateless recompute, deliberately"),
so re-deriving is exactly equivalent to having persisted it, with no second
source of truth about what has been seen — which is the thing ADR 0091 says
drifts. With an in-memory store there is nothing to rebuild from and the
step is skipped.

`aef loop skills` already did this (ADR 0117, "the knowledge store is
rebuilt from the durable memory file each run"). `aef run` did not. One
caller having the right shape is not the shape being enforced.

### 2. `aef run` scopes the default retriever to the agent (F2)

Without a `context:` block `build_retriever` returns `None`, so
`agent_services` defaults a retriever — over the *durable, multi-agent* store
`--memory` names, with `agent_id=None`. It returned another tenant's record.

`aef run` now passes `agent_id`. The default in `agent_services` stays
`None`, because "all agents" is the honest reading of a caller that did not
say; what changed is that no real caller leaves it unsaid over a shared
store. ADR 0118's comment claiming this default "only ever fronts a
throwaway store" was wrong and is corrected in place, with an erratum
appended to that ADR.

### 3. The `configure` frame carries the policy, the agent id and the clock (F3)

Since ADR 0094 the node bodies run in a worker process, and that worker did
`services = agent_services()` — no policy, no agent id, no pinned clock. A
node consulting `services.policy_engine` was judged deny-by-default whatever
the base ref configured, so **candidate, incumbent and every cohort member
scored the same 0.0**: the exact uniform-zero symptom `aef/services/runtime.py`
opens by describing, one process boundary further out, for a sixth time.

ADR 0123 added a `configure` frame for the cassette. That frame is extended
rather than joined by a second channel — a second channel is a second list to
drift. It now carries `policy` (encoded by `scenario_runner.policy_payload`,
decoded by its existing inverse `policy_config_from_payload`, so there is one
encoding of a `PolicyConfig` and not two), `agent_id`, and `clock_values`.
The worker rebuilds its services once per scenario from `agent_services`,
carrying the memory and knowledge stores over so that one worker still serves
the whole corpus with production-like store-level state.

The clock's cursor in the worker is independent of the parent's, and that is
disclosed in the code: the parent's executor consumes its copy to build each
`Context.now`, in another process. `Context.now` — the value the node
contract says a node actually uses, since "nodes never call the clock
themselves" — is pinned exactly, by the parent. The worker's clock exists so
that a node breaking that contract gets a recorded value rather than wall
time.

### 4. `elapsed_ms` differs between the two paths, and is documented, not changed (F4)

The isolated path's stopwatch includes per-node IPC. A `budget_ms`
calibrated with `aef loop score` can therefore fail at the gate. The
stopwatch is **not** changed: timing only the executor's inner work would
stop measuring what a candidate costs to run under the gate, and subtracting
an estimated IPC cost would be inventing a number. ADR 0113's Consequences
carries the measurement and `aef loop score --help` says it.

### 5. `run_loop` refuses to start on the kept branch (F7)

`run_loop` advances `loop/kept` with `update-ref`, which moves a branch
without touching the index or the working tree. When that branch is also
HEAD, the reviewer is left with an index that disagrees with its own HEAD
commit — `git status` reads as a staged reversal of the change the loop just
kept, and the next commit in that checkout would undo it.

`KeptBranchCheckedOutError` is raised before anything is created or gated,
naming the branch and the action ("check out another branch"). `update-ref`
stays: `merge` or `reset` on the checked-out branch is the loop touching a
person's working tree, which ADR 0114 refuses.

### 6. The gates select scenarios by `graph_id` (F11)

`corpus/` holds `demo_agent` and `summary_agent` recordings since ADR 0123,
and `_gates_with_evidence` ran all of them against whichever graph the
entrypoint named — diluting every mean with scenarios the candidate cannot
satisfy. `aef loop score` already filtered, because it can load the graph
in-process and read `graph.id`; the gates, which deliberately cannot, did
not.

The rule, stated because it is a choice rather than a deduction:

- Some gated scenario carries `graph_id == config.graph_id` → gate on
  exactly those.
- No scenario matches and the corpus records ONE graph → gate on all of
  them. `--graph-id` defaults to `"default"` and is the ARCHIVE key, a
  different namespace from `graph.id`; a single-graph corpus has nothing to
  disambiguate, and requiring the two namespaces to agree would break every
  existing single-graph corpus to fix a mixed-corpus defect.
- No scenario matches and the corpus records SEVERAL graphs →
  `CorpusGraphMismatchError`, by name. There is no defensible subset, and
  running all of them is the defect. **Named and raised, not an empty
  scenario list**: empty reads to G2/G3 as "no evidence", which escalates —
  the same outcome, with none of the information about why.

G2 gets the same filtered scenarios the cohort ran. It reads its own corpus
and reports anything absent from `precomputed` as missing, so handing it the
unfiltered corpus after filtering the cohort would turn every other graph's
scenario into a rejection.

### 7. `aef loop score --config` applies the config's policy (the suspected item, reproduced)

`cmd_score` called `run_scenario` with no policy — deny-by-default — while
`aef run --config` applies `build_policy_config` and the gates apply
`_policy_from_base_ref`, from the same `aef.yaml`. Three paths, two of them
agreeing. Reading the file directly is correct here for the reason it is
correct in `aef run` and wrong in the gates: `loop score` scores the
incumbent the owner trusts, from a path the owner typed, and never a
candidate.

## Evidence

Environment: worktree `fix/seams-a` off `705543d`; every command prefixed
`PYTHONPATH=$PWD`, venv interpreter, pytest with `-p no:warnings` and a
basetemp outside the tree. **No live model calls were made in this wave.**

**F1/F2 — `.scratch/repro_run_path.py`** (`run_graph_module` three times with
`--memory`, no `--config`, on a retrieve→work(fails)→reflect→consolidate
graph, plus a pre-seeded `OTHER-TENANT` record):

```
before  run 0: retrieved ['memory:failure:d9d484cb…']   retrieved_signatures []
        run 1: retrieved 2 records                      retrieved_signatures []
        run 2: retrieved 3 records                      retrieved_signatures []
        (d9d484cb is OTHER-TENANT's record; no knowledge chunk ever appears)
after   run 0: retrieved []                             retrieved_signatures []
        run 1: retrieved 1 record                       retrieved_signatures []
        run 2: retrieved ['knowledge:failure:failure:work', …]
                                                        retrieved_signatures ['failure:work']
```

Run 2 is the first run from which the lesson exists: the consolidator
requires a signature in two distinct runs (one is an episode, ADR 0110).
Tests: `test_run_with_durable_memory_retrieves_the_lesson_consolidated_by_earlier_runs`,
`test_run_without_a_context_block_does_not_retrieve_another_tenants_record`.

**F3/F4 — `.scratch/repro_budget_isolated.py`** (a 4-node graph whose last
node calls `services.policy_engine.evaluate` on a tool needing `net.read`,
with `PolicyConfig(allowed_scopes={"net.read"})` handed to BOTH runners):

```
before  in-process  score 1.0  errors 0  elapsed 0.125 ms
        isolated    score 0.0  errors 1  elapsed 0.767 ms
after   in-process  score 1.0  errors 0  elapsed 0.119 ms
        isolated    score 1.0  errors 0  elapsed 0.790 ms
```

F4, unchanged by design, from the same script (three runs each): in-process
**0.082 / 0.119 / 0.125 ms**, isolated **0.715 / 0.767 / 0.790 ms** — about
0.18 ms of IPC per node. `budget_ms` set at 5x the in-process elapsed
(0.417 ms): in-process 1.0, isolated 0.0, identical code.
Tests: `test_the_harness_policy_reaches_a_node_running_in_the_worker`,
`test_no_policy_still_means_deny_by_default_in_the_worker` (the control),
`test_the_scenarios_agent_id_reaches_the_worker`,
`test_policy_payload_round_trips_through_the_configure_frame`.

**F7 — `.scratch/repro_kept_checkout.py`** (owner standing on `loop/kept`,
one turn, fake cycle):

```
before  HEAD before: loop/kept
        turn 1: KEPT 8217f41a9386 …; loop/kept@8217f41a9386
        HEAD after : loop/kept 8217f41a9386
        content in HEAD commit: RETRY_BUDGET = 4
        worktree file:          RETRY_BUDGET = 3
        git status --porcelain: 'M  agents/demo/graph.py'   <- a staged reversal
        second run: kept RETRY_BUDGET = 5, worktree 4, status still 'M  …'
after   KeptBranchCheckedOutError: HEAD is 'loop/kept', the branch this loop
        advances with update-ref … Check out another branch first …
```

Tests: `test_refuses_to_start_while_the_kept_branch_is_checked_out` (which
also asserts nothing was gated and nothing moved),
`test_the_same_loop_runs_from_any_other_branch` (the control),
`test_a_non_default_kept_branch_name_is_the_one_refused`.

**F11 — `.scratch/repro_graph_id_gates.py`** (a five-scenario corpus, two
`demo_agent` and three `summary_agent`, with a spy standing in for
`CohortBuilder` to capture what it was asked to run):

```
before  graph_id='demo_agent': cohort saw ['demo-1','demo-2','sum-1','sum-2','sum-3']
        graph_id='default'   : cohort saw ['demo-1','demo-2','sum-1','sum-2','sum-3']
after   graph_id='demo_agent': cohort saw ['demo-1','demo-2']
        graph_id='default'   : REFUSED CorpusGraphMismatchError: the corpus records
                               2 graphs ('demo_agent','summary_agent') and none of
                               them is --graph-id 'default' …
```

Tests: `test_the_gates_run_only_the_scenarios_recorded_from_this_graph`,
`test_a_mixed_corpus_with_no_matching_graph_refuses_by_name`,
`test_a_single_graph_corpus_still_gates_on_all_of_it`.

**The suspected item — `.scratch/repro_score_policy.py`** (one `aef.yaml`
with `tools.allow: [net.read]`, one graph, three paths):

```
before  aef loop score --config   train mean 0.0000  (per-scenario s1: 0.0)
        run_scenario(sc, graph, POL)          1.0
        aef run --config          working_memory['policy'] = 'allow', no errors
after   aef loop score --config   train mean 1.0000
        aef loop score (no --config)          0.0    (deny-by-default, unchanged)
```

Tests: `test_score_applies_the_configs_policy_like_aef_run_does`,
`test_score_without_a_config_is_still_deny_by_default` (the control).

**Mutations** (each: perturb the production value, run, see the named test
fail, revert, confirm no `MUTATION` marker survives in `aef/`):

```
M1  aef run's consolidate-at-start removed        1 failed (F1 test)
M2  aef run passes agent_id=None                  1 failed (F2 test)
M3/M4 configure frame sends policy=None,
      agent_id=None (parent side)                 2 failed (F3 policy + agent-id tests)
M5  worker ignores the frame's policy             1 failed (F3 policy test)
M6  the kept-branch refusal removed               2 failed (F7 tests)
M7  the graph_id filter computed and discarded    1 failed (F11 filter test)
M8  a mixed corpus falls back to all scenarios    1 failed (F11 refusal test)
M9  cmd_score builds no policy from --config      1 failed (score-policy test)
```

**Green bar.** `pytest -q` **1797 passed**, from 1783 at `705543d` (+14, none
removed); `mypy aef examples` 127 files clean; `ruff check .` clean;
`ruff format --check aef tests examples` clean.

Two container tests (`test_a_timed_out_container_is_actually_dead`,
`test_closing_the_session_leaves_no_container_running`) each failed once
across three full runs and passed in isolation and on the third full run.
Both assert on the machine-global `docker ps` set, so a concurrent worker's
container on the same daemon reads as a leak. Environmental, pre-existing,
untouched by this diff — recorded rather than papered over.

## Consequences

- **ADR 0118's "A1 closed" is true on the assembled path for the first
  time.** Dimension 2's evidence cited it; until now the run that evidence
  describes did not happen when the CLI ran it. The rubric score is NOT
  moved by this wave — no new capability was added — but the dimension-2
  claim that was overstated is now supported.
- **G3 can distinguish candidates by policy-governed behaviour.** Before,
  every such candidate scored 0.0 against a 0.0 incumbent and a 0.0 cohort,
  and G3's verdict on them carried no information. How many real candidates
  this touched is unknown: the loop's recorded runs are on `agents/demo`,
  which consults no policy, so this was invisible in every measurement this
  program has taken. That is the point — a uniform zero looks like a fair
  comparison.
- **`aef loop run` against `corpus/` now needs `--graph-id`.** With two
  graphs recorded, the default `"default"` matches nothing and refuses. That
  is a deliberate break: the previous behaviour was to run both graphs'
  scenarios against one graph.
- **A budget_ms in an existing scenario may be wrong.** None in `corpus/`
  sets one, so nothing is broken today; anyone adding one should calibrate
  from an isolated run.
- The clock now crossing to the worker is a behaviour change for any node
  that calls `services.clock()` — which the node contract says none should.
  Such a node previously got wall time under the gate and now gets a
  recorded value; neither matches the in-process cursor exactly, and the
  code says so rather than implying parity.

## Confidence

High on F1, F2, F3, F7, F11 and the score-policy fix: each was reproduced
before the change, is asserted by a test that fails under mutation, and has
a control test proving the fix did not simply loosen something.

Medium on the completeness of F3. The frame now carries policy, agent id and
clock; whether anything else a node may `require_*` still differs between the
parent's `Services` and the worker's is not proved by a test that enumerates
them — `test_service_parity.py` compares `aef run` against the in-process
gate path, and nothing yet compares either against the worker. That is the
next seam of this shape and it is stated rather than closed.

Low on F4 being sufficient. A documented footgun is still a footgun; the
honest fix is for `budget_ms` to be recorded and judged on one path, which is
a design change this ADR does not make.
