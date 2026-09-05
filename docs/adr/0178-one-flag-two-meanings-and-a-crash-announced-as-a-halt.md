# ADR 0178: One flag with two meanings, and a crash announced as a halt

## Status

Accepted. Fix wave J2 of the upgrade loop: two findings from the third seam
hunt, each reproduced by running a command before anything changed. **No
rubric dimension moves** — nothing here adds a capability. One closes a
diagnostic that was permanently wrong about the repo shape it exists to
serve; the other stops the nightly summary naming the wrong remedy.

**Errata** are appended to ADR 0167 (its obligation-2 and obligation-6 fixes
were correct and the flag feeding them carried a second meaning) and to
ADR 0157 (it documented `--agent-path` as the persona under `--proposer`,
and nothing reconciled that with the flag's other reader).

## The findings, reproduced

`PYTHONPATH`, the venv and long paths elided. Both blocks are real output
from this branch's parent commit (db2987a).

### R2 — `--agent-path` is one flag with two meanings

The fixture is the real `aef migrate` on a two-persona repo, widened root,
with `from src.client import C` appended to ONE generated graph and
`src/client.py` doing `import anthropic` — the same planted fault ADR 0167's
obligation-6 finding used, one flag over.

```
graphs written:
   .claude/agents/accela.md  ->  .claude/agents/migrated/marlin_accela/graph.py
   .claude/agents/azure.md   ->  .claude/agents/migrated/marlin_azure/graph.py
planted `from src.client import C` in .claude/agents/migrated/marlin_accela/graph.py

$ aef loop doctor --repo <pilot> --state <s> --corpus <c> \
      --agent-root .claude/agents --agent-path .claude/agents/accela.md
    [--] reflect node routed to  no reflect node in the graph
         fix: add make_reflect_node() to your graph AND make a node
              `return delta, 'reflect'` — an Edge alone does not route (ADR 0070)
    [--] blessed baseline        0 archived version(s)
         fix: aef loop bless --repo . --state <s> --agent-path .claude/agents/accela.md
              --agent-root .claude/agents
    [OK] model calls visible     1 graph scanned, none reaches a model SDK the
                                 harness cannot see
EXIT=1
```

Three wrong lines about a correctly generated repo.

- **`no reflect node in the graph`** is said of a markdown file, and the fix
  tells the reader to add a node `aef migrate` has already written and
  routed. Executing that generated module gives the trace
  `['prompt_agent', 'reflect', 'consolidate']` (ADR 0167 §3 measured it).
- **`[OK] model calls visible`** is a clean bill of health over a repo with
  a planted invisible model call. The persona `.md` is opened, reaches no
  imports, and counts as `1 graph scanned` — and the wide scan that would
  have opened the generated graphs is disabled, because `--agent-path` is
  not at its default (ADR 0167 §8's condition, read literally).
- The **`bless` fix line** names the persona. Under the DEFAULT root a
  persona is outside the tree `bless` archives, so following it gets
  `... is NOT inside the tree this would archive`.

And the same two lines reach every cycle, because `_warn_unmet_obligations`
calls the same function:

```
$ aef loop cycle --repo <pilot> --state <s> --workdir <w> --corpus <c> \
      --no-memory --proposer rule_based_prompt --agent-root .claude/agents \
      --agent-path .claude/agents/accela.md
    preflight: 5 of 6 obligation(s) unmet (corpus + tripwire, reflect node routed
    to, observations, halt channel, blessed baseline). ADVISORY — ...
EXIT=0
```

(That scratch repo's corpus was empty, so obligation 1 is on the list too;
the finding is `reflect node routed to`, which is on it *forever*.)

**`--agent-path .claude/agents/accela-agent.md` is the documented
invocation.** ADR 0157 §1 reproduces exactly it, and `--proposer`'s own help
text says `rule_based_prompt: for a `.md` prompt-file agent (--agent-path
<persona>.md)`. So the flag genuinely has two meanings — and the four
`--agent-path` arguments on `cycle`, `run`, `bless` and `doctor` carried **no
help text at all**, which is why the only written record of the second
meaning lived under a different flag.

This is ADR 0167's F2 shape one level up. F2 was "the detector understood one
of the two shapes a graph can take"; this is "the detector was fixed, and the
flag feeding it was carrying a second meaning nobody had joined up". Two
modules each individually correct and individually tested, and nothing ran
one's *invocation* through the other.

### R8 — exit 3 is announced as "HALTED"

```
aef.harness.loop: EXIT_HALTED=2  EXIT_ERROR=3

--- the rendered adopter workflow's exit-code case ---
  0) escalated, or nothing to propose — read the verdict line
  1) REJECTED by a gate — the system working, not a broken job
  2) HALTED — do not retry, a person must look
  *) the cycle raised: this is an ERROR, not a verdict
  arms present: ['*', '0', '1', '2']

$ status=3; <the rendered case>; echo "$meaning"
  the cycle raised: this is an ERROR, not a verdict

--- and then, because 3 -ge 2, the failure step runs ---
  echo "## Self-rewiring loop HALTED in target" >> "$GITHUB_STEP_SUMMARY"
  aef loop status --repo . --state ~/.aef-loop-state >> "$GITHUB_STEP_SUMMARY" || true
  exit 1

--- this repo's own workflows ---
  loop-monitor.yml: # HALTED, or an invocation the CLI refuses — should fail the job and
  loop-monitor.yml: - name: Surface a halt
  loop-monitor.yml: echo "## Self-rewiring loop HALTED" >> "$GITHUB_STEP_SUMMARY"
  loop-gate.yml:    # exit 2 = the loop halted; do not retry, read the ledger
```

The failure RULE is right: `-ge 2` catches both, which is what ADR 0167 §6
chose the code against. What is wrong is the WORDS. ADR 0167 §6 picked 3
rather than reusing 2 for exactly one reason — *"a halt and a crash call for
different actions (release the kill switch versus fix the invocation)"* — and
then the surface an owner actually reads told them, for both, to go look at
the kill switch. This repo's own `loop-monitor.yml` had no per-code summary
at all, and `loop-gate.yml`'s comment stopped at 2.

## Decisions

### 1. A persona is resolved to its generated graph, by migrate's own mapping

`aef/harness/preflight.py` gains `AgentSource` and `resolve_agent_source`.
Anything not ending in `.md` is returned unchanged, so every existing caller
is unaffected. A `.md` is looked up in **`discover_prompt_agents`** —
imported from `aef.cli.migrate`, not re-derived — and becomes that persona's
`out_relative`.

Imported rather than re-spelled because the mapping is not one rule but
four: lowercase-and-fold to an identifier, prefix a leading digit or a
keyword, disambiguate collisions across the run, and place the result at
`<agent-root>/migrated/<module>/graph.py` (ADR 0152 §2). A second spelling
here would be the ADR 0149 shape — two answers to one question, drifting the
first time either gains a case — and this file has already lost a whole
obligation to precisely that (ADR 0167's C↔D finding).
`test_the_mapping_is_migrates_own_not_a_second_spelling_of_it` asserts the
resolved path equals `site.out_relative` for every persona the real
`run_migrate` wrote.

The obligations report on the graph and **say which file they read**, because
the answer is about a file the caller did not type:

```
$ aef loop doctor --repo <pilot> --state <s> --corpus <c> \
      --agent-root .claude/agents --agent-path .claude/agents/accela.md
    [OK] reflect node routed to  .claude/agents/migrated/marlin_accela/graph.py:
         make_prompt_agent_node(route='reflect') builds a node that routes to it
    [--] blessed baseline        0 archived version(s)
         fix: aef loop bless --repo . --state <s>
              --agent-path .claude/agents/migrated/marlin_accela/graph.py
              --agent-root .claude/agents
    [--] model calls visible     .claude/agents/migrated/marlin_accela/graph.py:
         src/client.py:1 imports anthropic — the harness cannot see it
EXIT=1
```

**The proposer is untouched.** `rule_based_prompt` still receives the persona
path; nothing about which file gets a lesson appended changes. Only the two
obligations that ask a question about Python resolve it, plus obligation 5's
`bless` fix string, which is a command that must run.

### 2. No generated graph is said in words, and is not "no reflect node"

```
    [--] reflect node routed to  persona .claude/agents/accela.md has no generated
         graph — `aef migrate` would write it to
         .claude/agents/migrated/marlin_accela/graph.py and nothing is there.
         Nothing was read, so nothing is claimed about the graph's wiring or its
         model calls
         fix: run `aef migrate --dir . --agent-root .claude/agents` to generate the
         graph for this persona, or pass --agent-path naming the module that builds
         your graph. ...
```

Both obligations carry it. "No reflect node in the graph" is a claim about a
graph that was read; when there is no graph, saying it is a false statement
about a file that does not exist, and the fix it prints is an edit nobody can
make. A `.md` that no persona discovery claims gets its own sentence too — it
is neither a graph nor a persona, and that is what is wrong with it. (At the
CLI under a *widened* root that last case never arrives: ADR 0167 §4's Zone
guard refuses `--agent-path NOTES.md` with `Zone C (core)` before preflight
runs. It arrives under the default root, and to any library caller.)

### 3. The wide scan follows the persona, and NOT every named path

Obligation 6 widens to `discover_graph_files` when `scan_all_graphs` is set
**or when the path was resolved from a persona**. The reason is ADR 0167
§8's, applied to a second case rather than restated: the wide scan is for a
path *this package guessed*. A persona-resolved graph is such a guess — the
owner named an agent, and the graph is this package's derivation from it.

**Deliberate deviation from the brief**, recorded rather than done quietly.
The brief said the wide scan should run "whenever the resolved graph is under
the agent root". That is a superset: it would also widen for an
explicitly-named `.py` under the root. Nothing in either seam hunt reproduced
a problem with that case; ADR 0167 §8 decided in writing that *"a caller that
names a path still gets an answer about that path"*, and
`test_scanning_only_the_defaulted_path_passes_on_the_stub` pins it. Widening
it here would be a fix wave strengthening a control on invocations nobody has
shown a problem with — ADR 0141's rule, which ADR 0167 §4 already applied to
itself. A future owner who wants the wider default should change it as a
decision, not inherit it from this wave.

`test_naming_one_persona_still_scans_the_OTHER_agents_graphs` is the one that
earns the widening, and it earned it the hard way: the first version of the
mutation table had **M2 SURVIVE**, because the planted fault was in the graph
the named persona resolves to, so the narrow scan found it and the test
proved nothing. The fault now lives in the *other* agent's graph.

### 4. `--agent-path` says both forms, on every subcommand that takes it

One `_AGENT_PATH_HELP` string, on all five arguments (`gate` keeps its own
first sentence about `--entrypoint` and appends the shared text). It names
the module form, the per-agent path `aef migrate` prints, the persona form
with `--proposer rule_based_prompt`, and what leaving it at the default does
to obligation 6.

`test_every_loop_agent_path_argument_documents_both_forms` DERIVES the list
from the built parser rather than naming five subcommands — ADR 0167's M7
lesson: a test that names the four that existed would have been satisfied the
day a fifth appeared. `test_the_proposer_help_and_the_agent_path_help_agree`
asserts the two flags' help texts still point at each other.

### 5. A halt and a crash are two summaries with two remedies

The `case` in `aef/cli/adopt_loop.py`'s rendered workflow and in this repo's
own `.github/workflows/loop-monitor.yml` gains a `3)` arm, and the failure
step is renamed and taught to tell them apart. The cycle step writes its exit
code to `$RUNNER_TEMP/cycle.status` before failing the job, because
`if: failure()` carries no status of its own.

Executed, not asserted (`bash -c` over the arms extracted from the rendered
YAML):

```
  exit 0 -> escalated, or nothing to propose — read the verdict line
  exit 1 -> REJECTED by a gate — the system working, not a broken job
  exit 2 -> HALTED — the kill switch is on; clearing it is a deliberate act
  exit 3 -> ERROR — the cycle crashed; no kill switch is set, fix the invocation
  exit 9 -> exit 9 is not a code this loop defines — the cycle raised

--- the failure step, run for each recorded code ---
  cycle.status = 2:
      ## Self-rewiring loop HALTED in target
      The kill switch is on. Read the ledger, then remove
      ~/.aef-loop-state/HALTED to resume — a deliberate act, not an
      automatic one.
  cycle.status = 3:
      ## Self-rewiring loop ERROR in target — the cycle crashed
      This is NOT a halt: no kill switch is set and clearing one changes
      nothing. The exception is in the cycle log above; the remedy is to fix
      the invocation (the module, the entrypoint, the corpus, the config).
  cycle.status = (no code recorded):
      ## Self-rewiring loop job FAILED in target
      No cycle exit code was recorded, so the cycle is not what failed —
      read the failing step above.
```

The third arm is not decoration: `Surface a halt` fired on `if: failure()`,
which includes the checkout, the install and the module guard step (ADR
0172's R3). Those were being announced as halts too.

`loop-gate.yml`'s comment now lists exit 3 with its remedy, and says plainly
that `aef loop gate` does not return it yet — see the open item below.

**The failure RULE is unchanged**, and that is asserted rather than assumed:
`test_the_rendered_nightly_workflow_would_fail_the_job_on_that_code` (ADR
0167's) still reads `-ge 2` out of `adopt_loop.py`, and
`test_the_workflows_still_fail_the_job_on_every_code_at_or_above_two` pins
it for both of this repo's own files. An exit code chosen without checking
the rule that consumes it is how 1 came to mean two things.

## Mutations

Eleven planted, **eleven caught**, every restore verified byte-identical by
SHA-256 (`git checkout --` was never used).

| # | Mutation | Caught by |
|---|---|---|
| M1 | a persona `.md` is read as Python again (the pre-fix behaviour) | 9 tests, incl. `test_a_persona_resolves_to_the_graph_migrate_generated_for_it`, `test_the_documented_prompt_proposer_invocation_reports_on_the_generated_graph` |
| M2 | obligation 6 does not widen for a persona-resolved graph | `test_naming_one_persona_still_scans_the_OTHER_agents_graphs` |
| M3 | a persona with no generated graph falls through to the Python answer | `test_a_persona_with_no_generated_graph_says_so_in_words`, `..._is_told_to_migrate` |
| M4 | the reflect obligation stops naming the file it actually read | `test_a_persona_resolves_to_the_graph_migrate_generated_for_it`, the CLI end-to-end one |
| M5 | the `bless` fix names the persona again | `test_the_bless_fix_names_the_graph_not_the_persona` |
| M6 | `--agent-path` loses its help text on ONE subcommand | `test_every_loop_agent_path_argument_documents_both_forms` |
| M7 | the rendered summary calls exit 3 a HALT again | `test_the_cycle_summary_says_what_the_exit_code_MEANS`, `test_the_exit_code_case_is_shell_that_maps_every_code` |
| M8 | the rendered failure step stops recording which code failed | `test_the_failure_step_does_not_call_a_crash_a_halt` |
| M9 | this repo's own nightly summary loses the exit-3 arm | `test_the_nightly_summary_gives_every_exit_code_its_own_words` |
| M10 | this repo's failure step says HALTED for a crash again | `test_the_failure_step_tells_a_halt_from_a_crash` |
| M11 | the gate workflow's comment stops at exit 2 | `test_the_gate_workflow_names_the_exit_code_an_exception_gets` |

M2 is the one worth naming: it **survived the first pass**, and the reason is
the reproduce-first rule about verifying a detector against a planted fault.
The test that was supposed to prove the widening had the fault inside the
narrow scan's own target, so it passed either way. Moving the fault to the
other agent's graph is what made the mutation lethal.

## Consequences

- `aef/harness/preflight.py` now imports from `aef/cli/migrate.py`, inside
  the function rather than at module scope. That is harness→cli, which is the
  wrong direction for a layering rule this repo does not otherwise state; it
  is accepted because the alternative is a second copy of the persona→module
  mapping, and ADR 0149's finding is that two copies of one derivation is a
  defect waiting for its first divergence. `migrate` imports nothing from
  `preflight`, so there is no cycle.
- A `.md` `--agent-path` that names no discovered persona is now an UNMET
  obligation where it used to be met (obligation 6 reported `1 graph
  scanned`). That is a behaviour change, and it is the honest one: nothing
  was scanned.
- Obligation 6 scans more files on the persona form. On a nine-graph repo it
  reads nine instead of one, which is the point.
- The rendered nightly workflow's failure step is renamed `Surface a halt or
  an error`. No test named the old step by name; the adopter's existing
  workflows are not rewritten by this (adopt never overwrites a file that
  exists), so a repo adopted before this keeps the old wording until it
  regenerates.
- `$RUNNER_TEMP/cycle.status` is a new file the rendered workflow writes. It
  lives in the runner temp, not the state directory, so it cannot reach a
  candidate's diff.

## Still open — NOT fixed here, for the final wave

**Eleven of the thirteen `aef loop` subcommands still report a crash as exit
1.** Only `cycle`, `run`, `doctor` and `bless` return `EXIT_ERROR`; every
other handler lets the exception reach `aef/cli/main.py`'s catch-all, which
returns 1 — and 1 is also `EXIT_REJECTED`, "the candidate was rejected, the
system is working". That is ADR 0167's R3, still standing for the majority of
the surface, and `loop-gate.yml`'s new comment says so in the file where it
matters. It is deliberately not fixed here: it is a change across the whole
of `aef/cli/loop.py`, which two other workers held during this wave.

## Confidence

High on both reproductions: each is a command, its real output and its exit
code, run on the parent commit before anything was edited, and re-run after —
both "after" blocks are pasted above.

High on R2's fix, which is exercised end to end through the real
`run_migrate` into the real `aef loop doctor`, and on R8's, whose four arms
and three summary bodies were **executed in bash** rather than matched as
text.

**Medium on R8's breadth**: the YAML was never run by a scheduler. What was
executed is the `case` and the failure step's body, extracted from the
rendered document, exactly as ADR 0172 states for its own guard step.

Nothing is claimed about whether any prompt-file repo's loop will now
propose anything. What changes is that its diagnostic stops being wrong about
a correct graph, and that a crashed night stops telling the owner to go and
look at a kill switch nobody set.
