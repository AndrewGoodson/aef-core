# ADR 0075: Obligation 2 broke the gates

## Status
Accepted. Phase 2 round 2 of the overnight run — the remaining seam-sweep
joins: `adopt`-emitted artifacts → the CLI they invoke, and reflect node →
memory → `MemoryEvidence` → proposer.

## The headline

ADR 0073 found that obligation 2 (add a reflect node) made obligation 3
impossible, because every reflect node needs `critic` and `judge` and
`aef run` wired neither. It fixed two construction sites: `aef run` and
`aef loop record`.

**There was a third, and it is the one the gates use.**

`scenario_runner.run_scenario` — the code that re-executes every corpus
scenario inside the sandbox, for the candidate, the incumbent and all five
control-cohort members — built `Services(clock=...)` and nothing else.
Reproduced with the same graph run both ways:

```
direct run WITH critic+judge -> nodes: ['work', 'reflect']
through scenario_runner      -> terminated=False, node_path=[], score 0.0
   failure: ServiceNotConfiguredError: service 'critic' was not configured
```

So for any adopter who satisfied obligation 2, **every one of the 7×N
scenario executions crashed before running a node.** Candidate 0.0, incumbent
0.0, every cohort member 0.0 — and G3 rejects a candidate that does not beat
the cohort's p95, so **G3 rejected every candidate forever**, while
`aef loop doctor` reported the obligation green.

The two halves were each tested. Nothing composed them: this repo's own
`agents/demo/graph.py` — the agent behind the whole-pipeline acceptance proof
— has no reflect node, so the one agent the gates are tested against is the
one shape that could not expose this.

## The rest

**ADR 0074's fix survived one class over.** `LoopConfig.entrypoint` lost its
`agents.graph:build_graph` default; `G2OutcomeNonRegression.entrypoint` kept
its own. So the driver correctly reported *"no entrypoint configured: G2/G3
will refuse"* and G2 went and imported `agents.graph` anyway, crashing with
`G2ExecutionError` instead of refusing — and the crash left the ledger with a
`proposed` entry and no verdict. A fix applied to one of two identical
defaults is half a fix.

**The emitted CI workflows could not work in any adopting repo.** Three
independent reasons, each fatal: `pip install -e ".[dev]"` installs *this*
repo, which is only `aef` inside aef-core; no `--entrypoint`, so G2/G3 could
never run in an adopter's CI; no `--build-command`, so G1's default
`pytest -q` exits 5 in a repo with no tests and fails every candidate. The
workflow shipped beside a LOOP.md that *does* pass `--entrypoint` — the two
were written at different times and nothing compared them.

**The weekly digest ran hourly.** `if: ${{ a }} || b` is one interpolation
followed by literal text, so the whole condition is a non-empty string, and a
non-empty string is truthy in an Actions `if:`.

**A missing `--memory` was reported as a rejection.** `Path(None)` raises
`TypeError`, `main()` catches everything and returns exit 1 — the code
meaning "this candidate is no good". A configuration error reported as a
verdict is one CI will retry forever, and it made the driver's own explicit
refusal unreachable.

**The grounding never left the process.** `cycle()` passed only a branch name
to `gate()`, which rebuilt an empty `Proposal` stub with
`is_control=True`. So the owner's review report described a
memory-grounded proposal as *"none (control-cohort member)"*, and no memory
record id appeared anywhere in loop state. Grounding is enforced at
construction and was then discarded before anything could audit it. The
proposal, its rationale and its citations now reach both the report and the
ledger.

**`FileMemoryStore` dropped `valid_from`/`valid_until`** — silently, in the
store whose own comment says silent record loss is what it exists to prevent.
A semantic memory with a validity window came back looking permanently valid.
`grep -rln FileMemoryStore tests/` returned **zero files**: the durable store
the whole loop depends on had no direct test.

**The scaffolded agent made G2 vacuous.** `Outcome.passed` requires
`plan_status == "done"`, and `Comparison.regressed` returns `False` when the
incumbent did not pass. Neither `aef init`'s template nor `aef adopt`'s shim
ever constructs a `Plan` — so a corpus recorded from a scaffolded agent
gives G2 nothing it can reject, while reporting *"every previously-passing
one still passes"* over scenarios where none ever passed.

**LOOP.md documented half the reflect wiring.** It says an `Edge` is not
enough and the node must `return delta, "reflect"` — true, and it never says
the edge is *also* required. The executor refuses a route with no declared
edge behind it, so an adopter following the text literally gets
`node 'work' routed to 'reflect', but no declared edge ... has a true
condition`. The edge is the authorisation; the return value is the choice.

## What the memory wire actually does

Worth recording, since ADR 0065 left it open: **it works.** A reflect node
writes `kind="failure"` records; `MemoryEvidence` filters on that kind and on
exclusion of validation/holdout-derived runs, nothing else; a real
`aef loop cycle` produces a proposal whose citations resolve to real record
ids. The exclusion filter was verified against a planted fault (rewriting a
`run_id` to a validation scenario id correctly produced "no admissible
failure memory"). What was broken was everything downstream of it.

## Consequences
- Adopters must re-generate `.github/workflows/loop-*.yml`; the previously
  emitted ones cannot have been working.
- The gate runner now wires `RuleBasedCritic`/`RuleBasedJudge` and a
  throwaway in-process memory. Memory is deliberately not durable there: a
  gate run must not mutate the evidence a later proposal is built from.
- `tests/harness/test_adopter_runtime.py` starts at the emitted artifact,
  extending ADR 0074's rule to `aef.cli.adopt_loop`, whose caller is the
  adopter's CI.

## Confidence
High: each was reproduced by running, and the previously-broken
configuration — an adopter satisfying all five obligations, reflect node
included — now passes all six gates end to end from the shipping CLI, with
the reward hack still caught by the tripwire. **Not claimed:** that the join
list is exhausted. Five joins have been swept; `proposer → workspace → G0`
has not, and the five lower-severity findings recorded in ADR 0074 remain
open.
