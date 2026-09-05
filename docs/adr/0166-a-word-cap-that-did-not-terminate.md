# ADR 0166: A word cap that did not terminate, and a 0.0000 that would not say why

## Status
Accepted. Fix worker D2 of the upgrade loop, closing ADR 0156 §D2 and the
"further defect" ADR 0156 reported against `aef loop score --json`.
No rubric dimension moves — this is a defect fix, not a measurement.

## Context

ADR 0156 §D2 found, from a `faulthandler` stack past a 45-second wall, that
the scorer was not waiting on a model. It was inside `re.search`.

Every summary scenario in `corpus/` declared its word cap as
`^(?:\s*\S+){1,N}\s*$`. The inner `\s*` is nullable, so two adjacent
iterations may split one non-space run at any position, and the number of ways
to cut a k-character string into ≤ N runs is exponential in k. A **match**
short-circuits on the first greedy path. A **failure** — a summary one word
over the cap — must exhaust every one of them, and
`aef/harness/checks.py::_holds` calls `re.search` with no timeout.

Every recorded cassette sits at or under its cap, so no green test in this
repo ever reached the failing branch and every live gate pass could. It cost
I11 three attempts past a ten-minute wall, which ADR 0123 recorded as a
suspected throttle, and it cost ADR 0156's own increment four more; S2 had to
score on a rewritten scratch copy of the corpus to produce any number at all.

## The reproduction

Run before anything was changed, each pattern in a **child process** under a
wall clock, because the parent cannot time a call that never returns
(`redos_repro.py`, `redos_path_repro.py`, both under the worker's scratch;
the second goes through this repo's own code, not a copy of the pattern):

```
corpus pattern : ^(?:\s*\S+){1,35}\s*$
linear pattern : ^\s*\S+(?:\s+\S+){0,34}\s*$
at-cap input   : 35 words
over-cap input : 36 words

corpus pattern, 35 words (at cap)              match=True  in 0.47 ms
corpus pattern, 36 words (ONE OVER)            DID NOT TERMINATE in 8 s
linear pattern, 35 words (at cap)              match=True  in 0.19 ms
linear pattern, 36 words (ONE OVER)            match=False in 0.18 ms
```

Through `checks._holds` and `evaluation.score_scenario`, on the real
`corpus/validation/sum-13-cider-press.json`:

```
scenario       : sum-13-cider-press.json
corpus pattern : ^(?:\s*\S+){1,35}\s*$

_holds, corpus pattern, 35 words (at cap)                  -> True in 0.01 ms
_holds, corpus pattern, 36 words (ONE OVER)                DID NOT TERMINATE in 8 s
score_scenario, summary of 35 words (at cap)               -> 0.25 in 0.06 ms
score_scenario, summary of 36 words (ONE OVER)             DID NOT TERMINATE in 8 s
```

And the same two lines after the fix, same script, same scenario file:

```
corpus pattern : ^\s*\S+(?:\s+\S+){0,34}\s*$

_holds, corpus pattern, 36 words (ONE OVER)                -> False in 0.02 ms
score_scenario, summary of 36 words (ONE OVER)             -> 0.0 in 0.06 ms
```

One word over the cap was the difference between 0.05 ms and never, on
exactly the input the check exists to catch.

## Decision

Four changes, each of which closes the defect on its own.

### 1. `max_words` and `min_words` — the cap, with no regex in it

`OPS` gains `max_words` and `min_words`: `len(str.split()) <= N` and
`>= N`. The value must be a non-negative `int` (`bool` is rejected — a check
reading `"value": true` is a mistake, not a cap of one), and a **non-string**
target fails the check rather than being stringified, because
`len(str([1, 2]).split())` is 2 and a check that silently passes on the wrong
kind of value is worse than one that fails loudly on it.

This is what the corpus was trying to say. It cannot backtrack.

### 2. The corpus keeps a regex, and this is the deviation worth reading

The obvious migration is "replace the regex with `max_words`". It is wrong,
and measuring it is what showed that.

`^(?:\s*\S+){1,N}\s*$` is **1 ≤ tokens ≤ N**, not `tokens ≤ N`: the `{1,`
gives it a lower bound. Over 12,000 generated strings (4,000 per cap
30/35/40, varying token count, token content, separator width and
leading/trailing space, restricted to the region where the original
terminates), three candidate rewrites disagree with the original **zero**
times. They separate on exactly one input — the one ADR 0156 leaned on:

```
the input the arms differ on — an empty / whitespace-only summary
(the original decides it in O(1): `{1,` cannot be satisfied):
  ''       original=False  safe_regex=False  max_words_only=True   max_and_min_words=False
  '   '    original=False  safe_regex=False  max_words_only=True   max_and_min_words=False
  '\n'     original=False  safe_regex=False  max_words_only=True   max_and_min_words=False
```

A bare `max_words` **accepts an empty summary**. ADR 0156 established that a
provider returning `""` and a provider that raises both give
`score 0.0000, cost_tokens 0` for these scenarios, and used that to attribute
repeat 3's zero to a failed call. Migrating to `max_words` alone would have
turned that 0.0000 into 0.25 and quietly retired the signal. Adding
`min_words: 1` restores the predicate exactly — but it is a **fifth** check on
a four-check scenario, so every recorded score moves (`0.75` → `0.80`), and
the metric is no longer the metric ADR 0123 recorded.

So the twenty existing scenarios keep one check, rewritten to the linear form
`^\s*\S+(?:\s+\S+){0,N-1}\s*$` — the separator `\s+` is not nullable, so every
iteration boundary is forced. `max_words`/`min_words` are the ops **new**
scenarios should use, and the refusal message says so.

**The migration list** — twenty files, one line each, `checks` the only key
that moved (asserted per file by a JSON diff over every top-level key, then by
`git diff --stat`: 20 files changed, 20 insertions, 20 deletions):

| cap | from | to | scenarios |
|---|---|---|---|
| 30 | `^(?:\s*\S+){1,30}\s*$` | `^\s*\S+(?:\s+\S+){0,29}\s*$` | sum-03, sum-06, sum-09, sum-12, sum-15, sum-18 |
| 35 | `^(?:\s*\S+){1,35}\s*$` | `^\s*\S+(?:\s+\S+){0,34}\s*$` | sum-01, sum-05, sum-08, sum-11, sum-13, sum-16, sum-19 |
| 40 | `^(?:\s*\S+){1,40}\s*$` | `^\s*\S+(?:\s+\S+){0,39}\s*$` | sum-02, sum-04, sum-07, sum-10, sum-14, sum-17, sum-20 |

Every pattern in the corpus was a word cap of this one shape; none needed a
per-pattern judgment beyond the cap number.

**The metric is unchanged.** `aef loop score
agents.summary.graph:build_graph --corpus corpus --splits train,validation
--json`, before and after, `diff`ed: **identical, byte for byte**.

```
train      mean 0.9792  stdev 0.0722  ci95 [0.9383, 1.02]   n=12  cost 920
  sum-01 1.0  sum-02 1.0  sum-03 1.0  sum-04 1.0  sum-05 1.0  sum-06 1.0
  sum-07 0.75 sum-08 1.0  sum-09 1.0  sum-10 1.0  sum-11 1.0  sum-12 1.0
validation mean 0.9167  stdev 0.1291  ci95 [0.8134, 1.02]   n=6   cost 457
  sum-13 1.0  sum-14 0.75 sum-15 1.0  sum-16 0.75 sum-17 1.0  sum-18 1.0
cassette: 18 hits, 0 misses, on_miss=fail
```

ADR 0123's numbers, including all three `0.75` content failures.

### 3. A static detector, at load and again before every search

Python's `re` has no timeout and this repo takes no dependency for one
(CLAUDE.md), so the defence is static. `refuse_catastrophic_regex` refuses a
pattern with a repeated group that can match one input many ways:

1. a repeated group whose body contains a **nullable** quantifier (`*`, `?`,
   `{0,m}`) — `(?:\s*\S+){1,35}`, the corpus's cap. A nullable separator lets
   two adjacent iterations split one token.
2. a repeated group whose body is a **single unbounded-quantified atom** —
   `(a+)+`, `(a*)*`, `(a+)*`, the textbook case.

It runs in `TaskCheck.__post_init__`, so a corpus carrying the old cap is
refused **at load** rather than hanging one scenario at score time, and again
inside `_holds`, which is the only place a pattern meets an input.

This is not a decision procedure for regular-expression ambiguity — that needs
an automaton — and it refuses a few safe patterns (`(?:a*b){1,5}` is linear
and would be refused). The direction of the error is deliberate: a
refused-but-safe pattern is a loud message carrying its own rewrite; a missed
unsafe one hangs the scorer forever and looks like a slow model.

**Verified against a planted fault before being trusted.** Ten patterns that
must be refused, eleven that must pass — including the safe rewrite itself,
because a fix whose error message recommends a pattern the detector then
rejects is a dead end:

| must refuse | must pass |
|---|---|
| `^(?:\s*\S+){1,35}\s*$` (S2's exact pattern), `{1,30}`, `{1,40}` | `^\S+$`, `(?:foo\|bar){1,3}`, `\bword\b` |
| `(a+)+`, `(a*)*`, `(a+)*`, `^(\S+)+$` | `^\s*\S+(?:\s+\S+){0,34}\s*$` and the 29/39 forms |
| `(?:x?y){2,}`, `((?:ab)+)+`, `(?:a\|b*){2,}` | `lesson`, `[()]+`, `\(\d+\)`, `(?:\d{2,4})`, `^a{2,3}$` |

All 21 agree. And planted in a scratch corpus file, `load_scenario` refuses
it, names the file, and leads with `unusable check:` rather than `malformed
scenario payload:` — the pattern parses perfectly; what is wrong with it is
that running it would not return.

**The length backstop, and what it deliberately does not do.** Truncating a
long input before matching would answer a different question than the check
asked — "at most 35 words" of the first 10,000 characters is not the same
predicate — so `_holds` does not truncate. Instead, an input over
`MAX_REGEX_INPUT_CHARS` (10,000) against a pattern carrying **any** repeated
group is refused with a reason, because the detector above is conservative
rather than a proof. A pattern with no repeated group is unaffected at any
length; so is `contains`.

> **ERRATUM (ADR 0177, fix worker J1).** Two corrections, and they are
> different mistakes.
>
> **"any repeated group" was the wrong rule, not merely a conservative one.**
> A **bounded** quantifier's iteration count does not grow with the input:
> `(x )?` enters its body at most once and `(?:\s+\S+){0,34}` at most 34
> times, whatever length you hand them, so the length of the input tells you
> nothing new about them. Measured at 12,000 characters, this backstop refused
> **six of the eleven `MUST_PASS` patterns above** — including all three
> word-cap rewrites the refusal message recommends, and both of ADR 0171's
> shipped content checks, each of which decides that input in under 0.4 ms.
> The `MUST_PASS` list was verified against the **detector** and never against
> the **backstop**. The backstop now keys on an UNBOUNDED quantifier (`+`,
> `*`, `{n,}`) via `_unboundedly_repeated_group_bodies`; the static detector
> in §3 is unchanged and still refuses both families at load.
>
> **And a refusal was suite-fatal, which is the opposite of this section's own
> intent.** The design argument for refusing at load is that one bad check
> should cost one file rather than the run — but `_holds`'s refusal raised
> through `score_scenario`, which sat OUTSIDE the try/except in **both**
> scoring paths (`scenario_runner.run_scenario`, `isolated_suite._run_one`),
> so one scenario's raise killed the corpus: reproduced as
> `aef loop score … error: refusing to run regex check … EXIT=1` with the
> second, perfectly scorable scenario never run. A raising check now scores
> that scenario 0 with `failure = "unusable check: …"` and the run's REAL
> outcome. See ADR 0177 §R5.

### 4. `loop score --json` says which kind of zero it is

ADR 0156 had to infer from split-level token accounting that repeat 3's
`sum-13: 0.00` was a failed call rather than a wrong answer, because
`run_scenario` computes both the `failure` string and the list of failed
checks and `cmd_score` emitted **neither**. Each split row now carries an
`attribution` object — present only for scenarios that have something to say —
and the human output prints the same lines under each score.

The two shapes, from `tests/cli/test_loop_score.py` (one model-calling graph,
a stub provider, two scenarios differing only in whether the cassette can
answer). Both score `0.0000`; before this key existed, that was the whole
report:

```json
"per_scenario": {"provider-died": 0.0, "wrong-answer": 0.0},
"attribution": {
  "provider-died": {
    "failure": "ModelProviderError: cassette miss ..."
  },
  "wrong-answer": {
    "checks": "0/1 passed",
    "checks_failed": ["working_memory.answer contains 'red': got 'blue'"]
  }
}
```

On the real corpus it immediately explains the two long-standing `0.75`s,
which ADR 0123 had recorded in prose:

```json
"sum-14-quarry-lake": {
  "checks": "3/4 passed",
  "checks_failed": ["working_memory.summary contains 'swimming': got 'Swimming will be permitted at Ketley quarry lake ...'"]
}
```

— the model capitalised the term at the start of a sentence and `contains` is
case-sensitive.

## Consequences

1. **ADR 0156 §D2 consequence 4 is discharged.** "D2 blocks every live
   measurement in this repo until it is fixed" no longer holds: a live run
   whose model overruns a word cap now scores 0 for that check in
   microseconds. The four live measurement increments queued behind this can
   proceed.
2. **A live 0.0000 is now attributable without spending a call.** The
   distinction ADR 0156 established with `zero_signature.py` and token
   arithmetic is in the report.
3. **The old cap cannot come back.** It is refused at scenario load, so a
   scenario carrying it fails the whole corpus rather than hanging one score,
   and `tests/harness/test_check_patterns.py` asserts the property over the
   real `corpus/` rather than over an example.
4. **`min_words` exists but is unused on disk.** The twenty migrated scenarios
   keep the equivalent regex; using `max_words` + `min_words` there would be
   correct and would change every recorded score, which is a decision for
   whoever next re-records the corpus, not for a defect fix.

## Mutations

Each performed for real: perturb, run, restore from a byte backup, prove the
restore by sha256.

| # | mutation | result |
|---|---|---|
| M1 | `refuse_catastrophic_regex` returns immediately | 1 failed |
| M2 | `max_words` compares the wrong way round | 1 failed |
| M3 | `_holds` skips the defence-in-depth refusal | 1 failed |
| M4 | `cmd_score` drops the `failure` string again | 1 failed |
| M5 | one corpus scenario keeps the old word cap | 1 failed |

5 of 5 caught; every `before`/`after`/`backup` sha256 equal.

**M3 found a weak test on the way, and the test was fixed rather than the
mutation dropped.** With the refusal removed from `_holds`, the
defence-in-depth test did not go red — it **hung**, which is the defect
itself, and a hanging test is not a failing test. It now runs `_holds` in a
child process under a wall clock and asserts the outcome, so removing the
refusal fails in 5 seconds instead of never. The reproduction test for the
original pattern is built the same way, and for the same reason.

## Green bar

```
pytest -q                      2178 passed, 5 skipped   (from 2131; +47 —
                               44 in tests/harness/test_check_patterns.py,
                               3 in tests/cli/test_loop_score.py, 6 -> 9)
mypy aef examples              Success: no issues found in 131 source files
ruff check .                   All checks passed!
ruff format --check            252 files already formatted
```

## Reported, not fixed

- The `--check` help text in `aef/cli/loop.py` and the docstrings here list
  the ops. **No generated document lists them**: `grep "contains"` across
  `aef/cli/adopt.py`, `aef/cli/adopt_loop.py` and `aef/cli/templates/` finds
  nothing, so an adopted repo learns the check ops from `AGENT_INTEGRATION.md`
  and the CLI's own help, and neither needed an edit here. Recorded so M2 does
  not go looking.
- ADR 0156's third defect — `ClaudeCodeProvider` attributing the answer with
  `next(iter(model_usage))` — is another worker's; ADR 0154 reports it fixed
  by `answering_model()`, and nothing here touches `aef/providers/`.

## Confidence

High on the defect and on the fix: both reproduced by running, through this
repo's own code path, and the replayed metric comes back byte-identical.

High on the migration's equivalence: 12,000 generated strings per rewrite plus
the whole metric, and the one input where the candidates differ is stated
rather than averaged away.

**Medium on the detector's completeness.** It catches the two families this
corpus and the literature produce and is verified against 21 patterns, but it
is a syntactic rule, not an ambiguity decision procedure. A pattern outside
those two shapes could still backtrack badly; the 10,000-character backstop
narrows that, and does not close it. What is fully closed is the shape that
was actually here.
