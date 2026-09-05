# ADR 0174: A failed check is what the run did

## Status

Accepted. Worker **M4b** of `UPGRADE_LOOP.md` — the wire M4 (ADR 0157) and S1
(ADR 0155) hit from opposite sides on the same night, and which ADR 0157's
"Undone" section says nobody owned. Model: **`claude-opus-5[1m]`** (session
default). **3 live calls** (budget ≤ 8): one quota preflight, two bootstrap
recordings. Everything else offline. **No rubric dimension moves** — see "What
would earn a point".

## Context — the same gap, reported twice, from two directions

**M4's end** (ADR 0157). On a copy of the marlin clone, `aef loop bootstrap`
with an owner check the persona does not satisfy:

```
$ aef loop bootstrap agents.migrated.marlin_accela.graph \
    --corpus corpus --inputs inputs.json --memory memory.jsonl --config aef.yaml
recorded 2 scenario(s) in the train split
  passed  accela-preconditions
  passed  accela-missing-credentials
0 of 2 recorded run(s) failed. A corpus where everything passes cannot
demonstrate an improvement — every gate reading it has nothing to hold a
candidate to. …
  2 memory record(s) written to the durable store …
```

The memory file, both records:

```
accela-preconditions       -> success | no failure signals: 0 error(s) recorded, 0 tool call(s), none failed | failing_nodes= []
accela-missing-credentials -> success | no failure signals: 0 error(s) recorded, 0 tool call(s), none failed | failing_nodes= []
```

while the scorer, from the same run's cassette with no live call, says:

```
      0.0000  accela-missing-credentials
                check failed: working_memory.prompt_agent contains 'VERDICT:': got "**No. The Accela connector must remain `enabled: false` …"
      1.0000  accela-preconditions
```

and the cycle:

```
$ aef loop cycle --proposer rule_based_prompt --graph-id marlin-accela … --memory memory.jsonl
  ledger verified: 0 entr(ies)
  no admissible failure memory: no candidate this cycle
cycle verdict: no admissible failure memory: no candidate this cycle
```

**This reproduction was re-run offline for this ADR**, with `model_provider.impl:
command` pointed at a stub that replays the answers M4's live bootstrap
recorded — byte-identical model replies, zero quota. Same three outputs.

**S1's end** (ADR 0155). Six summary validation scenarios through the real
`retrieve → draft → reflect → consolidate` graph, one durable store across the
six runs, offline:

```
  sum-13-cider-press:   score=1.00 checks=4/4 errors=0
  sum-14-quarry-lake:   score=0.75 checks=3/4 errors=0
      FAILED CHECK: working_memory.summary contains 'swimming': got 'Swimming will be permitted at Ketley quarry lake this summer …
  sum-15-bookbinder:    score=1.00 checks=4/4 errors=0
  sum-16-cliff-path:    score=0.75 checks=3/4 errors=0
      FAILED CHECK: working_memory.summary contains 'landslip': got 'Landslip after heavy rain removed twenty metres of cliff, clo…
  sum-17-clockmaker:    score=1.00 checks=4/4 errors=0
  sum-18-heron-rookery: score=1.00 checks=4/4 errors=0

memory: 6 success record(s), 0 failure record(s)
  x1  success:summarise sum-13-cider-press in at most 35 words
  x1  success:summarise sum-14-quarry-lake in at most 40 words
  x1  success:summarise sum-15-bookbinder in at most 30 words
  x1  success:summarise sum-16-cliff-path in at most 35 words
  x1  success:summarise sum-17-clockmaker in at most 40 words
  x1  success:summarise sum-18-heron-rookery in at most 30 words

CONSOLIDATED: 0 knowledge entr(ies)
```

**Two of the six runs failed an owner check and every record says `success`.**
Six signatures, each occurring once, ADR 0110's two-run threshold unreachable
by construction — which is why arms (b) and (c) of the ACE four-arm were the
same arm and why 84 live calls compared one configuration against itself.

One cause: `make_reflect_node` writes `kind="failure"` iff `failure_signals(state)`
is non-empty, and that reads `state.errors` and `state.tool_results`. An owner
check is the task metric (ADR 0113), evaluated by the harness **after** the run.
The two never meet.

## The falsification, stated before the change was made

> If writing check-derived failure records makes `bootstrap`'s "never invents a
> failure" rule (ADR 0145) or `harvest`'s "records what the run did" rule (ADR
> 0060) false — i.e. if an owner check failing is not "what the run did" — stop
> and argue it here.

**It did not fire, and the argument is already in this repo's own code.**
`BootstrapInput`'s docstring draws the distinction verbatim: `expected` is *"a
judgement about what the run turned out to do"* and is refused by name;
`checks` are *"a specification of the task written before the run"* and are
carried through. The check is the owner's, written before anything ran. The
observed value is the run's. Evaluating one against the other is recording what
happened — it is the same act `score_scenario` already performs, and bootstrap
already performs `classify` and prints its answer. What changed is that the
answer now reaches memory instead of only stdout.

Two narrowings are owed, and are made here rather than left to be discovered:

- **ADR 0145's sentence "a graph with no reflect node writes nothing here and
  the sink stays empty"** is now narrower: a graph with no reflect node whose
  owner declared checks that failed leaves one record.
  `test_the_check_record_does_not_need_a_reflect_node` pins it. The rule that
  survives is the one that matters: with **no checks declared** there is no
  owner claim to have failed and bootstrap authors nothing at all
  (`test_a_graph_that_declares_no_checks_still_leaves_an_empty_sink`).
- **ADR 0060 is untouched.** Nothing here labels a scenario `expected:
  must_fail`; `Expected.UNSPECIFIED` is still written explicitly, and the
  tripwire suggestion is still a printed command the owner runs.

## Decision

### 1. `aef/harness/check_memory.py` — the producer

`check_failure_record(...) -> MemoryRecord | None`, plus a `write_...` form.
Given the owner's checks and the run's final state, it evaluates the checks
and, when any fail, runs the **real** `Critic`/`Judge` over that state with the
check failures supplied as evidence, returning one `kind="failure"` record in
exactly the content shape `make_reflect_node` writes — so the consolidator, the
retriever, `render_retrieved_context` and `RuleBasedPromptProposer` all read it
with no change.

It returns `None`, and each case has a reason rather than a convenience:

- **no checks** — a scenario that declares nothing about its answer makes no
  claim, so there is no owner metric to have failed;
- **every check held** — nothing happened;
- **the run recorded an error** — its own reflect node already wrote a failure
  record, and `score_scenario` itself *ignores the check fraction* when
  `final_state.errors` is non-empty. A record built from checks the scorer
  disregarded would be evidence of something nobody measured.

### 2. Design (a), the derived state — and why (b) was rejected by measurement

The `Critic` reads `state.errors`. Two ways to show it a check failure:

**(a) — shipped.** Apply a `StateDelta` carrying the failures to a **local
copy** of the final state and critique that. The copy never leaves the
function: the scenario, the trace, `classify`, `score_scenario` and the corpus
all see the state the run actually produced.

**(b) — rejected.** Inject the failures into the run's real `state.errors`
before reflection. Measured on `sum-14-quarry-lake`:

```
  as run:    task_completion=0.7500  checks=3/4
  injected:  task_completion=0.0000  checks=3/4
  classify().passed  as run=True  injected=False
```

Two independent corruptions. The score falls to zero *because* the checks
failed — `score_scenario` stops counting the check fraction the moment errors
exist — so the metric changes when you measure it, and the 3/4 that is the
actual task outcome is thrown away. And `classify` reports the run **raised**,
which it did not, so bootstrap's "FAILED" line and G2's outcome comparison
would both call a wrong answer a crash. (b) is not a stylistic alternative; it
is a metric that reports its own observation.

`Critique.grounded_in` therefore indexes the derived evidence rather than the
recorded state. That is a real provenance cost and it is paid, not hidden: the
same lines sit at the same indices in the record's `check_failures`, so every
citation resolves to something a reader of the record can see
(`test_grounded_in_resolves_against_the_recorded_check_failures`).

### 3. The signature, and what recurrence has to mean

`consolidate.default_signature` gains a branch, read **before** the
`failing_nodes` one: a failure record carrying `failed_checks` is signed
`failure:` + the check keys joined by `>`. A key is `check:<path>:<op>` — the
check's identity **without its expected value**.

Dropping the value is load-bearing twice.

- **Recurrence.** Measured, both corpora, shipped keying versus a key that also
  hashes the value:

  | corpus | shipped (`path:op`) | value-keyed |
  |---|---|---|
  | summary validation split (S1's) | **1 entry** | **0** |
  | marlin pilot (M4's) | **1 entry** | 1 |

  S1's split is the case the whole increment exists for: two runs failed
  `working_memory.summary contains …` with two *different* required terms, and
  under value-keyed signatures they are two singletons and the store stays
  empty — exactly the state ADR 0155 measured. The shipped keying makes ADR
  0110's two-run rule reachable on a corpus of distinct scenarios for the first
  time.
- **Leakage.** The signature is a prompt surface: it is `render_retrieved_context`'s
  `[label]` and `RuleBasedPromptProposer`'s `<!-- aef sig=… -->` marker. A
  value-keyed signature puts the answer in both.

The cost is stated rather than smoothed: two required-substring failures on one
field merge into one lesson. That is one behaviour — *this field keeps omitting
a required term* — and not the catch-all `consolidate.py` warns against, which
merges failures with nothing in common. `test_a_different_field_is_a_different_lesson`
pins the other side.

`failing_nodes` stays `[]` on these records because no node failed, and
`node_id` is the constant `"task_checks"`, which is the harness's scorer and is
documented as not being a graph node. Guessing a node would attribute the
observation to code that ran cleanly.

### 4. The rendering, and what an adversary still learns

ADR 0157's caveat is the sharpest sentence in this programme: *ACE's method and
teaching to the test are the same operation, and nothing in the loop
distinguishes them.* Its measured instance was a bullet reading
``contains 'VERDICT:'`` appended to a persona that then emitted `VERDICT:`.

So `_describe_failure` never reads `check.value`. It names the state path, the
operator in prose, and the **observed** value:

```
check failed: working_memory.prompt_agent does not contain a required substring
the owner declared; observed 406 words, 2836 chars: '**No. The Accela connector…'
```

The rule is uniform across all six operators, including the numeric ones where
the loss is real: a `max_words` failure reports *"is longer than the owner's
maximum; observed 47 words"* and never the cap. An agent learns the direction,
not the threshold. Two tests grep the entire record — and the rendered prompt —
for a planted literal.

**What it still leaks, stated because a redaction claim with no residual is a
claim nobody checked:**

1. **The state path.** An agent shown `working_memory.prompt_agent` learns
   which of its outputs is graded. That is arguably the point, and it is also
   information the persona did not previously have.
2. **The operator.** `contains` tells an agent that *some* required substring
   exists. Under an `equals` check on a small-domain field — a boolean, a
   status enum — "does not equal the value the owner declared" plus the
   observed value can leave exactly one alternative. **For a binary field this
   redaction leaks the answer completely**, and no rendering of "you were
   wrong" can avoid that.
3. **The observed value**, which is the agent's own output. For a `contains`
   failure it is by construction the text that does *not* contain the target —
   though on `sum-14` it contains `Swimming` where the check wanted `swimming`,
   so a sufficiently attentive reader could infer the target from a
   case-sensitivity defect. Honest, and worth knowing.
4. **The number of failed checks and how many held** (`checks_passed`,
   `checks_total`), which bounds the search.

The defensible claim is narrow: **a lesson can no longer be satisfied by
pasting a string out of it.** It is not that the check is unguessable.

### 5. One call site, and two refusals with reasons already in the codebase

The brief named three candidate sites. Only one is taken.

- **`bootstrap` — wired.** The owner's checks arrive in the inputs file, the
  run happens, `RunScopedMemory` mirrors the record into the durable sink the
  cycle reads. This is where the reproduction lives.
- **`score` / `run_scenario` — refused**, and not because the file belongs to
  another worker. `run_scenario`'s own docstring states the invariant:
  *"Memory is in-process and thrown away: the gate re-executes recorded
  scenarios to compare behaviour, and writing to the adopter's durable store
  would let a gate run mutate the evidence a later proposal is built from."*
  Wiring a producer there would let scoring a candidate manufacture the
  evidence for the next one.
- **`run --record-runs` / `harvest` — refused, because there is no check
  there.** `RecordedRun` has no checks field and `aef run` takes no checks
  argument: a production run carries no owner claim about its answer. Checks
  are a property of a *scenario*, and harvest promotes a run to a scenario with
  none. Inventing one at harvest time would be the system labelling its own
  runs, which is precisely ADR 0060. Closing this properly means letting an
  owner attach checks to a live objective, which is a CLI-surface decision and
  not a patch.

## Proof, end to end

### The marlin pilot — memory → entry → candidate

Offline (stub provider replaying M4's recorded replies), then live.

```
$ aef loop bootstrap … --inputs inputs.json --memory memory.jsonl --config aef.yaml
recorded 2 scenario(s) in the train split
  passed  accela-preconditions
  passed  accela-missing-credentials
0 of 2 recorded run(s) raised, and 1 FAILED AN OWNER CHECK — the task metric,
which fails without an error (ADR 0113).
  3 memory record(s) written to the durable store …
  1 of them is/are a check-derived FAILURE record: the owner's check, evaluated
  against what the run produced (ADR 0174). A signature recurring in two
  distinct runs becomes a lesson (ADR 0110).
```

The record:

```
accela-missing-credentials -> failure
   feedback: 1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
     working_memory.prompt_agent does not contain a required substring the owner
     declared; observed 406 words, 2836 chars: '**No. The Accela connector…
   failed_checks: ['check:working_memory.prompt_agent:contains'] | grounded_in: ['errors[0]']

$ grep -c VERDICT memory.jsonl
0
```

A second input failing the same check, then consolidation:

```
CONSOLIDATED 1 entr(ies)
  failure:check:working_memory.prompt_agent:contains | kind=failure | runs=2
    run_ids= ['accela-missing-credentials', 'accela-pinellas']
```

and the cycle that previously said `no admissible failure memory`:

```
  ledger verified: 4 entr(ies)
  proposed cycle-20260905T032809-prompt on local branch loop/cycle-… (proposer=rule_based_prompt)
  G0  pass   1 file(s), 4 line(s), all Zone A; 0 Python file(s) statically scanned …
  G1  pass   1 build command(s) succeeded against the merged workspace
  G4  pass   no owner-only safety metadata declared by the candidate
  G5  pass   0/3 accepted in the last 7d; drift 0.007/0.500 from the blessed baseline
  G2  fail   TrustBoundaryError: scratch destination …/workspace must be empty
  gated: reject
```

The bullet the loop wrote into the persona:

```diff
+## Lessons (aef)
+
+- <!-- aef sig=failure:check:working_memory.prompt_agent:contains runs=2 --> 1 error(s)
+  recorded; 0/0 tool call(s) failed. errors[0]: check failed: working_memory.prompt_agent
+  does not contain a required substring the owner declared; observed 406 words, 2836 chars:
+  '**No. The Accela connector…
```

Compare ADR 0157's bullet, whose text contained ``contains 'VERDICT:'``. The
candidate is now built from evidence a real deployment produces, and the lesson
is about the behaviour.

G2's failure there is ADR 0157's defect 1 — `G2Outcome` re-materialising the
workspace `G1Builds` already created — and **that defect was fixed on `main` by
M4c (ADR 0170) while this increment was running**. The run above is kept because
it is what this worker measured on its base; the merged result is below and it
is different.

#### Re-run after merging M4c (ADR 0170) — the gates now execute the candidate

Same repo, same evidence, same three scenarios, on the merged code:

```
  ledger verified: 1 entr(ies)
  proposed cycle-20260905T035600-prompt on local branch loop/cycle-… (proposer=rule_based_prompt)
  evidence: 7 corpus pass(es) (21 scenario execution(s)): 1 candidate + 1 incumbent
            + 5 random control(s); 3/3 gated scenario(s) recorded from graph 'marlin-accela'
  G0 pass · G1 pass · G4 pass · G5 pass (drift 0.007/0.500)
  G2  fail   3 previously-passing scenario(s) no longer pass (zero tolerance)
  gated: reject
```

**A control cohort was built for a prose candidate and 21 scenario executions
ran.** Both of ADR 0157's load-bearing gate defects are gone, so the whole path
from a failed owner check to a gate that actually executes the candidate is
open.

The rejection, however, is **the artifact UPGRADE_LOOP's own rule names** —
*"never let a cassette miss score a changed prompt as 0 and call that a
rejection"* — and it was confirmed rather than assumed, at zero live cost:

```
INCUMBENT (unchanged persona):  3 cassette hit(s), 0 miss(es)  mean 0.3333
CANDIDATE (bullet appended):    0 cassette hit(s), 3 miss(es)  mean 0.0000
```

Appending one bullet changes the request, so every recorded call misses, every
node errors, and every previously-terminating scenario "no longer passes". The
correct invocation is `--cassette-miss live`, which is 21 scenario executions
against a live provider — **beyond this worker's remaining budget of 5 calls**,
so it was not run and no live gate verdict is claimed. What this increment
proves is that the evidence, the candidate and the gate execution now exist;
what a live gate pass would cost is stated instead of guessed.

### Live — 3 calls

Quota preflight (ADR 0150's corrected argv): `is_error: False`, `result: 'OK'`,
`usage.input_tokens: 2`, answering model `claude-opus-5[1m]` (read from
`modelUsage`'s token counts, not its first key — ADR 0155's provenance defect,
fixed on `main` by ADR 0154). **1 call.**

Then the same sequence against `model_provider.impl: claude_code` on a fresh
copy, empty corpus, two objectives, **2 calls**:

```
recorded 2 scenario(s) in the train split
  passed  live-clearwater
  passed  live-pinellas
0 of 2 recorded run(s) raised, and 2 FAILED AN OWNER CHECK …
  4 memory record(s) written to the durable store …
  2 of them is/are a check-derived FAILURE record …

CONSOLIDATED 1
  failure:check:working_memory.prompt_agent:contains runs=2 ['live-clearwater', 'live-pinellas']
   1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
   working_memory.prompt_agent does not contain a required substring the owner
   declared; observed 555 words, 3568 chars: '## Determination: **NO — `…

$ grep -c VERDICT live_memory.jsonl
0

  ledger verified: 1 entr(ies)
  proposed cycle-20260905T033844-prompt … (proposer=rule_based_prompt)
  G0 pass · G1 pass · G4 pass · G5 pass (drift 0.007/0.500) · G2 fail (TrustBoundaryError)
```

Two live model calls, two independent objectives, two runs failing one check,
one lesson. Nothing was synthesised.

### S1's split — six scenarios → one entry → the prompt

The same six-scenario pass, with the producer:

```
  sum-14-quarry-lake: score=0.75 … FAILED CHECK … -> check-failure record 351d1a7e written
  sum-16-cliff-path:  score=0.75 … FAILED CHECK … -> check-failure record 3c44ac80 written

memory: 6 success record(s), 2 failure record(s)
  x2  failure:check:working_memory.summary:contains
  x1  success:summarise sum-13-cider-press in at most 35 words
  … (five more singleton successes)

CONSOLIDATED: 1 knowledge entr(ies)
  failure:check:working_memory.summary:contains  kind=failure runs=2
```

Then the next run — knowledge rebuilt from the durable memory the way
`aef run --memory` does it, `retrieve → draft`, prompt captured:

```
### WITH the producer
rebuilt knowledge: 1 entr(ies)
retrieved_context chunks: 9
prompt contains the lesson header: True
   Lessons from this agent's earlier runs (most relevant first):
   - [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
   - [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed
   - [failure:check:working_memory.summary:contains] 1 error(s) recorded; 0/0 tool call(s)
     failed. errors[0]: check failed: working_memory.summary does not contain a required
     substring the owner declared; observed 35 words, …
   - [success] no failure signals: …
   - [success] no failure signals: …

### WITHOUT the producer
rebuilt knowledge: 0 entr(ies)
retrieved_context chunks: 6
   Lessons from this agent's earlier runs (most relevant first):
   - [success] no failure signals: 0 error(s) recorded, 0 tool call(s), none failed   (×5)
```

S1's wiring finally has something to carry. Before this, every bullet the
retriever could offer said *no failure signals*.

**What is NOT claimed: that this makes the summary agent better.** No task
score was measured here. ADR 0155's four arms would have to be re-run to say
anything about that, and the honest statement of what they would need is
below.

### Re-run on S3b's corpus (ADR 0171), merged from `main` mid-increment

The same rig over the **17** summary validation scenarios S3b's content
negatives added, before the producer:

```
17 summary validation scenario(s)
  … sum-30-ganister-tarn: score=0.80 checks=4/5 … FAILED CHECK: working_memory.summary max_words 28
  … sum-33-cotterdale-bus: score=0.80 … sum-35-priory-gatehouse: score=0.80 … sum-36-larkfield-quarry: score=0.80
memory: 17 success record(s), 0 failure record(s)      (seventeen unique signatures)
CONSOLIDATED: 0 knowledge entr(ies)
```

**Four content negatives, and every record still says `success`.** With the
producer: 4 failure records, **one** signature
`failure:check:working_memory.summary:max_words`, **1 knowledge entry across 4
distinct runs**. This is the recurring-failure evidence ADR 0155 said the layer
needed, from a corpus this worker did not build.

Two honest observations from that run, neither of them flattering:

1. **The cap is in the objective anyway.** Every one of these scenarios asks
   *"summarise … in at most 28 words"*, so redacting `max_words`' value from
   the lesson buys nothing **on this corpus**: the agent is told the number in
   the task. The redaction is still the right default — a `contains` marker is
   not in the objective, and the marlin pilot's `VERDICT:` was not — but the
   claim "the lesson does not leak the cap" is worth strictly less here than it
   sounds. The record's own text is clean (`is longer than the owner's maximum;
   observed 41 words`); the objective beside it is not.
2. **The lesson is retrieved and does not reach the model.** On the
   six-scenario split it renders into the draft prompt (above). On the
   seventeen-scenario one it is **chunk 14 of 24, score 0.125**, and
   `render_retrieved_context`'s `max_items=5` shows five `no failure signals`
   successes instead. That is ADR 0110's own I4 finding — near-duplicate
   records crowding out a distinct lesson as experience accumulates —
   reappearing at the render cap rather than the token budget. See the defects
   below; the knob exists and is off.

## Regression tests and mutations

+50 tests, none removed — 2262 → 2305 on the pre-merge base, and 2402 → 2452
after merging `origin/main` mid-increment (which brought S3b's corpus and four
other workers' tests). `tests/harness/test_check_memory.py` is new (26);
`test_bootstrap.py`, `test_consolidate.py`, `test_task_checks.py` and the two
CLI bootstrap tests gain the rest.

Six mutations, six kills. Every in-repo restore was byte-verified against a
`shasum -a 256` taken before the edit (`git checkout --` was never used; the
tree carried uncommitted work throughout).

| mutation | what failed |
|---|---|
| **drop the producer from `bootstrap`** — the whole pilot sequence re-run | `no admissible failure memory: no candidate this cycle`, and bootstrap back to *"0 of 2 recorded run(s) failed. A corpus where everything passes…"* |
| leak `check.value` into the lesson | 8, incl. both anti-leak tests and 3 of the per-operator sweep |
| key the signature on the value as well | 12, incl. the two-run-rule test and the merge test |
| write a check record even when the run raised | `test_a_run_that_errored_writes_nothing` |
| inject the failures into the run's real state | `test_the_runs_state_is_not_mutated`, `test_a_clean_run_that_fails_an_owner_check_leaves_failure_memory` |
| sign a check-derived failure by its (empty) failing nodes | 5, incl. both consolidate signature tests and the rendered-prompt test |

## Green bar

`pytest -q`: **2482 passed, 6 skipped**; collected **2438 → 2488 (+50, none
removed)** after two `origin/main` merges (2262 → 2305 on the pre-merge base).
`mypy aef examples`: 134 files, clean. `ruff check .`: clean. `ruff format
--check aef tests examples`: 270 files, clean. S1's golden
(`tests/agents/test_summary_prompt.py` — the `agents/summary` prompt
byte-identical with nothing retrieved) is green; `agents/summary/graph.py` was
not touched.

## What would earn a rubric point, and what S1 would need

Nothing is claimed here. Dimension 2 is where this belongs and it does not move,
because **no task score was measured**: the artifact is a capability that was
absent and is now present, on the rubric's own rule that a score moves on an
artifact showing improvement.

**S1's four arms are now runnable and were not before.** What they need is a
corpus whose failures RECUR — which is exactly what ADR 0155's consequences
section asked for and what this producer makes possible on a corpus of distinct
scenarios, since the recurrence is now in the *check*, not in the objective. On
today's summary split that is one lesson from two runs; a corpus built to
exercise the layer would give several. **S3b is building that corpus tonight**,
and re-running (a)/(b)/(c)/(d) against it is the measurement that could move
dimension 2 — not this ADR.

The other thing standing between a prompt candidate and an *accept* is ADR
0157's defects 1 and 2, neither of which is closed here.

## Defects found outside this worker's files

0. **`knowledge_boost = 0.0` hides the only lesson there is, and it now has a
   counter-example.** ADR 0110 swept 0 / 0.5 / 1 / 3 and recorded that it
   "changed no coverage number anywhere", so the benefit was consolidation and
   not ranking. On S3b's 17-scenario split, over the memory this producer
   writes, the single check-derived entry ranks:

   | `knowledge_boost` | rank of the lesson | survives `render_retrieved_context(max_items=5)` |
   |---|---|---|
   | **0.0 (default)** | **14 of 24** | **no** |
   | 0.5 | 3 of 24 | yes |
   | 1.0 | 3 of 24 | yes |
   | 3.0 | 0 of 24 | yes |

   Seventeen near-identical `no failure signals` successes outrank one lesson.
   The default is not re-argued here — one corpus is not a sweep, and
   `aef/services/context/` is not this worker's file — but ADR 0110's sweep was
   run on a corpus that could not produce this shape, and this is the first
   corpus that can. Reported for whoever re-runs S1's arms.

1. **`aef loop cycle` needs `--graph-id` or it silently drops all the
   evidence.** Without it the run reports `2 record(s) dropped as another
   graph's scenario; no admissible failure record for this graph` — correct
   behaviour, unhelpfully similar to having no evidence, and the graph id is
   available from the corpus the same command already loaded.
   (`aef/cli/loop.py`, `aef/harness/proposer.py`.)
2. **ADR 0157's defects 1 and 2 reproduced unchanged on this worker's base**
   (G2 raising `TrustBoundaryError` on every non-Python candidate that clears
   G1; G3 with no null hypothesis for one) — **and are FIXED on `main` by M4c,
   ADR 0170**, merged mid-increment. Re-run there, the gates build a prose
   control cohort and execute 21 scenarios. Reported as observed, then closed
   by another worker; no longer open.
3. **`aef loop score` takes `module:factory`, `aef loop bootstrap` takes
   `module`.** The same graph is named two ways by two subcommands of one
   command; `bootstrap`'s form passed to `score` gives
   `error: entrypoint must be 'module:factory'`. (`aef/cli/loop.py`.)
4. **A copied corpus directory carries a stale `manifest.json`** and the next
   cycle refuses with `corpus shrank: 3 previously-admitted scenario(s) are
   gone`. The refusal is right; there is no command to reconcile a manifest
   with the scenarios actually present, so the only fix is hand-editing JSON.

## Consequences

- The loop's silence on a prompt-file repo had two causes (ADR 0157). M4 fixed
  the proposer; this fixes the evidence. A migrated `.md` agent that answers
  and gets the owner's task metric wrong now leaves failure memory, and two
  such runs make a lesson.
- **`aef loop bootstrap`'s report no longer says "everything passed" when the
  owner's metric failed.** S3b reproduced the old behaviour on their own batch:
  eight inputs, three content negatives the owner's checks caught, and
  `0 of 8 recorded run(s) failed. A corpus where everything passes cannot
  demonstrate an improvement` printed underneath them — the count was
  `classify`'s alone while the checks sat in the same inputs file. It is now
  one count with the same definition of failure the memory producer uses, split
  into its two halves on one line (`2 of 3 recorded run(s) FAILED: 1 raised or
  ended with a failed plan, 1 failed an owner check`), with per-scenario labels
  `FAILED` / `WRONG` / `passed` — because a crash and a wrong answer need
  different fixes and one label for both hides which an owner has. The
  "everything passes" advisory is a claim about the corpus and is now silent
  whenever it would be false.
- A lesson computed from a check no longer contains the check. It contains
  enough to identify which output is graded and how — see the four numbered
  leaks — and that residual is the honest price of feedback at all.
- `CheckReport` now carries the failed `TaskCheck`s beside the prose lines. The
  prose names `check.value` and is right for an owner's report; the structured
  form is what a producer of memory reads, so the two audiences are served
  without either parsing the other's output.
