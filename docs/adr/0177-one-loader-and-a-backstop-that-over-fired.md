# ADR 0177: One loader, and a backstop that over-fired

## Status

Accepted. Fix worker **J1** of the upgrade loop, closing **R1** (HIGHEST),
**R5** and **R1's tail** from the third seam hunt. Model: `claude-opus-5[1m]`.
**Zero live model calls** — every reproduction below is a filesystem fact, a
subprocess or a regex timing, and none of them needs a model. **No rubric
dimension moves.**

Three findings, one shape between two of them and the shape is ADR 0091's: a
fact with more than one owner, kept correct in one of them. What spelling of a
graph entrypoint this repo accepts had **three** owners and ADR 0168 taught
one. What "this regex could blow up" means had one owner and it asked the wrong
question of a length.

---

## R1 (HIGHEST) — `--entrypoint` could not name a graph under a widened root, and G2 blamed the candidate

### Reproduced

`aef migrate --dir . --agent-root .claude/agents` is ADR 0152 §4's opt-in and
the **only** way a persona becomes Zone A. Run on the seam hunt's `r1` clone,
whose `.claude/agents/reviewer.md` is a prompt-file agent:

```
$ aef migrate --dir . --agent-root .claude/agents
wrote 1 prompt agent graph(s):
  <clone>/.claude/agents/migrated/reviewer/graph.py
EXIT=0

$ find . -name graph.py -not -path './.git/*'
./.claude/agents/migrated/reviewer/graph.py
./agents/migrated/graph.py

$ aef loop score '.claude/agents/migrated/reviewer/graph.py:build_graph' \
    --corpus corpus --splits train --config aef.yaml
error: the 'package' argument is required to perform a relative import
for '.claude/agents/migrated/reviewer/graph.py'
EXIT=1
```

Exit 1 is `EXIT_REJECTED`. ADR 0168 §M4 fixed exactly this error for `aef run`
by teaching `aef/cli/run.py::import_graph_module` the file form — and there
were **three** loaders. `aef/harness/scenario_runner.py:47` and
`aef/harness/node_worker.py:53` each kept their own
`importlib.import_module`, so the fix reached `aef run` and `aef loop record`
and neither of the two the gates use.

Through `aef loop cycle` it is worse than a refusal, because the two sides of
G2 used **different** loaders. The incumbent's outcome is reconstructed from
the recording (`recorded_outcome`, derived from a scenario `aef loop record`
could load, because `aef loop record` goes through `aef run`'s importer); the
candidate is executed by `node_worker`, which could not load it. Reproduced
through the real gate, on a real git repo with a widened `ZonePolicy`:

```
G2 outcome : fail
G2 reason  : 1 previously-passing scenario(s) no longer pass (zero tolerance)
  evidence : s1: REGRESSION — incumbent passed (plan=done, 0 error(s));
             candidate did not (terminated=False, plan=None, 1 error(s), 0 policy denial(s))
```

The worker had said something much more specific, and it was thrown away at
`g2_outcome.py`'s `return {sid: r.outcome for sid, r in results.items()}`:

```
$ python -c "run_corpus_isolated(ws, [s], entrypoint='.claude/agents/migrated/reviewer/graph.py:build_graph')"
failure: IsolationError: worker for '.claude/agents/migrated/reviewer/graph.py:build_graph'
failed: cannot import '.claude/agents/migrated/reviewer/graph.py': TypeError: the 'package'
argument is required to perform a relative import for '.claude/agents/...'
```

`ScenarioResult.failure` existed, was populated, and had no reader.

So on the documented opt-in **every prompt candidate is rejected forever**, and
two consecutive rejections halt the loop — with a ledger saying the candidate
regressed the corpus, which is false.

### Erratum on ADR 0168

ADR 0168 §M4's decision reads:

> `aef/cli/run.py::import_graph_module(module_path)` — **the one importer**,
> used by `run_graph_module` **and** `load_graph_module` (which `aef loop
> record` shares), replacing the two copies of `importlib.import_module` that
> were there.

"The one importer" was true of `aef/cli/run.py` and false of the repo. The
`grep` that would have found it is one line, and it is now a test
(`test_no_graph_loading_call_site_still_calls_import_module_directly`, an AST
scan rather than a text scan, because three of these files now *discuss*
`importlib.import_module` in a comment explaining why they no longer call it).

ADR 0168's own "Not fixed here, reported" section names `aef/cli/loop.py`'s
module arguments and stops there; the harness's two loaders are not in it. The
reason is visible in the ADR's evidence: every M4 reproduction ran `aef run`,
and `aef run` was the loader that got fixed.

### Decision — one loader, in the harness

`aef/harness/graph_loading.py` holds `import_graph_module`,
`looks_like_a_path`, `ensure_cwd_importable` and a new `split_entrypoint`.
It is in the **harness**, not the CLI, for the reason `aef/harness/zones.py`
already carries `DEFAULT_AGENT_PATH`: the harness may not import the CLI, so
the CLI imports the harness. `aef/cli/run.py` imports the three published
names and binds `_ensure_cwd_importable` as an alias, so
`from aef.cli.run import import_graph_module` keeps working — three test
modules and the generated `AGENT_INTEGRATION.md` reach for it — while there is
one implementation.

Call sites switched, all of them:

| call site | before | after |
|---|---|---|
| `aef/cli/run.py::import_graph_module` | the definition | re-export of `aef.harness.graph_loading` |
| `aef/cli/run.py::load_graph_module`, `run_graph_module` | the local definition | the harness's, unchanged behaviour |
| `aef/harness/scenario_runner.py::load_graph` | `importlib.import_module` | `import_graph_module` |
| `aef/harness/node_worker.py::load_graph` | `importlib.import_module` | `import_graph_module` |

`aef/config/domain_gates.py:121` also calls `importlib.import_module` and is
deliberately untouched: it imports an **evaluator suite**, not a graph, and no
`--agent-root` moves one.

`split_entrypoint` splits on the **last** colon, not the first, because
`C:\x\graph.py:build_graph` is a path with two of them; and a bare `graph.py`
with no factory is refused rather than read as a module with an empty
attribute.

**(b) the worker names what it could not load.** `node_worker.load_graph`
already caught `BaseException`, which covers the `TypeError` — but its message
was `cannot import '<module>'` with no entrypoint, and the parent reports that
string verbatim. It now reads `cannot import '<module>' (from entrypoint
'<entrypoint>'): TypeError: ...`. `scenario_runner.load_graph` caught
`ImportError` **only**, and `importlib.import_module` raises `TypeError` for a
leading dot — which is exactly how the error escaped `load_graph`, escaped
`cmd_score`, and reached the CLI's catch-all. It catches `ImportError`,
`ValueError` and `TypeError` now and names the entrypoint too.

**(c) G2's verdict carries the failure text.** `_execute` returns
`(outcomes, failures)`; the reason line gains `N of them failed rather than
answered: <first line, ≤200 chars>` and each regression's evidence line gains
the same excerpt. A candidate that ran and answered differently is unaffected
(`_why_note(regressed, {}) == ""`), which is the control.

### After (verbatim)

```
$ aef migrate --dir . --agent-root .claude/agents
wrote 1 prompt agent graph(s): <clone>/.claude/agents/migrated/reviewer/graph.py
EXIT=0

$ aef loop score '.claude/agents/migrated/reviewer/graph.py:build_graph' \
    --corpus corpus --splits train --config aef.yaml
task metric — .claude/agents/migrated/reviewer/graph.py:build_graph (reviewer) — repeat=1
  model calls: 1 cassette hit(s), 0 miss(es), on_miss=fail — replayed
  train       n=1   with_checks=1   mean=1.0000 stdev=0.0000 ci95=[1.0000, 1.0000] repeat_spread=0.000000
      1.0000  rev-1
EXIT=0
```

A stub `command` provider (`argv: ["/bin/sh", "-c", "...printf 'VERDICT: pass...'"]`)
answered the model call — a real provider, a real subprocess, no live call.

And the gate, on the same shape of entrypoint:

```
G2 outcome : fail
G2 reason  : 1 previously-passing scenario(s) no longer pass (zero tolerance)
             1 of them failed rather than answered: IsolationError: worker for
             '.claude/agents/migrated/reviewer/graph.py:build_graph' failed: cannot import
             '.claude/agents/migrated/reviewer/graph.py' (from entrypoint '.claude/agents/…
  evidence : s1: REGRESSION — … — IsolationError: worker for '.claude/agents/…' failed:
             cannot import '.claude/agents/…'
```

Still a FAIL, and it should be — the gate has no evidence of non-regression.
What changed is that the ledger now says *why*, so an operator reads "the
entrypoint is wrong" instead of "the candidate broke the corpus".

### R1's tail — the two sides of G2 load identically

`test_both_sides_of_g2_resolve_a_widened_root_entrypoint_identically` runs the
incumbent's loader in-process and the candidate's in the **subprocess the
worker actually is** (`python -c "from aef.harness.node_worker import
load_graph; print(load_graph(sys.argv[1]).id)"`, cwd = the widened repo), and
asserts both produce `reviewer`. The asymmetry is what turned an import error
into a "regression", so the property under test is the symmetry, not either
half.

---

## R5 — S3b's content regexes tripped the 10,000-char backstop and aborted the whole suite

### Reproduced

ADR 0171 shipped content checks written to tell two judges apart. Two of them —
the only two regexes in the whole corpus that carry a repeated group — use
bounded optional groups:

```
(?i)(not (have been )?overloaded|no overloading|overloading (was )?(rejected|ruled out|discounted|dismissed))
(?i)(not (yet )?(re)?open|no confirmed date|still closed|has not returned|remains closed|delayed indefinitely|still awaiting)
```

They are perfectly linear, they are correctly **allowed** by ADR 0166's static
detector at load, and the length backstop — `if len(actual) >
MAX_REGEX_INPUT_CHARS and _repeated_group_bodies(pattern): raise` — fired on
them. The input that trips it is the ordinary failure these checks exist to
catch: a model rambling past the 36-word cap, which is the family all seven of
ADR 0171's negatives belong to. A corpus of two scenarios, one summary 12,000
characters and one 9,000:

```
$ aef loop score agents.summary.graph:build_graph --corpus <scratch> --splits train
error: refusing to run regex check '(?i)(not (have been )?overloaded|no overloading|
overloading (was )?(rejected|ruled out|discounted|dismissed))' against 12000 characters:
the pattern repeats a group and the input is over 10000 characters. ...
EXIT=1
```

Exit 1 = `EXIT_REJECTED`. And the **9,000-character scenario never ran at
all**: `score_scenario` sits OUTSIDE the try/except in both scoring paths
(`scenario_runner.py:~209`, `isolated_suite.py:~188`), so one scenario's raise
takes the suite with it.

The patterns themselves, measured on that same 12,000-character input:

```
non-match  len=12000 found=False 0.245 ms  (?i)(not (have been )?overloaded|...
match      len=12000 found=True  0.002 ms  (?i)(not (have been )?overloaded|...
non-match  len=12000 found=False 0.457 ms  (?i)(not (yet )?(re)?open|...
```

### Erratum on ADR 0166

Two sentences of ADR 0166 §3 need correcting, and they are different mistakes.

**The backstop's rule was wrong, not merely conservative.** ADR 0166 wrote:

> an input over `MAX_REGEX_INPUT_CHARS` (10,000) against a pattern carrying
> **any** repeated group is refused with a reason, because the detector above
> is conservative rather than a proof.

The detector's conservatism is a good argument for a length backstop. It is
not an argument for keying that backstop on *any* repetition, because a
**bounded** quantifier's iteration count does not grow with the input: `(x )?`
enters its body at most once and `(?:\s+\S+){0,34}` at most 34 times, whatever
length you hand them. The length of the input tells you nothing new about a
bounded group, so including one is not caution — it is a rule that answers a
question it was not asked. Measured against ADR 0166's own `MUST_PASS` list at
12,000 characters, the old backstop refused **six of eleven** patterns the
detector had just accepted, *including all three word-cap rewrites the refusal
message recommends*:

| pattern | repeated groups | unbounded | old backstop | now | time |
|---|---|---|---|---|---|
| `^\s*\S+(?:\s+\S+){0,34}\s*$` | 1 | 0 | REFUSED | ran | 0.012 ms |
| `^\s*\S+(?:\s+\S+){0,29}\s*$` | 1 | 0 | REFUSED | ran | 0.010 ms |
| `^\s*\S+(?:\s+\S+){0,39}\s*$` | 1 | 0 | REFUSED | ran | 0.011 ms |
| `(?:foo\|bar){1,3}` | 1 | 0 | REFUSED | ran | 0.137 ms |
| S3b's `overloaded` pattern | 2 | 0 | REFUSED | ran | 0.173 ms |
| S3b's `open` pattern | 2 | 0 | REFUSED | ran | 0.382 ms |
| `^\S+$`, `\bword\b`, `lesson`, `[()]+`, `\(\d+\)`, `(?:\d{2,4})`, `^a{2,3}$` | 0 | 0 | ran | ran | < 0.08 ms |

A fix whose recommended rewrite the same module then refuses on the input the
check exists to catch is the dead end ADR 0166's own `MUST_PASS` list was built
to prevent — the list was checked against the **detector** and never against
the **backstop**.

**And a refusal was suite-fatal.** ADR 0166 said, of the detector at load
time, that a corpus carrying a bad pattern "is refused **at load** rather than
hanging one scenario at score time" — the whole design intent being that one
bad check should cost one file, not the run. The `_holds` refusal had no such
containment: it raised through `score_scenario`, which no caller had wrapped.

### Decision — two parts, each closing a different half

**(a) the backstop counts UNBOUNDED repetition only.**
`_unboundedly_repeated_group_bodies(pattern)` is `_repeated_group_bodies`
filtered by `_is_unbounded` on the group's own quantifier — `+`, `*`, `{n,}`.
`_is_unbounded` already existed and is reused rather than re-derived. The
static detector is **untouched**: it still refuses both families at load, and
`(?:x?y){2,}` — bounded body, unbounded group — is still refused there, before
the backstop is ever consulted.

Verified against a planted fault before being trusted, on three lists:

- ADR 0166's ten `MUST_REFUSE` and eleven `MUST_PASS` through the **detector**:
  all 21 agree, unchanged.
- ADR 0166's eleven `MUST_PASS` plus ADR 0171's two shipped patterns through
  the **backstop** at 12,000 characters: all 13 run, none in more than
  0.4 ms (the table above).
- Every regex the real `corpus/` ships — 114 checks, deduplicated — asserted to
  return a `bool` on a 12,000-character summary
  (`test_every_regex_the_corpus_ships_runs_on_a_twelve_thousand_character_answer`).
- Three unbounded shapes (`^(?:\s+\S+)+$`, `(?:ab)*c`, `(?:\s+\S+){2,}`) must
  still be refused at that length, and are.
- The original ReDoS pattern `^(?:\s*\S+){1,35}\s*$` must still be refused at
  every length, and is — by the detector, in a child process under a wall
  clock, on both a 36-word input and the 12,000-character one.

**(b) a check that raises scores THAT scenario 0, never the suite.**
`score_scenario` moves INSIDE a `try` in both paths. A `CheckError` (which
`CatastrophicPatternError` subclasses) gives `score = 0.0` and
`failure = "unusable check: <the refusal text>"` — the `unusable check:` prefix
being the attribution, and the one `aef/harness/corpus.py` already uses for
this class of problem, so it reaches `loop score`'s report through
`_score_attribution`'s existing `failure` key without `aef/cli/loop.py` being
touched.

The **outcome** is the real one — `classify(...)`, `terminated=True` — and not
`_failed`'s errored shape. The graph ran; what could not be computed is the
score. Reporting it as an errored run would charge the candidate for the
owner's check, and G2's question (did behaviour regress?) has an honest answer
here even when G3's (did the score improve?) does not.

### After (verbatim, same corpus, same command)

```
$ aef loop score agents.summary.graph:build_graph --corpus <scratch> --splits train
task metric — agents.summary.graph:build_graph (summary_agent) — repeat=1
  model calls: 2 cassette hit(s), 0 miss(es), on_miss=fail — replayed
  train       n=2   with_checks=2   mean=0.8333 stdev=0.0000 ci95=[0.8333, 0.8333] repeat_spread=0.000000
      0.8333  sum-21-ramble-12000
                check failed: working_memory.summary max_words 30: got "The inquiry into the ..."
      0.8333  sum-21-ramble-9000
                check failed: working_memory.summary max_words 30: got "The inquiry into the ..."
EXIT=0
```

Both scenarios scored; the content checks held; the word cap failed, which is
the finding the scenario was recorded to produce.

---

## The test that pinned the old behaviour

`test_a_very_long_input_is_refused_rather_than_truncated` asserted the refusal
for `LINEAR` (`^\s*\S+(?:\s+\S+){0,34}\s*$`) — a bounded repetition, and one of
the three rewrites ADR 0166's own error message recommends. It was updated
deliberately rather than deleted: it now asserts the refusal for `^(?:\s+\S+)+$`
(unbounded), which is the property the backstop is for, and the control that
`LINEAR` at that length RUNS is the parametrised test beside it. The reason
this matters is stated in `reproduce-first`: a test that pins wrong behaviour
defends the defect through every refactor.

One other test moved: `test_a_malformed_entrypoint_is_refused` matched
`module:factory`, which now names half the accepted forms. It matches
`<module or file path>:<factory>`; the property is unchanged.

---

## Mutations

Each performed for real: sha256 the file, byte backup, assert the anchor is
present (a mutation whose anchor is missing silently no-ops), perturb, assert
the file changed, run, restore from the backup, assert the sha256 matches the
one taken before the edit. Never `git checkout --`.

| # | mutation | result |
|---|---|---|
| M1 | `scenario_runner.load_graph` imports a dotted name only (the R1 defect restored) | KILLED — 4 failed |
| M2 | `node_worker.load_graph` imports a dotted name only (the R1 defect restored) | KILLED — 3 failed |
| M3 | the worker drops the entrypoint from its message | **SURVIVED the first pass** (below) — KILLED after the control was rebuilt |
| M4 | G2 drops the failure strings again (the R1-tail defect restored) | KILLED — 1 failed |
| M5 | the backstop keys on ANY repeated group again (the R5 defect restored) | KILLED — 10 failed |
| M6 | the backstop never fires (the fix that looks obvious and is wrong) | KILLED — 4 failed |
| M7 | `score_scenario` back OUTSIDE the try, in-process path | KILLED — 2 failed |
| M8 | `score_scenario` back OUTSIDE the try, isolated path | KILLED — 1 failed |

8 of 8 caught; every before/after/backup sha256 equal.

**M3 found a weak control on the way, and the control was rebuilt rather than
the mutation dropped.** The test asserted the entrypoint appeared in the
failure string the parent reports — and `IsolationError` wraps every worker
failure in `worker for '<entrypoint>' failed`, so deleting the entrypoint from
`load_graph`'s own message left the assertion passing. It now calls
`node_worker.load_graph` directly and asserts on `WorkerError`, which is the
message a caller that is not the session sees. Seven of eight mutations were
killed by tests written before the mutation ran; that one was not, and it is
the reason the mutation pass exists.

## Green bar

```
pytest -q                      2544 passed, 6 skipped   (2550 collected, from a
                               baseline of 2516 collected on this branch before
                               any test was added — +34, none removed)
mypy aef examples              Success: no issues found in 135 source files
ruff check .                   All checks passed!
ruff format --check aef tests examples   272 files already formatted
```

+34 tests: 20 in the new `tests/harness/test_graph_loading.py`, 14 in
`tests/harness/test_check_patterns.py`.

## Defects found outside this wave's files (reported, not fixed)

1. **`aef/cli/loop.py`'s `--module` help text still says "module".**
   `aef loop record`, `bootstrap --module`, `bless` and `cycle` all go through
   `load_graph_module` and so accept a file path today, and `loop score`'s
   `--entrypoint` does too as of this ADR — but nothing in the help text says
   so, and an operator on a widened root has no way to learn it from the CLI.
   ADR 0168 reported the same thing; it is still true, and `aef/cli/loop.py`
   is held by two other workers this wave.
2. **`loop score` wants `module:factory` where `loop bootstrap` wants
   `module`.** Recorded in `IMPROVE_LOG.md` already; unchanged here, and now
   that both accept a path the asymmetry is one colon rather than two spellings.
3. **`ScenarioResult.failure` reached only one reader even after this fix.**
   G2 reports it now; `harness/loop.py`'s cohort path constructs
   `precomputed` outcomes and drops the strings again, so a cohort-run
   rejection still cannot say why. That path is another worker's file.

## Confidence

High on all three reproductions and all three fixes: each was reproduced by a
command whose output is pasted above, each fix was re-run against the same
command, and each is pinned by a test that fails when the defect is put back
(8 of 8 mutations).

High on the R1 fix's completeness within the repo: the "one loader" claim is
carried by an AST scan of every module under `aef/` rather than by a comment,
and by an identity assertion (`cli_run.import_graph_module is
import_graph_module`) rather than by two behaviours that happen to agree.

High on the refined backstop rule: bounded repetition cannot backtrack
catastrophically over a group it may enter a fixed number of times regardless
of input length, and the claim is checked against 21 detector patterns, 13
backstop patterns at 12,000 characters, all 114 regex checks the corpus ships,
three unbounded shapes that must still be refused, and the original ReDoS
pattern.

**Medium, still, on the detector's completeness** — ADR 0166's own
qualification is unchanged and this ADR narrows the backstop rather than
strengthening it. The direction of the residual risk moved slightly: a pattern
whose *bounded* repetition is nonetheless pathological (a very large `{0,N}`
over an ambiguous body) is now run where it used to be refused above 10,000
characters. Nothing in the corpus has that shape and the largest bound on disk
is 39, but it is a real narrowing and it is stated rather than averaged away.

**Nothing here says a prompt candidate now passes the gates.** R1's fix means
G2 can *judge* one under a widened root; whether it accepts one is a live
measurement nobody has run, and this increment made zero model calls.
