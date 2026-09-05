# ADR 0191: A mode string is not a fact, a flag that bound one proposer of three, and the nightly that still could not propose

## Status

Accepted. Fix wave **L3** of the upgrade loop — the four findings of the final
seam hunt that were left open, plus the four the orchestrator closed. **Zero
live model calls.** Every measurement here comes from a stub provider —
`model_provider.impl: command` pointed at a shell script that exits non-zero on
chosen invocations, a real subprocess through the real `CommandProvider`, the
same substitution ADR 0181 and ADR 0185 used — or from running this repo's own
CLI against this repo's own corpus. **No gate's verdict logic is touched**, and
`tests/harness/test_promotion_safety.py` is byte-for-byte what it was. **No
rubric dimension moves.**

Each of the four was reproduced by RUNNING it before a line was edited, and
each fix was mutated and watched to fail its own control.

## Context

The final seam hunt reported eight findings against the seams the K- and
L-waves left. Four were closed by the orchestrator before this wave started and
are recorded at the bottom for the audit trail. The four here are the ones with
code behind them, and three of the four share one shape: **a fact was inferred
from a request rather than carried from what happened.**

- F1 inferred "the model was reached" from the string `"live"`.
- F2 inferred "this proposer restricts its evidence" from the fact that *a*
  proposer did.
- F6 inferred "there is nothing to propose" from "the file I guessed at is not
  there".

## F1 (HIGH) — `--cassette-miss live` with no `--config`, and every scenario becomes a dead call

### Reproduced

`_live_provider_from_base_ref` (ADR 0181) read the opt-in *after* the config:

```python
if config.cassette_miss != "live":
    return None
agent_config = _agent_config_from_base_ref(config)
if agent_config is None:
    return None                     # <- the hole
if not agent_config.gates.live_model_calls:
    raise LiveGatingDisabledError(...)
```

So `--cassette-miss live` with no `--config` was not refused; it ran with no
provider at all. Reproduced with `LoopConfig(config_path=None,
cassette_miss="live")` and `run_corpus_isolated(..., live_provider=None)` over
four scenarios whose recordings were stripped of `model_calls`:

```
config_path=None, cassette_miss='live':
  _live_provider_from_base_ref -> None   (NO refusal raised)
  ledger will record live_model_calls=False

run_corpus_isolated(cassette_miss='live', live_provider=None):
  s1: score=0.0000 dead_call=True retried=True
        failure=NodeEvaluationError: ModelProviderError: cassette miss (key
        6a9b6ea9c515, ...) and no live provider to fall through to:
        on_miss='live' needs an inner ModelProvider (model_provider.impl in
        aef.yaml, e.g. claude_code — ADR 0112)
  s2: score=0.0000 dead_call=True retried=True
  s3: score=0.0000 dead_call=True retried=True
  s4: score=0.0000 dead_call=True retried=True
```

Every scenario in the corpus. The failure string names a `ModelProviderError`,
so ADR 0185's `is_dead_call` — whose only live condition was `cassette_miss ==
"live"` — classified all four as deaths. Each was retried, so **the corpus ran
twice**. And each was then handed to G3 as *excluded* rather than scored. On
the identical per-scenario numbers:

```
counted  (ADR 0123, the replayed rule): G3 FAIL — 1 previously-passing
    scenario(s) now score below 0.5 (zero tolerance, regardless of the aggregate)
excluded (ADR 0185, live+no-provider): G3 PASS — candidate mean 1 beats the
    control cohort's p95 of 0.9429
```

Below 25% dead the candidate is judged on what survived; above the floor G3
refuses saying "the model was not answering", when the truth is "you omitted
`--config`". Throughout, the `gated` ledger event recorded
`live_model_calls: false` — the audit trail's own answer to "did this run under
the operator's login?" was *no*, and nothing read it.

### The rule

**(a) A live run with no config is refused, by name, before any scenario
runs.** `_live_provider_from_base_ref` raises `LiveGatingWithoutConfigError`
where it used to `return None`. In the harness rather than only in the CLI, so
`gate`, `cycle` and `run` all get it as library entry points, and the four
commands get it a second time at the surface an operator types at
(`_require_config_for_live_cassette`, wired into `gate`/`score`/`cycle`/`run`).

The refusal, verbatim:

```
--cassette-miss live needs a --config: there is no aef.yaml for the gate to
read model_provider from at 'main', so no provider can be built and EVERY model
call the corpus makes would miss with 'no live provider to fall through to'.
Those misses name a ModelProviderError, so each one classifies as a dead call,
is retried once, and is then EXCLUDED from G3 — a run in which the model was
never reached would read as a run the model answered. Pass --config <path to
aef.yaml, relative to the repository root> with gates.live_model_calls: true,
or drop --cassette-miss live and score from the recorded cassettes.
```

and at the CLI:

```
error: `cycle --cassette-miss live` needs --config. The provider a live
cassette miss falls through to is read from that file's model_provider block
(at the base ref, so a candidate cannot choose its own), and there is no other
source for it. With no --config there is no provider, every model call misses
with 'no live provider to fall through to', and those misses are excluded from
the comparison as dead calls — so a run in which the model was never reached
reports as one the model answered (ADR 0191). Pass --config <path to aef.yaml,
relative to the repository root> with gates.live_model_calls: true, or drop
--cassette-miss live and score from the recorded cassettes.
```

`LiveGatingWithoutConfigError` is deliberately **not** a `PolicyConfigError`,
unlike its sibling `LiveGatingDisabledError`. That class means "the rules could
not be read", which every command reports as `EXIT_REJECTED` — a verdict on a
candidate — and reporting a missing flag as a rejection is what makes CI retry
it forever (ADR 0075, ADR 0167 §6). This is `EXIT_ERROR`.

**(b) `is_dead_call` requires a provider to have been PRESENT.** A third
condition, and the caller passes it as a fact about the run it just performed
rather than letting the function re-derive it from the mode it was asked for:

```python
def is_dead_call(failure, *, cassette_miss: str, live_provider_present: bool) -> bool:
    if failure is None or cassette_miss != "live" or not live_provider_present:
        return False
```

A miss with nothing behind it is a **miss**: scored 0, counted, never excused,
never retried. Both scoring paths pass `live_provider is not None` from the
same place they build the cassette, so the two constructions cannot drift
(ADR 0091's rule).

**(c) K1's control test was rewritten**, and this is the part worth reading.
`test_the_same_miss_fails_when_no_provider_crosses` drove *exactly* the state
F1 lives in — `cassette_miss="live"`, `live_provider=None` — and asserted
`results["miss"].outcome.error_count == 1`. That was true before ADR 0185 and
stayed true after it, while the same scenario silently became `dead_call=True
retried=True` and left G3's comparison. A control that constructs the failing
state and then asserts a property the failure cannot move is a control in name
only. It now asserts the classification, the score, the retry and the failure
text.

### Verification

After the fix, the same script:

```
config_path=None, cassette_miss='live':
  raised LiveGatingWithoutConfigError: --cassette-miss live needs a --config: ...
  _live_model_calls also refuses: LiveGatingWithoutConfigError

run_corpus_isolated(cassette_miss='live', live_provider=None):
  s1: score=0.0000 dead_call=False retried=False
  s2: score=0.0000 dead_call=False retried=False
  s3: score=0.0000 dead_call=False retried=False
  s4: score=0.0000 dead_call=False retried=False
```

Tests: `test_live_with_no_config_is_refused_by_name_before_anything_runs`,
`test_the_cli_refuses_a_live_cycle_with_no_config_as_an_ERROR`,
`test_the_same_miss_fails_when_no_provider_crosses` (rewritten),
`test_a_live_miss_with_NO_PROVIDER_is_not_a_dead_call`.

**Mutations.** Restoring the early `return None` → the two refusal tests fail
(`DID NOT RAISE LiveGatingWithoutConfigError`). Dropping the
`live_provider_present` condition → `test_a_live_miss_with_NO_PROVIDER_is_not_a_dead_call`
**and** the rewritten K1 control both fail. Both files restored
byte-identically, shasum-verified.

## F2 (HIGH) — `--graph-id` restricted the evidence for one proposer of three

### Reproduced

`--graph-id`'s help text promises *"the graph whose recorded scenarios are this
loop's evidence"*. The filter that kept that promise lived inside
`RuleBasedPromptProposer._admissible`, and `_build_proposer` constructs the
DEFAULT `RuleBasedProposer()` with no graph id at all —
`MemoryEvidence.from_store(memory, config.corpus)` filtered validation and
holdout run ids and nothing else. On this repo's own two-graph corpus
(`demo_agent` + `summary_agent`), with three failure records whose `run_id`s
are `summary_agent` **train** scenarios:

```
$ aef loop cycle --repo . --state ... --workdir ... --graph-id demo_agent \
    --agent-path agents/demo/graph.py --corpus corpus --memory ...
  ledger verified: 0 entr(ies)
  proposed cycle-20260905T085525-0 on local branch loop/cycle-20260905T085525-0
    (never pushed; proposer=rule_based)
```

and the `gated` ledger event:

```json
"grounded_in": ["m3 (memory): the summary invented a number",
                "m2 (memory): the summary dropped the ferry name",
                "m1 (memory): the summary dropped the reservoir date"]
```

Three `summary_agent` records grounding a change to `agents/demo/graph.py`,
with the flag on the command line.

### The rule

**The evidence a proposer may see is a property of the EVIDENCE, not of which
proposer happens to read it.** `MemoryEvidence.from_store` takes `graph_id` and
applies the filter once, where the evidence is assembled, so every proposer
goes through it — one filter, not one per proposer. `cycle()` passes
`config.evidence_id` (not `graph_id`: ADR 0182's two namespaces, and this is
the `Graph.id` one). Records dropped this way are reported on their own field,
`MemoryEvidence.foreign`, separate from `excluded`, because they are two
different operator actions: one is a corpus that mixes graphs with a
`--graph-id` naming one of them, the other is a leak of the set the proposer
must not see.

The rule inside the filter is `RuleBasedPromptProposer`'s own, unchanged and
deliberately narrow: **deny what is KNOWN to belong to another graph's
scenario, and admit a `run_id` the corpus has never heard of** — a production
run has an arbitrary id that appears in no scenario, and production experience
is exactly what this exists to learn from. Widening it to an allowlist would
switch the loop off for every adopter whose runs are not corpus replays, and a
test says so.

`RuleBasedPromptProposer` keeps its own copy, and that is not a second filter
in the sense F2 objected to: it applies to a `MemoryEvidence` a caller built by
hand, it is idempotent against already-filtered records, and the authoritative
application is now upstream of every proposer.

### Verification

```
$ aef loop cycle ... --graph-id demo_agent --agent-path agents/demo/graph.py ...
  3 memory record(s) excluded as belonging to a graph other than 'demo_agent'
  no admissible failure memory: all 3 record(s) came from scenarios of another
    graph, not 'demo_agent': no candidate this cycle
EXIT=0
```

The verdict line, not a note above it, because `cmd_cycle` journals `lines[-1]`
(ADR 0165) and an operator told only "no admissible failure memory" will go and
record more failures when the remedy is to point `--graph-id` at the graph
those runs came from.

Tests, in `tests/harness/test_evidence_is_one_graphs.py`:
`test_the_default_proposer_no_longer_grounds_in_another_graphs_records` (the
hunt's own reproduction),
`test_the_same_records_under_their_OWN_graph_id_are_admitted` (the positive
case — the filter must be a filter, not a wall, and the DEFAULT proposer turns
the admitted evidence into a proposal),
`test_a_run_id_the_corpus_has_never_heard_of_is_still_admitted`,
`test_the_filter_is_on_the_evidence_and_not_on_any_proposer`.

**Mutation.** Replacing `_foreign_run_ids(corpus, graph_id)` with an empty set
→ the reproduction and the positive test both fail, the first because the
default proposer grounds in another graph's records again. Restored
byte-identically, shasum-verified.

## F6 (MEDIUM) — this repo's own nightly cycle still could not propose, and exited 0

### Reproduced

ADR 0188 gave the nightly cycle `--graph-id demo_agent`. One line down, with a
non-empty memory file:

```
$ aef loop cycle --repo . --state ... --workdir ... --graph-id demo_agent \
    --corpus corpus --memory <two failure records>
  ledger verified: 0 entr(ies)
  no agent source at agents/migrated/graph.py in main
  (the ref exists; the file is not in it): no candidate
cycle verdict: no agent source at agents/migrated/graph.py in main (the ref
exists; the file is not in it): no candidate
EXIT=0
```

`DEFAULT_AGENT_PATH` is `agents/migrated/graph.py` — what `aef migrate` writes
into an ADOPTING repo, which is exactly right and is ADR 0149's whole point.
aef-core has `agents/demo/` and `agents/summary/`. The workflow passed no
`--agent-path`. So the loop could not propose, and the workflow's own case
statement reads exit 0 as *"escalated, or nothing to propose — read the verdict
line"*, the healthy answer.

ADR 0189 got the **sentence** right — it distinguishes an absent file from an
absent ref, which is F-M8-1's fix — and left the **disposition** wrong.

### The rule

**(a)** The workflow passes `--agent-path agents/demo/graph.py`, pinned in
`tests/harness/test_workflows.py` beside ADR 0188's `--graph-id` pin. The pin
derives the path from the workflow and asserts the named file exists in the
repo, so it cannot outlive the file it names.

**(b)** A ref that exists without the file in it is a **configuration error**,
`EXIT_ERROR`, raised from `cycle()` so every caller gets it. The message names
the path, the ref, which of the two questions failed, and what *is* there —
read from the ref with `git ls-tree`, never from the working tree, because the
candidate is built from the ref:

```
error (AgentSourceMissingError): no agent source at agents/migrated/graph.py in
main (the ref exists; the file is not in it), so there is nothing for the
proposer to edit. This is the invocation, not a verdict: pass --agent-path
naming a graph that exists at main. Python files under agents/ at main:
agents/demo/__init__.py, agents/demo/graph.py, agents/summary/__init__.py,
agents/summary/graph.py.
```

`EXIT=3`. `>= 2` is what CI fails on, so the state that produced F6 now fails
the job instead of showing a green tick.

`AgentSourceMissingError` is not a `PolicyConfigError`, for
`LiveGatingWithoutConfigError`'s reason: the rules were read fine, the
invocation points at nothing.

### Verification

Tests, in `tests/cli/test_cycle_refuses_a_missing_agent_source.py`:
`test_the_default_path_missing_from_the_ref_refuses_instead_of_exiting_zero`,
`test_the_cli_reports_it_as_EXIT_ERROR`,
`test_naming_a_path_that_IS_in_the_ref_proposes` (the control — a refusal that
fired either way would have replaced a silent no-op with a loud one), and
`test_this_repos_nightly_cycle_names_the_graph_file_it_may_edit`.

**Mutations.** Restoring the `no candidate` return → the two refusal tests
fail. Removing `--agent-path` from the workflow → the workflow pin fails. Both
files restored byte-identically, shasum-verified.

## F7 (LOW-MED) — the retry-cost bound is per call, and it is enforced per scenario

### Reproduced

ADR 0185's consequences say *"the retry costs at most one extra call per dead
scenario"*. It does not. The retry re-runs the whole SCENARIO, and a scenario
costs as many calls as its graph makes. Measured on a two-call graph
(`draft:` then `revise:`) whose stub provider exits 7 on its fourth
invocation — the second call of the second scenario:

```
s1: score=1.0 dead=False retried=False
s2: score=1.0 dead=False retried=True
total provider invocations: 6
calls a clean 2-scenario run would have cost: 4
```

Two extra calls for one dead scenario, not one.

### The correction

This is an **erratum on the statement**, not a change to the mechanism. The
retry is still bounded, which is what it needed to be; the number written down
was wrong. The true bound is **one extra scenario EXECUTION — up to K calls for
a K-call scenario, and at worst one extra full corpus pass.** Stated in calls
because calls are what the quota is denominated in. The docstring at the
enforcement site in `isolated_suite.run_corpus_isolated` now says so with this
measurement in it, and ADR 0185's consequence carries an erratum.

Test: `test_the_retry_costs_one_extra_SCENARIO_not_one_extra_CALL`, asserting
6 and asserting `4 + 2` — the second is the control that keeps the claim honest
in the other direction, because "the bound is wrong" must not become "there is
no bound".

**Not done, and why.** F7 also asked that "the evidence line reports calls, not
scenarios, when it can". It cannot, here: G3's evidence line is built from
`CohortVerdict.retried_scenarios`, and no call count reaches it — the isolated
path's `ScenarioResult` carries none, and the worker's `cassette` block
(`hits`/`misses`) stops at the worker protocol. Threading it through would
change `ScenarioResult`, `VariantRun`, `CohortVerdict` and G3's own reporting,
and the gates' verdict logic is out of this wave's scope by instruction. The
statement is corrected where it is made; the line still counts scenarios, and
this paragraph is the record that it does.

## Closed by the orchestrator, recorded for the audit trail

- **F3** — S1c's `+2` is **withdrawn**: its seed no longer reproduces after
  ADR 0186 moved the corpus to one model.
- **F4** — the score path's producer now stamps execution time.
- **F5** — `score --memory`'s help text no longer overclaims.
- **F8** — the rubric heading is relabelled.

## Errata on earlier ADRs

- **ADR 0181** (K1) — `_live_provider_from_base_ref` returned `None` for a
  missing config *before* reading the opt-in, so `--cassette-miss live` with no
  `--config` was not refused; it ran with no provider and every call failed. K1
  refused the *opted-out* case by name and left the *unconfigured* case silent.
  Its control test `test_the_same_miss_fails_when_no_provider_crosses` drove
  that exact state and asserted a property the defect could not move.
- **ADR 0185** (S2b) — two corrections. `is_dead_call`'s second condition was
  gated on the mode string alone, which is a request rather than a fact: with
  no provider present a cassette miss was classified as a death, retried, and
  excluded. And "the retry costs at most one extra call per dead scenario" is
  wrong; the bound is one extra scenario execution, up to K calls for a K-call
  scenario. Neither correction lowers a threshold: the p95 rule, the cohort
  size, the zero-tolerance rule, the cost ratio and the refusal floor are
  byte-for-byte what they were.
- **ADR 0176 / 0182** (I1 / K3) — the `graph_id` / `evidence_graph_id` split is
  right and stands, but `--graph-id` bound the evidence for
  `RuleBasedPromptProposer` only. The default `RuleBasedProposer` was
  constructed with no graph id and `MemoryEvidence.from_store` filtered only
  validation and holdout ids, so on a two-graph corpus the flag's promise held
  for one proposer of three.
- **ADR 0188** (J0b) — giving this repo's nightly cycle `--graph-id demo_agent`
  was necessary and not sufficient. One line down, `--agent-path` defaulted to
  an adopter's layout, so with a non-empty memory the cycle still could not
  propose and still exited 0.

## Consequences

- `--cassette-miss live` is now refused in two more circumstances, and both
  refusals are `EXIT_ERROR`. An operator who was relying on live mode running
  provider-less (there is no reason to) sees a message instead of a run.
- `is_dead_call` has a new required keyword. Every caller in `aef/` passes it
  from where the cassette is built; a third-party caller gets a `TypeError`
  rather than a silently wrong default, which is the right way round.
- `MemoryEvidence` has a new `foreign` field and `from_store` a new `graph_id`
  keyword, both defaulting to the previous behaviour, so a caller that passes
  neither is unchanged.
- `aef loop cycle` gains an exit-3 path it did not have. A scheduled loop
  pointed at a path that is not there now fails its job. That is the point.
- The gates' verdict logic is untouched, and
  `tests/harness/test_promotion_safety.py` is unchanged.
