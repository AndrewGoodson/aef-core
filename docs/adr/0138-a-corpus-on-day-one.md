# ADR 0138: A corpus on day one

## Status
Accepted. Increment K2 of `READY_LOOP.md`; record in `IMPROVE_LOG.md`.
**No rubric dimension moves** — this is adoption readiness, not a scoring
claim.

## Context

`aef adopt` writes `corpus/README.md` and nothing else, and `LOOP.md` says
an empty corpus makes G2 and G3 refuse — correctly, because a gate with no
evidence has nothing to say. So the loop an adopter has just installed can
do nothing until they hand-record scenarios, one `aef loop record`
invocation at a time. Reproduced on a fresh repo (one 8-line raw-SDK agent,
`aef adopt` then `aef migrate`):

```
$ ls corpus/
README.md

$ aef loop doctor --repo . --state ../state --corpus corpus \
      --agent-path aef_migrated.py
  [--] corpus + tripwire       0 scenario(s), 0 tripwire(s)
       fix: aef loop record <module> --corpus corpus --scenario-id tripwire-1 ...

$ aef loop record agents.demo.graph --corpus c --scenario-id s1 \
      --objective "an ordinary task"
recorded s1 (train)               # passed=True

$ aef loop record agents.demo.graph --corpus c --scenario-id s2 \
      --objective "a hard task" \
      --working-memory '{"difficulty": 9, "quality_needed": 9}'
recorded s2 (train)               # passed=False
```

That is the shape of the problem: **one command per scenario, and the
failing ones — the only ones that carry information — need a hand-written
`--working-memory` JSON blob each** (ADR 0074 made those reachable from the
CLI at all; it did not make them cheap).

## Decision

`aef loop bootstrap --inputs inputs.json`: run the configured graph once per
input, record each run as a TRAIN scenario, report which runs failed. Four
rules, each inherited from a component that learned it the hard way, and one
seam found while building it.

1. **Always TRAIN, and no flag to override.** Verbatim from `harvest`: if
   the system could fill the set that gates it, the gate would measure the
   system's own choices. `bootstrap()` has no `split` parameter — a keyword
   argument for a rule is a default, and a default is something a caller
   changes. A `split` key in the inputs file is *refused*, with the command
   that does accept one.

2. **Never labels `expected`.** Only an owner can say a task *should* have
   failed (ADR 0060). Bootstrap records what happened, prints the ids that
   failed, and generates — never runs — the `aef loop record ... --expected
   must_fail` line for each, with that input's objective and working memory
   filled in. An `expected` key in the inputs file is refused rather than
   ignored: an owner whose claim was silently dropped would believe the
   corpus carries a tripwire it does not.

3. **Refuses to overwrite an existing id**, and refuses the *whole
   invocation* before running anything, so a batch that collides halfway
   through leaves no half-written corpus. The rule and its wording moved
   into `recorder.refuse_existing_ids`, shared with `record_to_corpus` —
   a second copy of a rule is ADR 0091's drift waiting to happen.

4. **Reports the failure count, and says so when it is zero:** *"a corpus
   where everything passes cannot demonstrate an improvement — every gate
   reading it has nothing to hold a candidate to."* That is a finding about
   the inputs, printed as one.

**The seam: fresh `Services` per input.** The gates re-execute each scenario
in isolation with its own `InMemoryMemoryStore`
(`harvest._reexecution_services`). A bootstrap that shared one store across
inputs would record later runs that depended on what earlier ones
remembered — scenarios that cannot reproduce alone, which is the one thing a
corpus must never contain. `bootstrap()` therefore takes a *factory*, not a
`Services`.

**The inputs file.** A JSON list of objects (or an object with an `inputs`
list). Each needs `objective`; each may set `id` (default `<prefix>-<n>`),
`working_memory`, `notes`, `checks` and `budget_ms`. Objective plus working
memory is the minimum because that is exactly what `AEFState` needs to reach
a task at all, failing ones included.

**`checks` and `budget_ms` ARE accepted per input; `expected` is not,** and
the line between them is not arbitrary. A check or a budget is a
specification of the task written *before* the run — it says what a correct
answer looks like, and nothing about reading it lets the system grade
itself. `expected: must_fail` is a judgement about what the run turned out
to do, which is why `record_run` refuses the label when the agent completes
the task. Accepting the first two removes a second CLI pass; accepting the
third would let the system set its own tripwire.

**Exit code.** A bootstrap that recorded nothing exits non-zero. A workflow
keying off exit 0 would otherwise believe a corpus had been seeded — the
ready loop's rule is that the tooling does not report green for something
that did not happen.

## Evidence

Every command run against the reproduction repo above (`aef adopt` +
`aef migrate` on a raw-SDK agent), corpus reset to the README `adopt` wrote.

```
$ aef loop doctor ... --corpus corpus            # BEFORE
  [--] corpus + tripwire       0 scenario(s), 0 tripwire(s)

$ aef loop bootstrap agents.demo.graph --corpus corpus --inputs ../inputs.json
recorded 4 scenario(s) in the train split
  passed  bootstrap-1
  passed  bootstrap-2
  FAILED  beyond-the-budget
  FAILED  bootstrap-4
2 of 4 recorded run(s) FAILED.
  Bootstrap labels nothing: only an owner can say a task SHOULD have failed
  (ADR 0060). Consider marking one of these a tripwire — beyond-the-budget,
  bootstrap-4
    aef loop record agents.demo.graph --corpus corpus \
      --scenario-id beyond-the-budget-tripwire \
      --objective "a task past the retry budget" \
      --working-memory "{\"difficulty\": 9, \"quality_needed\": 1}" \
      --split validation --expected must_fail
    ...
exit=0

$ aef loop doctor ... --corpus corpus            # AFTER BOOTSTRAP
  [--] corpus + tripwire       4 scenario(s), 0 tripwire(s)

$ <the printed command, pasted verbatim>
recorded beyond-the-budget-tripwire (validation) -> corpus/validation/...

$ aef loop doctor ... --corpus corpus            # AFTER THE OWNER'S ONE ACT
  [OK] corpus + tripwire       5 scenario(s), 1 tripwire(s)
```

Not a green light over an empty set — the corpus is scoreable evidence that
moves:

```
$ aef loop score agents.demo.graph:build_graph --corpus corpus
  train       n=4  with_checks=1  mean=0.5000 stdev=0.5774 repeat_spread=0.000000
      0.0000 beyond-the-budget   1.0000 bootstrap-1
      1.0000 bootstrap-2         0.0000 bootstrap-4
  validation  n=1  with_checks=0  mean=0.0000
```

Refusals, run:

```
$ aef loop bootstrap ... --inputs ../inputs.json     # a second time
error: scenario id(s) already exist: ['beyond-the-budget', 'bootstrap-1',
'bootstrap-2', 'bootstrap-4']. Overwriting would replace the behaviour the
corpus recorded with the behaviour it has now ...     exit=1
   corpus/train unchanged: 4 files; corpus/validation unchanged: 1 file

$ aef loop bootstrap ... --inputs bad.json           # {"expected": "must_fail"}
error: input 1: 'expected' is not accepted — only an owner can say a task
should have failed (ADR 0060) ...                     exit=1
```

Mutations, each perturbing the production value, each reverted, corpus
`git diff --exit-code` clean afterwards (25 tests in the two new files):

```
BASELINE                                        25 passed
M1 writes a non-train split                      2 failed, 23 passed
M2 labels expected                              11 failed, 14 passed
M3 overwrites an existing id                     2 failed, 23 passed
M4 failure count not reported                    2 failed, 23 passed
M5 zero-failure warning removed                  1 failed, 24 passed
M6 one shared Services for every input           1 failed, 24 passed
M7 a refused key is ignored                      2 failed, 23 passed
REVERTED                                        25 passed
```

Green bar:

```
pytest -q          1845 passed, 1 skipped (from 1820; +25, none removed)
mypy aef examples  128 files clean
ruff check .       clean
ruff format --check aef tests examples   238 files already formatted
```

## Consequences

- **Definition-of-done statement 1 moves, and does not complete.** "A
  raw-SDK repo goes from `git clone` to a gated candidate without
  hand-writing a node or a scenario" — the scenario half is now true: four
  train scenarios and a tripwire, from one command plus one pasted line, no
  JSON authored by hand. The node half is K1's, and this increment ran into
  it (below).
- **The corpus obligation needs one owner act, by design.** `preflight`'s
  first obligation is `scenarios AND tripwires`, and bootstrap deliberately
  cannot supply the second. So the honest sequence is bootstrap → read the
  failed ids → paste one generated command. The alternative — bootstrap
  labelling a tripwire because the run failed — is exactly what ADR 0060
  forbids, and a tripwire the system set for itself detects nothing.
- **The adoptee's own migrated graph still cannot be bootstrapped**, and
  this is the K1 defect measured from a second direction:

  ```
  $ aef loop bootstrap aef_migrated --corpus ../k1-corpus --inputs ../inputs.json
  recorded 0 scenario(s) in the train split
    ERRORED (nothing recorded)  bootstrap-1: TypeError: "Could not resolve
      authentication method. Expected one of api_key, auth_token, ..."
    ... (4 of 4)
  NOTHING was recorded and the corpus is unchanged.       exit=1
  ```

  The migrated node calls the adopter's function, which builds its own
  `anthropic.Anthropic()`, so the run raises before producing a trace. Until
  K1 routes that call through `Services.model_provider`, an adopter can
  bootstrap only a graph that does not call a model — which is why the
  measurement above uses this repo's `agents/demo`.
- **A wrong prediction, recorded.** The first implementation printed the
  zero-failure sentence for that run: *"0 of 0 recorded run(s) failed. A
  corpus where everything passes cannot demonstrate an improvement."*
  Nothing had passed; nothing had run. "Everything passed" and "nothing ran"
  are different facts, and printing the first for the second is this repo's
  signature defect — a green light for something that does not hold — written
  by the increment whose whole subject is that shape. Fixed, tested
  (`test_a_run_that_raises_is_reported_and_records_nothing` asserts the
  everything-passed line is *absent*), and left in this ADR rather than
  quietly corrected.

## Confidence

High on the four rules: each is enforced by a test whose mutation was run
and failed, and each is one this repo already paid for elsewhere.

Moderate on the shape of `inputs.json`. It is derived from what `AEFState`
needs and from `aef loop record`'s existing flags, not from an adopter who
has written one — nobody outside this repo has produced an inputs file, and
the first real one will probably want something the schema refuses (a
per-input `agent_id`, or a shared `working_memory` prefix). Unknown keys are
an error, so that will surface loudly rather than silently, which is the
right way round.

Low on the failure count meaning what an adopter thinks it means. `failed`
here is `outcome.classify(...).passed == False` — the same definition G2
uses, deliberately — but on a graph whose failure mode is a raised exception
rather than a `failed` plan, the runs land in `errored`, not `failed`, and
the count reads 0. The adoptee measurement above is exactly that case.
