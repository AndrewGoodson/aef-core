# ADR 0142: Zone A hygiene — the adopter pays for what `adopt` did not write

## Status
Accepted. Fix wave E of `READY_LOOP.md`; recorded in `IMPROVE_LOG.md`.
**No rubric dimension moves** — this is adoption hygiene, not a scoring claim.
Both defects were found by K3 (ADR 0139) while proving an adopted repo can
gate a candidate, and both were reported there rather than fixed, because
they lived outside that increment's file scope.

## Context

Two things an adopter hits on day one, neither of which is about their agent.

### E1 — committed bytecode is charged as drift

`aef adopt` wrote no `.gitignore`. An ordinary `git add -A` after the first
run therefore commits `agents/**/__pycache__/*.pyc` into **Zone A** — the one
tree the loop may propose changes to, and the tree `aef loop bless` archives
as the baseline G5 measures drift against. The bytecode is created *after*
the blessing (by `aef loop bootstrap`, `aef run`, `pytest` — anything that
imports the agent) and committed *before* the cycle, so it is present on the
candidate side and absent from the baseline, and `structural_drift` charges
every line of it.

This is ADR 0074's defect arriving from the other side. That fix made both
sides read from **git** rather than one side from git and one from disk; it
cannot help when the bytecode is *in* git.

### E2 — `aef migrate` writes to the one directory the loop cannot touch

`aef/cli/migrate.py:run_migrate` hardcodes `out = root / "aef_migrated.py"`.
The repo root is **Zone C**. A candidate touching it is rejected by G0, and
`aef loop bless --agent-path aef_migrated.py` archives a Zone A tree that
does not contain it. Neither `migrate`'s own report nor anything `aef adopt`
generated said so: the strings `Zone A` and `agents/` did not appear anywhere
in the generated `CLAUDE.md`, `AGENTS.md` or `AEF_MIGRATION_CHECKLIST.md`,
while the checklist told the adopter to "Convert each call site into a Node
function receiving Services.model_provider."

`migrate.py` is owned by another worker in this wave, so this ADR changes
only what `adopt` *says*. The change `migrate` still needs is stated under
Consequences.

## Decision

**E1.** `run_adopt` writes a `.gitignore`, under the scaffold's own
never-overwrite rule. When one already exists it is **skipped and reported**,
never appended to: silently adding a generated line to a tracked config the
adopter owns is the never-overwrite rule broken by another route. The report
goes into the migration checklist — which `aef adopt` prints and also writes
to `AEF_MIGRATION_CHECKLIST.md` — and names the two patterns and the measured
cost of not having them.

The coverage check (`gitignore_gaps`) is an exact match against the literal
pattern forms that keep bytecode out of a CPython 3 tree, in two families
(`__pycache__/…` and `*.pyc`-shaped), because **either alone is sufficient**
and nagging an adopter to add a pattern equivalent to one they already have
is how generated advice stops being read. Comments are not rules: a naive
`"__pycache__" in text` reads `# __pycache__/` as coverage, which is the
detector failing in the direction that costs a drift budget.

Deliberately **not** ignored: `corpus/` and `.github/workflows/`. Those are
Zone B — the evidence and the gates — read from git; an ignored corpus is an
empty one.

**E2.** The Zone A constraint is stated where an adopter meets it: a new
`## Where converted nodes have to live` section in the generated
`CLAUDE.md`/`AGENTS.md`, and a new item in the common (framework-independent)
half of the migration checklist. Both are interpolated from
`aef.harness.zones.DEFAULT_AGENT_ROOT`, not spelled out, so a doc cannot name
a directory the harness does not enforce; a test cross-checks the name
against the directory `adopt` actually creates.

## Evidence

Every command run in this worktree, `python` = `.venv/bin/python`,
`PYTHONPATH` = the worktree. **Zero model calls.**

### E1 reproduced, BEFORE the fix

K3's numbers re-derived rather than copied. `scratchpad/repro_e1.py` drives
the K3 adoption sequence twice against a fresh `git init` — adopt → write the
minimum agent → `git add -A` → bootstrap → tripwire → failing `aef run
--memory` → `aef loop bless` → `git add -A` → `aef loop cycle` — once with a
hand-written `.gitignore` (K3's control) and once with none (what `aef adopt`
left an adopter). G5's own line, from `ledger.jsonl`:

```
WITHOUT .gitignore (what `aef adopt` leaves you)
  tracked .pyc under agents/: ['agents/__pycache__/__init__.cpython-313.pyc',
    'agents/mine/__pycache__/__init__.cpython-313.pyc',
    'agents/mine/__pycache__/graph.cpython-313.pyc']
  G5: pass — 0/3 accepted in the last 7d; drift 0.468/0.500 from the blessed baseline

WITH .gitignore (K3's hand-written control)
  tracked .pyc under agents/: []
  G5: pass — 0/3 accepted in the last 7d; drift 0.024/0.500 from the blessed baseline
```

`scratchpad/precision_e1.py` re-runs `structural_drift` on the same archive
and the same candidate branch and itemises it:

```
nogi   agents/README.md                              base= 12 cand= 12 differing=  0 of 12
       agents/__init__.py                            base=  0 cand=  0 differing=  0 of  0
       agents/__pycache__/__init__.cpython-313.pyc   base=  0 cand=  3 differing=  3 of  3
       agents/mine/__init__.py                       base=  0 cand=  0 differing=  0 of  0
       agents/mine/__pycache__/__init__...pyc        base=  0 cand=  3 differing=  3 of  3
       agents/mine/__pycache__/graph...pyc           base=  0 cand= 29 differing= 29 of 29
       agents/mine/graph.py                          base= 30 cand= 30 differing=  1 of 30
       TOTAL differing=36 / total=77 -> drift=0.4675324675324675
       93.5% of the 0.500 budget consumed; headroom 0.0325

gi     (the same four source files, no bytecode)
       TOTAL differing=1 / total=42 -> drift=0.023809523809523808
       4.8% of budget consumed; headroom 0.4762
```

**35 of the 36 differing lines are bytecode; 1 is the candidate.** A
one-line change spends 93.5% of the budget. `_drift_exhausted_twice` halts
the loop on two consecutive drift rejections, so an adopter who ran
`git add -A` on day one is two candidates from a halted loop for reasons
that have nothing to do with their agent.

### E1 after the fix

The same script, unchanged, with `aef adopt` now writing the `.gitignore` —
so the "WITHOUT" arm is no longer a repo without one:

```
WITHOUT .gitignore (what `aef adopt` leaves you)
  tracked .pyc under agents/: []
  G5: pass — 0/3 accepted in the last 7d; drift 0.024/0.500 from the blessed baseline

WITH .gitignore (K3's hand-written control)
  tracked .pyc under agents/: []
  G5: pass — 0/3 accepted in the last 7d; drift 0.024/0.500 from the blessed baseline
```

**0.468 → 0.024.** The two arms are now identical, which is the point: the
adopter no longer has to hand-write the thing K3's fixture had to.

### E2 reproduced, BEFORE the fix

`scratchpad/repro_e2.py`, against a fresh adopted repo:

```
1. WHERE migrate writes
   $ aef migrate --dir .                                            exit 0
   wrote <repo>/aef_migrated.py
   files matching aef_migrated*.py at the repo ROOT: ['aef_migrated.py']
   under agents/: []
   migrate output mentions 'Zone':   False
   migrate output mentions 'agents/': False

2. WHAT THE ZONE CLASSIFIER SAYS
   inspect_path("aef_migrated.py") -> zone=C allowed=False
   aef_migrated.py: Zone C (core) — not under the agent root 'agents';
   only Zone A is agent-writable
   DEFAULT_AGENT_ROOT = 'agents'

3. THE REAL DIFF PATH — a real commit, through read_candidate /
   inspect_candidate, no mock
   changed paths: ('aef_migrated.py',)   allowed: False
   reject: aef_migrated.py: Zone C (core) — not under the agent root 'agents'

4. WHAT `aef adopt` GENERATED TELLS THE ADOPTER
   AEF_MIGRATION_CHECKLIST.md: 'Zone A' present=False  'agents/' present=False
   CLAUDE.md:                  'Zone A' present=False  'agents/' present=False
   AGENTS.md:                  'Zone A' present=False  'agents/' present=False
   ...while the checklist says: "Convert each call site into a Node function
   receiving Services.model_provider."
```

### E2 after the fix

Same script, same repo shape:

```
4. WHAT `aef adopt` GENERATED TELLS THE ADOPTER
   AEF_MIGRATION_CHECKLIST.md: 'Zone A' present=True  'agents/' present=True
     "Put every node you convert under `agents/` — Zone A, the only tree the
      loop is allowed to propose changes to. `aef migrate` writes
      `aef_migrated.py` to the repo ROOT, which is Zone C: measured, a
      candidate touching it is rejected with `G0 rejected it: candidate
      touches paths outside Zone A` and the cycle exits 1. Move the generated
      nodes under `agents/` before running the loop (ADR 0142)."
   CLAUDE.md / AGENTS.md: 'Zone A' present=True  'agents/' present=True
     "## Where converted nodes have to live: `agents/`"
```

Steps 1–3 are unchanged, and that is honest: `migrate` still writes to the
root. What changed is that the adopter is told, before they run it.

### Tests

Eight new tests. Seven in `tests/cli/test_adopt.py`:

- `test_run_adopt_writes_a_gitignore_that_keeps_bytecode_out_of_zone_a`
- `test_the_generated_gitignore_actually_makes_git_ignore_zone_a_bytecode`
  (asks `git check-ignore`, not a string match — and asserts the agent
  *source* is still not ignored)
- `test_run_adopt_never_overwrites_a_gitignore_and_says_what_is_missing`
- `test_a_gitignore_that_already_covers_bytecode_is_not_nagged`
- `test_gitignore_gaps_ignores_commented_out_patterns` (the detector's own
  control)
- `test_the_checklist_names_the_zone_a_root_the_harness_actually_uses`
- `test_claude_md_states_where_converted_nodes_must_live`

One in `tests/cli/test_pristine_adoption.py` — the end-to-end one, on
unmodified `aef adopt` output:

- `test_the_first_git_add_dash_a_does_not_spend_the_drift_budget_on_bytecode`
  — writes an agent, blesses, runs `compileall` (day one's "run something"),
  `git add -A`, commits, makes a one-line candidate on a branch, then reads
  the **archive `bless` wrote** and the **tree git holds** and runs the
  gate's own `structural_drift` over them. It asserts no `.pyc` is tracked
  under Zone A and that the drift is under 0.10.

Two pinned assertions in `tests/cli/test_adopt.py` were updated
**deliberately**, and this is the note saying so: the exact written-file set
gains `.gitignore`, and `test_run_adopt_is_idempotent_on_second_run` goes
15 → 16 on both counts. That pin is what makes "adopt quietly started writing
something" a failure rather than a discovery, so it is changed by hand, never
relaxed.

### Mutations

Each perturbs a production value in `aef/cli/adopt.py`, is run, and is
reverted from a byte-identical backup (`shasum` verified;
`git diff --stat` afterwards shows only the intended three files).
Suite: `tests/cli/test_adopt.py` + `tests/cli/test_pristine_adoption.py`.

```
BASELINE                                                    66 passed
M1  run_adopt writes no .gitignore                           6 failed, 60 passed
      -> "bytecode is tracked in Zone A: [... 3 .pyc ...]"
      -> and the pinned file-set + idempotency counts
M2  render_gitignore drops __pycache__/ and *.py[cod]        3 failed, 63 passed
      -> git check-ignore returns 1; the drift test sees the .pyc
M3  gitignore_gaps always returns ()                         2 failed, 64 passed
      -> an existing .gitignore is never reported
M4  gitignore_gaps uses a naive `"__pycache__" in text`      1 failed, 65 passed
      -> a COMMENTED-OUT pattern reads as coverage
M5  the checklist names `src/` instead of DEFAULT_AGENT_ROOT 1 failed, 65 passed
M7  the CLAUDE.md Zone A section is deleted (1223 chars)     1 failed, 65 passed
REVERTED                                                    66 passed
```

Two attempted mutations were **not** detected, and both are recorded because
a mutation that survives is information:

- **M5-first-line-only** — replacing only the checklist item's opening
  f-string fragment left the rest of the item still naming `agents/`,
  `Zone A` and `aef_migrated.py`. Correct non-detection: the information
  survived the edit. The real M5 above changes the interpolated root.
- **M6** — renaming the CLAUDE.md heading and the first sentence left the
  migrate paragraph intact, so every asserted string was still present.
  Also correct, and M7 (delete the whole section) is the version that
  removes the information.

### Green bar

```
pytest -q                              1885 passed, 1 skipped
                                       (ADR 0139 recorded 1877 passed,
                                        1 skipped -> +8, none removed)
mypy aef examples                      Success: no issues found in 129 source files
ruff check .                           All checks passed!
ruff format --check aef tests examples 239 files already formatted
model calls made                       0
```

## Consequences

- **The adopter's first `git add -A` is no longer a two-candidate fuse.**
  The drift a one-line candidate is charged went 0.4675 → 0.0238 on the
  measured sequence, and the fixture comment in K3's
  `raw_sdk_adoptee` that says the `.gitignore` is "NOT written by
  `aef adopt`" is now out of date — the fixture writes it before
  `run_adopt`, so it is skipped rather than overwritten and the test is
  unaffected. That comment is `tests/cli/test_adoption_sequence.py`, owned
  by another worker in this wave; flagged, not edited.

- **`migrate.py` still needs a change, and this ADR does not make it.**
  The exact change, for the orchestrator to route to whoever owns that file:

  > `aef/cli/migrate.py:run_migrate` hardcodes `out = root /
  > "aef_migrated.py"` (line 634). Add an `--out` argument threaded from
  > `aef/cli/main.py:_cmd_migrate`, **defaulting to
  > `f"{DEFAULT_AGENT_ROOT}/migrated/graph.py"`** (imported from
  > `aef.harness.zones`, never spelled out), creating parent directories,
  > keeping the existing never-overwrite/`--force` rule. Whatever the
  > destination, `report()` should state the zone of the path it wrote:
  > a path outside the agent root is one the loop can never propose a
  > change to, and today the report says nothing. A warning alone would be
  > the cheaper half; the default is the half that stops the adopter from
  > having to know.

  Note the interaction with the second K3 defect, still open: `aef loop
  bless --agent-path <path outside Zone A>` succeeds while archiving a tree
  that does not contain it (`aef/harness/preflight.py:bless`). Fixing
  `migrate`'s default makes that path harder to reach; it does not fix it.

- **A textual coverage check is a floor, not a proof.** `gitignore_gaps`
  matches literal pattern forms. An adopter whose `.gitignore` says
  `agents/**/*.pyc`, or who relies on a global `core.excludesFile`, is
  reported as having a gap they do not have. The failure direction is a
  redundant checklist line, not a spent drift budget, which is the right
  way round — but it is a false positive and it is not proved absent.
  Using `git check-ignore` would answer exactly; it needs a git repo and a
  subprocess in a code path that today runs against a bare directory, so it
  is not done. The new test does use `git check-ignore` against the file we
  generate, so what we *write* is verified against git's own semantics.

- **What is still not covered.** The `.gitignore` is written for a Python
  adoptee. A repo whose Zone A carries build output from another toolchain
  (`node_modules/`, `target/`, `dist/`) gets nothing for it, and the same
  arithmetic applies with a bigger numerator. Nothing detects that; the
  checklist does not mention it.

## Confidence

**High on E1's mechanism and fix.** The before and after numbers come from
`aef loop cycle` writing its own ledger on a real adopted repo, twice each,
plus the arithmetic re-derived line by line; the regression test asserts
through `bless`'s archive and the gate's own `structural_drift` rather than
against hand-built dicts, and it fails with the 0.4675-shaped tree when the
`.gitignore` is removed.

**High that E2's constraint is now stated, moderate that stating it is
enough.** The generated text is derived from `DEFAULT_AGENT_ROOT` and
cross-checked against the directory `adopt` creates, so it cannot drift into
naming the wrong place. But documentation is the weakest control available
here — the strong one is `migrate` writing to a Zone A path by default, and
that is another worker's file. An adopter who does not read the checklist
still lands where K3 landed.

**Low on `gitignore_gaps` against `.gitignore` files in the wild.** It was
tested against four hand-written shapes. Git's ignore semantics are richer
than any of them.
