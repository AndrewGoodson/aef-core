# ADR 0167: The unfixed twin, the journal that stopped at the happy path, and the tree the baseline was of

## Status

Accepted. Fix wave G1a of the upgrade loop: seven findings from two seam
hunts over M1 (ADR 0152), M3 (ADR 0154) and J0F (ADR 0165), each reproduced by
running a command before anything changed. **No rubric dimension moves** —
nothing here adds a capability; six of the seven close a control that was
believed to exist, and the seventh removes a permanent red from a correct
graph.

An **erratum on ADR 0165** is appended to that file: its central claim held
for one of the two commands that run a turn, and for the normal return only.

## The findings, reproduced

`PYTHONPATH` and the venv elided; long paths shortened. Every block below is
real output from this branch's parent commit (999fa17).

### F1 — `aef loop run` is the unfixed twin of the defect ADR 0165 fixed

`cmd_run` read `memory=FileMemoryStore(...) if args.memory else None` — the
same expression, in the same file, ninety lines below the one ADR 0165 guarded
— with no guard, and journalled nothing at all.

```
$ aef loop run --repo <r> --state <s> --workdir <w> --turns 2 --budget-minutes 1
    kept branch loop/kept at dd6f055c5902 (from main)
    turn 1: ledger verified: 0 entr(ies)
    turn 1: no memory store configured: nothing to learn from, no candidate
    stopped: turn 1 produced no candidate
  kept 0, reverted 0, loop/kept@dd6f055c5902 — review and merge by hand; Tier-1 auto-merge is off
EXIT=0
```

Five times. Then:

```
--- contents of the state dir ---
   (state dir does not exist)

$ aef loop monitor --repo <r> --state <s>
  checked 0 merged change(s)
    cycles run: 0 (last never)
    last PROPOSED: never
    last KEPT/MERGED: never
EXIT=0
```

`cycles run: 0`, no warning. That is precisely the "a loop that has run 180
nights and produced nothing is byte-identical to a loop nobody has ever
started" ambiguity ADR 0165 §2 argues cannot be allowed to stand — reached
from the sibling subcommand, with a clean exit code and a monitor that says
the loop was never started.

### F6 — `cmd_cycle` journalled only the turns that returned normally

`record_cycle_attempt` sat *after* the `try`, so the `LoopHaltedError`,
`PolicyConfigError` and `CorpusGraphMismatchError` branches all returned
before reaching it. With the kill switch engaged:

```
$ aef loop cycle --repo <r> --state <s> --workdir <w> --no-memory
  HALTED: the self-rewiring loop is halted: owner stopped it. Remove <s>/HALTED
  to resume — a deliberate act, not an automatic one.
EXIT=2
  JOURNAL cycles.jsonl: DOES NOT EXIST
```

A nightly cycle dying on the same config error every night leaves the journal
as empty as one nobody has run — the exact failure the journal was added to
make visible, on the paths where the failure is loudest.

### F2 — obligation 2 was permanently red on every graph `aef migrate` writes for a prompt agent, and the graph routes correctly

`aef migrate --dir <clone of the pilot>` on the real 8-persona repo, then:

```
$ aef loop doctor --repo <pilot> --state <s> --corpus <pilot>/corpus \
      --agent-path agents/migrated/marlin_accela/graph.py
    [--] reflect node routed to  a reflect node exists but nothing routes to it
         fix: add make_reflect_node() to your graph AND make a node
              `return delta, 'reflect'` — an Edge alone does not route (ADR 0070)
EXIT=1
```

and, executing that same generated module with a stub provider:

```
  trace: ['prompt_agent', 'reflect', 'consolidate']
```

`_reflect_is_routed_to` looked for a three-argument `(state, ctx, services)`
function whose `Return` carries the literal. M1's generated module has no node
function: it calls `make_prompt_agent_node(agent_file=..., route="reflect")`
and the closure lives in `aef/reasoning/prompt_agent.py`. So the obligation
was unmeetable for the entire class of repo M1 exists to serve, and the fix
line told the reader to add a node that is already there.

This is the C↔D shape again (ADR 0091, ADR 0149's F1): two modules, each
individually correct and individually tested, and **nothing ran one's output
through the other**.

### F7 — the baseline recorded the files but not which tree they were of

`aef migrate --agent-root .claude/agents` is what the migration report itself
tells a prompt-file repo to run (ADR 0152). Blessing under that root:

```
$ aef loop bless --repo <r> --state <s> --agent-root .claude/agents \
      --agent-path .claude/agents/migrated/marlin_accela/graph.py
  blessed .claude/agents/migrated/marlin_accela/graph.py as baseline v1 for graph 'default'
EXIT=0

  entry.json keys: ['base_sha', 'file_digests', 'gate_report', 'graph_id',
                    'head_sha', 'notes', 'recorded_at', 'rolled_back_from', 'version']
  agent_root recorded: <<ABSENT>>
```

A later cycle at the default root, against that baseline:

```
$ aef loop cycle --repo <r> --state <s> --workdir <w> --memory <m> \
      --agent-path agents/demo/graph.py --build-command python -c pass
    gated: reject — G5 rejected it: cumulative drift: 1.000 exceeds the budget of 0.500
EXIT=1
```

G5 unions the two key sets, and the two sides describe disjoint trees, so the
first candidate is charged 1.000 for a two-line change. Two rejections halt the
loop. ADR 0084 fixed the *candidate* side of this by giving `_config` a
`zone_policy`; the *baseline* side still recorded no root at all, so nothing
anywhere could notice the two disagreed.

The second half, F5's: with the root widened and `--agent-path` left at
`DEFAULT_AGENT_PATH` — which lives under the DEFAULT root and is therefore
**Zone C** under the widened one —

```
$ aef loop doctor --repo <r> --state <s> --corpus <r>/corpus --agent-root .claude/agents
    [--] reflect node routed to  no reflect node in the graph
         fix: aef loop bless --repo . --state <s> --agent-path agents/migrated/graph.py
EXIT=1

$ aef loop cycle ... --agent-root .claude/agents        # --agent-path default
    the proposer produced nothing from the available evidence
EXIT=0
```

Six obligations reported about a file the loop may not touch, a `bless` fix
line that drops `--agent-root` (so following it blesses the *other* tree), and
a cycle that exits 0 having done nothing. Neither command said the two flags
disagreed.

### M4 (folded in) — `bless` accepted a `--state` directory inside the repo that `cycle` refuses

`harness.loop._preflight` has refused this since ADR 0090: with `--state`
inside the working tree, `git add -A` sweeps the ledger and archive into the
candidate's own commit and the audit trail becomes part of what it audits.
Four of the nine subcommands taking both `--repo` and `--state` never call
`_preflight`, so they never asked:

```
REFUSED   loop gate     REFUSED   loop monitor  ACCEPTED  loop digest
REFUSED   loop status   ACCEPTED  loop harvest  REFUSED   loop cycle
REFUSED   loop run      ACCEPTED  loop bless    ACCEPTED  loop doctor

$ aef loop bless --repo <r> --state <r>/state --agent-path agents/demo/graph.py
  blessed agents/demo/graph.py as baseline v1 for graph 'default'
EXIT=0
contents of <r>/state: ['archive', 'ledger.jsonl']
```

`bless` is the worst of the four: the baseline is the one artefact that must
sit outside the candidate's reach, and under a widened `--agent-root` an
in-repo archive can end up inside its own next baseline.

### R3 (folded in) — an exception is exit 1, and exit 1 is also "a healthy rejection"

`aef/cli/main.py`'s catch-all returns **1** for any exception, and
`EXIT_REJECTED` is also 1 — "this candidate is no good, the system is
working". The rendered nightly workflow fails the job on `status >= 2`. So a
bad config, a missing corpus, an import error, a provider that is down, and
the `agents.migrated.graph` placeholder whose `build_graph()` raises
`NotImplementedError` all read as a healthy rejection and the job stays green
— and, because the exception escaped `cmd_cycle` before the attempt was
journalled, `cycles.jsonl` gained nothing and the staleness alarm could never
fire for those nights either. Two independent alarms, both blind to the same
class of night. Reproduced on the clone by G1b: `REAL EXIT=1`, state dir empty.

### R6 (folded in) — the containment fallback reported every Monday as an attack

`Digest.render()` printed `**A proposal reached for the harness. Read the
ledger.**` whenever any ledger entry in the window carried
`security_event: True`. S5's containment fallback — no Docker on the runner,
or an owner who wrote `containment: off` — is exactly such an entry. So the
owner's weekly oversight surface reported their own configuration as an
attack, which is an alarm firing on the normal case.

## Decisions

### 1. Both commands that run a turn are held to both rules, and the list is derived

`_require_memory_flag` takes the subcommand name and `cmd_run` calls it, so
`aef loop run` refuses without `--memory`/`--no-memory` exactly as `cycle`
does — in the handler, with the parser deliberately still permissive, for the
reason ADR 0165 gives (`cmd_run` is importable; a guard that binds only when
argparse is involved is not a guard).

`tests/cli/test_loop_turn_commands.py` does **not** name the two commands and
stop. It parses `aef/cli/loop.py` and derives every `cmd_*` handler importing
`cycle` or `run_loop` from `aef.harness.loop`, maps each to its subcommand
through its own `set_defaults(handler=...)` line, and asserts the derived set
equals the set the file knows how to invoke. A third twin fails that assertion
before it can ship, and once added to the table it is held to both rules
automatically. The planted third handler (M7) is caught by exactly that test.

**`run` journals one attempt per TURN, not one per invocation.** The staleness
alarm counts consecutive attempts that proposed nothing, with a threshold of
three; each turn is a separate chance to propose, so ten quiet turns recorded
as one attempt would need thirty turns to reach a threshold meant to fire
after three. All of a run's entries carry one timestamp — they are written
together, at the end — because nothing in `assess_cycle_staleness` reads
anything finer than the last attempt's age, while the order and the count are
per turn. A run that stops before turn 1 still journals one entry: it occupied
a scheduled slot and produced nothing.

After:

```
$ aef loop run --repo <r> --state <s> --workdir <w> --turns 2 --budget-minutes 1
  error: a run without memory cannot propose — ... Pass --memory <file> ... or
  pass --no-memory to say you mean that. ... this repo's own scheduled cycle was
  a no-op every night (ADR 0165), and `aef loop run` was the same command with
  no guard at all (ADR 0167).
EXIT=2

$ aef loop run ... --no-memory            # three times
--- <state>/cycles.jsonl ---
  {"at": "...", "command": "run", "proposed": false, "verdict": "turn 1: no candidate — turn 1 produced no candidate (--no-memory was passed: this run could not propose)"}
  ... x3

$ aef loop monitor --repo <r> --state <s>
    cycles run: 3 (last 0.0 day(s) ago)
    last PROPOSED: never
    WARNING: SCHEDULED CYCLE PRODUCING NOTHING — 3 consecutive cycle(s) have run
    and proposed nothing. ...
```

`CycleAttempt` gains `command`, so one journal can carry both and "which
command has gone quiet" is answerable. It defaults to `""` for entries written
before this change, and nothing keys off it.

### 2. Every path out of the driver is journalled, including the ones that raise

`cmd_cycle`'s journal call moved into a `finally`, with each `except` branch
setting the verdict to `"<kind> (<ExceptionName>): <message>"` first. An
exception the handler does not name is caught, named, journalled and
**re-raised unchanged** — `main()` still turns it into whatever it turned it
into before; the only difference is that the journal no longer goes silent on
the failure a scheduled loop is most likely to repeat. `cmd_run` does the same
for its own three named refusals plus the unnamed case.

```
$ aef loop cycle ... --no-memory          # kill switch engaged
  HALTED: the self-rewiring loop is halted: owner stopped it. ...
EXIT=2
  JOURNAL cycles.jsonl: 1 line(s)
    {"at": "...", "command": "cycle", "proposed": false,
     "verdict": "HALTED (LoopHaltedError): the self-rewiring loop is halted: owner stopped it. ..."}
```

**Reported honestly:** the kill-switch path is reproduced end to end at the
CLI; `PolicyConfigError` and `CorpusGraphMismatchError` are reachable through
the CLI only behind a blessed baseline whose drift is inside budget *and* a
corpus recorded from the matching graph, because the earlier gates reject
first. Those two are exercised by injecting the exception at the collaborator
boundary — `aef.harness.loop.cycle`, which `cmd_cycle` calls — never by
mocking `cmd_cycle` itself.

### 3. Preflight recognises the second shape of "routed to reflect"

A call whose callee is bound by `from aef.reasoning... import make_*_node` and
which carries `route="<reflect id>"` as a keyword now counts, alongside the
hand-written node shape, which is unchanged. The factory that *builds* the
reflect node is excluded: `make_reflect_node(route="reflect")` is a self-loop,
not something arriving at it. A `route=` keyword on anything else — a local
helper, an import from elsewhere — is not evidence, because vouching for it
would make the obligation trivially satisfiable.

```
    [OK] reflect node routed to  make_prompt_agent_node(route='reflect') builds a node that routes to it
```

`test_the_real_migrate_output_passes_the_real_preflight` runs the REAL
`run_migrate` on a prompt-file fixture and reads its REAL output back through
the REAL `_reflect_is_routed_to` — the C↔D lesson, made a test, in the join
where the defect lived.

### 4. The baseline records which tree it is of, and the two flags must agree

`ArchiveEntry` gains `agent_root` (defaulting to `""`, so every entry written
before this loads unchanged), `bless` records it, and preflight's *blessed
baseline* obligation reports **unmet with a named reason** when the recorded
root differs from the root in force:

```
  [--] blessed baseline  1 archived version(s), but v1 was blessed with --agent-root
       '.claude/agents' and this loop is running under 'agents' — G5 would measure
       every candidate's drift between two different trees
       fix: the baseline and this invocation must name the SAME Zone A tree. Either
       re-run with --agent-root '.claude/agents', or start a new graph id and bless
       it under 'agents' — re-blessing the same graph is refused, because the drift
       budget is measured against the baseline and silently replacing it resets that
       budget without anyone deciding to (ADR 0053).
```

`""` is *not* treated as a mismatch. A baseline blessed before the field
existed is not evidence of disagreement, and failing every one of them would
be a control firing on the ordinary case — which trains the reader to skip the
line, the same argument ADR 0165 makes for not warning about an unstarted
loop. The `bless` fix string also carries `--agent-root` when it is not the
default, which the reproduced `doctor` output dropped.

And `bless`/`cycle`/`run`/`doctor` refuse when `--agent-root` is non-default
and `--agent-path` is not inside it, naming both paths, saying the path was
left at its default when it was, and naming the per-agent path `aef migrate`
actually wrote (found by globbing `<root>/migrated/*/graph.py`):

```
error: `loop doctor` was given --agent-root '.claude/agents' and --agent-path
'agents/migrated/graph.py', and 'agents/migrated/graph.py' is not inside
'.claude/agents'. It was left at its default, and that default names a file under
the DEFAULT root 'agents'. ... Pass --agent-path naming a graph under
'.claude/agents': one of .claude/agents/migrated/marlin_accela/graph.py.
```

**Only when the root is non-default**, decided rather than defaulted. Under
the default root this would be a new refusal on invocations no finding here
reproduced a problem with, and strengthening a control is an owner's decision
rather than a fix wave's side effect — ADR 0141's own rule, applied to itself.
The question asked is the real one: `zones.inspect_path(path, ZonePolicy(...))`
returning Zone A, not a string prefix test.

### 5. One place asks whether the state directory is inside the repo

`_config()` is called by exactly the nine subcommands that take both `--repo`
and `--state`, so `_check_state_is_outside_the_repo` is called there — the
same function the driver calls, **imported rather than re-implemented**, since
two copies of one predicate is the ADR 0091 shape and this pair would drift
the first time the rule gained a case. `bless()` asks again, in
`aef/harness/preflight.py`, because `bless` is importable and a control that
binds only when argparse is involved does not bind on the path a library
caller takes (L6's lesson, and the reason ADR 0165's refusal lives in the
handler).

`tests/cli/test_loop_state_outside_repo.py` derives the list from the built
argparse parser and asserts each subcommand refuses **and does not create the
directory**. That second assertion is not decorative: it caught a defect this
wave introduced. Journalling a run's failure created `<state>/` before the
refusal reached the caller, so the first version of the fix wrote
`cycles.jsonl` into the very directory it had just refused to use. Putting the
check in `_config` — which runs before the try block — is what makes the
ordering right, and the mutation that removes it fails on `cycle` for exactly
that reason.

`bootstrap` also takes `--state` and is deliberately excluded: it has no
`--repo` at all, so there is no repository root to compare against and nothing
this check could say.

### 6. An exception has its own exit code, and the workflow's rule was read

`EXIT_ERROR = 3`, beside `EXIT_OK`/`EXIT_REJECTED`/`EXIT_HALTED` in
`aef/harness/loop.py`. `cmd_cycle` and `cmd_run` catch what they do not
expect, print it, **journal it with the exception's name**, and return 3.
`main.py`'s catch-all is unchanged — this is not a global change to how the
CLI reports exceptions, only to how the two commands that run turns report
theirs, because they are the two that a scheduler runs unattended.

3 rather than reusing 2: a halt and a crash call for different actions
(release the kill switch versus fix the invocation), and `status >= 2` catches
both. The rule was READ from `aef/cli/adopt_loop.py` rather than assumed —
`test_the_rendered_nightly_workflow_would_fail_the_job_on_that_code` asserts
the rule is still `-ge 2` and that `EXIT_ERROR` satisfies it, because an exit
code chosen without checking the rule that consumes it is how 1 came to mean
two things.

`_config` and `load_graph_module` moved INSIDE `cmd_cycle`/`cmd_run`'s `try`,
because that is where a bad `--config`, an unreadable corpus and the
placeholder's `NotImplementedError` actually happen. One exception is
deliberately NOT journalled: `LoopStateInsideRepoError`, caught before the
generic handler, because the journal lives under `--state` and writing it
would create the directory just refused — the defect §5 describes this wave
introducing and the enumerating test catching.

After:

```
$ aef loop cycle ... --module agents.migrated.graph --memory <m>
  error (NotImplementedError): convert your call sites into nodes
REAL EXIT=3

journal exists: True
  {"at": "...", "command": "cycle", "proposed": false,
   "verdict": "error (NotImplementedError): convert your call sites into nodes"}

the rendered workflow fails the job when status >= 2: exit 3 -> FAILS the job
```

### 7. A containment event is a security event with its own sentence

`EventKind.CONTAINMENT` (one additive member in `ledger.py`; an unknown
`kind` string cannot be read back, so the member has to exist for the event to
exist). `Digest` gains `containment_events` and `containment_reasons`; the
`**A proposal reached for the harness**` line now fires only when there is a
security event that is **not** a containment event, and containment events get
their own heading:

```
- Security events: 1

**Shadow runs were not contained.**
- shadow ran uncontained: no container runtime found (docker/podman)
  Counted as a security event because the candidate was not contained, not
  because it attacked anything. Install docker or podman, or say so
  deliberately in the config.
```

Still counted in `security_events` — the owner must know the candidate was
not contained — and reasons are de-duplicated, so three identical fallbacks
are one line and a count of three. The control test (`a real security event
still says a proposal reached for the harness`) is what keeps this a rename
rather than the alarm being removed.

## Mutations

Twelve planted, twelve caught, every restore verified byte-identical by
SHA-256, plus one more against the real generated module.

| # | Mutation | Caught by |
|---|---|---|
| M1 | `cmd_run` stops requiring a memory flag | `test_every_turn_running_subcommand_refuses_without_a_memory_flag[run]`, `test_the_refusal_is_in_the_handler_not_only_the_parser` |
| M2 | `cmd_run` journals nothing | `test_every_turn_running_subcommand_journals_its_attempt[run]`, `test_a_run_journals_one_attempt_per_turn_not_one_per_invocation`, `test_the_monitor_names_a_run_that_has_been_producing_nothing` |
| M3 | `cmd_cycle` journals only the normal return (the pre-fix placement) | 6 tests, including `test_a_halted_cycle_is_journalled` and all three injected exception paths |
| M4 | preflight forgets the factory shape | `test_a_factory_node_built_with_route_reflect_counts_as_routed`, `test_a_factory_route_to_a_custom_reflect_id_is_honoured`, `test_the_real_migrate_output_passes_the_real_preflight` |
| M5 | `bless` stops recording the agent root | `test_bless_records_which_zone_a_tree_it_archived`, `test_a_baseline_blessed_under_another_root_is_reported_unmet_by_name` |
| M6 | the agent-root/agent-path guard always proceeds | all four of `test_a_widened_root_with_the_default_agent_path_is_refused` |
| M7 | **a THIRD subcommand runs a turn and nobody added it** | `test_the_list_of_turn_running_subcommands_is_derived_not_remembered` |
| M8 | `_config` stops asking whether the state dir is inside the repo | 5 of `test_every_subcommand_refuses_a_state_directory_inside_the_repo` |
| M9 | `bless` stops asking as a library call | `test_bless_refuses_it_as_a_library_call_too` |
| M10 | an unexpected exception is `EXIT_REJECTED` again (the pre-fix behaviour) | `test_an_exception_from_the_graph_is_exit_error_not_a_rejection[cycle]` |
| M11 | the digest renders a containment event as an attack again | `test_a_containment_event_is_not_reported_as_a_proposal_reaching_the_harness` |
| M12 | the digest stops naming the containment reason | 4 monitoring tests, including the control that a real security event still names the harness |
| R | the REAL generated module regenerated and edited to `route=END` | `_reflect_is_routed_to` returns `(False, "…nothing routes to it…")`; restored byte-identically and green again |

M7 is the one worth naming. The finding was that a defect fixed in one command
was left standing in its twin; a test that names the two commands would have
been satisfied the day the third appeared. Deriving the list from the AST is
what makes the *class* of defect closed rather than this instance of it.

## Consequences

- `aef loop run` now requires a memory flag. No invocation in this repo's
  workflows, `adopt` templates or documents passes `loop run` at all
  (`grep` finds it only in tests and ADRs), so no emitted document needed a
  flag added; the tests that call it were updated to say which they mean.
- `cycles.jsonl` can now contain entries from two commands and entries with an
  `error (...)`/`HALTED (...)` verdict. `read_cycle_attempts` skips a
  malformed line, as before, and `assess_cycle_staleness` is unchanged.
- `ArchiveEntry.agent_root` is additive and defaulted; `from_payload` reads it
  with `.get`, so every existing `entry.json` loads and reports "root not
  recorded".
- Four subcommands that previously accepted an in-repo `--state` now refuse.
  That is a behaviour change on an invocation the driver already called
  unsafe, and the message is the driver's own.
- +55 tests, 2153 → 2208.

## Confidence

High on all five reproductions: each is a command, its real output and its
exit code, run on the parent commit before anything was edited, and re-run
after. High on F1, F2 and M4's fixes — each was re-run end to end and the
"after" output is pasted above.

High on F7's *reporting* half (the obligation, the refusal, both driven
through the CLI). **Medium on F7's effect**: nothing retroactively repairs a
baseline already blessed without a root, and the drift rejection itself is
unchanged — a repo carrying a mismatched baseline today will still see
`cumulative drift: 1.000` until someone runs `doctor` and reads the new line.
Whether any such baseline exists in the wild is not measured.

Medium on F6's coverage: one of three named exception paths is reproduced end
to end at the CLI and two are reached by injecting at the collaborator
boundary, because the gates reject before those raise. The `finally` covers
all of them and the unnamed case too, which is the property being claimed.

Nothing is claimed about whether any scheduled loop will now propose anything.
As ADR 0165 said of its own change, nothing here makes that more likely; what
changes is that a loop producing nothing says so, from both of the commands
that can produce something.
