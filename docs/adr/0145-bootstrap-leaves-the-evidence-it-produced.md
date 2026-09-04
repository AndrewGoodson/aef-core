# ADR 0145: Bootstrap leaves the evidence it produced

## Status
Accepted. Increment L3 of `INGEST_LOOP.md`; record in `IMPROVE_LOG.md`.
**No rubric dimension moves** — this is adoption readiness, not a scoring
claim. It closes one of the four things ADR 0139 measured as still missing
between `aef adopt` and a gated candidate, and fixes a second construction
site found while closing it.

## Context

ADR 0139 measured the minimum an adopter must supply beyond what `adopt` and
`migrate` write, by removing each item and running the cycle. Two of the six
belong to this command.

**Requirement 4 — a FAILING run whose memory the cycle can read.** ADR 0139
recorded it as something bootstrap *cannot* supply: "it gives every input its
own `InMemoryMemoryStore` (deliberately — ADR 0138's seam), so nothing it
records survives the process". The adopter's remedy was a hand-written
`aef run --objective ... --working-memory ... --memory <file>` after the
bootstrap that had just run the same graph over four inputs and knew exactly
which two had failed.

**And a model-calling graph cannot get its first corpus at all**, because the
cassette the gates replay from does not exist until something makes the call
once.

### Reproduced first, RUN — both halves

A fresh git repo, one Zone A graph whose work node routes to `reflect`, four
inputs of which two fail. Every command run; `PYTHONPATH` and the venv elided.

**(a) bootstrap leaves no memory behind, and the cycle then has nothing.**

```
$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json \
      --no-loop-state
recorded 4 scenario(s) in the train split
  passed  bootstrap-1        passed  bootstrap-2
  FAILED  beyond-the-budget  FAILED  bootstrap-4
2 of 4 recorded run(s) FAILED.                                        exit=0

$ ls state/memory.jsonl
ls: state/memory.jsonl: No such file or directory

$ aef loop bless --repo . --state state --agent-path agents/mine/graph.py
blessed agents/mine/graph.py as baseline v1 for graph 'default'

$ aef loop cycle --repo . --state state --workdir state/work \
      --module agents.mine.graph --corpus corpus \
      --entrypoint agents.mine.graph:build_graph --memory state/memory.jsonl \
      --agent-path agents/mine/graph.py --build-command true
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle              exit=0
```

Two runs failed, the reflect node wrote a `MemoryRecord` for each, and both
died with the process that made them.

**(b) a model-calling graph cannot be bootstrapped.**

```
$ aef loop bootstrap agents.mine.modelgraph --corpus mc-corpus \
      --inputs inputs.json --no-loop-state
recorded 0 scenario(s) in the train split
  ERRORED (nothing recorded)  bootstrap-1: ModelProviderError: cassette miss
    (key 99cac4c3b731, model 'claude-sonnet-4-5', 1 message(s), max_tokens 64,
    first user text 'an ordinary task') and no live provider to fall through
    to: on_miss='live' needs an inner ModelProvider (model_provider.impl in
    aef.yaml, e.g. claude_code — ADR 0112)
  ... (4 of 4)
NOTHING was recorded and the corpus is unchanged.                    exit=1
```

**And `--config` was already in the parser.** It has been there since ADR
0138's own commit. Nothing in that message, in `LOOP.md`, or in
`AGENT_INTEGRATION.md` names it — the error names `aef.yaml`, which it cannot
get to this command, and K3 concluded that "a model-calling graph cannot get
its first corpus" while the flag that fixes it sat unused. **A flag nobody is
pointed at is not a feature, and this ADR treats it as the defect it is.**

## Decision

### `--memory <file>` — and the isolation rule is kept, not traded

The obvious implementation is one shared `FileMemoryStore` across every
input. It would work, and it would destroy the property ADR 0138 built the
factory for: input 4 would read back what inputs 1–3 remembered and the
scenario recorded for it could not reproduce alone. A corpus of scenarios
that only pass in the order they were written is worse than no corpus.

So `RunScopedMemory(scratch, sink)`: **reads go to `scratch` alone** — a
fresh `InMemoryMemoryStore` per input — **and every write is mirrored into
`sink`**, the same `FileMemoryStore` `aef loop cycle --memory` reads. Both
rules hold simultaneously and neither is a caller's choice.

`bootstrap()` builds that store and **hands it to the services factory**,
whose type changes from `Callable[[], Services]` to
`Callable[[MemoryStore], Services]`. That is the load-bearing part of the
change: while the caller chose the store, the isolation rule lived at the
call site and the durability rule could not be expressed at all.

**Bootstrap authors nothing.** The sink receives exactly the records the
graph's own reflect node wrote — same id, same `run_id`, same content. A
graph with no reflect node leaves it empty, and that is reported as a finding
about the graph rather than filled in:

```
  no memory records: this graph wrote none, so `aef loop cycle --memory` will
  say `no admissible failure memory` and propose nothing. Route a node to a
  `reflect` node (obligation 2) — bootstrap records what the run did and never
  invents a failure to fill the gap (ADR 0060).
```

That is ADR 0060 from the memory side: a system that writes the failure
evidence it then proposes from has graded itself. `--memory` absent and
`--memory` given but empty are **different facts** and print differently;
`memory_records` is `None` for the first and `0` for the second, because
printing "nothing was learned" for "you did not ask" is the green-light-for-
nothing shape this repo keeps finding.

**Knowledge is deliberately NOT rebuilt from the sink**, which is where this
parts company with `aef run --memory` (which does consolidate before running,
ADR 0125). Consolidating here would put lessons from input 3 into input 4's
context and recreate the cross-input dependency by another route.

### `--config <aef.yaml>` — one construction site, shared with `aef run`

The flag existed. What it did was build the model provider and the reflection
impl **in `cmd_bootstrap`'s own code**, while `run_graph_module` built the
provider, the policy config, the context config, the reflection impl, and
called `build_domain_gates` to fail early. So a scenario recorded by
bootstrap pinned behaviour under the engine's DEFAULT policy while the same
graph under `aef run` ran under the adopter's — the corpus describing
something production is not. Nobody had noticed because nothing compared
them, which is ADR 0091's finding verbatim.

`aef/cli/run.py` now exposes `RunConfig` and `build_run_config(path)`; both
commands read an `aef.yaml` through it or not at all.
`test_bootstrap_reads_its_config_through_aef_runs_construction_site` parses
`cmd_bootstrap` and asserts it calls `build_run_config` and does **not** call
`build_model_provider` or `load_agent_config`. A source assertion is usually
a smell; here the property *is* which of two identical constructions crossed
the boundary, and no behavioural test can see that.

**Recording is the one pass that is supposed to be live, and the price is
printed.** `BootstrapOutcome.model_calls` is summed from the cassettes the
recorder pinned, never estimated:

```
  recording spent 2 live model call(s). Recording is the one pass that is
  SUPPOSED to be live: the gates replay these from each scenario's cassette
  and need no credential (ADR 0123).
```

And when the graph asks a model with no provider configured, bootstrap adds
the sentence the provider cannot write, because the provider has never heard
of this command:

```
  This graph calls a model and no provider was configured, so the recording
  had nothing to record. Pass --config <aef.yaml> to bootstrap: it builds the
  same model provider `aef run` builds, and recording is the one pass that is
  SUPPOSED to be live — the cassette the gates replay from does not exist
  until something makes the call once (ADR 0123).
```

**Every existing bootstrap rule stands**: train only with no flag to
override, never labels `expected`, refuses the whole invocation on an
existing id before running anything, reports the failure count and says what
zero failures means, and honours the kill switch on both `--state` and
`--no-loop-state` (ADR 0141).

## Evidence

### After — the same sequence, `--memory` added, nothing else hand-written

```
$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json \
      --no-loop-state --memory state/memory.jsonl
recorded 4 scenario(s) in the train split
  passed  bootstrap-1        passed  bootstrap-2
  FAILED  beyond-the-budget  FAILED  bootstrap-4
2 of 4 recorded run(s) FAILED.
  Bootstrap labels nothing: only an owner can say a task SHOULD have failed
  (ADR 0060). Consider marking one of these a tripwire — beyond-the-budget,
  bootstrap-4
  4 memory record(s) written to the durable store — what the graph's own
  reflect node observed, nothing bootstrap decided. `aef loop cycle --memory
  <the same file>` proposes from these.
    aef loop record ... --expected must_fail                          exit=0

$ wc -l < state/memory.jsonl
4
$ <kind, run_id, content.failing_nodes for each line>
success bootstrap-1        []
success bootstrap-2        []
failure beyond-the-budget  ['work']
failure bootstrap-4        ['work']

$ <the printed tripwire line, verbatim>
recorded beyond-the-budget-tripwire (validation)

$ aef loop bless --repo . --state state --agent-path agents/mine/graph.py
blessed agents/mine/graph.py as baseline v1 for graph 'default'

$ aef loop cycle --repo . --state state --workdir state/work \
      --module agents.mine.graph --corpus corpus \
      --entrypoint agents.mine.graph:build_graph --memory state/memory.jsonl \
      --agent-path agents/mine/graph.py --build-command true
  preflight: 2 of 6 obligation(s) unmet (observations, halt channel). ADVISORY
  ledger verified: 1 entr(ies)
  proposed cycle-20260904T154639-0 on local branch loop/cycle-20260904T154639-0
    (never pushed; proposer=rule_based)
  gated: reject — G3 rejected it: candidate does not beat the p95 of the
    random control cohort — this is the null hypothesis, not an improvement
                                                                     exit=1
```

**`no admissible failure memory` → a proposed and gated candidate, and the
only thing added to the sequence is one flag.** The verdict is a rejection
and that is the correct outcome, not a disappointment: G3 comparing against a
real control cohort is the gate working (ADR 0139's rule — a test that
demanded acceptance could be satisfied by weakening G3).

The four records are the graph's, not bootstrap's: two `success` and two
`failure`, `failing_nodes: ['work']` on the failures, `run_id` equal to each
input's scenario id. `MemoryEvidence.from_store` admits them because train
scenarios are not off-limits; the owner's validation tripwire has a different
id and is not cited.

### After — the model-calling graph

```
$ aef loop bootstrap agents.mine.modelgraph --corpus mc-corpus \
      --inputs inputs.json --no-loop-state
  ... ModelProviderError: cassette miss ... and no live provider to fall
      through to ...
NOTHING was recorded and the corpus is unchanged.
  This graph calls a model and no provider was configured, so the recording
  had nothing to record. Pass --config <aef.yaml> to bootstrap: ...   exit=1
```

**The live recording path itself is NOT exercised, and this is the honest
limit of the increment.** All three shipped impls (`claude_code`, `codex`,
`anthropic`) make real calls and there was no quota to spend on one, so what
is proved is the wiring and the accounting:
`test_config_records_a_model_calling_graph_through_aef_runs_own_wiring` runs
`aef loop bootstrap agents.summary.graph --config <aef.yaml>` with a fake
provider substituted at `aef.cli.run`'s own import of `build_model_provider`
— the single construction site — and asserts the scenario's cassette holds
exactly the calls the fake answered and that the count is printed. Whether a
real `claude_code` recording succeeds end to end is untested here.

### Mutations — 10 planted, 10 caught, each restored from a byte-identical backup

Baseline: the three test files, 85 tests. M7, M8 and M10 belong to ADR 0147 and
are listed there too; the round was run as one.

```
BASELINE                                                          85 passed
M1  the durable sink is dropped again (pre-0145 behaviour)         3 failed
M2  reads fall through to the sink (durable, not isolated)         2 failed
M3  bootstrap writes a failure record of its own (ADR 0060)        3 failed
M4  a second model-provider construction site comes back           2 failed
M5  the missing-provider hint stops naming --config                1 failed
M6  the live-call count is never accumulated                       2 failed
M7  bless stops checking containment (ADR 0147's half)             1 failed
M8  containment compares raw strings, so ./agents/x.py refuses     1 failed
M9  "did not ask for a sink" printed as "asked and got nothing"    1 failed
M10 the empty-Zone-A refusal folded into the containment one       1 failed
```

Each mutation was reverted by copying back a file whose SHA-1 was recorded
before the round and re-checked after (`git checkout --` would have destroyed
uncommitted work — `INGEST_LOOP.md`'s rule).

M2 is the one worth naming: it is the *plausible* implementation of this
increment — share the store, get durability — and it fails
`test_isolation_survives_the_durable_sink`, which is the seam this ADR exists
to not break.

### Green bar

```
pytest -q          1960 passed, 1 skipped   (from 1945; +15, none removed)
mypy aef examples  129 source files, no issues
ruff check .       All checks passed
ruff format --check aef tests examples   239 files already formatted
model calls made   0 — a fake provider everywhere a provider was needed
```

## Consequences

- **ADR 0139's requirement 4 moves from "the adopter supplies it" to "the
  command that already ran the graph supplies it".** The measured sequence is
  now bootstrap → paste the tripwire line → bless → cycle, with no
  hand-written `aef run` and no hand-written scenario. Requirements 1, 2, 3
  and 5 are unchanged and belong to other increments.
- **A `LOOP.md` sentence is now false and is not this file's to fix.** The
  generated `LOOP.md` and ADR 0139 both say bootstrap cannot supply the
  failing run's memory. L6's first-day document is where that gets rewritten;
  this ADR is the record that it must be.
- **`aef run` and `aef loop bootstrap` cannot configure differently any
  more**, and the drift they had was real: `policies`, `tools.allow` and
  `evaluator.suites` never reached a recording. A corpus recorded before this
  change under a non-default `require_hitl_above_risk` pins behaviour the
  adopter's own runtime does not have.
- **An errored input's model calls are not counted.** The recording cassette
  lives inside `record_run` and dies with the exception, so `model_calls`
  under-reports exactly the runs that raised after paying for a call. Stated
  in the code and here rather than rounded up.

## Confidence

**High** on both reproductions and on the measurement: every command above
was run against a repo built for the reproduction, before and after, and the
proposed-and-gated result is read from the cycle's own output with the ledger
behind it.

**High** on the isolation seam surviving, because the mutation that breaks it
is the implementation this increment was most likely to have shipped.

**Medium** on the `--config` half. The wiring, the cassette and the count are
proved with a fake; the live path is not, and the difference between them is
exactly the thing K3 could not do. An adopter with a real `claude_code` login
is the first person who will find out.

**Low** on anything this says about a repo nobody wrote to be scanned. The
adoptee here is a fixture this programme authored, which is `READY_LOOP.md`
K5's whole point and no test closes it.
