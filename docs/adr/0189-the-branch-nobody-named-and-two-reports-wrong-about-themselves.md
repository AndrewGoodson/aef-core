# ADR 0189: The branch nobody named, and two reports wrong about themselves

## Status

Accepted. Fix wave **L1** of `UPGRADE_LOOP.md`, closing all three findings ADR
0187 (increment M8) pinned as strict xfails. Model: `claude-opus-5[1m]`. **Zero
live model calls**: every reproduction and every regression test runs with
`model_provider.impl: command` and `argv: ["/bin/echo", "{system}",
"{prompt}"]`, M5's offline form (ADR 0158). **No rubric dimension moves.**

Each finding was reproduced by RUNNING it before anything was edited; the real
output of each reproduction is below, with the real output after the fix beside
it. Each fix carries a regression test that was watched to FAIL under a
mutation of the fix and then restored byte-for-byte, verified by sha256.

---

## F-M8-1 (HIGH) — a repo whose default branch is not `main` exited 0 having done nothing

### Reproduced, before any edit

The isolated case from ADR 0187, re-run from scratch: a repo with one persona,
one `AGENTS.md`, one skill, whose **only** difference from the passing case is
`git init -b trunk`.

```
--- adopt     EXIT=0  detected framework: prompt_files (1 agent, 1 skill, AGENTS.md)
--- migrate   EXIT=0  scanned 1 Python file(s)
--- bootstrap EXIT=0  2 of them is/are a check-derived FAILURE record …
--- bless     EXIT=0  blessed .claude/agents/one-agent.md as baseline v1 for graph 'one-agent'
--- doctor    EXIT=1
============================================================
$ aef loop cycle   (--base left at its default)
  preflight: 3 of 6 obligation(s) unmet (corpus + tripwire, observations, halt
    channel). ADVISORY — this command does not refuse on them; run `aef loop doctor`
  ledger verified: 1 entr(ies)
  no agent source at .claude/agents/one-agent.md in main: no candidate
cycle verdict: no agent source at .claude/agents/one-agent.md in main: no candidate
EXIT=0
============================================================
>>> ledger kinds: ['blessed']
>>> `main` exists: False
>>> branches: ['trunk']
```

The persona is present, committed, and was blessed one step earlier. What is
absent is the ref — and the sentence blames the file, on the exit code that
means nothing was wrong, in words a legitimate empty proposal also prints.

### The fix, in three parts, as ADR 0187 asked for it

**(a) The default is derived from the repository.** One function,
`aef.harness.loop.resolve_default_base_ref(repo)`, which the CLI imports —
ADR 0149's rule that a default has exactly one derivation. The order, and why
it is this order:

1. **`refs/remotes/origin/HEAD`**, when it is a symbolic ref. It is the
   repository's own published answer to "what is the default branch", it is
   what a candidate would eventually target, and — unlike anything derived
   from HEAD — it does not move when the operator checks something else out.
   A nightly cycle and an interactive one must resolve the same base or the
   two runs are not comparable, and that is the whole reason this term is
   first.
2. **The branch HEAD is on**, unless it is one of the loop's own
   (`LOOP_BRANCH_PREFIX = "loop/"`). A fresh `git init -b trunk` has no remote
   at all, so nothing above can answer; the branch the operator is working on
   is then the only statement the repository makes about which line of
   development is current. The loop-branch exclusion is what keeps this from
   being circular: a cycle run while an un-gated candidate is checked out must
   not base the next candidate on it, or the diff, the G0 budget and G5's
   drift are all measured against a baseline nothing blessed.
3. **`FALLBACK_BASE_REF = "main"`**, for a detached HEAD with no remote and a
   repo with no commits — the cases where the repository has no answer at all.
   Nothing that works today changes, because a repo with `origin/HEAD` or a
   `main` checkout resolves to `main` at step 1 or 2.

**The term deliberately dropped.** ADR 0187 sketched "the branch HEAD was on
when the state dir was created" between 1 and 2. It would need a new persisted
file under `--state` — new Zone B state, and a new format — to disambiguate
exactly one case, the operator sitting on a `loop/` branch, which step 2's
exclusion handles directly from what already exists. A default that has to
invent state in order to be derivable is the shape ADR 0139 argues against, so
it is not here and this paragraph is why.

`FALLBACK_BASE_REF` lives beside `LoopConfig.base_ref`, the default it is a
default *for*, for the reason `zones.DEFAULT_AGENT_PATH` lives beside the root
it is built from: the CLI's `--base` default and the dataclass default cannot
then drift apart. `--base`'s argparse default is `None` in all five parsers, so
"the owner did not say" is distinguishable from "the owner said `main`" — the
same distinction ADR 0176's F2 needed for `--graph-id`.

**(b) A base ref that does not exist is a configuration error.**
`require_base_ref(repo, ref)` raises `BaseRefError`, reported as `EXIT_ERROR`
(3, ADR 0167's "the command could not do its job … a configuration error that
stops the turn before it starts"), naming the ref and listing the branches that
do exist. It is asked in `cycle()` and `gate()` **before `_preflight`**, so no
message about the kill switch, the ledger or the corpus can arrive first and be
believed; at the head of `run_loop()`, before `_ensure_branch` cuts anything
from the ref; and in `aef/cli/loop.py` for `gate`, `bless` and `doctor` —
`bless` and `doctor` never reach `_preflight` at all, and `gate`'s CLI check is
belt-and-braces that turns a `BaseRefError` into a plain `error:` line. `doctor`
matters most of the five: it is the readiness command, and ADR 0187's complaint
was that it reported a repo ready that would then no-op.

Not inside `_preflight` itself, and that is a decision rather than an
oversight: `monitor` shares `_preflight` and reads no ref, so putting the check
there made a read-only `aef loop monitor` start requiring a git repository.
Five tests said so out loud before this ADR was written
(`test_a_shrunken_corpus_stops_a_cycle` and four others went red), and the
right answer to a control that fires on the wrong command is to move it, not
to weaken it.

`require_base_ref` returns silently when the directory is not a git repository
at all (`GitRepo.is_repo()`). A plain directory has no refs to be right or
wrong about; that is not the mistake this function exists to catch, every
command that genuinely needs a repository fails on its own first call out to
git with git's own message, and `aef loop doctor` is a diagnostic that must
still run and say what IS missing rather than refuse to look.

**(c) "Ref missing" and "file missing at ref" are two questions again.**
`GitRepo.ref_exists(ref)` is new; `path_exists_at`'s docstring now says in as
many words that it assumes the ref exists, and points at the neighbour that
answers the other question. Because `cycle()` establishes the ref first, the
line that used to be wrong can now only be right, and it says which:

```python
lines.append(
    f"no agent source at {agent_path} in {config.base_ref} "
    f"(the ref exists; the file is not in it): no candidate"
)
```

### After the fix, same repo, same commands

```
$ aef loop cycle   (--base left at its default)
  preflight: 3 of 6 obligation(s) unmet …
  ledger verified: 1 entr(ies)
  proposed cycle-20260905T082344-prompt on local branch
    loop/cycle-20260905T082344-prompt (never pushed; proposer=rule_based_prompt)
  gated: reject — G2 rejected it: 2 previously-passing scenario(s) no longer pass
cycle verdict: proposed cycle-20260905T082344-prompt — Decision(disposition=REJECT, …)
EXIT=1
>>> ledger kinds: ['blessed', 'proposed', 'gated', 'rejected']
>>> `main` exists: False
```

The G2 rejection is the expected replay artefact — `--cassette-miss fail` plus
a changed prompt is a changed cassette key — and is exactly the verdict
keystone reached in ADR 0187. What changed is that a verdict was reached at
all, on a repository with no `main` in it.

And `main` named explicitly, on all five commands:

```
$ aef loop doctor … --base main
error: base ref 'main' does not exist in <repo>. This repository's branches are:
loop/cycle-20260905T082344-prompt, trunk. Pass --base <ref> naming one of them;
the default is this repository's own default branch (origin/HEAD, else the branch
you are on), not the literal 'main'.
EXIT=3
```

`doctor`, `bless` and `gate` print it as `error:` from the CLI; `cycle` and
`run` reach the harness check and print `error (BaseRefError): …` from the
journalling handler, which also records the attempt in `cycles.jsonl` — a
nightly cycle failing this way every night should be visible to
`aef loop monitor`, so it is journalled rather than refused ahead of the
journal.

### Tests

`tests/harness/test_base_ref.py` — nine, all against real repositories, nothing
mocked, because the whole defect was in what git actually answers:
`…resolves_to_the_branch_head_is_on`, `…still_resolves_to_main`,
`…origin_head_wins_over_the_branch_checked_out`,
`…a_loop_branch_is_never_inherited_as_the_base`,
`…a_detached_head_with_no_remote_falls_back`,
`…refused_by_name_and_lists_what_exists`, `…a_ref_that_exists_is_not_refused`,
`…a_plain_directory_is_not_a_base_ref_mistake`, and
`…the_two_questions_path_exists_at_could_not_tell_apart`.

`tests/cli/test_second_repo_acceptance.py::test_a_repo_whose_default_branch_is_not_main_does_not_no_op_silently`
— ADR 0187's strict xfail, now a passing regression test through the real CLI.
It asserts both halves: the ledger gains `proposed` and `gated` with `no agent
source` and `no candidate` absent from the output (the default resolved), and
`--base main` exits `EXIT_ERROR` naming `main` and listing `trunk`.

**Its expected exit code changed, deliberately.** ADR 0187 wrote the xfail
against `EXIT_USAGE` (2) and said so. `EXIT_ERROR` (3) is right: 2 is
`EXIT_HALTED`'s number as well and means "do not retry", while 3's own comment
already names "a configuration error that stops the turn before it starts",
and ADR 0167's nightly rule fails the job on `>= 2` either way.

---

## F-M8-2 (LOW) — `migrate`'s skill header did not count the list under it

### Reproduced

Two skills of the adopter's, then `adopt` writes its own `new-model-check`
skill as a third:

```
$ aef adopt --dir .   EXIT=0
$ aef migrate --dir .
found 2 skill(s) and did NOT migrate any of them:
  SKILL    .claude/skills/new-model-check/SKILL.md   (aef's own — not yours)
  SKILL    .claude/skills/skill-0/SKILL.md
  SKILL    .claude/skills/skill-1/SKILL.md
>>> header says 2, rows listed = 3
```

keystone's `found 4` over five rows and datamining's `found 6` over seven, in
miniature.

### The fix

The header counts the rows it heads, and then says how that total splits:

```
found 3 skill(s) and did NOT migrate any of them (2 yours + 1 aef's own):
  SKILL    .claude/skills/new-model-check/SKILL.md   (aef's own — not yours)
  SKILL    .claude/skills/skill-0/SKILL.md
  SKILL    .claude/skills/skill-1/SKILL.md
```

and with no aef skill present the parenthetical is absent entirely:

```
found 3 skill(s) and did NOT migrate any of them:
```

Both of the reasons that produced the defect survive. ADR 0172's D4 made the
count exclude adopt's own output so that it stops changing the moment adoption
runs — that number is still stated, by name, as `2 yours`, and it is still the
one that does not move. `discover_skills` still names every file it declined to
migrate, aef's own included and labelled, because being silent about a declined
file is the one thing that block exists not to be. What did not survive is a
leading number that was not the number of rows beneath it: a report wrong about
itself teaches its reader to stop counting.

### Tests

`tests/cli/test_second_repo_acceptance.py::test_migrates_skill_header_count_matches_its_own_listing`
(0187's xfail, now passing, and additionally pinning the parenthetical and that
exactly one row is labelled as aef's) and
`tests/cli/test_migrate_prompt_agents.py::test_the_skill_header_counts_its_rows_with_no_aef_skill_present`
(the other shape).

`test_the_report_counts_two_and_still_names_the_third_marked` **pinned the old
header** and was updated deliberately, with the reason written into its
docstring — a test that defends a defect through every refactor is worse than
no test.

---

## F-M8-3 (MEDIUM) — the checklist pointed at a `CLAUDE.md` adopt had just skipped

### Reproduced

`CLAUDE.md` a symlink to `README.md` — datamining's shape, with the link
pointed somewhere the accident does not save it:

```
detected framework: prompt_files (1 agent, 1 skill, AGENTS.md)
appended aef block to <repo>/AGENTS.md (your bytes outside it are unchanged)
skipped <repo>/CLAUDE.md (a symlink, or under one — adoption never writes through a link)
  1. Read the generated CLAUDE.md in full before writing any code.
>>> CLAUDE.md content now: '# scratch\n'
>>> aef block in it     : False
```

Step 1 is the first thing a fresh coding-agent session in that repo reads, and
`CLAUDE.md`'s own promise — "self-contained: a fresh coding-agent session in
that other repo … can pick up the migration from it alone" — is false for a
file adopt never touched.

### The fix

`entry_file_checklist_item(entry_files, reason)` derives step 1 from the same
`written` / `appended` / `skipped` result the report prints, at the one place
that knows all three. Four cases, all tested:

| what adopt did | step 1 |
|---|---|
| appended to `AGENTS.md`, skipped `CLAUDE.md` | `1. Read the generated AGENTS.md in full before writing any code.` |
| wrote `CLAUDE.md`, appended `AGENTS.md` (the ordinary repo) | `1. Read the generated CLAUDE.md and AGENTS.md (they are byte-identical) in full before writing any code.` |
| a second `adopt`, both skipped as `already carries the current aef block` | unchanged from the row above — the file it skipped is exactly the file to read |
| both are symlinks, so neither took the block | `1. aef adopt could put its contract in NO entry file (CLAUDE.md: a symlink …; AGENTS.md: a symlink …) — so nothing below reached a file your coding agent reads. Fix that first: clear the obstruction and re-run \`aef adopt\`, or copy the \`aef:begin\`/\`aef:end\` block out of \`.github/copilot-instructions.md\`, which did get one, …` |

Two supporting changes make it derivable rather than guessed. The checklist is
now rendered **after** `CLAUDE.md` and `AGENTS.md` are handled rather than
between them — the `.gitignore` note three lines below it already worked that
way, for the reason written above it, that what the checklist says depends on
what happened. And the skip reason `already carries the current aef block` is
now the named constant `_BLOCK_ALREADY_CURRENT`, because the checklist reads it
back: a file skipped for *that* reason does carry the contract.

### Tests

`tests/cli/test_second_repo_acceptance.py::test_the_checklist_does_not_point_at_a_claude_md_adopt_skipped`
(0187's xfail, now passing, and asserting the positive — that step 1 names
`AGENTS.md` and that `AGENTS.md` really carries the block — not merely that it
is silent about `CLAUDE.md`);
`…::test_the_checklist_names_both_entry_files_when_adopt_wrote_both` (the
ordinary repo, and a second `adopt` over it); and
`tests/cli/test_adopt.py::test_the_checklist_says_so_when_no_entry_file_could_take_the_block`.

---

## Mutation checks

Each fix perturbed, its regression test run and watched to FAIL, then the file
restored from a byte backup and the restore verified by sha256. Never `git
checkout --`.

| mutation | control | result |
|---|---|---|
| restore the literal `main` default in `_config` | `…default_branch_is_not_main_does_not_no_op_silently` | FAILED |
| drop the refusal, keep the derivation | `…refused_by_name_and_lists_what_exists` | FAILED |
| let a `loop/` branch be inherited as the base | `…a_loop_branch_is_never_inherited_as_the_base` | FAILED |
| restore the adopter-only subtotal in the header | `…skill_header_count_matches_its_own_listing` | FAILED |
| restore the literal step 1 | `…does_not_point_at_a_claude_md_adopt_skipped` | FAILED |

```
all files restored byte-for-byte:
  aef/cli/adopt.py    a79f5b1bb2277fa8 == a79f5b1bb2277fa8
  aef/cli/loop.py     e5ca0ff59f066ea2 == e5ca0ff59f066ea2
  aef/cli/migrate.py  680566dd0c084933 == 680566dd0c084933
  aef/harness/loop.py bd5f6f90787a7a08 == bd5f6f90787a7a08
```

---

## Green bar

`pytest -q`: **2825 passed, 7 skipped, 1 xfailed, 1 failed**; 2822 → **2834
collected (+12, none removed)** — 9 in `tests/harness/test_base_ref.py`, 1 in
`test_migrate_prompt_agents.py`, 2 in the acceptance files. Three of ADR 0187's
four xfails became passing tests, which is why the xfail count falls from 4 to
1 while nothing is lost.
`mypy aef examples`: 135 files, clean. `ruff check .`: clean.
`ruff format --check aef tests examples`: 285 files, clean.

**The one failure is not this wave's and is not in this wave's files**:
`tests/test_prompt_surface.py::test_the_corpus_readme_records_which_model_wrote_what`
asserts `agg[("claude-fable-5-1",)] == 20` and `agg[("claude-opus-5[1m]",)] ==
19` over `corpus/*/*.json`, and the corpus now holds
`Counter({('claude-opus-5[1m]',): 37, (): 11, ('claude-fable-5-1',): 2})`. It
was already red at `18051c0`, before a byte of this wave was written: ADR 0186
(S3c) re-recorded the corpus onto one model and this pinned count — and the
`6/17` fraction beside it — was not moved with it. `corpus/` and the rubric are
outside this worker's files by instruction, and the count is a claim about
S3c's measurement rather than a test to be edited into green, so it is reported
here and left for its owner.

## Errata

**On ADR 0187.** All three findings are closed. Two of its statements are now
superseded rather than wrong:

- Its "Whether the fix should also *default* the base ref to the repo's own
  HEAD branch rather than the literal `main` is a design question for the fix
  wave" is answered: yes, with the three-term order above, and the middle term
  it proposed was dropped for the stated reason.
- Its xfail expected `EXIT_USAGE`; the shipped refusal is `EXIT_ERROR`, for the
  reason given under F-M8-1.
- Its "**Non-`main` default branches**, until F-M8-1 is fixed: `datamining`
  needed `--base` passed by hand" no longer holds. The survey's other five
  repos were never checked for the same shape and still have not been; what has
  changed is that a repo with that shape now reaches a verdict from the
  documented defaults instead of exiting 0.

**On ADR 0149.** Its closing argument — that a default naming a layout the
adopting repo does not have makes the documented sequence exit 0 having done
nothing, reproduced for the agent PATH — was true of a second default of
exactly the same shape, sitting three fields away in the same dataclass. The
comment in `aef/harness/zones.py` that names the failure for
`agents/demo/graph.py` describes `base_ref = "main"` word for word, and the
literal survived thirty-eight ADRs after the one that removed its twin.
`FALLBACK_BASE_REF` now sits beside `LoopConfig.base_ref` for the same reason
`DEFAULT_AGENT_PATH` sits beside `DEFAULT_AGENT_ROOT`. **The generalisation
worth carrying forward is that ADR 0149's rule is about a class, not a
constant**: any default in `aef/` that names a *repository's* branch, path or
layout is a guess about someone else's repo, and each one should be derived or
refused rather than spelled.
