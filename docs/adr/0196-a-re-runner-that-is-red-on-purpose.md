# ADR 0196: `make measure`, and it is red on purpose

## Status

Accepted. Worker **N5** of `ABOVE_95_LOOP.md` (increment N5, next-steps #8),
branch `upgrade/n5-measure-and-redaction`. Closes ADR 0188's dimension-5
deduction. Errata appended to ADR 0159 and ADR 0175 below.

## Context

ADR 0188 (J0b, the second independent score) gave dimension 5 nine of ten and
named the missing point exactly:

> several headline numbers reach a reader as docstring prose with the data one
> directory away and no re-runner (`make measure`) that regenerates the tables
> in CI

ADR 0191 then supplied the cost of that gap in a single line: S1c's `+2` was
**withdrawn because its seed no longer reproduced on the current tree**. The
corpus had moved to one model (ADR 0186); a table published three days earlier
had quietly stopped describing anything. It was found a night later, by hand,
during a hunt. A re-runner would have found it the day the corpus moved, which
is the whole argument for building one.

## Decision

`docs/research/measure.py`, driven by `make measure`, and a shared `--verify`
mode on every runner.

**The ADR is the expectation, not a constant.** Each pinned row carries two
regexes: one extracts the number from the runner's stdout, the other extracts
it from the ADR paragraph that publishes it. Drift is `ADR says X, re-derived
Y`. Perturbing a number in an ADR therefore fails exactly like perturbing the
data — which is the mutation `tests/test_measurements_reproduce.py::
test_a_perturbed_published_number_is_caught` runs, against a symlinked shadow
tree so no committed file is touched.

**Zero live calls, by construction.** Every `--verify` reads committed JSON /
JSONL, or replays a cassette under `on_miss="fail"`. No mode of this tool can
spend a token.

**No committed result file was edited.** Where a committed `report*.txt`
disagrees with its ADR, the ADR is pinned and the artefact is named as stale
(below). Rewriting an artefact to match a later correction would delete the
record of what was true when it was produced.

### The shared interface, and who needed changing

| runner | before | change |
|---|---|---|
| `i14/run_i14.py` | had `--report` | `--verify` alias |
| `j2/run_j2.py` | had `--report` | `--verify` alias |
| `j4/run_j4_selfpref.py` | had `--report` | `--verify` alias |
| `j4/run_j4_harm.py` | had `--report`/`--tally` | `--verify` alias |
| `i12b/aggregate.py` | printed unconditionally, no flags | `--verify` accepted |
| `i12c/aggregate.py` | printed unconditionally, no flags | `--verify` accepted |
| `i12/aggregate.py` | **raised `FileNotFoundError`** | data path fixed, `--verify`, writes only under `--write` |
| `i12c/seed.py` | `--out` required, always wrote | `--verify`, `--out` optional |
| `i12b/seed.py` | `--out` required | `--verify`; **still does not run**, see below |
| `i13/` | **no aggregator at all** | new `i13/verify.py` |
| `pilot-marlin/scan_control.py` | needed an uncommitted runs dir | `--verify` against a stand-in objective |

Four of the eleven already had a report mode and needed only an alias. Three
were fine and needed only the flag. **Four could not produce their published
table at all**, and that is the finding this increment was not looking for.

## What running it found

`make measure` on this tree: **48 rows reproduce, 5 expected drifts, 0
unexplained**, exit 1.

### 1. ADR 0155's table had a runner that could not run

`i12/aggregate.py` resolved `HERE = Path(__file__).parent / "results"`. The raw
JSON was flattened into `docs/research/i12/` at some point after the
measurement; the script had raised `FileNotFoundError` on every invocation
since. With the path fixed it reproduces ADR 0155 exactly — 0.8541 / 0.8541 /
0.8334 / 0.9166, spread 0.0833, 84 calls. The numbers were right. Nothing could
check that.

### 2. ADR 0175's step-0 table has no runner on this tree at all

`i12b/seed.py` imports `write_check_failure_record`, which ADR 0180 removed in
favour of `record_check_outcomes`. It raises `ImportError` before reaching any
measurement. This is recorded, not fixed: making it run would mean re-pointing
it at a producer that computes something different, and the resulting number
would not be the one ADR 0175 published.

### 3. ADR 0184's seed — the case this tool exists for

```
=== i12c-seed — S1c step 0 — the seed ADR 0184's +2 rests on
    ok    train scenarios                              20
    XFAIL failure records                              ADR says '3', re-derived '7'
    XFAIL records the excerpt property covers          ADR says '23', re-derived '27'
    XFAIL entry recurrence (distinct runs)             ADR says '3', re-derived '7'
    ok    consolidated entries                         1
```

**This failure is expected and is the withdrawn row's evidence.** ADR 0191 F3
withdrew S1c's `+2` on exactly this fact, having found it by hand. The four
rows above are that finding, mechanised: the drift is now named, quantified on
both sides, and re-checked on every `make measure`. Note that `train scenarios`
and `consolidated entries` still reproduce, and that `i12c-arms` — the arm
tables, read from the committed `arms.jsonl` — reproduces in full. It is the
seed underneath that moved, which is precisely why 0191 withdrew the score
rather than the table.

### 4. ADR 0159's oracle B was stale and nobody had said so

`run_i14.py --report` recomputes one block live from `corpus/`: oracle B, the
case-insensitive re-scoring. Everything else it prints comes from
`results.jsonl`. So when the corpus moved to one model, oracle B moved with it:
**ADR 0159 publishes 18/18 pass, rule 0/18, LLM 18/18; the same command today
derives 10/18, 8/18, 10/18.** ADR 0186 disclosed exactly this drift for the *v2*
run and did not check v1. The v2 pin now passes against ADR 0186's own
corrected number (9 pass), which is what a disclosure that was acted on looks
like.

### 5. `report-tally.txt` is a pre-correction artefact

`j4/run_j4_harm.py --tally` derives `helpful=6 harmful=3`. The committed
`report-tally.txt` says `helpful=7`. ADR 0180 §66 already publishes the
corrected `helpful=6 harmful=3 harmful_elsewhere=1` — the `.txt` is simply the
run from before `_tally` was fixed and was never regenerated. The pin is
against the ADR; the artefact is left alone and labelled.

## Red on purpose, and green in CI

`make measure` exits 1 while any row drifts, **including an explained one**. A
published number that no longer re-derives is a number nobody should cite,
whether or not an ADR says why. Softening that would turn the tool into
decoration in one commit.

CI therefore runs `make measure-ci` (`--fast --against-expectations`), which
fails when the drift set **changes**:

- a new drift fails — the regression this exists to catch;
- a *healed* drift also fails, so a note whose explanation has gone stale
  cannot outlive the drift it explains. If N2's re-run makes ADR 0184's seed
  reproduce again, CI goes red until the note comes out.

`tests/test_measurements_reproduce.py` runs the same fast subset as pytest, and
additionally asserts that every `known_drift` note names an ADR — a note that
explains nothing is a silencer.

**Where the fast/slow line is drawn**: fast is "reads committed JSON/JSONL",
about ten seconds for the whole subset; slow is "replays a corpus through a
cassette", which is `i12b/seed.py` and `i12c/seed.py` and takes tens of seconds
each. The slow pair is left to `make measure`. That means CI does **not**
re-check ADR 0184's seed on every push — stated plainly, because the seed is
the most interesting row in the file.

## What is not re-derivable, named rather than omitted

`measure.py --list` prints these with their reasons: `pilot-marlin/
scan_runs.py` and `repro_two_blockers.py` (need marlin's `.aef/runs`, which ADR
0163 deliberately does not commit), `second-repo/` (transcripts, not a table),
the two ReDoS timing reproductions (wall-clock assertions, not pinned in CI),
and the two `boost_sweep.py` scripts (downstream of the same seed as
`i12c-seed`, and drifting with it).

## Errata

- **ADR 0159** — its oracle-B block (18/18 pass; rule 0/18; LLM 18/18; AUC
  "n/a, one class only") describes `corpus/` as it stood before ADR 0186 moved
  it to one model. On today's corpus the same command derives 10/18, 8/18,
  10/18, AUC 0.469. The headline it is quoted for — rule 3/18, LLM 15/18, the
  two judges 0/18 — is unaffected and still re-derives, because it comes from
  the committed results file.
- **ADR 0175** — its step-0 seed table cannot be reproduced: `i12b/seed.py`
  does not import on this tree (finding 2 above). The arm tables it publishes
  do re-derive, exactly.

## Consequences

- Eleven runners, one `--verify`. A twelfth measurement is one registry entry.
- Two ADRs were found to publish numbers that no longer describe the repo, and
  one runner was found to have been broken for weeks — all of it in the first
  run of the tool, none of it visible to anything that existed before.
- `make measure` is red. Anyone reading the rubric's dimension-5 row should
  read that as the tool working, not as the repo failing.

## Confidence

High on the mechanism: the perturbation mutation is automated and passes, the
i12 path fix is proved by the table reproducing, and every drift above was
produced by running a command rather than by reading a file. Medium on
coverage: 53 rows across 13 measurements is a sample of the numbers those ADRs
publish, not all of them — an unpinned row still drifts silently, and adding
rows is the cheapest work in this file.
