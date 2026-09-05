# ADR 0182: A crash, a spelling, a namespace, and a fact nobody printed

## Status

Accepted. Fix worker **K3** of the upgrade loop. Five findings, each carried
over from another worker's "still open" or "defects outside my files": ADR
0178's *Still open* (K3-1), ADR 0176's outside-defects 1 and 2 (K3-2) and 3
(K3-3), ADR 0179's *Open and named* (K3-4), and one handed over mid-wave by
the coordinator after ADR 0180's S1b (K3-5).

> **Erratum (ADR 0191, F2).** K3-2's split of `graph_id` from
> `evidence_graph_id` is right and stands, and `_build_proposer` passes
> `config.evidence_id` to `RuleBasedPromptProposer` exactly as described. But
> that was the ONLY proposer it reached: the default `RuleBasedProposer()` is
> constructed with no graph id, and `MemoryEvidence.from_store` filtered only
> validation and holdout run ids. On a two-graph corpus `--graph-id
> demo_agent` therefore grounded a change to `agents/demo/graph.py` in three
> `summary_agent` records (reproduced). The filter is now applied on
> `MemoryEvidence.from_store` — one place, every proposer.

Model: **`claude-opus-5[1m]`** (session default). **ZERO live model calls** —
every reproduction below runs a local stub provider, a graph whose model path
is never taken, or reads a directory. **No rubric dimension moves.**

Every one of the five was reproduced by RUNNING a command before anything
changed. The commands and their real output are below, verbatim, with long
scratch paths elided.

---

## K3-1 — eleven of thirteen `aef loop` subcommands reported a crash as exit 1

ADR 0178's *Still open*, which is ADR 0167's R3 (*a crash's remedy is not a
rejection's*) still standing for the majority of the surface. G1a gave
`cycle`/`run` `EXIT_ERROR`; ADR 0167 gave it to `doctor`/`bless`. The other
nine plus `corpus reconcile` let the exception reach `aef/cli/main.py`'s
catch-all, which returns 1 — and 1 is `EXIT_REJECTED`, *"the candidate was
rejected, the system is working"*.

Three subcommands, three ordinary ways to be wrong:

```
$ python scratchpad/w/k3/repro_k3_1.py
EXIT_REJECTED=1  EXIT_ERROR=3

$ aef loop score agents.demo.graph --corpus <a plain file> --splits bogus
error: 'bogus' is not a valid Split
exit=1   <- EXIT_REJECTED (a verdict on a candidate)

$ aef loop record agents.demo.graph --corpus <a path under a plain file> \
      --scenario-id s-1 --objective 'do a thing'
error: [Errno 20] Not a directory: '.../afile.txt/under-a-file/train'
exit=1   <- EXIT_REJECTED (a verdict on a candidate)

$ aef loop harvest agents.demo.no_such_module --repo … --state … --runs … --corpus …
error: cannot import 'agents.demo.no_such_module': No module named 'agents.demo.no_such_module'
exit=1   <- EXIT_REJECTED (a verdict on a candidate)
```

The rendered nightly workflow fails the job on `-ge 2` and, since ADR 0178,
gives exit 3 its own summary — *"ERROR — the cycle crashed; no kill switch is
set, fix the invocation"*. A crashed `score`/`record`/`harvest`/`skills`/…
stayed green.

### Where the fix lives, and why not in `main()`

**Not in `aef/cli/main.py`'s catch-all**, and this is the load-bearing choice.
That catch-all serves `aef adopt`, `aef migrate`, `aef init`, `aef run`, `aef
eval`, `aef trace` and `aef doctor` as well. Those seven **issue no verdicts**:
1 there is the ordinary "this command failed" every CLI returns, nothing
distinguishes a rejection from a crash for them because they make no
rejections, and no finding in this program has reproduced a problem with their
codes. Moving all seven onto an exit-code vocabulary they do not use, to fix a
defect in the one command that does, is a fix wave strengthening a control on
invocations nobody has shown a problem with — ADR 0141's rule, which ADR 0167
§4 and ADR 0178 §3 both applied to themselves. The exit-code vocabulary (0
verdict / 1 REJECTED / 2 HALTED / 3 ERROR, and the `-ge 2` CI rule that reads
it) is the LOOP's, so the wrapper is the loop's too.
`test_a_top_level_command_still_returns_one` asserts the catch-all is
unchanged rather than leaving that in a comment.

**Not a `try` per handler either.** Thirteen handlers each free to forget is
how eleven of them came to be wrong at once. `_report_crash_as_error` is
applied by `_wrap_loop_handlers(loop_subs)` at the end of `add_loop_parser`,
over everything registered above it including the nested `corpus` group, so a
fourteenth subcommand is covered without being told to be. It prints the
exception **type** as well as its message (`error (ValueError): …`), because
the type is what tells a reader whether to fix the invocation or the repo.
`SystemExit` and `KeyboardInterrupt` are deliberately not caught.

The wrapper is applied AFTER every `set_defaults(handler=cmd_x)` line, so
`tests/cli/test_loop_turn_commands.py` — which derives the turn-running
subcommands from this module's AST by reading those lines — is unaffected.

**A named refusal stays a rejection.** The wrapper catches what nothing else
caught; it does not swallow the refusals each handler names by type. One
handler had been relying on the catch-all for a refusal: `cmd_record` let
`RecorderError` through, and ADR 0149's tripwire guard (*refusing to label a
scenario `must_fail` when the agent completed the task*) is exactly such a
refusal. `test_record_refuses_must_fail_when_only_the_dropped_policy_made_it_fail`
went red on the wrapper and was the thing that found it; `cmd_record` now
catches `(RecorderError, CorpusError)` by name, as `cmd_bootstrap` already
did, and the test is green on its original assertion of exit 1 — unchanged.

**The turn-running two are journalled**, including from the region G1a could
not reach: the flag guards and everything read before each handler's own
`try`. `_journal_crash` is best-effort and skips `LoopStateInsideRepoError`,
which must never be journalled because the journal lives under the `--state`
just refused.

### After

```
$ aef loop score agents.demo.graph --corpus <a plain file> --splits bogus
error (ValueError): 'bogus' is not a valid Split
exit=3

$ aef loop record agents.demo.graph --corpus <a path under a plain file> …
error (NotADirectoryError): [Errno 20] Not a directory: '.../under-a-file/train'
exit=3

$ aef loop harvest agents.demo.no_such_module …
error (EntrypointError): cannot import 'agents.demo.no_such_module': No module named …
exit=3
```

`test_every_loop_subcommand_reports_a_crash_as_an_error` enumerates the
subcommands from the **real parser** (G1a's pattern) and drives each with one
`Namespace` that answers every flag guard and supplies nothing else, so the
first argument any handler reads raises `AttributeError`. One instrument for
all fourteen call sites: a hand-built failure per subcommand would be fourteen
different tests wearing one name.

---

## K3-2 — `run --module` was on the old loader, and `--entrypoint` was a fourth spelling

ADR 0176's outside-defects 1 and 2. **I1's claim was verified against CURRENT
main rather than assumed**: J1 (ADR 0177) switched `scenario_runner.load_graph`
to the one *importer* and left the *splitter* demanding both halves, so I1's
note was still true after that merge.

```
$ python scratchpad/w/k3/repro_k3_2.py

=== load_graph_reference  (ADR 0176's one loader: record/bootstrap/harvest/cycle/score)
  dotted module       'agents.demo.graph'                ok       Graph(id='demo_agent')
  module:factory      'agents.demo.graph:build_graph'    ok       Graph(id='demo_agent')
  file path           'agents/demo/graph.py'             ok       Graph(id='demo_agent')
  file path:factory   'agents/demo/graph.py:build_graph' ok       Graph(id='demo_agent')

=== load_graph_module     (`aef loop run --module`)
  dotted module       'agents.demo.graph'                ok       Graph(id='demo_agent')
  module:factory      'agents.demo.graph:build_graph'    REFUSED  ModuleNotFoundError: No module
                                                         named 'agents.demo.graph:build_graph'
  file path           'agents/demo/graph.py'             ok       Graph(id='demo_agent')
  file path:factory   'agents/demo/graph.py:build_graph' REFUSED  ValueError: … looks like a file
                                                         path and there is no file there

=== scenario_runner.load_graph (`--entrypoint` on gate/cycle/run)
  dotted module       'agents.demo.graph'                REFUSED  EntrypointError: entrypoint must
                                                         be '<module or file path>:<factory>'
  module:factory      'agents.demo.graph:build_graph'    ok       Graph(id='demo_agent')
  file path           'agents/demo/graph.py'             REFUSED  EntrypointError: (same)
  file path:factory   'agents/demo/graph.py:build_graph' ok       Graph(id='demo_agent')
```

So `aef loop cycle --module agents/demo/graph.py --entrypoint
agents/demo/graph.py` accepted the first and refused the second, inside one
invocation — I1's sentence, still true.

### Decision

**One splitter, and it lives in the harness.** `graph_loading.split_entrypoint`
becomes the union rule ADR 0176 wrote for the CLI: split on the last colon,
only when what follows is a Python identifier, factory defaulting to
`build_graph`. `GRAPH_REFERENCE_HELP` and `DEFAULT_GRAPH_FACTORY` move there
with it, because `--entrypoint` is read by the harness (`scenario_runner`,
`node_worker`) and **the harness may not import the CLI** — the argument
`aef/harness/zones.py` already carries for `DEFAULT_AGENT_PATH`. A second copy
in the harness would be the ADR 0149 shape: two answers to one question,
drifting the first time either gains a case. `aef/cli/loop.py` re-exports both
names (`split_graph_reference = split_entrypoint`, `import X as X`), so every
published name keeps working from both paths and there is one definition of
each.

That this reaches `node_worker.load_graph` too is the point, not a side
effect: those are **the two sides of G2**, and ADR 0177's whole finding is that
an import error on one side only is indistinguishable downstream from a
behavioural regression. Giving them one importer and two splitters' worth of
tolerance would have left the same seam one layer up.
`test_node_worker_and_the_runner_split_an_entrypoint_identically` pins it.

`cmd_run` uses `load_graph_reference` like the other five, which also gives it
ADR 0085's `BaseException` guard for the first time — a candidate factory
raising `SystemExit` could exit that process cleanly. `p_run --module` takes
`GRAPH_REFERENCE_HELP`, and **one `ENTRYPOINT_HELP` replaces three** ("…e.g.
agents.mine.graph:build_graph" on `gate`, "…; G2/G3 refuse without it" on
`cycle`, "module:factory; G2/G3 refuse without it" on `run` — three
descriptions of one flag, all three wrong about what it accepts).

### After

```
=== load_graph_reference       all four forms ok
=== scenario_runner.load_graph all four forms ok

$ aef loop run --module agents.demo.graph:build_graph --repo <missing> …
error (GitError): git rev-parse --abbrev-ref HEAD failed (128): …   exit=3
```

— the loader is past, and the next thing to fail is the missing repo, on all
three spellings.

`COVERED` in `tests/cli/test_loop_graph_reference.py` gains `run`; `PENDING`
is empty. That pin was written to fail the day `run` was converted, and it did.

---

## K3-3 — `LoopConfig.graph_id` was one field for two namespaces

ADR 0176's outside-defect 3, and the reason its own F2 fix has a
warn-instead-of-fix branch. ADR 0125 separated the namespaces on purpose:
`archive.versions` reads the value as a **directory name** (what `aef loop
bless` blessed under), `RuleBasedPromptProposer` reads it as a **`Graph.id`**
to admit or drop each memory record by. One field could not serve both, so
deriving the id from the corpus moved the archive key out from under a blessed
baseline and G5 rejected every candidate for having nothing to compare to —
measured, not guessed (`test_an_adopted_repo_gates_a_candidate_end_to_end`).

The configuration that stayed broken is the documented one: `aef loop bless`
takes no `--corpus` at all, so the first-week sequence blesses under
`"default"` while the corpus records `demo_agent`, and ADR 0176 printed

```
--graph-id not given. The corpus … records one graph, 'demo_agent', but a
blessed baseline already sits under the archive key 'default' … WARNING:
--proposer rule_based_prompt will drop this corpus's failure records as
another graph's.
```

and then did exactly that.

### Decision

`LoopConfig.evidence_graph_id: str | None = None`, with
`LoopConfig.evidence_id` answering `evidence_graph_id or graph_id`. `None`
means "the same as the archive key", so **every caller that never heard of the
field behaves exactly as before**. `_build_proposer` is its one reader; every
`archive.*` call and `_scenarios_for_graph` keep `graph_id`.

`resolve_graph_id_from_corpus` then **never moves the archive key** — the line
`args.graph_id = derived` is gone — and the rule collapses from four cases with
two warnings to one derivation with one refusal:

| situation | archive key | evidence id |
|---|---|---|
| no `--corpus`, or an empty one | `default` | (unset — falls back) |
| `--graph-id X`, X in the corpus | `X` | `X` (nothing said) |
| `--graph-id X`, X not in the corpus, nothing blessed under it | **refused** — a typo, neither namespace |
| `--graph-id X`, X not in the corpus, blessed under it, one corpus graph | `X` | **derived**, and said |
| `--graph-id X`, X not in the corpus, blessed under it, several corpus graphs | `X` | **warned** — the one warning left |
| omitted, one corpus graph | `default` | **derived**, and said |
| omitted, several corpus graphs | **refused**, listing them |

Both warn-instead-of-fix branches become derivations. The refusal on an
ambiguous corpus is unchanged and is the one warning that survives, for the
reason it was written: which graph's evidence a turn may ground in is not
guessable, and a wrong guess is indistinguishable from having no evidence.

The verdict line says `[evidence graph id derived from --corpus: 'demo_agent']`
rather than `[--graph-id derived …]`, because the flag is no longer what moved
and a summary naming it would send a reader to check an archive that had not
changed.

### After

```
$ aef loop cycle … --corpus corpus --memory memory.jsonl \
      --proposer rule_based_prompt --agent-path agents/demo/persona.md
  --graph-id not given; the evidence graph id is derived as 'demo_agent' from the
  2 scenario(s) in corpus, which record one graph. The archive key is unchanged
  ('default'), so a blessed baseline stays where it was blessed (ADR 0182)
  ledger verified: 0 entr(ies)
  proposed cycle-… on local branch loop/cycle-…-prompt
cycle verdict: proposed cycle-… [evidence graph id derived from --corpus: 'demo_agent']
```

`test_a_blessed_default_and_a_demo_agent_corpus_get_both_answers` asserts both
halves at once: the proposer grounds in `demo_agent`'s evidence, and
`archive.versions(state/archive, "default")` is still non-empty while
`archive.versions(…, "demo_agent")` is empty.

Four tests that pinned the one-field behaviour were **rewritten deliberately**,
each carrying its history in the docstring — including
`test_the_corpus_is_not_read_twice_into_two_different_answers`, which compared
the corpus's graph id against `graph_id(args)` and would now pin the defect.

---

## K3-4 — the containment warning was recorded and printed nowhere

ADR 0179's *Open and named*. R3 moved
`prompt_agent.persona_in_user_turn` out of `state.errors` — where it zeroed
the task metric, became failure memory and was pasted into the persona by the
proposer — and into the containment record the node writes on every run, with
`containment_warnings(state)` as THE reader. It closed by saying the surfacing
was not done, and that until it was, *"the fact lives in the trace and in
`working_memory` and nothing prints it."*

Reproduced end to end through the real CLI, on a real `aef migrate`d prompt
agent with `model_provider.impl: command` and an argv template with no
`{system}` slot — ADR 0169's `codex` row, driving a local stub script:

```
$ python scratchpad/w/k3/repro_k3_4.py
$ aef migrate --dir repo --agent-root .claude/agents
  generated .claude/agents/migrated/answerer/graph.py

$ aef loop bootstrap <graph.py> --corpus corpus --inputs inputs.json --config aef.yaml
recorded 1 scenario(s) in the train split
  scenario q-1: containment_warnings -> [('prompt_agent', {'isolation':
    ['single_turn', 'user_turn_persona'], 'message': "provider 'cassette' declares no system…

$ aef loop doctor --repo repo --state state --corpus corpus --agent-root .claude/agents
Loop readiness — 6 things you must supply
  [--] corpus + tripwire       1 scenario(s), 0 tripwire(s)
  [OK] reflect node routed to  make_prompt_agent_node(route='reflect') builds a node that routes to it
  … (four more obligations, none of them this) …
exit=1

$ aef loop cycle --repo repo --state state --corpus corpus --no-memory
  preflight: 4 of 6 obligation(s) unmet (…)
  ledger verified: 0 entr(ies)
  no memory store configured: nothing to learn from, no candidate
cycle verdict: no memory store configured … exit=0
```

The fact is demonstrably on the recorded scenario, and neither command says a
word about it.

### Decision — a warning, not an obligation

`_containment_lines(states)` renders **one line per distinct provider**, not
per run: the fact is a property of the provider, so a corpus of two hundred
scenarios recorded against one CLI is one sentence. `cycle` and `gate` print
them beside the verdict; `doctor` prints them **below** `Preflight.render()`
and outside the six.

Outside deliberately. The six obligations are things an owner must SUPPLY, and
each carries a `fix:` that is an edit in this repo. A persona that travelled in
the user turn is a property of a CLI the owner already installed, and no
sentence anyone can write gives a binary a `--system-prompt` flag. Adding it to
the list would make `doctor` exit 1 forever on a correctly configured Codex
adopter — which is ADR 0179's own finding, one surface over. The line never
changes an exit code.

**Which states are read, and the one that is not.** `--memory` was checked and
carries nothing, by design: ADR 0179's whole finding is that this is not a
failure, so `make_reflect_node` never writes it into a `MemoryRecord`. A reader
that went looking there would find nothing on every repo, so the sources are
the two places an executed run's state survives — the most recent recorded run
under `--runs` (new on `doctor`; `cycle`/`gate` already had the flag) and the
corpus scenarios, which are the runs the gates re-execute. The absent third
source is asserted rather than left as a comment, because "we checked and it is
not there" is a claim that goes stale
(`test_the_memory_store_is_not_a_source_and_that_is_deliberate`).

The most recent run only: the question is what the provider you are running NOW
does, and an answer assembled from a year of runs would name a CLI the owner
replaced in March.

### After — verbatim

`aef loop doctor`:

```
  [!!] persona channel         prompt_agent: persona sent in the USER turn by provider 'cassette' (isolation: single_turn, user_turn_persona) — see ADR 0179
       Not an obligation and not a fix: the persona is untrusted-channel text on this provider, so ADR 0152's containment story does not hold for it. Read ADR 0179 before treating a low score from such a run as the agent's fault.
```

`aef loop cycle` / `aef loop gate`:

```
  prompt_agent: persona sent in the USER turn by provider 'cassette' (isolation: single_turn, user_turn_persona) — see ADR 0179
cycle verdict: …
```

Silent — no line, and no `[OK] persona channel` either — when the persona was
the system message. A green tick for the absence of a hazard would make it look
like an obligation the owner satisfied.

---

## K3-5 — `aef loop score --memory`

Handed over mid-wave by the coordinator, after K2's ADR 0180 made the
check-failure producer one idempotent function and measured (S1b) that wiring
it into `bootstrap` **alone** lets staleness walk a training lesson out of the
prompt while a scored split never re-sees it: `runs_since_last_seen` 17 by the
seventeenth scenario, 0 with the producer on the scored split.

```
$ python scratchpad/w/k3/repro_k3_5.py
$ aef loop bootstrap agents.demo.graph --corpus corpus --memory bootstrap-memory.jsonl
  1 of 1 recorded run(s) FAILED: … 1 failed an owner check
  bootstrap-memory.jsonl: 1 record(s)

$ aef loop score agents.demo.graph --corpus corpus        # no --memory
      0.0000  wrong-one
                check failed: scores.quality equals 0.5: got 1.0
exit=0  score-memory.jsonl: 0 record(s)

$ aef loop score agents.demo.graph --corpus corpus --memory score-memory.jsonl
  pass 1: exit=0  1 record(s)  kinds=['failure']
  pass 2: exit=0  1 record(s)  kinds=['failure']

$ ... --repeat 3 --memory score-memory.jsonl
  exit=0  1 record(s) — idempotent on (run_id, signature)
```

**ADR 0174's refusal of the gate path stands and is not reopened.** A gate run
that writes to the adopter's durable store lets scoring a candidate manufacture
the next one's evidence. `aef loop score` is neither a gate nor a recording: it
scores the INCUMBENT the owner already trusts, in-process, over the owner's own
corpus, with the owner naming the file. So it is opt-in, off by default, and
the isolated path is untouched — the flag's help says so in those words.

`test_cmd_score_is_the_only_caller_that_supplies_a_durable_store` AST-scans all
of `aef/` and asserts the only `run_scenario(…, memory=…)` call site is
`aef/cli/loop.py::cmd_score`. `file::function`, not `file`: the first version
asserted the file and a planted call inside `cmd_gate` survived it (M13).

The control that keeps this honest is the one ADR 0174 wrote:
`check_failure_record` returns `None` when the run recorded an error of its
own, so a run whose reflect node already wrote failure memory is not
double-counted. `test_a_run_that_errored_is_not_double_counted` pins it against
`_corpus`'s `hard` scenario, which is why the new fixture is a run that
COMPLETES and fails its owner's check instead.

---

## Evidence

**Green bar**, all four, on this branch after the `origin/main` merge:

```
pytest -q                              2788 passed, 7 skipped, 1 xfailed
mypy aef examples                      Success: no issues found in 135 source files
ruff check .                           All checks passed!
ruff format --check aef tests examples 282 files already formatted
```

Test count **2679 → 2788** on this worker's own baseline (74e0a4d). The merge
with `origin/main` (K1's ADR 0181 + K2's ADR 0180) accounts for 41 of that and
this ADR for **+68**, counted per file rather than asserted:

| file | before | after |
|---|---|---|
| `tests/cli/test_loop_exit_codes.py` | — | **28** (new) |
| `tests/cli/test_loop_containment_surface.py` | — | **12** (new) |
| `tests/cli/test_loop_graph_reference.py` | 30 | 46 |
| `tests/cli/test_loop_score.py` | 9 | 14 |
| `tests/cli/test_loop_cycle_graph_id.py` | 11 | 14 |
| `tests/harness/test_graph_loading.py` | 20 | 23 |
| `tests/harness/test_g2_outcome.py` | 39 | 40 |

**Mutations: 14 planted, 14 killed**, every restore verified byte-identical by
SHA-256. `git checkout --` was never used.

| # | Mutation | Killed by |
|---|---|---|
| M1 | the wrapper returns `EXIT_REJECTED` again | 18 in `test_loop_exit_codes.py` |
| M2 | `_wrap_loop_handlers` is not applied | 19 |
| M3 | the wrapper stops journalling a turn-running crash | `test_a_crash_in_a_turn_running_command_is_journalled[cycle,run]` |
| M4 | `split_entrypoint` demands both halves again | 26 across two files |
| M5 | `cmd_run` goes back to `load_graph_module` | `test_run_no_longer_uses_the_old_loader` |
| M6 | `--entrypoint` on `run` gets its own help again | `test_every_entrypoint_flag_shares_one_help_string` |
| M7 | `evidence_id` ignores `evidence_graph_id` | 3 in `test_loop_cycle_graph_id.py` |
| M8 | the derivation moves the ARCHIVE key again | 5, incl. `test_adoption_sequence.py` |
| M9 | the cycle summary drops the containment line | `test_the_cycle_summary_prints_one_line_per_provider` |
| M10 | `doctor` drops it | `test_doctor_prints_the_warning_beside_the_obligations` |
| M11 | one line per RUN instead of per provider | `test_one_line_per_DISTINCT_provider_not_per_run` |
| M12 | `cmd_score` stops passing the store | `test_scoring_with_memory_writes_one_check_derived_failure` |
| M13 | **planted fault:** a gate path supplies the durable store | `test_cmd_score_is_the_only_caller_that_supplies_a_durable_store` |
| M14 | `run_scenario`'s `memory` defaults to a live store | same |

**M3 is the one worth naming.** It SURVIVED the first pass, and the reason is
the reproduce-first rule about verifying a detector against a planted fault:
the test meant to prove the wrapper journals a crash raised inside `_config`,
which is inside `cmd_cycle`'s **own** `try`, so the handler journalled it and
the wrapper was never exercised. The fault is now planted in the pre-`try`
region (`_require_agent_path_under_root`, which genuinely can raise), and a
second test asserts the region G1a already covered is still journalled exactly
once. M13 has the same shape one finding over: the first version of the
owner-only scan asserted a FILE, so a call planted in `cmd_gate` — the same
file — walked past it.

---

## Consequences

- A crashed `aef loop <anything>` fails a nightly job instead of reading as a
  healthy rejection, and the exception's type is in the message. `aef adopt`,
  `migrate`, `init`, `run`, `eval`, `trace` and `doctor` are unchanged, which
  is asserted.
- `cmd_record` catches `RecorderError`/`CorpusError` by name. Any other handler
  that was silently relying on the catch-all for a *refusal* would now report
  it as a crash; the suite found exactly one, and there is no third code path
  between them — a refusal is caught by type or it is a crash.
- `--entrypoint` accepts a bare module and a bare file path everywhere it is
  read, **including `node_worker`**, so a spelling one side of G2 accepts
  cannot be a regression on the other. `split_entrypoint` no longer refuses a
  colon-less reference: `tests/harness/test_graph_loading.py` and
  `tests/harness/test_g2_outcome.py` each had a test pinning that refusal, and
  both were rewritten with the history rather than deleted.
- `LoopConfig` grows a field. `evidence_graph_id=None` is today's behaviour
  exactly, so no existing caller, test or gate changes; only `aef loop cycle`
  ever sets it.
- `aef loop doctor` prints a seventh line that is not an obligation, and a new
  `--runs` flag it reads for one thing. The obligation count and the exit code
  are unchanged.
- `aef loop score --memory` writes to the adopter's durable store. It is the
  first non-recording command that can, and the AST scan naming
  `cmd_score` as its only call site is what keeps that from spreading.

## Defects found outside this worker's files

1. **The cassette recorder masks the provider name in the containment
   record.** Through `aef loop bootstrap --config <a slotless command
   provider>`, the recorded scenario's warning says `provider: 'cassette'`,
   not `'codex'` — the recording wrapper's `.name` reaches the containment dict
   while `isolation` passes through correctly (`['single_turn',
   'user_turn_persona']`). So the surfaced line names a wrapper rather than the
   CLI the owner installed, on exactly the path an adopter uses. Reproduced in
   `scratchpad/w/k3/repro_k3_4.py`; the fix belongs wherever
   `CassetteProvider` sets `name` (`aef/harness/scenario_runner.py` was this
   worker's only under the entrypoint clause, and this is not that).
2. **`aef migrate`'s report is stale about ADR 0179.** It still prints *"…and
   appends a `prompt_agent.persona_in_user_turn` error when it was the user
   turn"*, which R3 made false — it is a `warning` key inside the containment
   record now, and deliberately never an error. `aef/cli/migrate.py`.
3. **`aef loop bootstrap` returns `EXIT_REJECTED` for a missing
   `--state`/`--no-loop-state`**, where `cycle`/`run` return `EXIT_USAGE` for
   the equivalent `--memory`/`--no-memory` refusal (ADR 0141 vs 0165). Both are
   "this invocation cannot work"; one of them is reported as a verdict on a
   candidate. Not changed here because no finding reproduced a problem with it
   and `EXIT_USAGE` shares its number with `EXIT_HALTED` — worth an owner's
   decision rather than a fix wave's.

## Errata

- **ADR 0178, "Still open": CLOSED** here (K3-1). Its count was right — eleven
  of thirteen — and the fourteenth handler, `loop corpus reconcile`, is nested
  under a group and was in neither number.
- **ADR 0176, "Defects found outside this worker's files" 1, 2 and 3: CLOSED**
  here (K3-2 for 1 and 2, K3-3 for 3). Its prediction that `PENDING` "fails the
  day `run` is converted, which is when someone should read it" held exactly.
  Defects 4, 5 and 6 are untouched.
- **ADR 0176's F2 rule is narrowed.** "Derive when there is no baseline to
  orphan; say so loudly when there is" is replaced by "derive the evidence id
  always, and never move the archive key". The namespace separation ADR 0125
  protects is unchanged; what is gone is the branch that warned instead of
  fixing.
- **ADR 0179, "Open and named": CLOSED** here (K3-4). Its statement that the
  fact is "strictly more visible than it would be if this ADR had simply
  deleted the entry, and strictly less than it should be" is now false in its
  second half.
- **ADR 0180's S1b**: its measurement is what motivated K3-5, and the producer
  now has its scored-split caller. The measurement itself is not re-run here.

## Confidence

High on all five reproductions: each is a command or a script whose real output
is pasted above, run before anything was edited, and re-run after — every
"after" block is pasted too.

High on K3-1's fix, which is enumerated from the real parser over all fourteen
handlers, and on K3-3's, whose two halves are asserted in one test against the
real archive. High on K3-5's idempotence, which was run twice and with
`--repeat 3` against a real store.

Medium on K3-2's completeness: `aef run --module` (the top-level command, not
`aef loop run`) still goes through `cli.run.load_graph_module` and still
refuses `module:factory`. It is out of this worker's files and no finding has
reproduced a problem with it, but it is the seventh surface that names a graph
and it is now the only one on the old rule.

Medium on K3-4's usefulness as distinct from its correctness: the line is
printed and is silent when it should be, which is measured; that anyone reads
it, or that reading it changes a decision, is not.
