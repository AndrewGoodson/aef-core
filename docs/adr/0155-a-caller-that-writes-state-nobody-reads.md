# ADR 0155: A caller that writes state nobody reads

## Status

Accepted. Increment S1 of `UPGRADE_LOOP.md` (= I12 of `TO_90_LOOP.md`), the
ACE four-arm measurement on the task metric.

**Result: dimension 2 does not move. 17/20 stands.** The falsification
stated before the run — *if (c) ≤ (b) the knowledge layer buys nothing on a
task metric* — **fired**. ADR 0110's coverage result is demoted to a proxy
that this measurement did not show predicts task outcome, and the reason is
sharper than "the layer did not help": on this corpus **the layer never
engaged at all**.

**Model: `claude-opus-5[1m]` (canonical `claude-opus-5`), the session
default.** `claude-fable-5-1`'s quota is exhausted and the owner authorised
Opus; every arm here was re-measured on Opus and none of I3's, I10's or
I11's Fable numbers are reused. `--model` is deliberately **omitted** from
the argv so the session default answers; the answering model was read back
from the CLI's `modelUsage`, not assumed — see "A provenance defect found on
the way" below, because the provider's own answer to that question is wrong.

## Context: what the increment was asked to measure

Four arms over the summary corpus's validation split (6 scenarios, all
`graph_id == "summary_agent"`), fresh stores per arm so none inherits
another's experience, scored by the same `score_scenario` the gates use:

- **(a)** no retrieve node — the control
- **(b)** retrieve, raw records only — memory without the wiki
- **(c)** retrieve + knowledge layer — ADR 0110's contribution
- **(d)** (c) + `reflection.impl: llm` — ADR 0115's critic/judge

## The reproduction, first: the arms were the same experiment four times

Run before spending any quota, offline, with a provider that records every
prompt instead of sending it
(`docs/research/i12/repro_arms_identical.py`):

| arm | prompts | SHA-256 over every rendered prompt | chunks retrieved per scenario |
|---|---|---|---|
| a | 6 | `17530200d8e8f454…3cdc7ac0` | 0,0,0,0,0,0 |
| b | 6 | `17530200d8e8f454…3cdc7ac0` | 0,1,2,3,4,5 |
| c | 6 | `17530200d8e8f454…3cdc7ac0` | 0,1,2,3,4,5 |
| d | 6 | `17530200d8e8f454…3cdc7ac0` | 0,1,2,3,4,5 |

**One hash.** Retrieval was happening — chunk counts climb as experience
accumulates — and not one retrieved byte reached a model.
`agents/summary/graph.py::draft_node` built its prompt from
`working_memory` alone. The only reader of `state.retrieved_context`
anywhere in `aef/` was `retrieved_signatures()`, which computes the
helpful/harmful tally and shows a model nothing.

So ADR 0118's headline — *"the retriever finally has a caller"* — was true
and insufficient. A caller that writes state nobody reads is a caller in
name. Running the four arms as briefed would have spent 84 live calls
comparing one configuration against itself. An erratum is appended to ADR
0118.

## Decision

1. **`render_retrieved_context(state, *, max_items=5) -> str`** in
   `aef/reasoning/nodes.py`. Renders the retrieved lessons as a short
   bulleted block with each lesson's signature; `""` when there is nothing.
   Generic — it reads `AEFState` and nothing else, no services, no clock, no
   randomness — so it is safe inside a `deterministic=True` node and belongs
   to no single agent. Prefers a consolidated entry's `summary`, then
   `latest_feedback`, then a record's `verbal_feedback`, and degrades to the
   chunk's raw text rather than dropping a lesson it cannot parse.
2. **`draft_node` appends it when non-empty.** `draft_prompt` gains a
   `lessons: str = ""` parameter and nothing else changes.

The empty case is the load-bearing one. With nothing retrieved the prompt is
**byte-identical** to the pre-0155 one, pinned by a literal golden in
`tests/agents/test_summary_prompt.py`, so every cassette recorded against
the old prompt still hits and `aef loop score` on the committed corpus still
makes no live call. Both properties are mutation-checked: forcing
`lessons = ""` in `draft_node` fails the regression test; returning the
header instead of `""` from `render_retrieved_context` fails the golden and
three renderer tests.

## The measurement, on the wired graph

84 live calls, `--repeats 2`, one arm-repeat per foreground invocation with
each result written to disk as it landed. Raw JSON in `docs/research/i12/`.

| arm | mean | repeat 0 | repeat 1 | spread | calls | knowledge entries formed |
|---|---|---|---|---|---|---|
| (a) no retrieve | **0.8541** | 0.8333 | 0.8750 | 0.0417 | 12 | 0 |
| (b) raw records | **0.8541** | 0.8333 | 0.8750 | 0.0417 | 12 | 0 |
| (c) + knowledge | **0.8334** | 0.7917 | 0.8750 | 0.0833 | 12 | 0 |
| (d) + LLM reflection | **0.9166** | 0.8750 | 0.9583 | 0.0833 | 48 | 0 |

**Largest within-arm spread: 0.0833** — one scenario's worth of a single
check, on a 6-scenario split scored in quarters. That is the bar every
difference below has to clear, and at two repeats it is itself a weak
estimate; this claim says so rather than pretending otherwise.

| comparison | delta | exceeds the spread? |
|---|---|---|
| (b) − (a) — retrieval vs none | **+0.0000** | no |
| (c) − (b) — knowledge vs raw records | **−0.0207** | no |
| (d) − (c) — LLM reflection vs rule-based | **+0.0832** | no (0.0832 < 0.0833) |

The lessons genuinely reached the model this time: `lessons_in_prompt` is
true for 5 of the 6 scenarios in every retrieval arm (the first scenario of
a run has no experience yet), recorded per scenario in the raw JSON.

### Falsification (c) ≤ (b): FIRED

(c) scored **below** (b). Dimension 2 does not move, and **ADR 0110's
coverage result is demoted to a proxy that has not been shown to predict
task outcome.**

The reason is stronger than a null effect, and it is the finding this
increment actually produced: **not one knowledge entry formed in any arm.**
`RuleBasedConsolidator` requires a signature to recur in two distinct runs.
On this split:

- No run produces `state.errors` — a wrong summary is not an error — so
  `failure_signals()` is empty and every record is `kind="success"`.
- A success's signature is `"success:" + objective`, and the six validation
  scenarios have six distinct objectives.

So every signature occurs exactly once, nothing reaches the threshold, the
knowledge store stays empty, and arm (c) retrieves precisely what arm (b)
retrieves. The −0.0207 is sampling noise between two configurations that are
identical in practice. **The validation split cannot exercise the knowledge
layer**, and no number measured on it can support or refute ADR 0110's
claim. That is a defect in the corpus as an instrument, not evidence about
the layer — and it is why the demotion is to "unconfirmed proxy" rather than
to "disproved".

### Falsification (d) ≤ (c): did not fire, and the LLM reflection still stays off

(d) − (c) = **+0.0832**, against a spread of **0.0833**. A gain smaller than
the spread is not a gain. `reflection.impl: llm` stays off by measurement,
now for the third time (ADR 0115, ADR 0123, here). It is the one arm that
looks like it might be doing something, and the honest statement is that
this rig cannot tell: it costs 4× the calls (48 vs 12) for a difference the
noise covers.

### (b) − (a) = exactly 0.0000, and that is worth stating

Wiring the retriever into the prompt — the change this ADR makes — changed
no task score at all, per scenario, in either repeat. Retrieval now
demonstrably reaches the model and demonstrably did not help here. The
capability was missing and is now present; the claim that it improves this
task is not made.

## A defect found on the way: the check that catches long summaries hangs on long summaries

The first two live attempts at arm (a) died at the 600-second wall after
completing exactly one scenario. It was not throttling.

Every summary scenario caps length with `^(?:\s*\S+){1,35}\s*$`. `\s*\S+`
under a bounded repetition is ambiguous — the same text can be split between
the repetitions in exponentially many ways — so a subject that **cannot**
match forces the engine through all of them. Measured
(`docs/research/i12/regex-backtracking-repro.log`):

| words | matches | seconds |
|---|---|---|
| 30–35 | True | 0.0000 |
| **36** | — | **did not terminate in 600 s** |

The check exists to catch an over-length summary, and it is exactly an
over-length summary that makes it backtrack forever. Under the cassette
every recorded summary is within the cap, so the whole suite is green and
this never fires; it fires only live, only on the failure the check was
written to detect.

**This is very likely what ADR 0123 recorded as I13's unmeasured live noise
floor — "three attempts past a ten-minute wall".** That was read as a
throttle. It reproduces here as a regex.

The defect is in `corpus/**/sum-*.json` and in `aef/harness/checks.py`
running an owner-supplied pattern with no guard. **Neither is this worker's
file and neither was touched.** It is reported, not fixed. Any worker
measuring live on this corpus — S2's noise floor above all — hits it.

To measure at all, the rig rewrites that one pattern shape to
`^\s*\S+(?:\s+\S+){0,34}\s*$`, which is linear because `\S+` cannot contain
whitespace and `\s+` cannot contain non-whitespace, so the tokenisation is
forced and only one path exists. The rewrite is **proved, not asserted**
(`docs/research/i12/wordcap-equivalence-proof.log`): over caps 1–20 and every
subject from 0 to cap+3 words × 3 separators × 3 trailing forms, **0
disagreements**; and an over-cap subject is a non-match in both, which is
what makes a timeout safely readable as `False`. The rewrite lives in the
measurement rig, never in the repo, and `score_scenario` and every other
check are untouched.

## A provenance defect found on the way: the provider names the wrong model

`ClaudeCodeProvider.complete` takes the answering model as
`next(iter(payload["modelUsage"]), None)` — the first key of a dict whose
first key is the CLI's own auxiliary model. Measured on a real draft call:

```
usage:      {"input_tokens": 2, "output_tokens": 69}
modelUsage: {"claude-haiku-4-5-20251001": {in 1050, out 16},
             "claude-opus-5[1m]":         {in 2,    out 69}}   <- answered
```

The top-level usage matches the Opus row exactly; haiku is a side call the
CLI makes for itself. So `CompletionResult.model` — and therefore the
`Provenance.model` written into every recorded run by every node that calls
a model — says `claude-haiku-4-5` when Opus answered. Every arm JSON in
`docs/research/i12/` carries `"answered_by": {"claude-haiku-4-5-...": n}` and
**that field is wrong**; the model named at the top of this ADR is the one
the raw `modelUsage` and token counts identify.

`aef/providers/harness_provider.py` is not this worker's file. Reported, not
fixed.

## Consequences

- **Rubric: dimension 2 stays 17/20, delta 0.** Not +2, and not the +1 of
  partial credit either. The rubric's first rule is that a score moves only
  on a cited artifact showing improvement; the artifact here shows a
  capability that was missing, is now present, and moved nothing measurable.
  A reader may reject that: the counter-argument is that wiring a retrieved
  lesson into a prompt is the level-2 mechanism dimension 2 describes, and
  that the corpus — not the mechanism — is what failed to test it. That
  argument is why the corpus finding is recorded as a defect rather than as
  a result about the layer, and it is the argument a future increment should
  answer with a corpus whose scenarios can recur.
- **`reflection.impl: llm` stays off.** Third measurement, third time off.
- **ADR 0110's `knowledge_boost = 0.0` is untouched** — this increment never
  reached a state where ranking could matter.
- **What a corpus needs to test this layer**, stated so the next attempt
  does not repeat the run: scenarios whose signatures can recur — several
  scenarios sharing one objective, or failures that populate
  `state.errors` with a stable `failing_nodes` list. Without recurrence the
  consolidator is a no-op by construction and arms (b) and (c) are the same
  arm.

## Quota preflight

ADR 0150's corrected argv, run first as the loop requires:

```
is_error: false   result: "OK"   usage.input_tokens: 2
```

Two input tokens (3,324 cache-creation), against the 211,470 ADR 0126 set
out to fix and the 4,684 it claimed. The isolation flags work.

**Calls made: 84** (the briefed budget exactly) plus 4 spent on the preflight
and latency probes, plus at most 2 lost to the two regex hangs — 90 total,
of which 84 are in the table.

## Erratum (ADR 0174, worker M4b)

**"The validation split cannot exercise the knowledge layer"** was true of the
producers that existed, not of the split. Re-run offline, the six scenarios
give the numbers above — six `success` records, six unique signatures, **0
knowledge entries** — *and two of the six FAIL an owner check*
(`sum-14-quarry-lake`, `sum-16-cliff-path`). Nothing turned that into failure
memory, because `make_reflect_node` reads only `state.errors` and a check is
the task metric evaluated afterwards. The identical gap M4 hit from the other
side (ADR 0157).

With `aef/harness/check_memory.py` in place the same six runs produce **2
failure records sharing one signature** (`failure:check:working_memory.summary:contains`)
and consolidate to **1 knowledge entry**, which `render_retrieved_context` then
carries into the next run's draft prompt — where every bullet previously read
*"no failure signals"*. The recurrence lives in the CHECK rather than in the
objective, which is what makes it reachable on a corpus of distinct scenarios;
keyed on the check's expected value instead, this split still yields 0 entries
(measured, ADR 0174 §3).

**No arm is re-measured and no number above changes.** The four arms are now
runnable as a real comparison for the first time and re-running them needs
**live quota and a corpus whose failures recur** — this ADR's own consequences
asked for exactly that, and S3b is building it. The demotion of ADR 0110's
coverage result to an unconfirmed proxy stands until those arms are re-run.

## Note (orchestrator, at merge)

Written against the pre-J0 rubric: dim 2 was 17/20 on this branch and is **12/20** on `main` after ADR 0151 — J0 deducted precisely for the open retrieval→prompt link this ADR closes. The delta claimed is 0 either way; no row moves. The two defects reported here (the word-cap regex, the first-key model attribution) were fixed on `main` by ADRs 0166 and 0154 before this merge.


## Erratum (fix wave J3, ADR 0179): the one caller was this repo's own fixture

This ADR gave `render_retrieved_context` its caller and closed "a caller that
writes state nobody reads". The caller was `agents/summary/graph.py::draft_node`
— this repo's own validation fixture, which ships in **no** adopted repo — and
`aef migrate`'s generated template had no retrieve node at all. So the same
shape survived one level out: on every repo the scaffold generates,
`make_retrieve_node` was absent, `retrieved_context` was empty, and no prompt
read anything. Reproduced end to end with the real `run_migrate` and the real
runner.

Closed by ADR 0179's R6: the template gains the retrieve node and
`PromptAgentNode` becomes the second caller of this ADR's helper — the first
one that reaches an adopter. What is NOT closed is this ADR's actual result:
the four arms still show no task-metric benefit from retrieval, and R6
supplies a path to re-run them on an adopter rather than any evidence about
the outcome.
