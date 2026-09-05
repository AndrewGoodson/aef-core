# ADR 0176: Two spellings of "which graph", and no way back from a stale manifest

## Status

Accepted. Fix worker **I1** of the upgrade loop. Four findings, each carried
over from another worker's "defects outside my files": ADR 0174's 1, 3 and 4
(M4b) and ADR 0172's 1 (H1). Model: **`claude-opus-5[1m]`** (session default).
**ZERO live model calls** — every reproduction here runs a graph whose model
path is never taken, or reads a directory. **No rubric dimension moves.**

> **Erratum (ADR 0191, F2).** The two spellings of "which graph" are right and
> stand. What did not hold is the flag's reach: `--graph-id` restricted the
> evidence for `RuleBasedPromptProposer` only. The default `RuleBasedProposer`
> was constructed with no graph id and `MemoryEvidence.from_store` filtered
> only validation and holdout run ids, so on this repo's two-graph corpus
> `aef loop cycle --graph-id demo_agent` proposed a change to
> `agents/demo/graph.py` grounded in three `summary_agent` records
> (reproduced). The filter now lives on `MemoryEvidence.from_store`, applied
> once where the evidence is assembled, so every proposer goes through it.

Every one of the four was reproduced by RUNNING a command before anything
changed. The four commands and their real output are below, verbatim, paths
elided only where a `tmp` prefix would fill the page.

## F2 — `aef loop cycle` drops all the evidence without `--graph-id`

ADR 0174's defect 1. On a scratch repo: a Zone A persona, `agents.demo.graph`,
and two bootstrap inputs whose owner checks the graph fails — so ADR 0174's
check-derived producer writes two `failure` records into the durable store.

```
$ aef loop bootstrap agents.demo.graph --corpus corpus --inputs inputs.json \
    --memory memory.jsonl --no-loop-state
recorded 2 scenario(s) in the train split
  WRONG   wrong-one
  WRONG   wrong-two
2 of 2 recorded run(s) FAILED: 0 raised or ended with a failed plan, 2 failed an owner check
  2 memory record(s) written to the durable store …
exit=0

$ cat memory.jsonl | …
  failure  run_id=wrong-one
  failure  run_id=wrong-two
```

Both records are in the file. Then, without `--graph-id`:

```
$ aef loop cycle --repo repo --state state --workdir work --corpus corpus \
    --memory memory.jsonl --proposer rule_based_prompt \
    --agent-path agents/demo/persona.md
  ledger verified: 0 entr(ies)
  the proposer produced nothing from the available evidence: 2 record(s)
  dropped as another graph's scenario; no admissible failure record for this graph
cycle verdict: … no admissible failure record for this graph
exit=0
```

and with it:

```
$ aef loop cycle … --graph-id demo_agent
  proposed cycle-20260905T040818-prompt on local branch loop/cycle-…-prompt
  gated: reject — G1 rejected it: build command failed (exit -1): python -m pytest -q
exit=1
```

Same evidence, same command, one flag. And the flag's value —
`demo_agent` — was sitting in the corpus the command had already loaded.

### The complication, which is why this is not three lines

`--graph-id` is **two things**, and ADR 0125 separated the namespaces on
purpose:

- the **archive key** G5 reads its blessed baseline under (`archive.versions`),
  defaulting to `"default"`;
- via `_build_proposer`, a **`Graph.id`** that `RuleBasedPromptProposer` matches
  scenarios against — and only that proposer. `RuleBasedProposer`, still the
  default, never filters, which is why aef-core's own end-to-end adoption test
  was green while this was true.

`harness.loop._scenarios_for_graph` still gates *all* scenarios when the corpus
records one graph, and says why in its docstring: the two namespaces are
different and requiring them to agree would break every existing single-graph
corpus. The proposer's admission has no such tolerance.

So deriving unconditionally moves the archive key out from under a baseline the
owner already blessed. **Measured, not guessed** — the first version of this
fix derived unconditionally, and:

```
$ pytest tests/cli/test_adoption_sequence.py
E   AssertionError: not built: G5 rejected the candidate first, so its code
E   was never executed
E   assert '1 candidate + 1 incumbent + 5 random control(s)' in 'not built: …'
```

The documented adoption sequence blesses with no `--corpus` at all — `aef loop
bless` has no such flag — so it blesses under `"default"` and would then cycle
under `demo_agent`, with G5 holding nothing to compare against. That is a worse
defect than the one being fixed, and it was found by running the suite, not by
reading.

### Decision

`--graph-id`'s parser default becomes `None`, so **omitting the flag is
distinguishable from typing it** — the whole fix rests on that. One function,
`graph_id(args)`, answers `DEFAULT_GRAPH_ID` (`"default"`) for every subcommand
that does not derive, which is exactly what `default="default"` used to do; the
three former readers (`_config`, `bless`, `doctor`) go through it rather than
keeping three copies of `args.graph_id or "default"`.

`resolve_graph_id_from_corpus(args)` then settles the value against the corpus
`cycle` is about to load, **before** `_config` freezes it into `LoopConfig`, and
inside `cmd_cycle`'s `try` so a malformed corpus is journalled like every other
way the command can die (ADR 0167). Five cases, each with a reason rather than a
default:

| situation | answer |
|---|---|
| no `--corpus`, or an empty one | derive nothing; `"default"` as before |
| one graph, nothing blessed to orphan | **derive**, and say so |
| one graph, but a baseline sits under `"default"` and none under it | **keep the key**, and warn with the `bless` command that moves it |
| several graphs, no `--graph-id` | **refuse**, listing them |
| `--graph-id` names no corpus graph, nothing blessed under it | **refuse** — a typo |
| `--graph-id` names no corpus graph but a baseline sits under it | **warn** — ADR 0125's archive-key namespace, and not a typo |

The refusals raise `GraphIdError`, joining `PolicyConfigError` and
`CorpusGraphMismatchError` in `cmd_cycle`'s rejection branch, so they are exit 1
and journalled, never exit 3 and never a halt.

Why the third row is a warning and not a refusal, stated because it is the one
place this stops short of the finding as written: refusing there breaks the
documented first-week sequence, and strengthening a control on an invocation
nobody has reproduced a problem with is an owner's decision, not a fix wave's
side effect (ADR 0141's rule, applied to itself). The warning names the exact
command that makes the two namespaces agree.

Both the derived value and the fact of derivation are printed twice — once at
the moment it happens, and once **in the verdict line**, because that is the
line a workflow tees into its step summary and three lines up in a CI log is not
a place anyone reads:

```
  --graph-id not given; derived 'demo_agent' from the 2 scenario(s) in corpus,
  which record one graph
  …
cycle verdict: proposed cycle-… [--graph-id derived from --corpus: 'demo_agent']
```

### After

```
$ aef loop cycle … --proposer rule_based_prompt --agent-path agents/demo/persona.md
  --graph-id not given; derived 'demo_agent' from the 2 scenario(s) in corpus, which record one graph
  ledger verified: 0 entr(ies)
  proposed cycle-20260905T041550-prompt on local branch loop/cycle-…-prompt
  gated: reject — G1 rejected it: build command failed (exit -1): python -m pytest -q
cycle verdict: proposed cycle-… [--graph-id derived from --corpus: 'demo_agent']
```

## F3 — `loop score` took `module:factory`, `loop bootstrap` took `module`

ADR 0174's defect 3. The same graph, named two ways by two subcommands of one
command, each spelling failing on the other:

```
$ aef loop bootstrap agents.demo.graph --corpus corpus --inputs inputs.json --no-loop-state
recorded 1 scenario(s) in the train split
exit=0
$ aef loop score agents.demo.graph --corpus corpus
error: entrypoint must be 'module:factory', got 'agents.demo.graph'
exit=1

$ aef loop score agents.demo.graph:build_graph --corpus corpus
task metric — agents.demo.graph:build_graph (demo_agent) — repeat=1
exit=0
$ aef loop bootstrap agents.demo.graph:build_graph --corpus corpus2 --inputs … --no-loop-state
error: No module named 'agents.demo.graph:build_graph'
exit=1
```

and a third form nobody had reconciled — ADR 0168's file path, which
`record`/`bootstrap`/`harvest`/`cycle` have accepted since G1b:

```
$ aef loop score /…/agents/demo/graph.py --corpus corpus
error: entrypoint must be 'module:factory', got '/…/agents/demo/graph.py'
exit=1
```

Two loaders, neither wrong on its own. `cli.run.load_graph_module` imports a
dotted name **or a file path** (ADR 0168) and calls `build_graph`;
`harness.scenario_runner.load_graph` demands `module:factory`, uses bare
`importlib` (no file path, no CWD on `sys.path`) — and carries a control the
other does not: ADR 0085's `except BaseException`, so a factory that raises
`SystemExit` cannot exit the runner cleanly.

### Decision

**One parser and one loader for "which graph", and it is the union.** Nothing
was narrowed: every subcommand still accepts every spelling it accepted before.

`split_graph_reference(reference) -> (module-or-path, factory)` splits on the
**last** colon and only when what follows is a Python identifier, so
`agents/x/graph.py`, `agents/x/graph.py:make` and a Windows-shaped
`C:\a\graph.py` all resolve the way they read; a half-written `module:` or
`:factory` is refused by name rather than guessed at. The factory defaults to
`build_graph`, which is what `aef migrate` writes.

`load_graph_reference` is strictly stronger than both loaders it replaces: it
keeps ADR 0168's file-path import (which `score` never had) **and** ADR 0085's
`BaseException` guard (which `record`/`bootstrap`/`harvest`/`cycle` never had),
and adds the `isinstance(graph, Graph)` check to all five.

`GRAPH_REFERENCE_HELP` is **one string**, and the five arguments share it by
reference — five copies of a help string is how `score` came to describe the
same argument a sixth way in the first place. The three forms are named in it:

```
  GRAPH   which graph, in any of three forms — a dotted module exposing
          build_graph() ('agents.mine.graph'); 'module:factory'
          ('agents.mine.graph:build_graph'); or a path to the .py file that
          defines it ('.claude/agents/migrated/x/graph.py', optionally with
          ':factory'). The file form is the one to use under a widened
          --agent-root … (ADR 0168).
```

**Covered:** `record`, `bootstrap`, `harvest`, `cycle --module`, `score`.
**Not covered, deliberately:** `run --module`, whose handler is another
worker's file this wave (S4 holds `cmd_run`'s parser region). It is pinned as
`PENDING` in `tests/cli/test_loop_graph_reference.py`, so the day it is
converted the test says so and the person converting it updates both sets. Also
not covered: `--entrypoint` on `gate`/`cycle`/`run`, which is a string handed to
the **out-of-process** gates and consumed by `scenario_runner.load_graph` — see
"Defects found outside this worker's files".

The enumerating test derives the covered set from the **real parser** (the G1a
pattern), then runs all fifteen combinations of five subcommands × three forms
producer→parser→loader, plus `bootstrap` and `score` end to end on each form.

### After

```
$ aef loop score agents.demo.graph --corpus corpus
task metric — agents.demo.graph (demo_agent) — repeat=1
  train       n=1   with_checks=0   mean=1.0000 …
exit=0
$ aef loop score /…/agents/demo/graph.py --corpus corpus
task metric — /…/agents/demo/graph.py (demo_agent) — repeat=1
exit=0
$ aef loop bootstrap agents.demo.graph:build_graph --corpus corpus2 --inputs … --no-loop-state
recorded 1 scenario(s) in the train split
exit=0
```

## F4 — a copied corpus's stale manifest, and no way back

ADR 0174's defect 4. Bootstrap a corpus of three, copy the directory, delete one
scenario file:

```
$ ls copied/train ; cat copied/manifest.json
['s-1.json', 's-3.json']
{ "scenarios": { "s-1": "train", "s-2": "train", "s-3": "train" } }

$ aef loop cycle --repo repo --state state --workdir work --corpus copied --no-memory
error (CorpusShrankError): corpus shrank: 1 previously-admitted scenario(s) are
gone: ['s-2']. A suite that can be made to pass by deleting the failing case is
not a suite.
exit=3

$ aef loop score agents.demo.graph:build_graph --corpus copied
error: corpus shrank: 1 previously-admitted scenario(s) are gone: ['s-2']. …
exit=1
```

**The refusal is right and is not weakened here.** ADR 0141 built it because
`check_never_shrinks` had no production caller at all, and deleting the two
scenarios the agent failed raised `aef loop score` from 0.6667 to 1.0000 with
nothing complaining. A corpus that shrinks under the loop is the loop deleting
its own evidence. It fires on exactly the same condition after this change.

What was missing was any way back:

```
$ aef loop --help
positional arguments:
  {gate,monitor,digest,status,record,bootstrap,score,skills,harvest,cycle,run,bless,doctor}
```

No `corpus` subcommand at all. The only documented remedy was hand-editing
`manifest.json`, and the remedy people actually reach for is deleting the
manifest — which loses every id it was keeping, silently, and is exactly the
outcome the ledger exists to prevent.

### Decision

`aef loop corpus reconcile --corpus <dir>` rewrites the manifest from the
scenario files on disk and **prints every id it drops**:

```
$ aef loop corpus reconcile --corpus copied
  DROPPED  s-2 (was train) — no file on disk
manifest rewritten from disk: 1 dropped, 0 moved, 0 added, 2 scenario(s) now recorded
  Those ids are no longer admitted evidence. Commit this manifest in its own
  reviewable change — retiring a scenario is an owner's decision and the diff is
  the record of it (ADR 0141).
exit=0

$ aef loop corpus reconcile --corpus copied            # idempotent
manifest already describes the 2 scenario(s) on disk at copied; nothing to reconcile
exit=0

$ aef loop cycle … --corpus copied --no-memory          # and the next cycle proceeds
  ledger verified: 0 entr(ies)
  no memory store configured: nothing to learn from, no candidate
exit=0
```

`ADDED` and `MOVED` are reported too: the printed report is a complete account
of what the manifest gained as well as what it lost, or it is not a record.

**The control that makes this safe is that the loop cannot run it.** ADR 0060's
shape — the harness prints the command, a person runs it. Three enforcements,
because one AST scan is one hop deep:

1. `tests/harness/test_corpus_reconcile.py` AST-scans all of `aef/` and asserts
   the *only* caller of `reconcile_manifest` is `cli/loop.py::cmd_corpus_reconcile`.
   **Verified against a planted fault** (mutation M9): adding
   `reconcile_manifest(Path(args.corpus))` inside `cmd_cycle` fails it, naming
   that call site.
2. The string `reconcile` is banned outright from `cmd_cycle`'s and `cmd_run`'s
   source, so a helper introduced between them and the function does not slip
   past a one-hop scan.
3. `save_manifest`'s callers are pinned to `_record_in_manifest` (which unions
   one id in as it is admitted, never rewrites — ADR 0141) and
   `reconcile_manifest` itself.

Two other refusals, each with a reason:

- **a malformed scenario is not reconciled away.** `reconcile_manifest` lets
  `CorpusError` out and the CLI exits 1 with the id still admitted — dropping an
  id because its file failed to parse would let a corrupt write retire evidence,
  which is the deletion this ledger exists to notice;
- **a missing `--corpus` directory is refused, not created.**

And the `CorpusShrankError` message now names the command, on both its branches
(missing ids, and a split move), with `BY HAND` in it and the sentence *"No loop
subcommand does this for you; a loop that can rewrite its own evidence ledger has
no ledger."*

## F1 — `discover_skills` counted `aef adopt`'s own skill

ADR 0172's finding 1, reported there for migrate's owner. On a copy of the
marlin pilot clone:

```
### before adopt
  adopt   skills=5
  migrate skills=6
### after `aef adopt`
  detection line: prompt_files (8 agents, 5 skills, AGENTS.md, .codex, …)
  adopt   skills=5
  migrate skills=6
    .claude/skills/accela/SKILL.md
    …
    .claude/skills/new-model-check/SKILL.md   <-- adopt's OWN output
```

Adopt applies the exclusion (ADR 0172 D4) and migrate does not, so the scaffold
counts its own output as the adopter's prompt surface — a number that changes
the moment adoption runs.

### Where the constant lives, and why it is not imported from adopt

ADR 0172 D4 records that "no cycle is introduced — `aef/cli/adopt.py` already
imported `DEFAULT_MIGRATED_OUT` from migrate, and migrate imports nothing from
adopt." The reverse is therefore a hard cycle, and it was **reproduced** rather
than assumed: a module-level `from aef.cli.adopt import _ADOPT_SKILL_PATH`
patched into the real `aef/cli/migrate.py` (restore SHA-256-verified), imported
both ways round:

```
$ python -c 'import aef.cli.adopt'     exit=1
$ python -c 'import aef.cli.migrate'   exit=1
  File ".../aef/cli/migrate.py", line 120, in <module>
    from aef.cli.adopt import _ADOPT_SKILL_PATH
ImportError: cannot import name '_ADOPT_SKILL_PATH' from partially initialized
module 'aef.cli.adopt' (most likely due to a circular import)
```

So the string goes to `aef/harness/zones.py` — which both CLI modules already
import, and which imports neither — beside `DEFAULT_AGENT_PATH`, for the reason
that constant's own comment gives. `ADOPT_SKILL_PATH` is the one derivation
(ADR 0149).

### Decision

`aef/cli/migrate.py` gains `is_adopt_skill(root, path)` — adopt's rule, derived
from the shared constant, resolving both sides so a symlinked skills directory
answers the way adopt's own exclusion does — and `discover_adopter_skills`,
which is `discover_skills` minus aef's own.

**`discover_skills` itself is unchanged and still returns all of them**, and the
report still *names* the excluded file, marked. Dropping it from the listing
would make `aef migrate` silent about a file it declined to migrate, which is
the one thing that block exists not to be. Only the COUNT changes:

```
found 5 skill(s) and did NOT migrate any of them:
  SKILL    .claude/skills/accela/SKILL.md
  SKILL    .claude/skills/county-onboard/SKILL.md
  SKILL    .claude/skills/marlin-cost-check/SKILL.md
  SKILL    .claude/skills/mcp-contract-check/SKILL.md
  SKILL    .claude/skills/new-model-check/SKILL.md   (aef's own — not yours)
  SKILL    .claude/skills/verify-and-ship/SKILL.md
```

`MigrateResult.skills_own` carries the split, computed at the one place that
knows the repo root, so `report()` still renders from the result alone and a
hand-built result counts exactly what it used to.

### The pinned test, updated deliberately

`test_adopt_still_does_not_count_its_own_skill_after_reusing_migrates_discovery`
pinned **both** numbers (2 and 3) with the note that the day migrate mirrored the
exclusion, the test would say so. It did, and it does: it now asserts adopt and
migrate **agree**, keeps the raw-listing assertion (3) so the marking is not
mistaken for the defect returning, and carries the history in its docstring.

One residual, stated rather than hidden: `aef/cli/adopt.py`'s
`_ADOPT_SKILL_PATH` still spells the literal, because that file was another
worker's this wave. `test_adopts_own_skill_path_is_the_one_in_the_harness`
asserts it equals `zones.ADOPT_SKILL_PATH` and its failure message says to make
it an alias — the same one-line shape `DEFAULT_MIGRATED_OUT` already has.
Mutation M14 confirms that assertion bites.

## Evidence

**Green bar**, all four, on the merged branch:

```
pytest -q                              2570 passed, 6 skipped
mypy aef examples                      Success: no issues found in 134 source files
ruff check aef tests examples          All checks passed!
ruff format --check aef tests examples 273 files already formatted
```

Test count **2510 → 2570** (+60): 30 in `tests/cli/test_loop_graph_reference.py`,
14 in `tests/harness/test_corpus_reconcile.py`, 11 in
`tests/cli/test_loop_cycle_graph_id.py`, 4 in
`tests/cli/test_migrate_prompt_agents.py`, 1 in `tests/cli/test_adopt.py`.

**Mutations: 14 planted, 14 killed**, every restore byte-identical by SHA-256.

| # | mutation | killed by |
|---|---|---|
| M1 | never derive the graph id | 3 in `test_loop_cycle_graph_id.py` |
| M2 | guess instead of refusing on several graphs | 2 |
| M3 | derive unconditionally, orphaning a blessed baseline | 2, incl. `test_adoption_sequence.py` |
| M4 | accept an explicit id the corpus has never heard of | 1 |
| M5 | stop splitting `module:factory` | 12 in `test_loop_graph_reference.py` |
| M6 | `except Exception` instead of `BaseException` (ADR 0085) | 1 |
| M7 | give `score` its own help again | 4, incl. `test_loop_agent_root_guard.py` |
| M8 | the refusal stops naming the way back | 1 |
| M9 | **planted fault:** `cmd_cycle` reconciles the ledger | 3 in `test_corpus_reconcile.py` |
| M10 | reconcile drops ids silently | 2 |
| M11 | **control:** never-shrinks stops firing at all | 3 |
| M12 | migrate stops excluding adopt's own skill | 3 across two files |
| M13 | the listing stops marking aef's own skill | 1 |
| M14 | the shared constant drifts from adopt's | 2 |

M9 and M11 are the two that matter most: M9 verifies the owner-only control
against the exact fault it exists to catch, and M11 verifies that the
never-shrinks refusal is still a live detector after being given a remedy — a
control that has been handed an escape hatch and is no longer checked is
decoration.

## Consequences

- A prompt-file repo that bootstraps a corpus and cycles now proposes without
  being told a flag whose value was already on disk. The two configurations
  where it cannot safely be derived say so in words, name the command that
  fixes them, and do not guess.
- `--graph-id`'s double life is now **stated** in three places (the flag's help,
  `resolve_graph_id_from_corpus`'s docstring, and this ADR) instead of being
  discoverable only by reading `_scenarios_for_graph`. It is not resolved:
  `LoopConfig` still has one field for two namespaces, and the honest fix is a
  second field, which is `aef/harness/loop.py`'s to add.
- Every `aef loop` subcommand that names a graph in-process accepts the same
  three spellings and prints the same sentence about them, and a sixth
  subcommand that grows its own dialect fails a test derived from the parser.
- A stale manifest has a documented, printed, owner-run remedy for the first
  time, and the loop provably cannot reach it.
- Adopt and migrate report the same number about the same tree, and the file
  they disagreed about is still named in migrate's output rather than being made
  invisible by the fix.

## Defects found outside this worker's files

1. **`--entrypoint` is the fourth spelling of "which graph", and F3 did not
   reach it.** `gate`, `cycle` and `run` take `--entrypoint module:factory` as a
   *string* handed to the out-of-process gates, loaded there by
   `harness.scenario_runner.load_graph` — which still refuses a bare module and a
   file path. So `aef loop cycle --module agents/x/graph.py --entrypoint
   agents/x/graph.py` accepts the first and refuses the second, inside one
   invocation. The fix is `load_graph` calling the same splitter, which is
   `aef/harness/scenario_runner.py` — not this worker's file, and a change to
   the loader the gates run candidate code through deserves its own reproduction.
2. **`aef loop run --module` is the fifth in-process caller and still uses the
   old loader**, so it accepts a dotted name and a file path but not
   `module:factory`, and it does not have ADR 0085's `BaseException` guard.
   `cmd_run` is S4's region this wave; pinned as `PENDING` in
   `tests/cli/test_loop_graph_reference.py`.
3. **`LoopConfig.graph_id` is one field serving two namespaces** (the archive key
   and `Graph.id`), which is the root of F2 and the reason its fix has a
   "keep the key and warn" branch at all. `RuleBasedPromptProposer` reads it as a
   `Graph.id` and `archive.versions` reads it as a directory name. A second field
   — `evidence_graph_id`, defaulting to `graph_id` — would let the CLI derive one
   without moving the other, and would delete the warning branch. `aef/harness/loop.py`.
4. **`aef/cli/adopt.py` still spells `.claude/skills/new-model-check/SKILL.md`
   itself** rather than importing `zones.ADOPT_SKILL_PATH`. One line; pinned by
   `test_adopts_own_skill_path_is_the_one_in_the_harness` until adopt's owner
   takes it.
5. **`tests/harness/test_container_sandbox.py::test_a_timed_out_container_is_actually_dead`
   is flaky**, not caused by anything here: it failed once in a full run
   (`container(s) still running after the timeout: {'859ef4d2ca9b'}`) and passed
   on the immediately following targeted re-run and every subsequent full run. A
   docker-kill race in the test, worth a look by whoever owns the sandbox.
6. **The whole suite fails 28 tests without the venv on `PATH`.** `run_sandboxed`
   invokes `python`, and `PYTHONPATH` alone does not put one there — every
   sandbox, gate and evidence-loop test then fails with `[Errno 2] No such file
   or directory: 'python'`. It looks exactly like a real regression; it is a
   missing `PATH`. Worth a line in the contributor docs, or a `conftest` that
   refuses to run rather than reporting 28 confusing failures.

## Errata

- **ADR 0174, "Defects found outside this worker's files" 1, 3 and 4: CLOSED**
  here (F2, F3, F4 above). Defect 0 (`knowledge_boost = 0.0` hiding the only
  lesson) and defect 2 (already closed by M4c) are untouched.
- **ADR 0172, "Reported for migrate's owner, not fixed here": CLOSED** here (F1).
  Its prediction that
  `test_adopt_still_does_not_count_its_own_skill_after_reusing_migrates_discovery`
  "says so the day migrate mirrors it" held exactly: the test failed on that
  change and was updated with its history rather than silently re-pinned.
- **ADR 0125's rule that `--graph-id` "defaults to `default`"** is narrowed:
  the *parser* default is now `None` and the *meaning* of an omitted flag is
  `"default"` everywhere except `aef loop cycle`, where it is derived from the
  corpus when that is unambiguous and safe. The namespace separation the rule
  exists to protect is unchanged, and is what the "keep the key and warn" branch
  defends.

## Erratum — outside-defects 1, 2 and 3 are CLOSED (ADR 0182)

**Defects 1 and 2 (K3-2).** `--entrypoint`'s refusal of a bare module and a
bare file path was **verified against current main before being fixed**, which
mattered: ADR 0177 landed between these two ADRs and gave the loaders one
*importer* while leaving the *splitter* demanding both halves, so this ADR's
sentence — "`aef loop cycle --module agents/x/graph.py --entrypoint
agents/x/graph.py` accepts the first and refuses the second, inside one
invocation" — was still true after that merge, and the reproduction is pasted
in ADR 0182. `split_entrypoint` is now the union rule this ADR wrote for the
CLI, moved into `aef/harness/graph_loading.py` (with `GRAPH_REFERENCE_HELP`)
because the harness may not import the CLI. `cmd_run` uses
`load_graph_reference`; `COVERED` gains `run` and `PENDING` is empty. The
prediction that the `PENDING` pin "fails the day `run` is converted, which is
when someone should read it" held exactly.

**Defect 3 (K3-3), and the narrowing it forces on F2's own rule.**
`LoopConfig.evidence_graph_id` exists, read by `_build_proposer` alone.
F2's rule — *"derive when there is no baseline to orphan; say so loudly when
there is"* — is replaced by **"derive the evidence id always, and never move
the archive key"**. Both of this ADR's warn-instead-of-fix branches (the third
and sixth rows of its table) become derivations; the refusal on an ambiguous
corpus is unchanged and is the only warning left. The verdict line now reads
`[evidence graph id derived from --corpus: 'demo_agent']`, because the flag is
no longer what moved. Four tests in `tests/cli/test_loop_cycle_graph_id.py`
that pinned the one-field behaviour were rewritten with that history rather
than silently re-pinned.

Defects 4, 5 and 6 are untouched.

## Confidence

High on all four reproductions — each is a command whose real output is pasted
above, each fix re-run against the same command, each pinned by a test that
fails when the defect is put back (14/14 mutations).

Medium on F2's completeness: the "keep the key and warn" branch leaves a real
configuration in which the evidence is still dropped, and it is warned about
rather than fixed, because fixing it properly needs the second `LoopConfig`
field named in defect 3. Medium on F3's breadth: two of the seven surfaces that
name a graph (`--entrypoint`, `run --module`) are outside this worker's files
and are pinned as known gaps rather than closed. High on F4's control — the
owner-only property is the one thing here verified against a planted fault
rather than only against its own test.
