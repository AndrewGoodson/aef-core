# ADR 0123: A task a model can fail, replayed without a key

## Status
Accepted. Increment I11 of `ABOVE_90_LOOP.md`; record in `IMPROVE_LOG.md`.
`cassette_miss` defaults to `"fail"`; `"live"` is the named opt-in.

## Context

ADR 0113 gave the corpus a scalar that can fall without an error, and the
corpus then had nothing to fall on: every scenario in `corpus/` was a run of
`agents/demo`, whose one node either completes or records an error. Scored
before this increment, all six sub-1.0 scenarios carried an error and no
scenario failed on content alone (reproduced: `.scratch/reproduce.py`,
11 scenarios, 6 below 1.0, 6 with an error). The rubric's dimension 1
stopped at 17 for that reason — "corpus is 11 demo scenarios".

The obstacle to a content task was not the scorer. A graph that asks a
model cannot be re-executed by the gates: the sandbox holds no credential,
and even where it did, a live answer differs every run, so a candidate's
score would move for reasons that have nothing to do with the candidate.
The pinned clock (`fixed_clock`, ADR 0048) solved the same problem one
layer down; nothing pinned the model.

## Decision

1. **A scenario pins its model calls.** `Scenario.model_calls` carries
   every completion the recording made — the full request (messages, model,
   token cap) and the result — keyed by a stable hash of exactly those
   three fields. The key is derived at load, never trusted from the file: a
   cassette entry whose stored key does not match its own request is
   refused (`CassetteError`), so a hand-edited answer cannot pose as a
   recording. Legacy scenarios load with none.
2. **`CassetteProvider` replays; a miss fails by default.** A hit returns
   the recorded result and never touches the inner provider. A request the
   recording never saw is, under `on_miss="fail"`, a `ModelProviderError`
   naming the miss — the node fails, the score is 0 for that scenario, and
   the gate needs no key. This is the default everywhere a scenario is
   re-executed: `run_scenario`, the isolated worker, and therefore G2/G3.
   A changed prompt is a behavioural difference, and reporting it as one is
   the honest reading; answering it live from inside a gate would make the
   gate's verdict depend on which model happened to be on the other end.
3. **`"live"` is the opt-in, and it says so.** `LoopConfig.cassette_miss`
   / `--cassette-miss live` sends misses to the provider named in the BASE
   REF's `model_provider` (read the way the policy is read, ADR 0082) and
   records them; `aef loop score` reports hits and misses and labels the
   result `LIVE`. A live score and a replayed score are different
   measurements and the report does not let one pass for the other.
4. **The cassette reaches the worker through a `configure` frame.** The
   node bodies run in the isolated worker (ADR 0094), so the parent sends
   each scenario's calls before its nodes run; the worker swaps only its
   model provider, keeping memory so one worker still serves the whole
   corpus. What the worker learns is what the model said last time — which
   its own node could have hard-coded — and nothing that judges.
5. **`agents/summary` is the first content task.** retrieve → draft →
   reflect → consolidate; the draft node asks `require_model_provider()`
   to summarise `working_memory["text"]` within `max_words`, mentioning
   every `must_mention` term, and writes `working_memory["summary"]`. It
   scores nothing about itself. Twenty synthetic passages were recorded
   live through `aef loop record --config` (impl `claude_code`), each with
   owner `contains` checks per term, a `regex` word-count check, and a
   60 s budget; 12 train / 6 validation / 2 holdout, the holdout spent once
   with `--i-am-spending-the-holdout`. `aef loop record` gained `--config`,
   `--check` and `--budget-ms` to make that possible; `aef loop score`
   scores only the scenarios recorded from the graph it was given, since
   the corpus now holds two graphs' recordings.

## Evidence

Recording: 20 model calls, 4.9–9.8 s each, one per scenario.

Cassette score, `--repeat 3`: train mean **0.9792** (n=12, stdev 0.0722,
CI95 [0.9383, 1.0200]); validation mean **0.9167** (n=6, stdev 0.1291,
CI95 [0.8134, 1.0200]); repeat spread **0.000000** on both; 54 cassette
hits, 0 misses, 0 live calls. Three scenarios score 0.75 (`sum-07`,
`sum-14`, `sum-16`): the model put the required term at the start of a
sentence and capitalised it, and `contains` is case-sensitive. Those are
the first content failures the metric has ever seen, and they are also a
lesson in check authoring, recorded here rather than edited away.

Planted regression (the must-mention instruction removed from the draft
prompt) under the default policy: every request is a miss — 36 misses, 0
hits over two repeats, train and validation **0.0000**, no live call. The
regression is detected by the gate's default without spending anything.
The plant was reverted and proved byte-identical to its backup and to
HEAD.

Planted regression scored **live** — the measurement that would give the
live noise floor — **did not complete**. Predicted: 54 calls at ~6 s,
about six minutes. Observed: the first attempt (train+validation × 3) was
killed at a ten-minute timeout with no output; a second (validation × 3,
18 calls) was killed with the session's background tasks; a third
(validation × 3, foreground) also exceeded ten minutes. The recorder made
the same calls at ~6 s each an hour earlier; why `loop score --cassette-miss
live` ran so much slower is not diagnosed (quota throttling after ~110 calls
in the hour is the suspicion; it is a suspicion). Calls spent on the three
attempts are not exactly known because the CLI prints nothing until the
end; the upper bound is 54 + 18 + 18. The prediction was wrong and the
number is absent, stated here rather than estimated.

Judge A/B (I3 re-run on 18 summary states, position-swapped, 36 calls):
rule-based judge agrees with the checks on **3/18**, LLM judge on **9/18**;
they disagree with each other on 10/18; the LLM judge's scores sit between
0.23 and 0.50 with a position delta of 0.05–0.2 on 9 of 18 states; mean
11.9 s per judgment. Predicted before running and confirmed: neither judge
reads the answer — the rule-based judge scores `state.scores`, which this
agent leaves empty, and the LLM judge's evidence is errors, tool results,
scores and reflections, not `working_memory`. On a content task both are
blind by construction, and the position control shows the LLM judge's
residual variation is order sensitivity, not judgment.

Mutations, each performed for real (perturb, run, restore, diff-confirm):
M39 miss under `fail` falls through to live — 1 failed; M40 a hit still
calls the inner provider — 1 failed; M41 `model_calls` not loaded from the
payload — 1 failed; M42 a `contains` check always holds — 1 failed.

Green bar: pytest 1744 passed (from 1720; +24, two corpus-pinning tests
rewritten deliberately: the holdout is no longer empty, and it says which
two ids may be there), `mypy aef examples` 126 files clean, ruff clean.

Found on the way: the isolated worker's `PYTHONPATH` carried only the
workspace, so on a checkout whose venv resolves `aef` to a different tree
the parent spoke a protocol the worker had never heard of and every
scenario failed as "previously passing, no longer passes". The harness
root is now appended after the workspace. Not fixed, reported: the gates
do not filter scenarios by `graph_id`, so a `loop gate` over `corpus/`
now runs the demo against the summary scenarios too (they fail identically
for candidate, incumbent and cohort); `harvest` re-executes without a
cassette, so a harvested model-calling run would be rejected as
non-deterministic; and the judges' evidence omits the answer.

## Consequences

- The corpus holds a task a model can fail, scored deterministically
  without a credential, and a prompt regression moves the score under the
  default policy. Rubric dimension 1: 17 → 19, not 20 — the live noise
  floor is unmeasured and no loop turn has yet been kept or reverted on
  this suite (I12's job).
- Rubric dimension 3: 7 → 8. The corpus where the judges disagree, which
  I3 said was missing, now exists and the disagreement is a number; what
  the number says is that neither judge sees the answer. The next point
  needs a judge whose evidence includes it.
- Recording a model-calling scenario now costs one live call per model
  call in the graph, once; every gate run afterwards costs nothing.

## Confidence

High on the cassette and the default; the corpus is twenty synthetic
passages of one shape, and the live noise floor is a number this ADR does
not have.

## Erratum (ADR 0166, 2026-09-04)

The Evidence section above says of the three live attempts that "why `loop
score --cassette-miss live` ran so much slower is not diagnosed (quota
throttling after ~110 calls in the hour is the suspicion; it is a
suspicion)". **The suspicion was wrong, and the honest hedge was the right
call on the evidence available.**

It was not a throttle. It was this corpus's own word-cap check. Every summary
scenario carried `{"op": "regex", "value": "^(?:\\s*\\S+){1,N}\\s*$"}` — a
repeated group over a nullable-separated body, which matches in 0.05 ms and,
on a summary **one word over the cap**, backtracks over every partition of the
string and does not return. `aef/harness/checks.py::_holds` called `re.search`
with no timeout. The recorded cassettes all sit at or under their caps, so the
replayed runs in this ADR never touched the failing branch; the live runs
produced the first over-cap summary and hung on it. Diagnosed from a
`faulthandler` stack in ADR 0156 §D2, reproduced and fixed in ADR 0166.

Nothing else in this ADR changes. Every number here was measured on the
replayed path, and re-scoring the corpus after the pattern was rewritten
reproduces all of them byte-for-byte — train `0.9792`, validation `0.9167`,
and all three `0.75`s.
