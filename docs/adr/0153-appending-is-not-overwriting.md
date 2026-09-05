# ADR 0153: appending is not overwriting — `aef adopt` into a repo that already has files

## Status

Accepted. Increment **M2** of `UPGRADE_LOOP.md`. **No rubric dimension
moves** — INGEST_LOOP's rule stands: adoption work claims no rubric point.

## Context

`UPGRADE_LOOP.md`'s survey found seven agentic repos on this machine. Every
eligible one has **zero model-SDK call sites** and between three and
twenty-six agents that are `.md` prompt files. `aef adopt` had one label for
that shape — `none`, whose migration note reads "no agent framework or raw
model-SDK usage detected … there's no existing orchestration code to migrate
away from" — and one rule for files that already exist: skip them.

Three things follow, and all three were reproduced by RUNNING `aef adopt` on a
clone of a real repo (`marlin`: 8 agents, 5 skills, `AGENTS.md`, `.codex/`, no
`CLAUDE.md`) before anything was changed.

### R1 — the label said nothing about the eight agents

```
$ aef adopt --dir <clone>
detected framework: none
```

`none` is the label for "no orchestration code", which is true, and it is also
what a genuinely empty directory gets. Nothing in the report, the generated
`CLAUDE.md`, or the checklist mentioned that the repo has eight agents.

### R2 — the contract never reached the file the repo's agents read

```
skipped <clone>/.gitignore (already exists)
skipped <clone>/AGENTS.md (already exists)

$ grep -c AEF <clone>/AGENTS.md
0
$ grep -c AGENT_INTEGRATION <clone>/AGENTS.md
0
```

Adopt wrote a `CLAUDE.md` this repo does not have and does not use, and
skipped the `AGENTS.md` it does. The one file that repo's harness loads on
every session came out of adoption with **zero** mentions of the scaffold.

The same, in the other direction, on a repo that has a `CLAUDE.md`:

```
$ printf '# My repo\n\nHouse rules for agents here.\n' > CLAUDE.md
$ aef adopt --dir .
detected framework: none
skipped <repo>/CLAUDE.md (already exists)
$ cat CLAUDE.md
# My repo

House rules for agents here.
$ grep -c AGENT_INTEGRATION CLAUDE.md
0
```

`AGENT_INTEGRATION.md` was written, and nothing the adopter's agent opens
points at it.

### R3 — the adopted repo's loop never ran unattended

Found by the independent re-score (J0) and confirmed by two workers: the
`.github/workflows/loop-monitor.yml` that `adopt` renders had an hourly
`aef loop monitor` and a weekly `aef loop digest` and **no `aef loop cycle`
step at all**, while this repo's own workflow has had a daily cycle since ADR
0057. An adopting repo could get every obligation green and still never
propose anything except by hand.

## Decision

### D1 — a fifth framework label, `prompt_files`, with counts

`detect_prompt_surface` counts `.claude/agents/*.md`,
`.claude/skills/*/SKILL.md`, `AGENTS.md`, `.codex/`,
`.github/copilot-instructions.md` and `.cursor/rules/*`.
`detect_framework` returns `prompt_files` when the existing code/manifest scan
finds nothing and that surface is non-empty. The report carries the counts:

```
detected framework: prompt_files (8 agents, 5 skills, AGENTS.md, .codex)
```

**Precedence: a code/manifest signal wins the label.** The reason is what the
label is *for*: it selects the per-framework migration notes and the
convert-your-call-sites half of the checklist, and a repo with real
LangGraph/CrewAI/SDK call sites still needs those — the call sites are what
`aef migrate` can route losslessly and what makes a model call invisible to
the harness when it does not. Nothing is lost the other way round:
`describe_detection` reports the prompt counts under **every** label
(`raw_sdk (+ prompt files: 2 agents)`), and the "run `aef migrate` — it
registers your N prompt agents as graphs" checklist step is emitted whenever
N > 0. Choosing `prompt_files` first would hide the framework notes entirely,
which is a real loss; choosing the code label first hides nothing.

The checklist's convert-call-sites step becomes, for a prompt repo:

> Run `aef migrate --dir .` — it registers 8 prompt agents
> (`.claude/agents/*.md`) as graphs, one graph per agent at
> `agents/migrated/<agent>/graph.py` (the graph's `graph_id` is the agent's
> name), inside Zone A. There is no call site to convert: each node runs that
> agent's prompt as the system prompt of a single harness model call. The
> prompt runs; the agent's tools do not. NOTE which file the loop may then
> edit: the GRAPH is Zone A, the PERSONA `.md` is Zone C by default, so a
> candidate editing the prompt itself is rejected until you widen the agent
> root — `aef migrate --agent-root ...` is opt-in per repo and its report says
> what that adds to the loop's blast radius.

That text describes what **M1** landed (one graph per prompt agent, `graph_id`
= the agent name, `--agent-root` as the opt-in that widens Zone A to the
persona files). It is written against M1's shape and is wrong if M1 is
reverted; the paths in it are derived from `DEFAULT_MIGRATED_OUT`, never
spelled out, so a change to migrate's default moves the documents with it.

### D2 — append within markers, for the five entry files

`CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`,
`.cursor/rules/aef.mdc` and `.gitignore` are no longer skipped when they
exist. They gain a block:

```
<!-- aef:begin -->
## AEF scaffold (<repo>) — generated section
…
<!-- aef:end -->
```

`.gitignore` uses `# aef:begin` / `# aef:end`, because its syntax has no HTML
comments, and its block is only the two bytecode patterns and only when the
file covers neither already (ADR 0142's no-nagging rule, kept).

**Appending inside markers is not overwriting, and this is the argument.**
ADR 0034/0040's rule exists so that a scaffold cannot destroy an adopter's
work. Nothing here is destroyed: every pre-existing byte survives verbatim and
outside the block, the adopter can see exactly what was added because it is
delimited, re-running replaces only what is between the markers, and deleting
the block restores the file exactly. The rule the scaffold needs is **never
destroy**, and "never write" was a proxy for it that failed in the one case
that mattered — the file the repo's agents actually read.

`apply_block` refuses rather than guesses:

- a begin with no end, an end with no begin, or two begin markers → **skip**,
  with the reason (`refusing to guess which bytes are the block`);
- a file that is not readable as text → **skip**, with the reason;
- a symlink, or a file under a symlinked parent → **skip** (unchanged from
  before: adoption never writes through a link).

`AdoptResult` gains `appended_files` and `skip_reasons`, and the CLI reports a
third verb:

```
appended aef block to <clone>/AGENTS.md (your bytes outside it are unchanged)
skipped <clone>/aef.yaml (already exists)
skipped <clone>/.gitignore (already carries the current aef block)
```

The generated `CLAUDE.md`, `AGENTS.md` and the two harness pointers carry the
same block, which is what makes a second `aef adopt` a byte-for-byte replace
rather than a second append. The pointer files' body **is** the block now, so
there is one contract rather than four copies of it.

**The block quotes only the `.claude/agents/*.md` count.** That is a
correctness property, not a style choice: every other prompt-surface signal
names a file `aef adopt` itself writes, so a block quoting them would say
something different on the second run and rewrite four entry files forever.
The first version did quote the full surface, run 2 on the clone was not
idempotent, and that is how it was found — by running adopt twice, not by
reading it.

### D3 — the emitted workflow runs a cycle

`render_loop_monitor_workflow` gains a `0 3 * * *` cron and a
`workflow_dispatch`-able **Daily cycle** step passing `--state`,
`--memory ~/.aef-loop-state/memory.jsonl`, `--config aef.yaml`,
`--corpus corpus`, `--module`/`--entrypoint` (three `AEF_*` env values the
owner edits), `--build-command`, and `--cassette-miss fail`.

`fail`, not `live`, and the comment says why: CI has no coding-agent harness
login, so `live` there either fails for want of a credential or spends one
nobody chose to spend. Prompt candidates are scored live from a machine that
has the login.

The step tees the cycle's output into `$GITHUB_STEP_SUMMARY` **in words**,
because `no admissible failure memory` and `escalated` both exit 0 and a
nightly job that is green either way tells nobody which happened. Exit 1 (a
rejection — the system working) does not fail the job; exit 2 (a halt) does.

### D4 — the kit names every wired harness, and guesses at none

The generated `aef.yaml` listed two implementations. Four reach a node's model
call after ADR 0112/0154, so the template and the prompt-file section name all
four, with each one's status rather than a list:

- `claude_code` — default, the coding agent's own login, reproduced end to end;
- `codex` — from the CLI's documented flags, **not** reproduced;
- `grok` — measured through the provider, and the honest number goes with it:
  `--cwd <an empty directory>` is its load-bearing isolation flag, and **~17.9k
  tokens of the operator's own session still reach the model, with no flag that
  stops that**. Naming the flag without naming the leak would sell isolation
  the provider does not have;
- `command` — a generic CLI harness from an argv template. **GitHub Copilot's
  CLI is `command`, configured by the owner who installs it**; this repo ships
  no guess about its flags, because a flag's shape is not a flag's value
  (ADR 0150).

### D5 — `aef doctor` reports an entry file that never reaches the guide

Advisory, and only in a repo that looks adopted: `CLAUDE.md`/`AGENTS.md` that
name neither the marker block nor `AGENT_INTEGRATION.md` are reported with the
fix. A repo adopted before this ADR, or one whose block was deleted, still has
R2's gap and nothing else would say so.

## Evidence

Every command run in this worktree against a **copy** of the read-only pilot
clone. `python` = the repo `.venv`. **Zero model calls.**

### The reproduction (before the change)

Quoted in Context above: `detected framework: none`, `skipped AGENTS.md
(already exists)`, `grep -c AEF AGENTS.md` → **0**, and the existing-`CLAUDE.md`
repo whose file comes back unchanged with no pointer to the guide.

### After (the same clone, reset with `checkout -- . && clean -fd`)

```
$ aef adopt --dir <clone>
detected framework: prompt_files (8 agents, 5 skills, AGENTS.md, .codex)
wrote <clone>/CLAUDE.md
… 15 written …
appended aef block to <clone>/.gitignore (your bytes outside it are unchanged)
appended aef block to <clone>/AGENTS.md (your bytes outside it are unchanged)

$ grep -c AEF <clone>/AGENTS.md
2
```

Pre-existing bytes, by hash. `outside` = the file with the marker pair and
everything between it removed:

```
AGENTS.md   original bytes are a prefix of the result:  True
            sha256(original)          ffd0ff4aac70ce5f10f9d3c9efb02b6b612b24e44a614e24abc3587040620cc4
            sha256(outside, after)    f734386621e1ac90ffb1e980db3c4fbc996c0787ee1cd8b5313198a90a226dcf
.gitignore  original bytes are a prefix of the result:  True
            sha256(original)          f7e1bbe7ff336ef879b3ae00e146d6305778c20e911ab8077be6c5e193ec8e12
            sha256(outside, after)    cf2943409cc04d5905c9491ce2309d6cc90fd0c1b37c86e6ee737013a7063a25

$ git -C <clone> diff --stat
 .gitignore |  5 +++++
 AGENTS.md  | 36 ++++++++++++++++++++++++++++++++++++
 2 files changed, 41 insertions(+)
```

Insertions only. No line of either file was modified or removed.

### Idempotency, over the whole tree

```
$ aef adopt --dir <clone>        # run 2
detected framework: prompt_files (8 agents, 5 skills, AGENTS.md, .codex)
                                 # nothing written, nothing appended
$ diff run1.sha run2.sha         # sha256 of all 260 files, excluding the VCS dir
                                 # (no output)
IDEMPOTENT: run 2 changed no byte of any file
```

The detection line is identical on both runs, which is the property D2's
"agent count only" rule exists to protect.

### Tests

Twenty-two new test items — the four touched files go 111 -> 133 collected, and the suite 2002 -> 2024, with nothing removed. In `tests/cli/test_adopt.py`:

- `test_a_repo_whose_agents_are_prompt_files_is_not_reported_as_none` (the
  reproduction)
- `test_prompt_file_detection_does_not_count_what_adopt_itself_wrote`
- `test_a_second_adopt_on_a_prompt_repo_changes_no_byte_of_any_file`
- `test_the_block_is_replaced_in_place_and_the_bytes_outside_it_are_untouched`
  (hash of the outside text, against a planted *stale* block)
- `test_a_file_with_markers_adopt_cannot_resolve_is_skipped_with_the_reason`
  (3 params: unmatched begin, unmatched end, two blocks)
- `test_a_binary_entry_file_is_skipped_with_the_reason_not_appended_to`
- `test_the_checklist_tells_a_prompt_repo_to_run_migrate_not_to_convert_call_sites`
- `test_a_repo_with_call_sites_and_prompt_agents_keeps_the_sdk_notes_and_gains_the_step`
  (the precedence decision)
- `test_the_block_text_depends_only_on_signals_adopt_does_not_write`
- `test_the_cli_reports_appended_as_a_third_verb`
- `test_the_kit_names_every_wired_harness_and_guesses_at_none`
- `test_the_generated_entry_files_carry_the_block_they_would_append`
- `test_the_emitted_monitor_workflow_actually_runs_a_cycle` (parsed YAML, and
  the cycle's argv through the real CLI parser)

In `tests/cli/test_pristine_adoption.py`:
`test_the_kit_carries_the_prompt_file_sequence_and_the_sentence_that_makes_it_honest`
and `test_first_day_describes_the_appending_it_now_does`. In
`tests/cli/test_doctor.py`: the entry-file advisory and its silence in a
never-adopted repo. In `tests/test_prompt_surface.py`: `<adopt: LOOP.md>` and
`<adopt: aef block>` join the audited surface — the block is the only aef text
an adopter with their own `AGENTS.md` is guaranteed to have in front of their
agent.

Three pinned assertions were changed **deliberately**, and this is the note
saying so:

- `test_run_adopt_never_overwrites_harness_files` →
  `test_run_adopt_appends_to_existing_harness_files_without_touching_a_byte`
- `test_run_adopt_never_overwrites_existing_claude_md` →
  `test_run_adopt_appends_to_an_existing_claude_md_and_destroys_nothing`
- `test_run_adopt_never_overwrites_a_gitignore_and_says_what_is_missing` →
  `test_run_adopt_appends_the_bytecode_patterns_to_an_existing_gitignore`

Each moves from "the file is unchanged" to "the file's own bytes are unchanged
and the block is there". `test_run_adopt_is_idempotent_on_second_run`'s 17/17
counts did **not** move: a re-run reports the entry files as
`skipped (already carries the current aef block)`, because the computed text
equals what is on disk. The command-coverage floor in
`test_every_emitted_aef_command_is_one_the_cli_accepts` moves 30 → 50 (54
commands are extracted now; the prompt-file sequence adds six, in two
documents, with two flags a document could easily invent).

### Mutations

Each perturbs one production value, is run, and is restored from a
sha256-verified byte backup. Suite: `test_adopt.py`, `test_pristine_adoption.py`,
`test_doctor.py`, `test_prompt_surface.py`.

```
BASELINE                                                     133 passed
M1  detect_framework never returns prompt_files                1 failed
M2  an existing entry file is skipped, never appended to       8 failed
M3  apply_block appends a second block instead of replacing    2 failed
M4  apply_block guesses at unresolvable markers                3 failed
M5  the block quotes the full surface                          1 failed
M6  detection counts adopt's own output as the repo's agents   2 failed
M7  the gitignore block is appended even when covered          1 failed
M8  the checklist keeps "convert your call sites"              1 failed
M9  the emitted workflow has no daily cycle step               1 failed
M10 the workflow's cycle passes no --memory                    1 failed
M11 the workflow's cycle scores misses live in CI              1 failed
M12 the prompt-file sequence loses the cassette sentence       1 failed
M13 doctor never checks the file the agent reads               1 failed
M14 the third verb is collapsed back into "skipped"            1 failed
M15 the aef.yaml template lists only two harnesses             1 failed
M16 Grok's isolation flag named, the leak it leaves not        1 failed
RESTORED                                                     133 passed
```

M5 and M14 **survived the first pass** and are recorded because a mutation
that survives is information. M5 survived because the earlier
`_is_adopt_generated` fix had already made the two texts behaviourally
equivalent for idempotency — the wording was unpinned, so
`test_the_block_text_depends_only_on_signals_adopt_does_not_write` was added
to pin the property rather than the words. M14 survived because no test ran
the CLI handler at all; `test_the_cli_reports_appended_as_a_third_verb` does.
Both are detected above.

### Green bar

```
pytest -q                              2021 passed, 3 skipped
mypy aef examples                      Success: no issues found in 129 source files
ruff check .                           All checks passed!
ruff format --check aef tests examples 242 files already formatted
model calls made                       0
```

## Consequences

- **The never-overwrite rule is now stated as never-destroy, and the
  difference is auditable.** Five named files may gain a delimited block;
  everything else is skipped as before. An adopter who wants none of it
  deletes the block, and adopt will append a fresh one on the next run —
  which is itself a behaviour someone may not want, and there is no flag to
  suppress it. `--no-append` is not implemented; nobody has asked for it, and
  inventing a flag for a hypothesis is how the last five stubs got written.

- **The prompt-agent text depends on M1.** The one-graph-per-agent path, the
  `graph_id`, and `--agent-root` as the Zone A opt-in are M1's contract. The
  sentences naming them are wrong if M1 is reverted, and the paths in them are
  derived from `DEFAULT_MIGRATED_OUT` rather than spelled out, so a change to
  migrate's default moves them automatically. The `<agent>` directory
  component is a placeholder in every generated document; nothing here asserts
  how M1 sanitises an agent name into a module name.

- **The prompt-file sequence is documented but not yet executed.** The six
  commands in `FIRST_DAY.md`/`LOOP.md` all parse through the real CLI, and
  none of them has been RUN end to end against the clone — that is M5's
  acceptance test and M6's pilot. Under ADR 0148's rule this is the weaker
  kind of generated document: written from the parser, not from a terminal.
  It is labelled as a sequence, not as pasted output, and no output is quoted
  for it.

- **The live-cost sentence is a claim about the mechanism, not a
  measurement.** "Every gate pass of a prompt candidate is live" follows from
  a cassette being keyed on the request: change the prompt, every request is a
  miss. The *size* of the live noise floor is S2's measurement, and the
  documents point at it as "the bar" without naming a number, because no
  number has been measured yet.

- **`detect_prompt_surface` is a file-shape heuristic.** A repo whose agents
  live somewhere else entirely — a `prompts/` directory, a `.github/agents/`,
  a vendored harness — gets `none` and this ADR does nothing for it. The
  discriminator between "adopt wrote this" and "the adopter wrote this" is the
  generated `# … — AEF scaffold contract` / `# … — agent instructions
  (aef-core)` heading beside a marker; a file that happens to carry both is
  misread, and that has not been proved absent in the wild.

- **The daily-cycle workflow ships with placeholder `AEF_*` values**, exactly
  like the gate workflow's two. A repo that commits it unedited runs a cycle
  against `agents.migrated.graph`, which may not exist — the job fails
  visibly, which is the right direction, but it is a cron job that fails every
  night until someone edits three lines.

## Erratum (ADR 0172, 2026-09-04) — two claims above are wrong

Both were found by running things this ADR did not run.

**1. "Every pre-existing byte survives verbatim" held for LF only.** That
sentence is the whole argument of D2, and the Evidence section's
`original bytes are a prefix of the result: True` and
`git diff --stat` → `41 insertions(+)` were measured on LF files. Every
byte-preservation test above used an LF fixture. `Path.read_text()` translates
`\r\n` to `\n`, `apply_block` was byte-exact on the *translated* text, and
`Path.write_text()` wrote it back with `os.linesep` — so on a CRLF `AGENTS.md`
the same code path rewrote all five of the adopter's lines
(`41 insertions(+), 5 deletions(-)`, every original line a `-`) while the CLI
printed `your bytes outside it are unchanged`. On Windows the mirror applies to
every file this scaffold *writes*. ADR 0172 reads and writes bytes, renders
only the added bytes in the file's own line ending, and enforces the claim with
an assertion (`_verify_preserved`) that refuses the write rather than a
sentence in a document.

**2. "The job fails visibly" was false on a prompt-file repo.** The
Consequences section says a repo that commits the generated workflow unedited
"runs a cycle against `agents.migrated.graph`, which may not exist — the job
fails visibly, which is the right direction". On a prompt-file repo — the shape
every repo in the survey has — that module *always* exists, because `aef
migrate` writes the placeholder whenever it finds no wrappable call site. Its
`build_graph()` raises, `main()`'s catch-all returns 1 = `EXIT_REJECTED`, and
D3's own rule (`exit 1 does not fail the job; exit 2 does`) reads that as a
healthy rejection. Measured: `EXIT=1`, job green, nothing proposed, and nothing
in `cycles.jsonl` for ADR 0165's staleness warning to count. ADR 0172 adds a
guard step that imports the module and calls `build_graph()` before the cycle,
and fails the job by name when it cannot.

**Under-stated rather than wrong:** D2's three refusal shapes are described as
covering "markers adopt cannot resolve". They cover the three *unbalanced*
shapes. A **balanced** pair adopt did not author — a `CLAUDE.md` quoting the
markers this kit teaches — was neither covered nor refused, and it was the only
one of the four that destroyed anything. ADR 0172's marker signature is the
fix.

## Confidence

**High on R2 and its fix.** The gap and the repair were both measured on a
clone of a real repo with `grep`, `shasum` and `git diff --stat`, not
asserted; the idempotency claim is a hash of all 260 files after each of two
runs, and it caught a genuine defect in the first version of this change.

**High on the marker mechanics.** `apply_block` refuses three ambiguous
shapes rather than guessing, each with a test, and the outside-text hash is
asserted against a planted stale block rather than against a fresh file.

**Moderate on the prompt-file *label* being the right abstraction.** It is one
heuristic over six file-shape signals, tuned on seven repos that all belong to
one owner. The precedence rule is argued rather than measured — no repo with
both call sites and prompt agents was available to adopt.

**Low on the generated prompt-file sequence being correct end to end.** Every
line parses; no line has been executed in that order against a real prompt
repo. That is M5's job, and if it finds this document wrong, this ADR is the
thing that was written from the source rather than from a terminal.
