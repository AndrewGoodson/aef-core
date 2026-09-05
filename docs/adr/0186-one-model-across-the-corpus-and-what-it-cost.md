# ADR 0186: One model across the corpus, and what it cost

## Status

Accepted. Worker **S3c** of `UPGRADE_LOOP.md`, executing ADR 0162's defect 1 —
the one that worker reported and could not fix, because `corpus/` was not its
file:

> **Six corpus scenarios are `claude-fable-5-1` recordings** (`sum-01`…
> `sum-18`; `sum-13`…`sum-18` are in validation). Nothing states this
> anywhere […] Any future measurement that treats the validation split as one
> model's output is wrong by 6/17, and the quota for `claude-fable-5-1` is
> exhausted, so they cannot be re-recorded. **This worker's `load_pairs`
> refuses them; nothing else does.**

Model, everywhere in this document: **`claude-opus-5[1m]`** — the harness
session's own default, reached with `model: ""` in the recording config so no
`--model` flag is built (`harness_provider.py` appends it only when the string
is non-empty). That is S3b's rule (ADR 0171) and it is the only way the model
that answers is the model a later judge runs on.

**19 live calls of the 24 allowed.** No rubric dimension is claimed. This is
corpus hygiene with a measured consequence, and the consequence is not
flattering: **8 of the 18 re-recorded scenarios now fail an owner check that
they passed.** Both split means fall. That is the record of what the model
did, kept as such (ADR 0060: only an owner labels `expected`, and a check is
never adjusted to protect a score).

## Context

### The count is 20, not 18

ADR 0162 said six, then eighteen. Verified here by reading the answering model
out of every cassette rather than out of a document:

```
model counts: {'claude-fable-5-1': 20, '': 11, 'claude-opus-5[1m]': 19}
```

Twenty. `sum-01`…`sum-18` in train and validation, **plus `sum-19-tram-depot`
and `sum-20-seed-bank` in the holdout**, which no prior document names. (The
eleven with `''` are the `agents/demo` scenarios, which call no model at all;
they have no provenance to state.)

### Why the holdout stays Fable, deliberately

Eighteen were re-recorded. The two holdout scenarios were **not**, and this is
a decision rather than an oversight.

`record_run` refuses to write to the holdout without `allow_holdout=True`, and
`aef loop record` spells that `--i-am-spending-the-holdout`. The refusal's own
words are the reason: *"It is the owner's only independent read of whether the
loop is improving anything, and a recorder that fills it as casually as it
fills train destroys that independence silently."* Spending it is an owner's
act. A worker holding a flag that would let it past a control is exactly the
case IMPROVE_LOOP's "never weaken a control" and HARD-STOP gate 2 cover, so
the flag was not passed and the two scenarios are **declared exceptions**,
named in the test, named in the provenance table, and left for an owner to
decide.

The cost of that decision, stated rather than buried: the holdout is still a
Fable read of an Opus corpus. It should not be cited as this agent's
independent score until an owner re-records it. `aef loop score` cannot reach
it without the same flag, so nothing does so by accident.

## The inventory

Read from the cassettes, not from any document. `''` in the model column means
the scenario makes no model call.

| scenarios | split | recorded on | n | checks |
|---|---|---|---|---|
| `sum-01`…`sum-12` | train | `claude-fable-5-1` → **`claude-opus-5[1m]`** | 12 | 5 each |
| `sum-13`…`sum-18` | validation | `claude-fable-5-1` → **`claude-opus-5[1m]`** | 6 | 5 each |
| `sum-19`, `sum-20` | holdout | `claude-fable-5-1` (**unchanged, declared**) | 2 | 5 each |
| `sum-21`…`sum-28` | train | `claude-opus-5[1m]` (ADR 0171) | 8 | 4–6 |
| `sum-29`…`sum-39` | validation | `claude-opus-5[1m]` (ADR 0171) | 11 | 5 each |
| `easy-*`, `boundary-*`, `hard-both-*`, `val-*`, `tripwire-*` | mixed | *(no model call)* | 11 | 0–2 |

ADR 0123's recorded scores for the twenty: train **0.9792** (n=12), validation
**0.9167** (n=6), the three sub-1.0s being the case-sensitivity defects. ADR
0171 corrected those and every one of the twenty scored **1.0000**. That is
the number this increment starts from, and it is the number that moves.

## What was done

For each of the eighteen, in this order:

1. The corpus file is sha256'd and copied byte-for-byte to
   `docs/research/i14/fable-recordings/<id>.json`, and the copy's digest is
   asserted equal to the original's.
2. The corpus file is **deleted**, because `refuse_existing_ids` refuses to
   overwrite an id and there is no `--force`. That refusal is right — *"the
   entry that used to fail is gone, and `check_never_shrinks` cannot tell,
   because the id is still there"* — and the archive is what discharges it:
   the recording it protects is not lost, it is one directory over, and this
   ADR says where.
3. `aef loop record` runs with the **same id, split, agent id, objective,
   `working_memory` (the passage, `must_mention`, `max_words`), `budget_ms`,
   `expected` label and byte-identical owner `checks`**, all read off the
   archived file. Nothing is re-authored. The only new field is `notes`,
   which names this ADR and the archive path.
4. On any non-zero exit the archived bytes are written back and the run stops.

**The proof that only the answer moved is the cassette key.** The key is a
hash of the request (messages + model + `max_tokens`), and every re-recording's
key is identical to the one it replaced — `sum-01`'s is `d4fc36cc…8e5117`
before and after. A moved key would mean the prompt changed, and then the
before/after below would be comparing two different questions. Asserted per
file, alongside a key-by-key diff that permits only `trace`,
`model_calls[*].result`, `recorded_at`, `notes` and `source` to differ:

```
OK: 18 re-recorded scenarios; owner fields and cassette keys unchanged
corpus files changed vs HEAD: 18
OK: no other corpus file changed, manifest included
OK: all 18 archived recordings are byte-identical to HEAD
```

`corpus/manifest.json` is untouched: `_record_in_manifest` is a union keyed by
`(id, split)`, and neither moved.

`source` is one honest difference. The Fable recordings predate ADR 0141 and
carry no `source` key; the new ones carry `"source": "record"`, which is what
they are.

## The measurement

`aef loop score agents.summary.graph --corpus corpus --splits train,validation
--json`, replayed from cassettes both times — 37 hits, 0 misses, 0 live calls
on each side, so the comparison spends nothing and has no noise.

### Before (Fable answers on 18 of 37)

```
train      mean 0.9675  n=20  stdev 0.0799  CI95 [0.9325, 1.0025]   3 negatives
validation mean 0.9529  n=17  stdev 0.0874  CI95 [0.9114, 0.9945]   4 negatives
```

### After (one model across train and validation)

```
train      mean 0.9275  n=20  stdev 0.1019  CI95 [0.8828, 0.9722]   7 negatives
validation mean 0.9059  n=17  stdev 0.1029  CI95 [0.8570, 0.9548]   8 negatives
```

**train −0.0400, validation −0.0470.** Fifteen of the corpus's 37 summary
scenarios now fail an owner check, against seven before.

### The eight verdict changes, and the eight that held

Every re-recorded scenario went from 1.0000 to either 1.0000 or 0.8000. Nothing
moved the other way, because there was nowhere to move: all eighteen passed
everything before.

| id | split | cap | Fable words | Opus words | verdict |
|---|---|---|---|---|---|
| `sum-04-halden-reservoir` | train | 40 | 39 | **42** | 1.0 → 0.8, `max_words` |
| `sum-05-bramble-bakery` | train | 35 | 32 | **36** | 1.0 → 0.8, `max_words` |
| `sum-08-glasshouse-tomatoes` | train | 35 | 33 | **37** | 1.0 → 0.8, `max_words` |
| `sum-11-lantern-festival` | train | 35 | 30 | **37** | 1.0 → 0.8, `max_words` |
| `sum-13-cider-press` | validation | 35 | 35 | **36** | 1.0 → 0.8, `max_words` |
| `sum-14-quarry-lake` | validation | 40 | 39 | **44** | 1.0 → 0.8, `max_words` |
| `sum-16-cliff-path` | validation | 35 | 35 | **41** | 1.0 → 0.8, `max_words` |
| `sum-17-clockmaker` | validation | 40 | 35 | **44** | 1.0 → 0.8, `max_words` |
| `sum-01`, `02`, `03`, `06`, `07`, `09`, `10`, `12` | train | — | — | — | 1.0 → 1.0 |
| `sum-15`, `sum-18` | validation | — | — | — | 1.0 → 1.0 |

**Zero content checks changed verdict, in either direction.** Every term the
owner required — `Kestrel`, `Marrow Sound`, `Tuesday`, and the fifty-odd
others — is still present in every re-recording. All eight failures are the
word cap, by 1, 2, 2, 2, 1, 4, 6 and 4 words.

That is ADR 0171's central finding replicating on a sample it did not use.
0171 measured nineteen fresh recordings and wrote: *"On this task, at this cap
range, this agent's one reproducible failure is length."* Eighteen more
scenarios, written months earlier by a different worker against a different
model, agree. The failure family is now n = 15 rather than n = 7, and it is
still exactly one family.

### The mechanism, as far as this measures it

On the *identical* prompt — same system message, same user turn, same cap —
Opus writes longer than Fable:

```
n = 18
mean words   Fable 32.28   Opus 35.17     (+2.89)
longer 14    shorter 0     same word count 4
byte-identical summaries: none
```

Fourteen of eighteen longer, **none shorter**, and no two summaries are the
same text. Four land on the same word count by coincidence rather than by
repetition. The cap is the check that broke, and the caps did not move — the
writer did. Nothing here says *why*, and this rig cannot: one task family, one
cap range, one pair of models, n = 18. It should not be cited as a general
claim about either model's verbosity.

## What this changes for the measurements already taken

### ADR 0171's judge A/B (v2) no longer describes this corpus

v2 ran over 17 validation states. Six of them were Fable recordings —
`sum-13-cider-press`, `sum-14-quarry-lake`, `sum-15-bookbinder`,
`sum-16-cliff-path`, `sum-17-clockmaker`, `sum-18-heron-rookery` — and four of
those six have different answers and different verdicts now. So:

- **The pass/fail split it reports is stale.** v2's was 13 pass / 4 fail, and
  its headline is that the LLM judge's 16/17 beats a constant "pass" scoring
  13/17. On today's validation the split is **9 pass / 8 fail**, so a constant
  "pass" now scores 9/17 and the bar that number had to clear has moved.
- **AUC 1.000 was computed over 13 × 4 = 52 pairs.** The same statistic on
  this corpus would be over 9 × 8 = 72, and 8 of the 17 judged states are
  states the judge has never seen.
- `docs/research/i14/results-v2.jsonl` and `report-v2.txt` are therefore a
  record of a measurement, not a description of the corpus, and are left
  untouched and unre-run: re-running the judge costs 34 live calls and this
  worker's budget was 24, of which 19 are spent. **No `results-v3.jsonl`
  exists**, and claiming the v2 number for the current corpus would be wrong.

The corpus is *better* for grading a judge than it was — 8 negatives in
validation instead of 4, 47% of the split instead of 24%, which is closer to
the balance an AUC wants — and that is a reason to re-run v2, not a reason to
assume its answer.

The same caveat applies to ADR 0159's v1 numbers, which were taken when the
whole summary corpus was Fable's.

### ADR 0162's `load_pairs` refusal can be lifted, and should not be deleted

`docs/research/j4/run_j4_selfpref.py:176` refuses a pair whose recording is not
writer A's:

```python
if call.result.model != MODEL_A_NAME:
    raise SystemExit(
        f"{scenario_id}: recorded on {call.result.model!r}, not {MODEL_A_NAME!r}; "
        f"a self-preference control needs writer A to be one model"
    )
```

**Keep that.** It is the guard that caught the defect, and a corpus can mix
models again. What can be lifted is the *exclusion* it forced: `SELECTED` at
`run_j4_selfpref.py:110` lists only `sum-29`…`sum-39` because the other six
were Fable's, and its comment (lines 103–109) says so. On this corpus the
refusal no longer fires on `sum-13`…`sum-18`, so the line for S6's successor
is:

> `SELECTED` may now be the whole validation split — 17 scenarios rather than
> 11 — and with train, 37. The self-preference rig's n rises from 11 pairs to
> 17 (or 37), and its discriminating subset — the pairs where the owner's
> checks separate the two candidates, which was 5 of 11 — grows with the eight
> new negatives. Re-recording writer B's side is 6 more Haiku calls; the
> judging arms are 2 × 6 per judge.

Everything under `docs/research/j4/` is left byte-identical: it is another
worker's file, and its committed data describes the corpus it ran on.

### `corpus/README.md` — the provenance table it should carry

`corpus/README.md` is M7's. It currently names a model in exactly one place
("Nineteen scenarios (`sum-21` … `sum-39`) were recorded live on
`claude-opus-5[1m]`") and says nothing about the other twenty, which is the
sentence ADR 0162 called out. The rows it should carry are in
§"Provenance table for `corpus/README.md`" at the end of this ADR.

Two sentences that should go with the table, because a table of forty rows
does not say them:

- *Every summary scenario in `train` and `validation` was recorded on
  `claude-opus-5[1m]`. The two holdout scenarios (`sum-19`, `sum-20`) are
  `claude-fable-5-1` recordings from ADR 0123 and were deliberately not
  re-recorded, because writing to the holdout is the owner's act
  (`--i-am-spending-the-holdout`); they should not be read as this agent's
  current behaviour.*
- *`tests/harness/test_corpus_provenance.py` asserts this, with the two
  exceptions listed by name, so a mixed-model corpus cannot return silently.*

## The tripwire

`tests/harness/test_corpus_provenance.py`, four assertions:

1. Every scenario with a cassette names one model family, or is one of the two
   declared exceptions — matched as a *set*, so both a new off-family
   recording and a silent re-recording of an exception turn it red.
2. The declared exceptions are holdout-only. If one ever appears in train or
   validation, the reason for excepting it has evaporated and the exception
   must go rather than be inherited.
3. No train or validation summary scenario is off-family, stated separately
   because that is the property a measurement call site depends on: whoever
   selects a gated split and treats it as one model's output is right without
   consulting a list.
4. Every archived Fable recording still matches its replacement on checks,
   initial state, split, `expected`, `budget_ms` **and cassette key** — so the
   claim "only the answer moved" is checkable rather than asserted, for as
   long as both files exist.

Families are compared with the `[1m]` context-window suffix stripped, because
the harness reports `claude-opus-5[1m]` and `claude-opus-5` for one model (ADR
0169) and a guard defeated by a suffix is not a guard — ADR 0162's M3 made the
same point about `PairwiseRanker`.

## Mutations

Each performed for real against the new test: perturb, RUN, restore from a
byte backup whose sha256 is verified after the restore. No `git checkout --`.

| # | mutation | result |
|---|---|---|
| M1 | a train scenario's answer re-attributed to `claude-fable-5-1` | 2 failed — CAUGHT |
| M2 | the holdout silently re-recorded on the corpus model | 1 failed — CAUGHT |
| M3 | a declared exception moved from `holdout/` into `validation/` | 2 failed — CAUGHT |
| M4 | an owner check widened after the recording (`max_words` → 999) | 1 failed — CAUGHT |
| M5 | the passage the run was given edited after the recording | 1 failed — CAUGHT |

5 of 5. The control is `4 passed` before the first mutation and `4 passed`
after the last restore, and every restored file's digest equals its backup's.

M1 and M3 each trip two assertions rather than one, which is the design: M1
breaks both the corpus-wide set and the gated-splits property; M3 breaks both
the holdout-only rule and the gated-splits property, because a Fable recording
in `validation/` is exactly the thing test 3 exists for.

## Green bar

```
pytest -q                                     2724 passed, 7 skipped, 1 xfailed   (from 2720; +4)
mypy aef examples                             Success: no issues found in 135 source files
ruff check .                                  All checks passed!
ruff format --check aef tests examples        281 files already formatted
```

The docker-timing flake ADR 0171 and ADR 0162 both recorded
(`test_a_timed_out_container_is_actually_dead`) did not fire on this run.

## Live budget

**19 of the 24 allowed.**

| what | calls |
|---|---|
| quota preflight, ADR 0150's argv, session default (`is_error false`, `input_tokens 2`, `modelUsage` → `claude-opus-5[1m]`) | 1 |
| `sum-01`, recorded alone first to verify the argv before spending the rest | 1 |
| `sum-02`…`sum-07` | 6 |
| `sum-08`…`sum-12` | 5 |
| `sum-13`…`sum-18` | 6 |

No call was retried, none failed, every `stop_reason` was `end_turn`, and
every one resolved to `claude-opus-5[1m]` with `model_attribution:
"usage_match"` (ADR 0169). The raw preflight is in this worker's scratch; the
per-call evidence is the cassettes themselves, which is the point of them.

Five calls were left unspent deliberately. Re-running the judge A/B needs 34.

## Confidence

**High that the corpus is now one model on the splits anything reads.** It is
read out of the cassettes by a test, not asserted, and the test kills five
mutations including the two ways it could regress silently.

**High that only the answer moved.** The cassette key is a hash of the
request and every one is unchanged; the archive makes the claim re-checkable
by anyone, indefinitely.

**High on the score movement.** Both scores are cassette replays with 37 hits
and 0 misses, so there is no live variance in either number; the same command
produced both.

**Medium on what the score movement means.** It is a *measurement of the model
that answered*, not a regression in anything, and a reader could easily
misread a corpus mean falling as the agent getting worse. Nothing about
`agents/summary` changed. What changed is that eight summaries written by a
model that writes ~3 words longer went over caps that ADR 0123 set against a
model that wrote shorter — and four of the eight overran by 4 to 6 words,
which is more than the mean shift explains on its own.

**Low on any generality.** One task family, one cap range, one pair of models,
n = 18, and the caps were not chosen with this comparison in mind.

## Provenance table for `corpus/README.md` (M7's file)

| scenario | split | recorded on | recorded | ADR |
|---|---|---|---|---|
| `sum-01-kestrel-ferry` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-02-orchard-blight` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-03-tidewell-library` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-04-halden-reservoir` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-05-bramble-bakery` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-06-weir-otters` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-07-signal-box` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-08-glasshouse-tomatoes` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-09-choir-tour` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-10-clay-pit` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-11-lantern-festival` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-12-bell-recast` | train | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-13-cider-press` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-14-quarry-lake` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-15-bookbinder` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-16-cliff-path` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-17-clockmaker` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-18-heron-rookery` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0186 |
| `sum-19-tram-depot` | holdout | **`claude-fable-5-1`** | 2026-09-04 | 0123 |
| `sum-20-seed-bank` | holdout | **`claude-fable-5-1`** | 2026-09-04 | 0123 |
| `sum-21-ardvey-ferry` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-22-marlowe-street` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-23-cransley-cut` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-24-pellow-mill` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-25-hollin-bridge` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-26-netherby-clinic` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-27-sallow-vale` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-28-kellet-branch` | train | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-29-brindle-viaduct` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-30-ganister-tarn` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-31-quernmore-kiln` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-32-hessle-mills` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-33-cotterdale-bus` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-34-alder-carr` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-35-priory-gatehouse` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-36-larkfield-quarry` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-37-ryhope-pool` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-38-bewick-refusals` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |
| `sum-39-coldbeck-society` | validation | `claude-opus-5[1m]` | 2026-09-05 | 0171 |

The eleven `agents/demo` scenarios (`easy-*`, `boundary-*`, `hard-both-*`,
`val-*`, `tripwire-*`) make no model call and have no model provenance to
state; `README.md`'s "What this seed corpus covers" section is about them.

## Errata filed on other ADRs

- **ADR 0162, defect 1** — the count is 20, not 18 or 6: `sum-19-tram-depot`
  and `sum-20-seed-bank` in the holdout are also `claude-fable-5-1`. The
  eighteen re-recordable ones are re-recorded here; the two holdout ones are
  declared exceptions and remain the owner's decision.
- **ADR 0171, part 3** — its v2 judge A/B ran over a validation split of which
  6 of 17 states were Fable's, and 4 of those 6 have different verdicts now.
  Its AUC 1.000 and its 13/17 constant baseline describe `results-v2.jsonl`,
  not this corpus.
- **ADR 0123** — the twenty scenarios it recorded were recorded on
  `claude-fable-5-1`, which it does not say. Eighteen of them now answer on
  `claude-opus-5[1m]`; the Fable recordings are kept whole under
  `docs/research/i14/fable-recordings/`.
