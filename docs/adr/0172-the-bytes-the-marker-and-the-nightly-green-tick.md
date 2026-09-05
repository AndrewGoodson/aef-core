# ADR 0172: The bytes, the marker, and the nightly green tick

## Status

Accepted. Fix worker **H1** of the upgrade loop, closing five findings of the
second seam hunt in `aef/cli/adopt.py` and `aef/cli/adopt_loop.py`.
**No rubric dimension moves** — adoption work claims no rubric point
(INGEST_LOOP's rule, unchanged since ADR 0152/0153).

Model: `claude-opus-5[1m]`. **Zero live model calls.**

## Context

ADR 0153 gave `aef adopt` a third verb. Five entry files an adopter already
owns — `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`,
`.cursor/rules/aef.mdc`, `.gitignore` — stopped being skipped and started
gaining a delimited block, and the argument for why that is not overwriting is
one sentence: **every pre-existing byte survives verbatim and outside the
block.**

That sentence was true of the fixtures it was tested on. All of them were LF.

Five findings follow. Four were reproduced by running commands against scratch
repos and a copy of the read-only pilot clone; the fifth is a property of a
string in a YAML file for a scheduler this branch cannot run, and is labelled
as such rather than dressed up as a measurement.

### R1 — a CRLF entry file has every line rewritten, and adopt says it did not

`Path.read_text()` translates `\r\n` to `\n`. The marker logic is byte-exact on
the *translated* text. `Path.write_text()` writes it back with `os.linesep`.

A scratch repo: `AGENTS.md` and `.gitignore` in CRLF, one persona under
`.claude/agents/`, committed.

```
$ aef adopt --dir r1
detected framework: prompt_files (1 agent, AGENTS.md)
appended aef block to .../r1/AGENTS.md (your bytes outside it are unchanged)

$ git -C r1 diff --stat -- AGENTS.md
 AGENTS.md | 46 +++++++++++++++++++++++++++++++++++++++++-----
 1 file changed, 41 insertions(+), 5 deletions(-)

$ git -C r1 diff -- AGENTS.md | head -12 | cat -v
@@ -1,5 +1,41 @@
-# House rules^M
-^M
-Our agents read this file.^M
-Rule one: be careful.^M
-Rule two: never guess.^M
+# House rules
+
+Our agents read this file.
+Rule one: be careful.
+Rule two: never guess.
```

Five deletions. Every line of the adopter's file is a `-`, and the CLI printed
*your bytes outside it are unchanged* on the same run.

The mirror of this is on Windows: `write_text` emits `os.linesep`, so every
file this scaffold *generates* would be CRLF there, while every one of its own
byte-preservation tests compares against LF.

### R2 — a balanced marker pair in the adopter's prose makes adopt delete the text between it

`apply_block` took the first `<!-- aef:begin -->` and the next
`<!-- aef:end -->` **anywhere** — inside backticks, a code fence, a sentence —
and replaced everything between them. This kit's own `FIRST_DAY.md`,
`AGENT_INTEGRATION.md` and generated block all teach those two strings, so an
adopter documenting them is the ordinary case, not the exotic one.

A scratch repo whose `CLAUDE.md` quotes both markers with two house rules
between them:

```
$ grep -c "RULE 7" r2/CLAUDE.md      # before
1
$ aef adopt --dir r2
detected framework: prompt_files (1 agent)
appended aef block to .../r2/CLAUDE.md (your bytes outside it are unchanged)
$ grep -c "RULE 7" r2/CLAUDE.md      # after
0
$ grep -c "RULE 8" r2/CLAUDE.md
0
```

The file now reads:

```
`aef adopt` writes a block between <!-- aef:begin -->
## AEF scaffold (r2) — generated section
...
```

ADR 0153's three refusal shapes cover *unbalanced* pairs — a begin with no end,
an end with no begin, two begins. The **balanced pair adopt did not author** is
the fourth shape, it was not covered, and it is the only one of the four that
destroys anything.

### R3 — the rendered nightly workflow reads every exception as a healthy rejection

`aef migrate` writes the placeholder `agents/migrated/graph.py` whenever it
finds no wrappable call site, which is **every prompt-file repo** — the shape
of every eligible repo in the `UPGRADE_LOOP.md` survey. Its `build_graph()`
raises. The rendered workflow's `AEF_MODULE` defaulted to exactly that module,
so the module the workflow names *exists* and cannot build.

`main()`'s catch-all returns 1. 1 is `EXIT_REJECTED`. The rendered step's rule
is `if [ "$status" -ge 2 ]; then exit 1; fi`.

Reproduced, from inside an adopted-then-migrated prompt repo:

```
$ aef loop cycle --repo . --state ... --workdir ... \
      --module agents.migrated.graph --entrypoint agents.migrated.graph:build_graph \
      --corpus corpus --memory ../mem.jsonl --cassette-miss fail --build-command true
error: aef migrate found no wrappable call site in this repo. Nothing was generated,
deliberately, rather than emitting a graph that does nothing.
  preflight: 5 of 6 obligation(s) unmet (...)
EXIT=1
```

Exit 1, so the job is green, every night, with nothing proposed and — because
`cmd_cycle` never reached its journal — nothing in `cycles.jsonl` for ADR
0165's `SCHEDULED CYCLE PRODUCING NOTHING` warning to count.

This is the same failure ADR 0153 predicted and mis-called. Its consequences
section says a repo committing the workflow unedited "runs a cycle against
`agents.migrated.graph`, which may not exist — **the job fails visibly**". On a
prompt-file repo the module always exists, it raises, and the job does not fail
at all.

### R4 — adopt counts prompt agents flat; migrate discovers recursively

`discover_prompt_agents` uses `rglob`, and ADR 0152 measured that against the
Claude Code CLI: a repo with `.claude/agents/probe-one.md` and
`.claude/agents/sub/probe-two.md` had the CLI list both.
`detect_prompt_surface` used `glob("*.md")`.

A scratch repo with seven flat personas and one nested:

```
$ aef adopt --dir r4
detected framework: prompt_files (7 agents, 5 skills)
$ grep "prompt agents" r4/AEF_MIGRATION_CHECKLIST.md
- [ ] Run `aef migrate --dir .` — it registers 7 prompt agents ...
$ grep -o "7 under \`.claude/agents" r4/AGENTS.md
7 under `.claude/agents

$ python -c "...discover_prompt_agents(r4)..."
adopt   agents=7 skills=5
migrate agents=8 skills=6
$ aef migrate --dir r4 && ls r4/agents/migrated/
alpha  beta  delta  epsilon  eta  gamma  graph.py  theta  zeta      # eight
```

Three surfaces say 7 — the detection line, checklist step 5, and the block
appended into the file the repo's agents read — and migrate writes 8 graphs.

### S1 — the nightly cycle's state is frozen after the first run (suspected, reasoned, not executed)

Both rendered workflows cache `~/.aef-loop-state` under
`key: loop-state-${{ github.repository }}`. That key contains nothing that
varies. `actions/cache` skips its post-job **save** on an exact key hit, so run
1 populates the cache and no run after it ever writes one: the ledger,
`cycles.jsonl` and the archive would reset to run 1's contents every night, and
ADR 0165's staleness warning — which needs three consecutive journalled cycles
— could never see two.

**This one was not run.** It is YAML for a scheduler this branch has no access
to. What is asserted is a property of the string, and it is separated from the
four findings above deliberately.

## Decision

### D1 — read bytes, write bytes, render the block in the file's own ending

`apply_block_bytes` decodes without newline translation, resolves the block's
span, and **assembles** the result: `text[:start]` and `text[stop:]` are pasted
back verbatim, never re-rendered, and only the bytes adopt is *adding* take the
file's dominant line ending (`dominant_newline`, counted rather than guessed).
Pasting the outside slices back rather than normalising the whole result is
what makes a **mixed** file safe: the minority lines are the author's and stay
exactly as the author left them.

`_write_if_absent` reads with `read_bytes()` and writes with `write_bytes()`,
for new files too — the Windows mirror. A test AST-scans `aef/cli/adopt.py` for
any `read_text`/`write_text` call and requires zero, for the same reason
`tests/test_vendor_isolation.py` is an AST scan rather than a review note.

**The never-destroy rule is now executable.** `_verify_preserved(prefix,
suffix, result)` runs before every write: the bytes before the block and the
bytes after it must still be there, at the same ends, and the result must be
long enough to hold both. A violation returns `None` — the file is skipped with
a reason, not written. ADR 0153's central claim was an argument in a document;
it is an assertion in the code now.

### D2 — only a SIGNED marker pair is adopt's

The begin marker `aef adopt` writes carries a sha256 of the block body it
opens:

```
<!-- aef:begin sha256=1a2b3c4d5e6f7081 -->
...
<!-- aef:end -->
```

and, in `.gitignore`, `# aef:begin sha256=…`. Sixteen hex characters: 64 bits,
long enough that no prose contains one by accident, short enough to stay on one
line. The signature is inserted **inside** the comment so the marker stays
syntactically legal in the file it lives in.

`apply_block` treats only a signed pair as adopt's. Any other
`aef:begin`/`aef:end` text is inert prose: it is not searched, not matched, not
touched, and the block is appended after it. Re-running still replaces adopt's
own block, because the digest is a function of the body — the same body
reproduces the same marker byte for byte, which is what keeps a second `aef
adopt` a no-op.

The three refusals move onto the signed marker: two signed begins, a signed
begin with no end, and — see D3 — two candidate pre-signature blocks. The old
unbalanced *bare* shapes are now prose, and the fourth parametrisation asserts
that every byte of them survives.

**The digest is authorship, not integrity.** A hand edit inside the block makes
the stored digest disagree with the body, and adopt replaces the block anyway,
because the block is adopt's to maintain. Refusing there would mean one stray
keystroke stops the contract updating forever.

### D3 — a pre-signature block is MIGRATED once, with a printed notice

Every repo adopted between ADR 0153 and this one has a bare-marker block. The
two options were refuse-with-a-fix-line and migrate-once, and migrate-once
wins for a reason that is about the *file*, not about convenience: treating the
old block as prose would leave it in place and append a second one, and two
contradicting copies of the scaffold contract in the file the repo's agents
read is a worse failure than either.

It is recognised narrowly. A bare pair is adopt's only when the first non-blank
line of its body is a line `render_aef_block_body` or `render_gitignore_block`
actually emits (`## AEF scaffold (` / `__pycache__/`). R2's reproduction does
not match it, and neither does any quotation. Two candidates → refuse.

The notice is a **checklist item**, past tense, exactly like
`gitignore_appended_note()` — so it reaches both the terminal and
`AEF_MIGRATION_CHECKLIST.md` without changing `aef/cli/main.py`, which this
worker does not own. `AdoptResult.upgraded_blocks` carries the same fact for a
caller.

One consequence worth naming: `_is_adopt_generated` — the predicate that stops
adopt counting its own `AGENTS.md` as the adopter's prompt surface — accepts a
legacy block too. Keyed on the signature alone it would answer "not ours" for
exactly one run on every M2-era repo, and ADR 0153's "the detection line is
identical on both runs" would break during the upgrade.

### D4 — one discovery, one number

`detect_prompt_surface` imports `discover_prompt_agents` and `discover_skills`
from `aef.cli.migrate` rather than globbing. Adopt's own-output exclusion is
applied **on top**: the `/new-model-check` skill it writes is removed by path.
No cycle is introduced — `aef/cli/adopt.py` already imported
`DEFAULT_MIGRATED_OUT` from migrate, and migrate imports nothing from adopt.

> **ERRATUM (ADR 0176, fix worker I1): the finding below is CLOSED, and its
> prediction held exactly.** `aef/cli/migrate.py` now has
> `discover_adopter_skills`, which applies the same exclusion, and the two
> report the same number on the same tree (5 and 5 on the pilot clone, measured).
> The raw `discover_skills` is unchanged and the report still NAMES aef's own
> skill, marked `(aef's own — not yours)` — a migrate that goes silent about a
> file it declined to migrate is the one thing that block exists not to be; only
> the COUNT excludes it. `test_adopt_still_does_not_count_its_own_skill_after_reusing_migrates_discovery`
> did say so on that change, and was updated to assert the two AGREE rather than
> silently re-pinned.
>
> One correction to the paragraph below: "mirroring the exclusion is a change to
> `aef/cli/migrate.py`" was not sufficient. Migrate importing the constant from
> adopt is a **hard circular import**, reproduced both directions in ADR 0176 by
> patching it into the real file. The string now lives in `aef/harness/zones.py`
> — which both CLI modules already import and which imports neither — beside
> `DEFAULT_AGENT_PATH`, for the reason that constant's own comment gives.

**Reported for migrate's owner, not fixed here:** `discover_skills` has no such
exclusion, so on an adopted tree it counts the `SKILL.md` that `aef adopt`
itself wrote — measured 5 from adopt against 6 from migrate on the same repo.
Mirroring the exclusion is a change to `aef/cli/migrate.py`, which is another
worker's file. `test_adopt_still_does_not_count_its_own_skill_after_reusing_migrates_discovery`
pins both numbers, so the day migrate mirrors it, that test says so.

### D5 — the nightly cycle names a module that can build, and fails loudly when it cannot

Two changes, and the second is the load-bearing one.

`render_loop_monitor_workflow` takes a `prompt_module`. When adopt found prompt
agents it names the **first migrated prompt-agent module**, derived from
migrate's own discovery, sanitiser and output path — so the workflow and `aef
migrate` cannot disagree about the name. Never the placeholder.

And a step, before the cycle, that fails the job:

```yaml
      - name: The graph the cycle improves must build
        if: ${{ ... }}
        run: |
          python - <<'PY'
          import importlib, os, sys, traceback
          module = os.environ.get("AEF_MODULE", "").strip()
          ...
          PY
```

It refuses an unset `AEF_MODULE`, refuses the placeholder **by name** with the
reason (`its build_graph() raises NotImplementedError`), and otherwise imports
the module and calls `build_graph()`. On failure it writes the cause to
`$GITHUB_STEP_SUMMARY` and exits non-zero — a failed job, not a green one.

This is the fix rather than the module name, because a name adopt writes today
can be wrong tomorrow: the owner edits it, `aef migrate` has not been run yet,
an agent is renamed. A guard that executes the thing is correct in all of
those; a better default is correct in one.

**R3(c)**: the summary names the cause. The guard's message is
`AEF_MODULE=<m> does not build: NotImplementedError: <text>` — not migrate's
call-site sentence, which explains why the placeholder exists and not why
tonight failed. The cycle step's own summary heading gained the meaning of each
exit code in words (`escalated, or nothing to propose`, `REJECTED by a gate`,
`HALTED`, `the cycle raised: this is an ERROR, not a verdict`), because `(exit
1)` on a run page is a number, and four different nights produce it.

**Coordination with G1a.** G1a is giving `cmd_cycle` a distinct `EXIT_ERROR`.
`test_the_rendered_cycle_reads_as_a_healthy_rejection_and_the_guard_is_what_stops_it`
reads `aef/harness/loop.py`'s exit constants **at test time**: if `EXIT_ERROR`
exists and the CLI returns it, the test asserts it is a code the `status >= 2`
rule fails on; if not, it asserts the pre-G1a fact (exit 1, green job) and the
guard is what fails. It is sharp either way and needs no edit when G1a lands.

### D6 — the cache key varies per run

Both rendered workflows: `key: loop-state-${{ github.repository }}-${{
github.run_id }}` with `restore-keys: loop-state-${{ github.repository }}-`.
Run-scoped key so the post-job save always happens, prefix restore so each run
starts from the most recent previous one.

**This repo's own `.github/workflows/loop-monitor.yml` and `loop-gate.yml` have
the same constant key.** Read, confirmed, not edited — those files belong to
G1a, and this is the report.

### D7 — `shadow.containment` is discoverable from the config an adopter is handed

`render_aef_yaml` gains the commented block. `auto` is already the default, so
it is commented out; it names the three modes, the ADR, and the fact that
`auto` **refuses** rather than downgrading when there is no runtime or no
image — because a default an adopter cannot find in their own config is a
default they meet as a refusal instead.

## Evidence

Every command below run in this worktree, against scratch repos and a **copy**
of the read-only pilot clone. `python` = the repo `.venv`. Zero model calls.

### After — R1

```
$ aef adopt --dir r1
appended aef block to .../r1/AGENTS.md (your bytes outside it are unchanged)
$ git -C r1 diff --stat -- AGENTS.md .gitignore
 AGENTS.md | 36 ++++++++++++++++++++++++++++++++++++
 1 file changed, 36 insertions(+)

original bytes are a PREFIX of the result: True
offset of original in result:             0
CRLF in the added block: 41   lone LF in the added block: 0
.gitignore unchanged: True                 # already covers bytecode (ADR 0142)
```

Insertions only. Zero deletions.

### After — R2

```
$ aef adopt --dir r2
appended aef block to .../r2/CLAUDE.md (your bytes outside it are unchanged)
RULE 7 present after: 1
RULE 8 present after: 1
signed begins: 1          bare begins (the adopter's prose): 1
original bytes are a PREFIX of the result: True
sha256(original) df318503e0d643d13dc5c3d64b7651c3022e71ebfea025ebf4882d04f90543a0
```

The hash is the same one printed before adopt ran.

### After — R4

```
$ aef adopt --dir r4b
detected framework: prompt_files (8 agents, 5 skills)
adopt   agents=8 skills=5
migrate agents=8 skills=6 (its own new-model-check skill is the sixth)
$ grep -o "8 under \`.claude/agents" r4b/AGENTS.md ; grep -o "8 prompt agents" r4b/AEF_MIGRATION_CHECKLIST.md
8 under `.claude/agents
8 prompt agents
```

### After — R3, the rendered guard EXECUTED

Extracted from the YAML an adopter would commit and run as the runner would:

```
$ python run_guard.py r3repo              # before `aef migrate`
AEF_MODULE = agents.migrated.alpha.graph
EXIT = 1
AEF_MODULE=agents.migrated.alpha.graph does not build:
  ModuleNotFoundError: No module named 'agents.migrated'
Set AEF_MODULE (and AEF_ENTRYPOINT) in .github/workflows/loop-monitor.yml ...

$ python run_guard.py r3repo agents.migrated.graph      # the placeholder
EXIT = 1
AEF_MODULE is 'agents.migrated.graph' — the placeholder `aef migrate` writes when
it finds no wrappable call site. Its build_graph() raises NotImplementedError.

$ aef migrate --dir r3repo && python run_guard.py r3repo
EXIT = 0
```

Fails before migrate, fails on the placeholder by name, passes once the graph
exists. A guard that cannot pass is a guard nobody keeps, so the passing case
is a test too.

### The pilot clone, twice

A copy of the read-only pilot (8 agents, 5 skills, `AGENTS.md`, `.codex`, a
Copilot file and a Cursor rule, all pre-existing):

```
run 1: appended aef block to CLAUDE.md, .gitignore, AGENTS.md,
       .github/copilot-instructions.md, .cursor/rules/aef.mdc

AGENTS.md                        prefix=True offset=0 sha256(before)=ffd0ff4aac70ce5f
CLAUDE.md                        prefix=True offset=0 sha256(before)=023bb371e29db984
.gitignore                       prefix=True offset=0 sha256(before)=f7e1bbe7ff336ef8
.github/copilot-instructions.md  prefix=True offset=0 sha256(before)=dc5491b731c75210
.cursor/rules/aef.mdc            prefix=True offset=0 sha256(before)=52533088724cfd67

run 2: nothing written, nothing appended
IDEMPOTENT: True (260 files)   diff: []
```

`sha256(AGENTS.md before)` is `ffd0ff4aac70ce5f…`, the same value ADR 0153
records for that file.

**One thing that copy did NOT demonstrate**, stated because the temptation was
to leave it out: its detection line differs between run 1 and run 2
(six signals, then four). That pilot predates ADR 0153 — its Copilot and Cursor
files were written by an adopt that emitted **no markers at all**, so
`_is_adopt_generated` cannot recognise them until they have been appended to
once. It is not caused by this change (the old predicate answers the same way
on a file with no marker) and it is not fixed by it. What D3's legacy arm
prevents is the *same* one-run wobble for the M2 era, and that is asserted as a
unit property in
`test_an_m2_format_entry_file_is_still_recognised_as_adopts_own_output`, not
claimed from the pilot.

### Tests

+27 test items, **2269 → 2296 collected**, with nothing removed. The mutation
suite (`test_adopt.py`, `test_pristine_adoption.py`, `test_prompt_surface.py`)
goes **110 → 136**.

New in `tests/cli/test_adopt.py`:

- `test_a_crlf_entry_file_is_not_rewritten_line_by_line` (R1's reproduction)
- `test_the_block_takes_the_files_own_line_ending_and_every_byte_before_it_survives`
  (6 params: LF, CRLF, mixed either way, no trailing newline either way)
- `test_appending_to_a_crlf_file_is_insertions_only_and_git_agrees`
  (`git diff --numstat`, removed must be 0)
- `test_the_never_destroy_rule_is_checked_in_code_before_anything_is_written`
- `test_adopt_never_reads_or_writes_a_file_through_a_newline_translating_api`
  (AST scan)
- `test_bare_markers_in_the_adopters_prose_are_inert_and_nothing_between_them_is_lost`
  (4 params — the fourth is R2's balanced pair)
- `test_a_pre_signature_block_is_upgraded_once_in_place_and_the_adopter_is_told`
- `test_an_m2_format_entry_file_is_still_recognised_as_adopts_own_output`
- `test_the_signature_is_over_the_block_body_so_a_rerun_reproduces_it`
- `test_adopt_and_migrate_agree_on_the_number_of_prompt_agents`
- `test_adopt_still_does_not_count_its_own_skill_after_reusing_migrates_discovery`
- `test_the_generated_config_names_the_shadow_containment_default`
- `test_the_emitted_workflows_scope_the_loop_state_cache_to_the_run` (2 params)
- `test_the_nightly_cycle_never_defaults_to_the_placeholder_that_raises`
- `test_a_repo_with_no_prompt_agents_still_gets_the_guard_rather_than_a_silent_placeholder`
- `test_the_rendered_cycle_reads_as_a_healthy_rejection_and_the_guard_is_what_stops_it`
- `test_the_guard_passes_once_the_named_module_actually_builds`
- `test_the_cycle_summary_says_what_the_exit_code_MEANS`

Three pinned assertions changed **deliberately**:

- `test_a_file_with_markers_adopt_cannot_resolve_is_skipped_with_the_reason` —
  the three shapes are now stated on the marker adopt writes. The bare shapes
  they used to use moved to the new prose test, where they are appended after
  rather than refused, and that is the behaviour change D2 makes.
- `test_the_block_is_replaced_in_place_and_the_bytes_outside_it_are_untouched` —
  the planted stale block is signed, so it also pins that a *changed* block is
  still found.
- every `"<!-- aef:begin -->" in text` assertion → `signed_begins(text) == 1`,
  because the bare literal is no longer what identifies a block.

### Mutations

Each perturbs one production value, is run, and is restored from a
sha256-verified byte backup; every patch asserts its anchor before applying.

```
BASELINE                                                                136 passed
M1  apply_block treats the FIRST BARE begin as adopt's (the R2 defect)   9 failed
M2  the entry file is read/written through newline-translating APIs      8 failed
M3  the block is always rendered in LF, whatever the file uses           4 failed
M4  detect_prompt_surface globs one level again                          1 failed
M5  a pre-signature block is treated as prose (never upgraded)           2 failed
M6  the never-destroy check always answers yes                           1 failed
M7  the loop-state cache key is constant again                           1 failed
M8  the nightly cycle defaults to the placeholder that raises            3 failed
M9  the workflow has no build guard before the cycle                     3 failed
M10 the cycle summary is a bare exit code again                          1 failed
M11 the aef.yaml template never mentions shadow.containment              1 failed
RESTORED                                                                136 passed
```

**M10 survived the first pass** and is recorded because a surviving mutation is
information: the first version of `test_the_cycle_summary_says_what_the_exit_code_MEANS`
asserted the interesting arms (rejected, halted, raised) and not the exit-0
arm — which is the arm the nightly job is green on, and therefore the one that
matters most. The test now parses every arm out of the rendered shell `case`
and requires all four to be non-empty and to say the right thing.

### Green bar

```
pytest -q                              2291 passed, 5 skipped (2296 collected)
mypy aef examples                      Success: no issues found in 132 source files
ruff check .                           All checks passed!
ruff format --check aef tests examples 257 files already formatted
model calls made                       0
```

## Errata on ADR 0153

Two claims in ADR 0153 were wrong, and both were found by running things it did
not run.

**1. "Every pre-existing byte survives verbatim" held for LF only.** The
evidence section's `original bytes are a prefix of the result: True` and
`git diff --stat` → `41 insertions(+)` were measured on LF files, and every
byte-preservation test used an LF fixture. On a CRLF `AGENTS.md` the same code
path rewrote all five of the adopter's lines and reported the opposite; on
Windows every generated file would have been CRLF. The claim is now enforced
rather than asserted — `_verify_preserved` runs before every write — and the
fixtures have CRLF, mixed and no-trailing-newline twins.

**2. "The job fails visibly" was false on a prompt-file repo.** ADR 0153's
consequences section says a repo that commits the workflow unedited "runs a
cycle against `agents.migrated.graph`, which may not exist — the job fails
visibly, which is the right direction". On a prompt-file repo — the shape every
surveyed repo has — that module *always* exists, because `aef migrate` writes
the placeholder whenever it finds no call site; its `build_graph()` raises; the
exception becomes exit 1; and the workflow's own `status >= 2` rule reads exit
1 as a healthy rejection. The job is green, not failed, and nothing is
journalled. Fixed by D5.

A third statement of ADR 0153's stands but was under-stated: its three refusal
shapes are described as covering "markers adopt cannot resolve". They cover the
three *unbalanced* shapes; the balanced pair adopt did not author was neither
covered nor refused, and it was the only destructive one.

## Consequences

- **A file quoting the markers is now safe, and a file quoting a signed marker
  is not.** An adopter who pastes a real `<!-- aef:begin sha256=… -->` — say,
  copying a block out of another repo's `AGENTS.md` into their documentation —
  gets that pair treated as adopt's. Two such pastes are refused; one is
  replaced. This is a much narrower hazard than the one it replaces (the bare
  strings are in four generated documents; a valid 16-hex digest is not), but
  it is not zero and there is no flag to suppress the block.

- **The legacy upgrade is a one-way door, taken once.** After it, no repo has a
  bare-marker block of adopt's, and `_legacy_block_span` is dead weight that
  cannot be removed without stranding any repo that has not re-run adopt since.
  It stays.

- **The guard step runs the adopter's code in CI.** `importlib.import_module`
  plus `build_graph()` executes module-level and constructor code in the
  monitor job, which previously only installed packages and ran `aef` commands.
  That job has `contents: read` and no secrets, and the code is the repo's own
  from `main` — but it is a new execution, and naming it is cheaper than
  someone discovering it.

- **S1 is a fix to a string, not a demonstrated repair.** Nothing here proves
  that tonight's cached state survives; what is proved is that the key varies
  per run and the restore key does not. The first real scheduled run is the
  evidence, exactly as ADR 0165 says of its own workflow change.

- **`aef migrate`'s skills count still includes adopt's own skill.** Reported
  above, pinned by a test, not fixed — it is another worker's file.

- **This repo's own two workflows still carry the constant cache key.**
  Reported for G1a.

## Confidence

**High on R1, R2 and R4 and their fixes.** Each was reproduced by running a
command against a scratch repo and re-run after, with `git diff --stat`,
`grep -c` and sha256 of the original bytes pasted above; the pilot clone
re-verified all five entry files at offset 0 and 260 files idempotent.

**High on R3's mechanism and on the guard.** The exit code was produced by
running the cycle, and the guard was extracted from the rendered YAML and
executed in three states (missing module, placeholder, real graph).

**Medium on the workflow as a whole**, and for ADR 0165's reason unchanged: the
YAML was never run by a scheduler. The guard's *script* was executed; the step
that would run it was not.

**Low that the marker signature is the last word on authorship.** It answers
"did adopt write this pair", which is the question R2 needed. It does not
answer "has this block been edited", and deliberately so — the trade is stated
in D2 and could be revisited if anyone ever wants a tamper report.
