# ADR 0168: The diagnostic that never opened the agents

## Status

Accepted. Fix wave **G1b** of `UPGRADE_LOOP.md`. Model: `claude-opus-5[1m]`.
**Zero live model calls** — every reproduction here is a filesystem or a
classifier fact and none of them needs a model. **No rubric dimension moves.**

Six findings, each reproduced by running a command before anything was
changed: **F3** (HIGH), **F5** (MEDIUM), **F8** (LOW) and **S2** (suspected →
confirmed) from the first seam hunt, **R7** (MEDIUM) from the second, plus
**M4** (HIGH), folded in from the M4 increment, which hit it and worked around
it.

They share one shape, and it is the shape ADR 0091 keeps finding: a fact with
two owners, kept correct in one of them. Where `aef migrate` writes; what the
agent root is; which directory holds bytecode; what a graph id may contain;
what spelling of a module `aef run` accepts; which files `aef adopt` will
write.

Five of the six are only visible when one command's output is fed to another,
which is the C↔D lesson: every one of these components was individually tested
and individually correct. R7 is the sharpest case — a diagnostic prescribing a
command that the tool it names refuses to perform.

---

## F3 (HIGH) — `aef doctor` never opened the eight graphs that call a model

### Reproduced

A copy of the marlin pilot clone (8 `.claude/agents/*.md` personas, already
`aef adopt`ed), migrated with defaults:

```
$ aef migrate --dir <clone>
wrote 8 prompt agent graph(s):
  <clone>/agents/migrated/marlin_accela/graph.py
  ... 7 more ...

$ find <clone> -name graph.py | wc -l
       9

$ aef doctor --dir <clone> | grep model_calls
[OK] model_calls_visible:aef_adapter.py: 1 reachable module(s), none imports a model SDK
[OK] model_calls_visible:agents/migrated/graph.py: 1 reachable module(s), none imports a model SDK
```

Two entries against nine graphs on disk. Obligation 6 — ADR 0137's *every model
call must reach the harness* — **passed**, and it passed on
`agents/migrated/graph.py`: the call-site stub whose `build_graph()` body is
`raise NotImplementedError` and which makes no model call at all. The eight
graphs that do make one were never opened.

`_graph_entries` globbed `agents_root/*/graph.py` — one level. ADR 0152's
`aef migrate` writes `<agent root>/migrated/<module>/graph.py` — two. Neither
half is wrong on its own; both were tested; no test ran the producer into the
consumer.

**Second half.** `aef doctor` has no `--agent-root`:

```
$ aef doctor --dir <clone> --agent-root .claude/agents
usage: aef [-h] {init,adopt,migrate,doctor,run,eval,trace,loop} ...
aef: error: unrecognized arguments: --agent-root .claude/agents
```

So on a repo that took ADR 0152 §4's opt-in and widened Zone A, doctor reported
on the two files *outside* the widened root and said nothing about the sixteen
inside it (8 graphs + 8 personas).

### Erratum on ADR 0149

`_graph_entries`' docstring said, of deriving every path from
`DEFAULT_AGENT_ROOT`:

> Every path here is derived from `DEFAULT_AGENT_ROOT` via `aef.cli.migrate`,
> so moving the agent root or migrate's default cannot leave this list naming a
> directory nothing writes to.

That was true when it was written, and it was true of exactly one writer.
Derivation kept the **root** correct and said nothing about the **depth**; ADR
0152 added a second writer two levels down and the sentence went on reading as
a guarantee. A shared constant proves that two names spell one string. It
cannot prove that a glob matches what another command writes — only running
one into the other can, which is what
`tests/cli/test_doctor_discovery.py::test_doctor_lists_every_graph_migrate_wrote`
now does, asserting doctor's list against **migrate's own reported outputs**
rather than against a depth anyone typed.

### Decision

Discovery is **one function**, `aef.harness.zones.discover_graph_files(root, *,
agent_root=DEFAULT_AGENT_ROOT) -> list[str]`. It `rglob`s `graph.py` under the
agent root and adds the three entries that live outside it and can only be
named: `ADAPTER_SHIM`, `DEFAULT_AGENT_PATH` and `LEGACY_AGENT_PATH` (the
pre-0143 `aef_migrated.py`, kept so repos migrated before that day do not drop
out of the advisory). De-duplicated, stable order.

It lives in `aef/harness/zones.py` for the reason `DEFAULT_AGENT_PATH` already
does: `aef/harness/preflight.py` needs it and the harness does not import the
CLI. `aef.cli.migrate.LEGACY_MIGRATED_OUT` becomes an alias, like
`DEFAULT_MIGRATED_OUT` before it.

`aef doctor` gains `--agent-root`, defaulting to `DEFAULT_AGENT_ROOT`, threaded
`main.py -> run_doctor -> _graph_entries -> discover_graph_files`. An explicit
`--agent-path` still wins outright.

`rglob`, not a depth limit: a depth limit is a promise about a layout `migrate`
is free to change, and the same argument (measured against the CLI in ADR 0152
§2) already made `discover_prompt_agents` recursive.

### After

```
$ aef doctor --dir <clone> | grep -c model_calls
10
$ aef doctor --dir <widened-clone> --agent-root .claude/agents | grep model_calls
[OK] model_calls_visible:aef_adapter.py: ...
[OK] model_calls_visible:agents/migrated/graph.py: ...
[OK] model_calls_visible:.claude/agents/migrated/marlin_accela/graph.py: ...
... 7 more ...
```

### The preflight call site — reported, not edited

`aef/harness/preflight.py` belongs to another worker this wave. Obligation 6 is

```python
visible, detail, fix = model_calls_are_visible(repo_root, agent_path)
```

— **one** `agent_path`, defaulted to `DEFAULT_AGENT_PATH` by
`aef/cli/loop.py::cmd_doctor` (~L947) and `_warn_unmet_obligations` (~L159). So
`aef loop doctor` on the pilot clone judges obligation 6 against
`agents/migrated/graph.py` alone — the same stub, the same false pass — while
eight graphs go unscanned. The fix is the same shape as doctor's: when
`--agent-path` is not given explicitly, iterate
`discover_graph_files(repo_root, agent_root=...)` and report the obligation
unmet if **any** entry is invisible. `discover_graph_files` is importable from
`aef.harness.zones` today and needs nothing further from this branch.

---

## F5 (MEDIUM) — one report, two answers, and the gate agreed with neither

### Reproduced

```
$ aef migrate --dir <clone> --agent-root .claude/agents
wrote <clone>/agents/migrated/graph.py
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may propose changes to
...
BLAST RADIUS — what the self-rewiring loop may now propose changes to.
  Zone A is '.claude/agents'. The generated graphs are inside it.
```

Twelve lines apart, in one report. And the classifier the gates themselves use:

```
$ python -c "from aef.harness.zones import ZonePolicy, inspect_path; \
  v = inspect_path('agents/migrated/graph.py', ZonePolicy(agent_root='.claude/agents')); \
  print(v.zone, v.allowed); print(v.reason)"
C False
agents/migrated/graph.py: Zone C (core) — not under the agent root '.claude/agents';
only Zone A is agent-writable
```

`_zone_note` called `inspect_path` with the **default** `ZonePolicy` and
hardcoded `DEFAULT_AGENT_ROOT` in its own string. `result.agent_root` existed
and never reached it. The blast-radius block, three functions away, was computed
correctly — so the report was right once, wrong once, and stated the wrong one
first.

`BLAST RADIUS`'s own "The generated graphs are inside it" was also false, for
one of them: `--agent-root` moves the prompt-agent graphs, `--out` moves the
call-site graph.

### Decision

`_zone_note` takes the whole `MigrateResult` and classifies with
`ZonePolicy(agent_root=result.agent_root)` — the policy the loop will actually
run. It returns lines rather than one line, because the widened case has
something to say.

Landing outside a widened root is the **ordinary** case, not a mistake: the
call-site graph is not what `--agent-root` moves. So the note says that in
words, gives the `--out` value that would move it, and prints the
`--agent-path` values that **are** inside the root — because that is the next
thing the operator types. `BLAST RADIUS` names the call-site graph's zone too.

### After (verbatim, `--agent-root .claude/agents`)

```
wrote <clone>/agents/migrated/graph.py
  Zone C under the agent root this run used ('.claude/agents') — NOT agent-writable. A candidate
  touching this file is rejected with `G0 rejected it: candidate touches paths outside Zone A`,
  and `aef loop bless` will archive a Zone A tree that does not contain it.
    You widened the agent root to '.claude/agents', and this file is not under
    it — `--agent-root` moves the PROMPT AGENT graphs, `--out` moves this one. That
    is expected, not a mistake: it is the call-site graph, and this repo's agents are
    elsewhere. Move it too with
      aef migrate --dir . --agent-root .claude/agents --out .claude/agents/migrated/graph.py
    or leave it where it is and point the loop at a graph that IS inside the root:
      --agent-path .claude/agents/migrated/marlin_accela/graph.py
      ... 7 more ...

BLAST RADIUS — what the self-rewiring loop may now propose changes to.
  Zone A is '.claude/agents'. The PROMPT AGENT graphs are inside it.
  The CALL-SITE graph is NOT (agents/migrated/graph.py is Zone C) — `--out` moves that one,
  not `--agent-root`.
  The PERSONA FILES are inside it too (.claude/agents/accela-agent.md is Zone A).
  ...
```

Under the default root, unchanged: `Zone A (agents/**) — agent-writable, ...`.

The test asserts against `inspect_path` itself rather than against a phrase, so
it cannot drift away from the classifier the way the string did.

(G1a is separately making `bless`/`cycle` refuse a default `--agent-path` that
is Zone C under a widened root; this ADR only fixes what the report *says*.)

---

## F8 (LOW) — the advisory named the wrong directory

### Reproduced

The pilot clone's `.gitignore` covers no bytecode (`grep -c 'pycache\|py\[cod\]'`
→ 0). After `aef migrate --agent-root .claude/agents`:

```
$ python -c "import py_compile; py_compile.compile('.claude/agents/migrated/marlin_accela/graph.py')"
compiled
$ git add -A && git status --short | grep -i pycache
A  .claude/agents/migrated/marlin_accela/__pycache__/graph.cpython-313.pyc
```

Zone A content the loop never wrote — ADR 0142's 0.4675-of-0.500 drift charge —
under a root the advisory does not mention:

```
Add `__pycache__/` and `*.py[cod]` to your existing `.gitignore` — ... Committed
bytecode under `agents/` is Zone A content the loop never wrote, ...
```

`agents/` came from `DEFAULT_AGENT_ROOT`, correctly interpolated and wrong for
this repo.

### Decision

State the **rule**, not a path. `aef adopt` runs *before* `aef migrate`, and
`aef migrate --agent-root` is what decides where Zone A is, so adopt cannot know
the root — and saying so is more useful than guessing. The patterns themselves
were always repo-wide and cover either root; only the sentence was narrow.

### After

```
Committed bytecode under your AGENT ROOT is Zone A content the loop never wrote, and G5 charges
it as drift: measured 0.4675 of a 0.500 budget for a one-line candidate, against 0.0238 with the
bytecode excluded (ADR 0142). The agent root is `agents/` by default and whatever you pass to
`aef migrate --agent-root` otherwise (`.claude/agents/` for a prompt-file repo) — `aef adopt`
runs before `aef migrate` and cannot know which you will choose, so both patterns are repo-wide
and cover either.
```

`_DRIFT_COST` is shared with `gitignore_appended_note()`, which carried the same
narrow claim; both are correct now.

---

## S2 (suspected → **CONFIRMED**) — a graph id is joined onto a directory

### Reproduced, both halves

A scratch repo with `.claude/agents/evil.md` whose frontmatter says
`name: ../escape`:

```
$ aef migrate --dir <scratch>
  AGENT    ../escape  (.claude/agents/evil.md)
            -> agents/migrated/escape/graph.py
            -> aef run agents.migrated.escape.graph --objective "..." --config aef.yaml
            graph_id='../escape', wired prompt_agent -> reflect -> consolidate -> END
```

The **module** was sanitised (`escape`) — so no module path escapes. The
**graph id** was not, and the report prints it verbatim as the value to hand
`aef loop bless --graph-id`. `archive._graph_dir` was `root / graph_id` with
nothing between them. With `root` at `state/archive`:

```
recorded version 1
archive root contents: []
WROTE state/escape/v000001/entry.json
WROTE state/escape/v000001/files/agents/graph.py
```

One level **above** the archive root it was handed, with the archive root left
empty. `pathlib` makes the absolute form worse: `root / "/etc/x"` discards
`root` entirely. `versions()` and `record()` compute the same wrong directory,
so the store stays self-consistent while writing outside the tree the operator
pointed at — which is why nothing failed and nothing warned.

### Decision — both ends, because either alone leaves the other open

`aef/harness/zones.py` gains `segment_refusal(name) -> str`: `""` if `name` is
exactly one safe path segment, else why not. It reuses `_segments`, the same
deny-by-default rule already applied to diff paths. Normalisation is **refused,
not applied** — `./x` and `x` name one file, and silently accepting the first
lets two spellings of a graph id disagree about which directory they mean.

**`archive._graph_dir` refuses.** In the one place every read and every write
goes through, so `versions()` cannot report on a directory `record()` would not
create. Sanitising was rejected: mapping two ids onto one archive is exactly the
failure an append-only store exists to prevent.

**`aef migrate` never mints one.** `PromptAgentSite.graph_id` returns the
persona's name when it is a safe segment and the (already collision-
disambiguated) `module` when it is not, recording `unsafe_name_reason`. The
generated module gains a `GRAPH_ID` constant used for `Graph(id=...)`;
`AGENT_NAME` is untouched, because the persona's own name is what the model is
told it is and only the id that becomes a *directory* has to be a path segment.

Renamed rather than refused outright: refusing would drop the agent from the
migration over a `/` in a name, and the report says exactly what happened.

### After

```
  AGENT    ../escape  (.claude/agents/evil.md)
            -> agents/migrated/escape/graph.py
            graph_id='escape', wired prompt_agent -> reflect -> consolidate -> END
            NAME REFUSED as a graph id: path traversal ('..') is never resolved, only refused.
            A graph id is joined onto a directory (`<archive root>/<graph id>/v000001/`),
            so 'escape' is used instead. The persona keeps its own name for
            the model call; pass the id above to `aef loop bless --graph-id`,
            and rename the persona if you want the two to match.
```

```
$ python -c "from aef.harness import archive; archive.record(root, '../escape', ...)"
aef.harness.archive.ArchiveError: graph_id '../escape' is not usable as an archive directory:
path traversal ('..') is never resolved, only refused. A graph id is joined onto the archive
root, so it must be one path segment — no '/', no '..', no leading '/'. `aef migrate` reports
the safe id it generated for each agent; pass that.
```

A control test pins that ordinary ids are untouched — `planner`,
`marlin-accela`, `agent_2`, `v1.2.3`, `.hidden` all still record and read back.

---

## M4 (HIGH, folded in) — the report printed a command that cannot run

### Reproduced

From the repo `aef migrate --dir . --agent-root .claude/agents` produced, using
the command that same report printed:

```
$ aef run .claude.agents.migrated.marlin_accela.graph --objective "x" --config aef.yaml
error: the 'package' argument is required to perform a relative import for
'.claude.agents.migrated.marlin_accela.graph'
```

`PromptAgentSite.dotted` is the output path with `/` replaced by `.`, and under
the widened root the output path starts with `.claude`. A leading dot is a
**relative import** to `importlib`, and no dotted spelling of that path exists
at all — `.claude` is not an identifier, so no amount of quoting produces one.

**Erratum on ADR 0152.** M1 added `--agent-root` as the opt-in that puts a
persona in Zone A, and the generated command for every agent migrated under
that flag could not be run. M1's own measurement ran `aef run` on a graph
written at the **default** root (`agents/migrated/marlin_accela/graph.py`), so
the flag and the command were each exercised and never together. M4 hit it and
worked around it by keeping the graphs at the default root while passing
`--agent-root .claude/agents` to the loop — which is the two-trees-one-loop
state ADR 0152's own blast-radius block warns about.

### Decision — (a), `aef run` takes a file path

Option (b), refusing a root that is not importable, was rejected outright:
`.claude/agents` **is** the documented opt-in, so refusing it deletes ADR
0152 §4 rather than fixing it. There is no third spelling to fall back to.

(a) is one function and no new concept:

- `aef/cli/run.py::import_graph_module(module_path)` — the one importer, used
  by `run_graph_module` **and** `load_graph_module` (which `aef loop record`
  shares), replacing the two copies of `importlib.import_module` that were
  there.

  > **ERRATUM (ADR 0177, fix worker J1).** "The one importer" was true of
  > `aef/cli/run.py` and false of the repo. There were **three**:
  > `aef/harness/scenario_runner.py::load_graph` and
  > `aef/harness/node_worker.py::load_graph` each kept their own
  > `importlib.import_module`, and neither is in this ADR's "Not fixed here,
  > reported" section — because every M4 reproduction ran `aef run`, and
  > `aef run` is the loader that got fixed. The consequence was worse than the
  > defect M4 closed: `aef loop score` on a widened-root entrypoint exited 1
  > (`EXIT_REJECTED`), and G2 loaded the INCUMBENT through a recording this
  > importer could read while loading the CANDIDATE through the worker that
  > could not — so an import error on one side became
  > `1 previously-passing scenario(s) no longer pass`. There is now one
  > implementation, `aef/harness/graph_loading.py` (the harness, because the
  > harness may not import the CLI), and this module re-exports it. See
  > ADR 0177 §R1. A `.py` suffix or a separator means "file"; anything else is a dotted
  name.
- The choice is made on the **spelling**, never by trying the import and
  falling back. A dotted import that fails for its own reason — a typo inside
  the module, a missing dependency — would otherwise be retried as a filename,
  miss, and be reported as "no such file", hiding the real error behind a
  second one (`test_a_dotted_name_is_never_retried_as_a_file`).
- `sys.modules` is keyed on a hash of the **resolved** path, because
  `aef migrate` names every generated file `graph.py`.
- `migrate` prints `site.run_target`: the dotted form when every component is
  an identifier and not a keyword, the file path otherwise, with a line saying
  which and why.

### After (verbatim)

```
  AGENT    marlin-accela  (.claude/agents/accela-agent.md)
            -> .claude/agents/migrated/marlin_accela/graph.py
            -> aef run .claude/agents/migrated/marlin_accela/graph.py --objective "..." --config aef.yaml
            (a file path, not '.claude.agents.migrated.marlin_accela.graph': no dotted module name exists under
            '.claude/agents', and `aef run` takes either form)
            graph_id='marlin-accela', wired prompt_agent -> reflect -> consolidate -> END
```

and that command, run on the pilot clone with a `command`-provider config whose
`argv` is `["/bin/echo", "{prompt}"]` — a real provider, a real subprocess, **no
live model call**:

```
$ aef run .claude/agents/migrated/marlin_accela/graph.py \
    --objective "what are the preconditions?" --config stub.yaml
{
  "objective": "what are the preconditions?",
  "working_memory": {
    "prompt_agent": "# Marlin Accela agent\n\nPurpose: design, validate, and operate access
     to the **Accela Construct API v4** ... what are the preconditions?"
  },
  ...
```

The persona body is in the reply because `echo` echoes the prompt, which is
exactly what proves the persona reached the provider. Under the default root
the dotted form is still printed and still works — a control test pins that.

The pinned path is producer → parser → runner:
`test_the_printed_run_command_parses_and_runs_under_a_widened_root` takes the
`aef run ...` line out of the **real** `report()`, `shlex.split`s it, feeds it
to the **real** `build_parser()`, and runs the module argparse hands back
through the **real** `run_graph_module`.

### Not fixed here, reported

`aef loop bootstrap --module`, `aef loop record <module>` and `harness.loop`'s
module arguments: `aef loop record` goes through `load_graph_module` and so
takes a file path today, but the flags' help text still says "module" and
nothing tests the loop commands under a widened root. `aef/cli/loop.py` is
G1a's.

---

## R7 (MEDIUM, folded in) — the fix that `aef adopt` refuses to perform

### Reproduced

A repo whose `AGENTS.md` and `CLAUDE.md` are both symlinks into `docs/` — an
ordinary cross-tool arrangement, one file of house rules read under two names:

```
$ aef adopt --dir .
skipped .../CLAUDE.md (a symlink, or under one — adoption never writes through a link)
skipped .../AGENTS.md (a symlink, or under one — adoption never writes through a link)

$ aef doctor --dir .
[WARN] entry_file_points_at_the_guide:CLAUDE.md: ... the scaffold contract never reaches
the agent. fix: re-run `aef adopt --dir .`, which appends a block between
`<!-- aef:begin -->` and `<!-- aef:end -->` and leaves every other byte of the file alone
[WARN] entry_file_points_at_the_guide:AGENTS.md: ... fix: re-run `aef adopt --dir .` ...
```

`is_file()` follows the link, so the check reads the **target's** bytes, finds
no block, and prescribes the one command that is guaranteed not to add one —
adopt refuses a path that is a link or is under one, by design. Both checks warn
and the only advice on offer is a loop.

### Decision — fix the FIX, not the check

Reading through the link stays right, and that is the load-bearing half: a link
whose target carries the block **does** reach the agent, and narrowing the check
to real files would turn a correctly-adopted repo into two warnings
(`test_a_symlink_whose_target_carries_the_block_is_ok`, and the mutation that
adds `or entry_file.is_symlink()` fails it).

`_link_on_the_way_to(target_dir, path)` walks the leaf and every parent up to
the repo root — **the same walk adopt's writer does**, because adopt refuses a
path under a linked directory as well as one that is a link, and a leaf-only
check would prescribe the loop for the parent case. When it finds a link, the
fix names the real remedy and the reason the old one cannot work.

### After (verbatim)

```
[WARN] entry_file_points_at_the_guide:AGENTS.md: .../AGENTS.md is what your coding agent
reads and it names neither the aef marker block nor AGENT_INTEGRATION.md — the scaffold
contract never reaches the agent. fix: AGENTS.md is a SYMLINK to docs/house-rules.md, and
`aef adopt` never writes through a link — it reports `a symlink, or under one` and skips,
so re-running it will not add the block and telling you to is a loop. Do one of: add the
block to the TARGET (docs/house-rules.md) — appending `<!-- aef:begin -->` …
`<!-- aef:end -->` with a pointer to AGENT_INTEGRATION.md, which is what adopt would have
written — or replace the link with a real file that carries the target's content plus the
block. Either way the agent reading AGENTS.md sees the contract; adopt will then leave it
alone.
```

The `AGENTS.md -> CLAUDE.md` arrangement is not a loop and is not reported as
one: adopt appends to `CLAUDE.md`, which is a real file, and doctor reads
through the link and passes both. That case was run too.

`test_adopt_really_does_refuse_a_symlinked_entry_file` asserts adopt's half
against the **real** `run_adopt` rather than quoting its source, so the two
sides of the loop cannot drift apart without a failure.

---

## Green bar

`pytest -q`: **2195 passed, 5 skipped** (2200 collected) from a baseline of
2153 passed / 5 skipped taken on this branch before any test was added —
**+42, none removed**. `mypy aef examples`: 131 files, clean. `ruff check .`:
clean. `ruff format --check aef tests examples`: 252 files, clean.

Twelve mutations, twelve kills — one only after its control was rebuilt. Each file restored from a byte backup and verified
with a `sha256` taken before the edit; never `git checkout --`.

| mutation | tests that failed |
|---|---|
| `rglob("graph.py")` → `glob("*/graph.py")` (the F3 defect restored) | 4 in `test_doctor_discovery.py` |
| doctor drops `agent_root` on the way to discovery | `test_a_widened_agent_root_is_reported_on`, `test_the_doctor_cli_takes_an_agent_root` |
| `_zone_note` classifies with the default policy (the F5 defect restored) | `test_the_zone_note_reports_the_zone_under_the_root_the_loop_will_run`, `test_the_widened_note_names_the_agent_paths_that_are_inside_the_root` |
| `graph_id` is the persona name, unchecked (the S2 defect restored) | 3 in `test_migrate_prompt_agents.py` |
| `archive._graph_dir` joins the id on unchecked | 14 in `test_archive.py` |
| the advisory names `agents/` again (the F8 defect restored) | `test_the_bytecode_advisory_covers_a_widened_agent_root` |
| the report prints the dotted form unconditionally (the M4 defect restored) | `test_the_printed_run_command_parses_and_runs_under_a_widened_root`, `test_a_non_importable_root_is_named_in_the_report` |
| `aef run` only ever imports a dotted name | 3 in `test_run.py` + the end-to-end |
| `sys.modules` keyed on the basename, so two `graph.py` collide | **SURVIVED the first pass** — `spec_from_file_location` still loads the right file and still returns a distinct module, so `first is not second` passed while the registry entry pointed at whichever was loaded last. The control was rebuilt to assert `sys.modules` itself; re-mutated, it fails |
| doctor prescribes `re-run aef adopt` for a symlink again (the R7 defect restored) | `test_a_symlinked_entry_file_gets_the_real_remedy_not_rerun_adopt` |
| only the leaf is checked, never a symlinked parent directory | `test_an_entry_file_under_a_symlinked_directory_is_named_too` |
| the check narrows to real files (the fix that looks obvious and is wrong) | `test_a_symlink_whose_target_carries_the_block_is_ok` + the R7 remedy test |


## Defects found outside this wave's files (reported, not fixed)

1. **`aef loop`'s module arguments under a widened root.** `aef loop record`
   shares `load_graph_module` and so takes a file path today, but
   `aef loop bootstrap --module` and the flags' help text were not touched and
   nothing tests the loop commands under a widened root. `aef/cli/loop.py` is
   G1a's.
2. **`ArchiveError` from a bad `--graph-id` reaches the CLI uncaught.**
   `aef/cli/loop.py::cmd_doctor` calls `preflight`, whose obligation 5 calls
   `archive.versions(...)`; `cmd_bless` catches `BlessError` only. With the
   refusal above, a hand-typed hostile id now produces a traceback rather than
   a message. That is strictly better than the silent escape it replaces, and
   it is still the wrong surface. `aef/cli/loop.py` is G1a's.

## Confidence

High on all six: each was reproduced by a command whose output is pasted
above, each fix was re-run against the same command, and each is pinned by a
test that fails when the defect is put back. The C↔D lesson is carried by
running the real `run_migrate` into the real `_graph_entries`, and the real
`report()` into the real `build_parser()` into the real `run_graph_module` —
rather than by a shared constant, which is the thing ADR 0149's argument could
not do.

One qualification, recorded because it was a near-miss: the `sys.modules`
uniqueness mutation **survived the first pass**, and the reason was that the
control asserted the wrong thing (two distinct module objects, which the defect
also produces). It was rebuilt to assert the registry itself. Eleven of the twelve
mutations were killed by tests written before the mutation ran; that one was
not, and it is the reason the mutation pass exists.

Lower on breadth: one pilot repo, one harness, one widened-root shape. Nothing
here says the loop's own preflight sees the eight graphs — that is the reported
call site, and it is another worker's file.
