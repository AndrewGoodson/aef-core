# ADR 0180: The good column, the quotation, and the one call site

## Status

Accepted. Fix worker **K2** of the upgrade loop. Three findings, all reported
by earlier workers as *outside their files*, all reproduced here from committed
data before anything was changed. **Zero live model calls** — every number
below comes from `docs/research/j4/harm.jsonl` (S6, ADR 0162),
`docs/research/i12b/results/c_r0.json` (S1b, ADR 0175) and offline runs of the
shipped code. **No rubric dimension moves**; what a dimension-2 measurement
would now need is stated at the end.

## Finding 1 — the tally counted a harmful run as helpful

### Reproduced

ADR 0162 rig B's ten runs, replayed through the SHIPPED `default_signature` and
the SHIPPED `RuleBasedConsolidator` (the rig itself predates ADR 0174, so it
carried a private `check_signature`; this rebuild uses ADR 0174's string keys
and the repo's own function):

```
lesson: failure:check:working_memory.summary:max_words  x7

run                           own signature                                      reproduced?
--------------------------------------------------------------------------------------------
sum-23-cransley-cut           failure:check:working_memory.summary:max_words             yes
sum-24-pellow-mill            success:summarise sum-24-pellow-mill …                      NO
sum-31-quernmore-kiln         success:summarise sum-31-quernmore-kiln …                   NO
sum-34-alder-carr             success:summarise sum-34-alder-carr …                       NO
sum-39-coldbeck-society       failure:check:working_memory.summary:max_words             yes
sum-22-marlowe-street         success:summarise sum-22-marlowe-street …                   NO
sum-30-ganister-tarn          success:summarise sum-30-ganister-tarn …                    NO
sum-33-cotterdale-bus         success:summarise sum-33-cotterdale-bus …                   NO
sum-35-priory-gatehouse       failure:check:working_memory.summary:regex                  NO
sum-36-larkfield-quarry       failure:check:working_memory.summary:max_words             yes

failure:check:working_memory.summary:max_words  x10  helpful=7 harmful=3
```

`sum-35-priory-gatehouse` is the run the whole rig was built to find. It had
the word-cap lesson in context, it **resolved** the cap failure (30 → 28 words)
and its shortened summary stopped matching a content regex the baseline run had
passed. ADR 0118's tally has two branches around `_reproduced()`, so it landed
in the **good** column. The lesson was credited for the failure it caused.

That is why ADR 0162 refused to rank on the tally, and why it named the missing
outcome as the blocker for dimension 2: *"the missing third outcome has no
name."*

### Decision — three outcomes, and `helpful` gets narrower

`_tally` now splits the runs that had the lesson in context three ways:

| the run… | outcome |
|---|---|
| reproduced this failure | `harmful` |
| failed nothing | `helpful` |
| resolved this failure and failed something else | `harmful_elsewhere` |

`harmful_elsewhere` is a third field on `KnowledgeEntry`, beside `helpful` and
`harmful`, non-negative like both, recomputed from the records every
consolidation and never incremented (ADR 0091). On the same ten runs:

```
failure:check:working_memory.summary:max_words  x10  helpful=6 harmful=3 harmful_elsewhere=1
```

`helpful` is decremented and the run that caused a failure is out of the good
column. `docs/research/j4/run_j4_harm.py --tally`, unmodified, now prints
`helpful=6 harmful=3` (its own print statement has no slot for the third
counter); `report-tally.txt` is S6's record of what the tally said in S6's
window and is deliberately left as it was.

**The name.** `harmful_elsewhere`, over `neutral` and over `mixed`, because the
run is evidence *against* the lesson and the two rejected names read as
evidence for nothing. It is not `harmful`, because reproducing the lesson's own
failure and breaking something else are different observations with different
remedies, and merging them would be the catch-all `consolidate.py` already
warns about one level up.

**Failure is the record's `kind`, not a prefix on its signature.** The third
branch reads a new `produced_failures` map populated only from records the
producer marked `kind="failure"`. A run's own `success:<objective>` signature
is not a failure however it is spelled, and a custom `signature_fn` may spell a
failure any way it likes — inferring one from the string is the guess
`_failure_nodes` refuses to make. `M2` below is that mutation.

**What the rule cannot say, stated because a redaction with no residual is a
claim nobody checked.** The brief's definition of the third outcome is *a
different check failed that PASSED on the incumbent or previous run for this
scenario*. The consolidator sees `MemoryRecord`s, not scenarios, and has no
incumbent to compare against — it cannot know whether the other check had ever
passed. What it can see is that the run had the lesson and still failed, which
is enough to keep it out of the good column and **not** enough to blame the
lesson for it. `harmful_elsewhere` is therefore a superset of the shape ADR
0162 wanted, and a reader must not read one of its counts as a proven harm.

**Nothing ranks on it.** ADR 0162's condition (3) was "ranking on the tally
recovers the flipped check — NOT REACHED, and deliberately not attempted",
because measuring a knob against a backwards signal produces a number that
means nothing. The signal now reads forwards; that earns it a place in the
metadata, not a coefficient. `MemoryRetriever` is untouched and
`knowledge_boost` stays 0.0.

### One existing test pinned the old behaviour and was updated deliberately

`test_a_reordered_chain_is_a_different_failure_and_is_not_a_recurrence`
asserted `(helpful, harmful) == (1, 0)` for a run shown `failure:fetch>parse`
that instead failed `failure:parse>fetch`. The subsequence rule it exists for
is unchanged and still asserted; what changed is that "did not reproduce it,
failed something else" is no longer `helpful`. It now asserts `(0, 0, 1)`.

## Finding 2 — the record quoted the model's own output back into its prompt

### Reproduced

The shipped `check_failure_record` over `sum-35-priory-gatehouse`'s recorded
final state, with the with-lesson summary S6 measured:

```
THE MODEL'S OUTPUT:
  'From February, the Priory gatehouse gets twelve weeks of stonework,
   repointing and lead roof renewal, staying open except two April weeks;
   the precinct wall is assessed separately later.'

verbal_feedback:
  1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: check failed:
  working_memory.summary does not match the pattern the owner declared;
  observed 28 words, 186 chars: 'From February, the Priory gatehouse gets twe…

12-char windows of the OUTPUT present in verbal_feedback: 33
12-char windows of the OUTPUT present anywhere in content: 48
```

ADR 0174 argued the excerpt is honest, and it is: the observation is the run's,
not the owner's, so recording it records what happened. That argument is right
about *provenance* and silent about *destination*. `verbal_feedback` is a
prompt surface — `RuleBasedPromptProposer` pastes an entry's `latest_feedback`
verbatim into the persona, and `render_retrieved_context` renders it as a
lesson bullet — so the excerpt is the model's previous answer travelling into
its next prompt.

ADR 0162 measured what that costs, and it is the sharpest number in this
document. A 330-character bullet whose lesson text carried a 38-word example
summary made two at-cap runs **longer** and broke the very check the lesson
describes:

| id | cap | baseline | with lesson | newly failed |
|---|---|---|---|---|
| `sum-23-cransley-cut` | 25 | 23 w | **28 w** | `max_words` |
| `sum-39-coldbeck-society` | 38 | 38 w | **41 w** | `max_words` |

This is ADR 0110's own rule — *the model is never trusted with provenance; it
may write one prose string, and every counted field is computed from records* —
failing one layer down. There the model was kept out of the counted fields.
Here the model's text was **put into** the counted field's explanation.

### Decision — keep the counts, drop the quotation

Before:

```
check failed: working_memory.prompt_agent does not contain a required substring
the owner declared; observed 406 words, 2836 chars: '**No. The Accela connector…'
```

After:

```
check failed: working_memory.prompt_agent does not contain a required substring
the owner declared; observed 406 words, 2836 chars
```

Everything the harness computed survives: the state path, the operator in
prose, the word count, the character count, `checks_passed` and `checks_total`.
What leaves is the excerpt, which the harness did not compute — it copied it.
After the change, on the same `sum-35` data, **0** 12-character windows of the
output appear anywhere in the record's content.

Two smaller decisions inside it:

- **A non-string value is reported by type alone** (`a non-text value of type
  bool`), not by `repr`. `repr(True)` is the run's output as much as a sentence
  is, and its *length* is the answer on a boolean field (4 characters against
  5). ADR 0174's residual list names that leak as unavoidable for a
  small-domain `equals` check; it is unavoidable there and gratuitous here.
- **The forwarding address is a content key, not part of the line.** The first
  draft of this fix put "the output is in the run's trace" in the failure line
  and the `Critic`'s 160-character excerpt then cut the observation out of
  `verbal_feedback` — caught by a test, which is the only reason it is written
  here as a fact rather than shipped as a regression. The record now carries
  `output_location` beside `check_failures`; it is not rendered into any prompt
  (`render_retrieved_context` reads the summary or the feedback and nothing
  else) and is not copied into a `KnowledgeEntry`, whose content is a fixed set
  of keys.

**Where the output actually is**, since the lesson no longer carries it: in the
recorded scenario. `corpus/<split>/<scenario id>.json` holds the trace, which
replays to the final state, so the value the check read is
`resolve(final_state, check.path)`. `aef loop score` prints it per failing
check. A human can always see it; a lesson never does.

The regression test is the general property rather than one string:
`test_no_record_repeats_a_window_of_the_output_it_was_computed_from`
parametrises two real outputs — `sum-35`'s summary and the marlin verdict ADR
0174 quotes — across two operators, and asserts that no 12-character window of
the output survives anywhere in the record's content. Twelve is short enough
that an excerpt of any useful length trips it. `M3` restores the 60-character
excerpt and five tests fail.

## Finding 3 — one call site, and a lesson walked out of its own prompt

### Reproduced

ADR 0175's arm (c), from its committed results:

```
validation split: 17 scenarios
scored runs that failed an owner check: ['sum-14-quarry-lake', 'sum-32-hessle-mills',
  'sum-35-priory-gatehouse', 'sum-36-larkfield-quarry', 'sum-38-bewick-refusals',
  'sum-39-coldbeck-society']
failure records the arm actually wrote: {}

bootstrap only (shipped)         runs=3   runs_since_last_seen=17
producer on the scored split     runs=9   runs_since_last_seen=0
```

`"failures": {}` is `c_r0.json`'s own field. Six scored runs failed an owner
check and **not one of them could write a record**, because ADR 0174 wired the
producer into `bootstrap` alone. Every scored run writes a `success` record
instead, so `runs_since_last_seen` climbs monotonically, ADR 0116's staleness
demotion walks the entry from rank 0 to rank 25–39, and the two owner-check
negatives late in the split (`sum-35`, `sum-36`) never saw the word-cap lesson
at all — halving the power of the comparison S1b existed to run. A seam between
two correct mechanisms, exactly as ADR 0175 filed it.

The "producer on the scored split" row is an illustration, not a measurement:
it assigns the same cap signature to all six failing runs, and in the real arm
some of those checks were different. The load-bearing half is the first row and
the empty `failures` map.

### Decision — one function, idempotent, and the call sites named

`aef/harness/check_memory.py` exposes **`record_check_outcomes(...)`** —
`check_failure_record` written to a store at most once per `(agent_id, run_id,
failed check keys)`. It replaces `write_check_failure_record` (one name for one
thing; `bootstrap` and the tests move with it) and it returns the record that
is in the store, whether this call wrote it or an earlier one did — so
`bootstrap`'s `check_failed` line still reports the run that failed a check.

Idempotence has two guards, because they fail on different stores:

- **A derived id.** `check_record_id(agent_id, run_id, keys)` hashes what the
  observation *is*, so any store keyed by id collapses a repeat.
  `MemoryRecord.id` otherwise defaults to a fresh uuid4 and the second call
  would be a second record — not cosmetic: `source_record_ids` is the entry's
  only measure of how well-evidenced it is.
- **A query.** The function first asks the store whether it already holds a
  failure record for this run with these keys, which covers an append-only
  store (`FileMemoryStore`) and covers a second process.

The known hole is stated rather than left to be found:
`bootstrap.RunScopedMemory` answers queries from its per-input scratch while
mirroring writes into a durable sink, so a repeat write into that *sink* from a
later invocation is caught by the derived id and not by the query.

**What this ADR does not do is decide where it is safe to call.** ADR 0174
refused `scenario_runner.run_scenario` because the gates re-execute corpus
scenarios and a gate run that writes to the adopter's durable store lets
scoring a candidate manufacture the evidence for the next one. **That refusal
stands.** The store is the caller's to supply, and a gate path supplies none.
The two files that should gain a call site belong to other workers in this
wave, so the lines are reported rather than written:

- **`aef/harness/scenario_runner.py::run_scenario`** (J1) — a keyword-only
  `memory: MemoryStore | None = None`, defaulting to `None` so every gate path
  behaves exactly as today, and after `score_scenario`:

  ```python
  if memory is not None:
      record_check_outcomes(
          memory=memory, checks=scenario.checks, final_state=result.final_state,
          critic=services.require_critic(), judge=services.require_judge(),
          run_id=scenario.id, agent_id=scenario.initial_state.agent_id or "",
          created_at=scenario.recorded_at, graph_version=graph.version,
      )
  ```

- **`aef/cli/loop.py::cmd_score`** (I1) — a `--memory PATH` argument that
  builds a `FileMemoryStore` and passes it to `run_scenario`; without the flag,
  nothing changes. Scoring the incumbent over a corpus is the owner's own read
  and the one place outside `bootstrap` where an owner check meets a run and a
  durable store may legitimately be present.

**`harvest` is re-refused, and the reason was re-read rather than repeated.**
`RecordedRun` has no `checks` field, `harvest()` takes no memory store, and
`aef run` takes no checks argument: a production run carries no owner claim
about its answer, so there is nothing for the producer to evaluate. Inventing
one at harvest time is the system labelling its own runs, which is ADR 0060.
Closing that properly means letting an owner attach checks to a live objective
— a CLI-surface decision, not a patch.

## Mutations

Perturb, RUN, restore from a shasum-verified byte backup; the control is green
before and after and both files' sha256 are proved unchanged at the end.

| # | mutation | result |
|---|---|---|
| M1 | collapse the third outcome back into `helpful` | 3 failed — CAUGHT |
| M2 | decide "failed elsewhere" from every produced signature, not from failures | 3 failed — CAUGHT |
| M3 | put the 60-character excerpt of the output back in the failure line | 5 failed — CAUGHT |
| M4 | drop the query-based duplicate guard from `record_check_outcomes` | 2 failed — CAUGHT |
| M5 | let the record id default to a fresh uuid4 | 1 failed — CAUGHT |

5 of 5. Restored sha256: `7c10f8a9…7f4a375c` (`consolidate.py`),
`8972a809…84045ff8` (`check_memory.py`).

## Green bar

```
pytest -q                 2590 passed, 7 skipped, 4 xfailed   (from 2572; +18)
mypy aef examples         Success: no issues found in 134 source files
ruff check .              All checks passed!
ruff format --check aef tests examples   274 files already formatted
```

`tests/cli/test_prompt_repo_acceptance.py::test_a_prompt_file_repo_goes_from_
adopt_to_a_gated_prompt_candidate` fails, and it fails identically on the merge
base (`28823b2`) — verified by exporting `git archive HEAD` to a clean tree and
running the same suite there: **`1 failed, 2572 passed, 7 skipped, 4 xfailed`**,
the same single test, the same assertion. It is ADR 0178's R2 surface (`loop
doctor` and `--agent-path`) and nothing here goes near it.

## What a re-run of S1b's four arms would now need

No rubric change is claimed and the rubric is untouched. What ADR 0175's
falsification could not separate is stated so it is not re-derived:

1. **Arms (b) and (c) must be re-run with the excerpt gone.** The lesson S1b
   put in front of the model in ten of seventeen prompts read *"observed 31
   words, 208 chars: 'Vaccination clinics have relocated from Netherby
   Grange…'"* — an example of an over-long summary, inside a lesson telling the
   model to be shorter. ADR 0162 measured that shape making at-cap runs longer.
   (c) lost on the four negatives — the word-cap scenarios — which is precisely
   where the mechanism would bite. The arms as run cannot tell a knowledge
   layer that does not help from a lesson text that hurts.
2. **The producer must be on the scored split**, via the two call sites above,
   so a scored run that fails a check re-freshens its own lesson. Without it
   the treated and control subsets are the head and tail of one ordered split
   — S1b says so itself — and the split is not randomised.
3. **Repeats.** S1b's own same-prompt variance ran to 0.0857 on n=7 and every
   arm-to-arm delta sat inside it. Two repeats of (b) and (c) at 17 scenarios
   is 68 calls; cutting arm (d), which S1b showed sends byte-identical prompts,
   pays for exactly that.

That is the next dimension-2 measurement. This increment supplies the two
instruments it needs and claims nothing about the outcome.

## Consequences

- `KnowledgeEntry` gains `harmful_elsewhere`. Any code reading the tally should
  read all three; a `helpful` count from before this change is not comparable
  to one after it.
- `write_check_failure_record` is gone; `record_check_outcomes` is its
  idempotent replacement and the function every scored path should call.
- A check-derived lesson no longer contains any of the run's output. Anyone
  debugging from memory alone will find counts and a pointer; the text is in
  the corpus.
- Errata are recorded on **ADR 0118** (the tally had no third outcome) and
  **ADR 0174** (the excerpt, and the single wiring site).

## Confidence

**High** on all three reproductions: each ran against committed data through
shipped code, before and after, and each fix moves the reproduced number.

**High** on findings 2 and 3 as fixes. The excerpt property is asserted
generically over real outputs and mutation-checked; the idempotence property is
asserted end to end through the consolidator.

**Medium** on what `harmful_elsewhere` will be worth. It reads forwards now,
which is all that was claimed, but it is a superset of the shape ADR 0162
wanted, its n on the only real corpus is 1, and nothing ranks on it. A count of
1 is not yet evidence of anything.

## Addendum (orchestrator): the follow-ups

`run_scenario` gains `memory: MemoryStore | None = None` and calls `record_check_outcomes` when given one (the second wiring site; default None keeps every gate path unchanged; mutation-checked — disabling the call fails the test). `harmful_elsewhere` is surfaced in the retriever's chunk metadata and the skills draft. `cmd_score --memory` is K3's (ADR 0182).
