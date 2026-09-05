# ADR 0139: An adopted repo gates a candidate — and the minimum it takes

## Status
Accepted. Increment K3 of `READY_LOOP.md`; record in `IMPROVE_LOG.md`.
**No rubric dimension moves** — this is adoption readiness, not a scoring
claim. It makes definition-of-done statement **1** answerable with a command
and shows exactly where it is still false.

## Context

`tests/cli/test_adoption_sequence.py` drove a fresh adopted repo to five green
obligations and a blessed baseline, and stopped. Its one `aef loop cycle`
asserted `"ledger verified" in cycle.stdout` — which the cycle prints before
it has done anything — and passed no `--entrypoint`, so G2 and G3 would have
refused for lack of evidence even if a candidate had existed.

The most expensive thing an adopter is promised — propose, judge, keep — had
only ever run against this repo's own `agents/demo` and `agents/flaky`
fixtures, which this repo wrote to be easy. `tests/harness/test_structural_acceptance.py`
is the closest existing coverage and it calls `cycle()` in-process, with an
in-process memory store, against a hand-built four-file repo that was never
adopted.

**Reproduced, RUN.** Fresh repo, one 8-line raw-SDK agent, `aef adopt`, then
`aef migrate` (K1's routed form landed correctly), then the whole documented
sequence:

```
$ aef migrate --dir .
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 1 routed through Services.model_provider, 0 still calling your function

$ aef loop doctor --repo . --state <state> --corpus corpus --agent-path aef_migrated.py
  [--] corpus + tripwire       0 scenario(s), 0 tripwire(s)
  [--] reflect node routed to  no reflect node in the graph
  [--] observations            0 recorded run(s)
  [--] halt channel            none — a halt would tell nobody
  [--] blessed baseline        0 archived version(s)
  [OK] model calls visible     1 reachable module(s), none imports a model SDK

$ aef loop bootstrap aef_migrated --corpus corpus --inputs inputs.json
recorded 0 scenario(s) in the train split
  ERRORED (nothing recorded)  bootstrap-1: ModelProviderError: cassette miss
    ... and no live provider to fall through to
NOTHING was recorded and the corpus is unchanged.                    exit=1

$ aef loop bless --repo . --state <state> --agent-path aef_migrated.py
blessed aef_migrated.py as baseline v1 for graph 'default'            exit=0

$ aef loop cycle ... --entrypoint aef_migrated:build_graph --agent-path aef_migrated.py
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle               exit=0
```

**Exit 0, having done nothing.** That is the answer to READY_LOOP's "if the
cycle cannot produce a candidate, that is the finding" clause, and it is the
repo's signature defect shape one more time: a green light for something that
did not hold.

## Decision

Extend the adoption sequence to the end — one test, the adopter's real first
day — and **document the minimum at the top of the generated `LOOP.md`**
rather than in step five, because every item in it makes `aef loop cycle`
exit 0 having done nothing.

### The minimum, each item measured by removing it

Each row below is a working sequence with exactly one thing taken away, run,
and quoted. Nothing here is inferred from reading the code.

| Removed | `aef loop cycle` said | exit |
|---|---|---|
| the module-level numeric constants | `the proposer produced nothing from the available evidence` | 0 |
| the route to reflect (`return delta, END`) | `no admissible failure memory: no candidate this cycle` | 0 |
| the failing `aef run --memory <file>` | `no admissible failure memory: no candidate this cycle` | 0 |
| the graph's place in `agents/` (repo root instead) | `gated: reject — G0 rejected it: candidate touches paths outside Zone A` | 1 |

So the minimum an adopter must supply, beyond what `adopt` and `migrate`
write, is:

1. A graph **under `agents/`** (Zone A). `aef_migrated.py` lands at the repo
   root, which is Zone C — a candidate touching it is rejected by G0, and
   `bless` archives a Zone A tree that does not contain it (below).
2. **At least one module-level numeric constant** in it. That is the shape
   `RuleBasedProposer` and `ControlCohortGenerator` both operate on, and a
   5-member cohort needs enough reachable distinct mutations to exist.
3. **A reflect node, with a node that returns `"reflect"`** — and the `Edge`
   behind it (ADR 0070/0075). This is obligation 2, and it is the producer of
   every `MemoryRecord` the proposer can cite.
4. **At least one FAILING `aef run --memory <file>`**, pointed at the same
   file `aef loop cycle --memory` reads. `aef loop bootstrap` cannot supply
   this: it gives every input its own `InMemoryMemoryStore` (deliberately —
   ADR 0138's seam), so nothing it records survives the process.
5. Gated-split scenarios in `corpus/` — bootstrap's train split counts
   (`GATED_SPLITS` is train + validation) — plus the owner's tripwire.
6. A blessed baseline, and `--entrypoint` on the cycle.

**And a model-calling graph cannot supply (5) without a credential.** The
cassette the gates replay from does not exist until something makes the call
once, so `aef loop bootstrap` on K1's routed node exits 1 with `no live
provider to fall through to`. This is not a gap to be documented around: the
first recording of a real model call costs a real model call. An adopter with
no credential can only start the loop on a graph that calls no model — which
is what the new test does, and it is the first line of the new `LOOP.md`
section.

### What the test asserts, and where

`test_an_adopted_repo_gates_a_candidate_end_to_end`, marked `slow` (it is
N+2 corpus passes: 35 scenario executions), needing **no credential and
making no model call**:

adopt (fixture) → `aef migrate` → *bootstrap the migrated graph and watch it
refuse* → the minimum, hand-written → `aef loop bootstrap` → **the tripwire
line bootstrap printed, run verbatim through `shlex.split`** → a failing
`aef run --memory` → `aef loop bless` → `aef loop doctor` → `aef loop cycle`.

The gate assertions read the **ledger**, not the CLI's one-line summary. A
printed string proves a string was printed; `ledger.jsonl`'s `gated` entry
holds the evidence note and each gate's own reason, which is what "the gates
ran on real evidence" has to mean:

```
evidence: 7 corpus pass(es) (35 scenario execution(s)): 1 candidate +
          1 incumbent + 5 random control(s); corpus records one graph
          ('mine'); gating all 5 gated scenario(s)
  G0 pass  1 file(s), 2 line(s), all Zone A, no static-safety violations
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.024/0.500 from the blessed baseline
  G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
  G3 fail  candidate does not beat the p95 of the random control cohort —
           this is the null hypothesis, not an improvement
grounded_in: ['<record id> (memory): 1 error(s) recorded; ... errors[0]: gave up']
```

**The verdict is a rejection, and that is the assertion, not a disappointment.**
G3 rejecting on a real cohort comparison is the gate working. The test pins
the *absence* of `no null-hypothesis control cohort` — the refusal G3 returns
when nothing built a cohort — rather than pinning `pass`, because a test that
required an acceptance would be a test that could be satisfied by weakening
G3.

## Evidence

Every command run against a repo created by the test fixture (fresh git repo,
one raw-SDK agent, `aef adopt`).

**Before — what existed.** The old sequence's cycle, with the entrypoint the
generated `LOOP.md` prescribes and every obligation the old fixture can meet:

```
$ aef loop cycle ... --entrypoint aef_migrated:build_graph
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle          exit=0
```

and, in `tests/`, no assertion anywhere that a candidate was proposed **and**
gated in an adopted repo:

```
$ grep -rn "run.proposed" tests/
tests/harness/test_structural_acceptance.py:531:    assert run.proposed is not None, run.lines
tests/harness/test_structural_acceptance.py:532:    proposed = flaky_repo.show(f"loop/{run.proposed}", "agents/flaky/graph.py")
tests/harness/test_run_loop.py:234:        if run.proposed is None:
tests/harness/test_run_loop.py:237:            proposed=run.proposed,
tests/harness/test_llm_proposer.py:448:    assert run.proposed is not None and run.proposed.endswith("-llm")
tests/harness/test_llm_proposer.py:449:    assert repo.show(f"loop/{run.proposed}", PATH) == GOOD_BODY
tests/harness/test_llm_proposer.py:469:    assert run.proposed is not None and not run.proposed.endswith("-llm")
tests/harness/test_cycle_and_halt.py:80:    assert run.proposed is None
tests/harness/test_cycle_and_halt.py:89:    assert run.proposed is None
```

— all in-process `cycle()` calls against `agents/flaky`, a repo this repo
wrote.

**The minimum, measured.** Four variants, one removal each, run:

```
no module-level constants   ledger verified: 1 entr(ies)
                            the proposer produced nothing from the available evidence   exit=0
no route to reflect         no admissible failure memory: no candidate this cycle       exit=0
no failing aef run --memory no admissible failure memory: no candidate this cycle       exit=0
graph at the repo root      proposed cycle-... on local branch loop/cycle-...
                            gated: reject — G0 rejected it: candidate touches paths
                                   outside Zone A, or lands a non-regular file          exit=1
```

**After — the sequence completes.** The ledger of the new test's run is
quoted in full above; the CLI's own lines:

```
$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json --state <state>
recorded 4 scenario(s) in the train split
  passed  bootstrap-1     passed  bootstrap-2
  FAILED  beyond-the-budget   FAILED  bootstrap-4
2 of 4 recorded run(s) FAILED.
    aef loop record agents.mine.graph --corpus corpus \
      --scenario-id beyond-the-budget-tripwire --objective "a task past the retry budget" \
      --working-memory "{\"difficulty\": 9, \"quality_needed\": 1}" \
      --split validation --expected must_fail

$ <that line, shlex.split, run verbatim>
recorded beyond-the-budget-tripwire (validation)

$ aef run agents.mine.graph --objective hard --working-memory '{"difficulty": 9}' \
      --memory <state>/memory.jsonl
  -> plan.status "failed"; memory.jsonl holds one kind="failure" record with
     failing_nodes ["work"]

$ aef loop doctor ... --agent-path agents/mine/graph.py
  [OK] corpus + tripwire       5 scenario(s), 1 tripwire(s)
  [OK] reflect node routed to  work_node() returns 'reflect' as its Route
  [OK] blessed baseline        1 archived version(s)
  [OK] model calls visible     1 reachable module(s), none imports a model SDK

$ aef loop cycle ... --entrypoint agents.mine.graph:build_graph
  ledger verified: 1 entr(ies)
  proposed cycle-20260904T...-0 on local branch loop/cycle-... (never pushed;
    proposer=rule_based)
  gated: reject — G3 rejected it: candidate does not beat the p95 of the
    random control cohort — this is the null hypothesis, not an improvement
                                                                        exit=1
```

**Mutations**, each perturbing a production value, each run, each reverted
(`git diff --exit-code -- <file>` clean afterwards; the two K3 tests plus the
four pre-existing ones in the file):

```
BASELINE                                                  6 passed
M1 the proposer returns nothing                           1 failed, 5 passed
     -> "the proposer produced nothing from the available evidence"
M2 G3 built with verdict=None (its no-cohort refusal)     1 failed, 5 passed
     -> "no null-hypothesis control cohort — beating the incumbent proves nothing"
M3 the cohort build raises (G2/G3 refuse)                 1 failed, 5 passed
     -> "could not build evidence (MUTATION M3); G2/G3 will refuse"
M4 `aef run --memory` uses an in-memory store             1 failed, 5 passed
     -> memory.jsonl never written
M5 `aef migrate` never emits the routed form              1 failed, 5 passed
     -> "0 routed through Services.model_provider"
M6 the LOOP.md minimum moved below the six obligations    1 failed, 5 passed
     -> "the minimum has drifted below the obligations it must precede"
M7 the printed tripwire line drops --expected must_fail   1 failed, 5 passed
     -> no line matches, so nothing the owner can paste
REVERTED                                                  6 passed
```

**Green bar:**

```
pytest -q          1877 passed, 1 skipped   (collected 1876 -> 1878; +2, none removed)
mypy aef examples  129 source files, no issues
ruff check .       All checks passed
ruff format --check aef tests examples   239 files already formatted
model calls made   0
```

## Consequences

- **Definition-of-done statement 1 is now answerable, and the answer is "not
  yet, and here is exactly what is missing".** "A raw-SDK repo goes from
  `git clone` to a gated candidate **without hand-writing a node or a
  scenario**": the scenario half is true (K2 — bootstrap plus one pasted
  line); the node half is **false**, and the six items above are the precise
  size of the falsehood. Statement 3 is strengthened: the obligations were
  already green-only-when-true, and this shows what green does and does not
  buy — every obligation green is *necessary* and not *sufficient* for a
  candidate, because the proposer's inputs (constants, durable failure
  memory) are not obligations at all.
- **The minimum leads `LOOP.md`.** It is at the top because each item's
  failure mode is `exit 0` with nothing done, which reads as success. An
  obligation whose failure mode is a green light cannot live in step five,
  and a test now pins the ordering (M6).
- **A wrong prediction, recorded.** I expected the blocker to be the
  proposer's need for failure memory — READY_LOOP's own guess, and mine. It
  was necessary but not sufficient: **Zone A placement** turned out to matter
  just as much and was not on anyone's list. `aef migrate` writes its module
  to the repo root, which is the one place in an adopted repo where the loop
  is structurally forbidden to work, and nothing says so. Two of the four
  measured blockers (Zone A, the tunable constant) are properties of *where
  and how the code is written*, not of what the adopter has recorded.
- **Two defects found, neither fixed here** (both live outside K3's file
  scope; reported instead):
  1. **`aef loop bless --agent-path <a path outside Zone A>` succeeds and
     archives a baseline containing none of it.** Run against the adoptee,
     `bless ... --agent-path aef_migrated.py` printed `blessed
     aef_migrated.py as baseline v1` and the archive held exactly one file:
     `agents/README.md`. `bless` checks `path_exists_at(ref, agent_path)`,
     then archives the Zone A tree — two different questions, and the message
     names the first while doing the second. The `blessed baseline`
     obligation then goes green on evidence unrelated to the agent.
     (`aef/harness/preflight.py:bless`, `aef/cli/loop.py:cmd_bless`.)
  2. **`aef adopt` writes no `.gitignore`, and committed bytecode is charged
     as drift.** An ordinary `git add -A` after the first run commits
     `agents/**/__pycache__/*.pyc` into **Zone A**. Those files did not exist
     when the baseline was blessed, so G5 charges them: measured
     **0.4675 of a 0.500 budget** for a one-line candidate, against
     **0.0238** for the same candidate with the bytecode excluded — a 20x
     over-report, and the adopter's second candidate would be rejected for
     drift it did not cause. This is ADR 0074's defect arriving from the
     other side: that fix made both sides read from git; nothing stops an
     adopting repo from having the bytecode *in* git. The new fixture writes
     the `.gitignore` itself, with the numbers in a comment, and the
     generated `LOOP.md` now says to add one before blessing.
     (`aef/cli/adopt.py`.)

## Erratum (ADR 0170, 2026-09-04) — requirement 2 is a cohort property, and it now has a prose cohort

Requirement 2 above ("at least one module-level numeric constant") was measured
here on the **proposer**: remove the constants and `aef loop cycle` says *the
proposer produced nothing from the available evidence*. ADR 0148 re-measured it
on `migrate`'s generated graph and found the constant is needed by the
**control cohort** at least as much — whatever proposes the candidate, the
thing that judges it was built by mutating constants.

That reading was right, and it is now only half true. `ProseControlCohortGenerator`
(ADR 0170) gives G3 a real null hypothesis for a **prompt** candidate: N
placebo bullets in the same `## Lessons (aef)` section, matched to the
treatment's token count, carrying no content word of it. So requirement 2 reads,
as of ADR 0170:

> **2'. At least one module-level numeric constant — for a Python agent.** A
> prompt-file agent (`.md`/`.markdown`/`.txt` in Zone A) needs none: it is
> proposed against by `--proposer rule_based_prompt` and controlled by the prose
> cohort. Every *other* file kind still has neither a proposer nor a cohort, and
> G3 still refuses — by name, saying which.

Requirements 1 and 3–6 stand unchanged. The rest of this ADR is unamended.

## Confidence

High that an adopted repo can gate a candidate: the sequence runs from a
fresh `git init` through six executing gates in subprocesses, and the
assertion is the ledger's own record of what each gate ran on.

High on the four measured minimum items: each was removed, run, and quoted,
and four of the seven mutations attack exactly those paths.

Moderate on the minimum being *complete*. It is the minimum for **this**
agent shape — one work node, two integer constants, a reflect node. A graph
whose failure mode is a raised exception lands in `errored` rather than
`failed` (ADR 0138 already flags this) and would need the structural
proposer's `add_bounded_retry` to apply; a graph with one small integer
constant may not yield five distinct control mutations and would fail cohort
generation with a different message than any quoted here. Neither was run.

Low on anything this says about a repo nobody wrote to be scanned. The
adoptee is still a fixture this repo authored — smaller and less helpful than
before, but authored. That is K5's whole point and no test can close it.
