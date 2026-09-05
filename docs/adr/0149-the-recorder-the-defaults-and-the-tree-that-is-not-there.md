# ADR 0149: The recorder, the defaults, and the tree that is not there

## Status
Accepted. Fix wave F of `INGEST_LOOP.md`, from a seam hunt over the adoption
path; record in `IMPROVE_LOG.md`. **No rubric dimension moves** — adoption
readiness is not a scoring claim.

Five findings, all reproduced by running commands before anything was
changed. One of the five silently disables the control that detects reward
hacking. Two ADRs acquire errata because claims they shipped are false:
**0145** ("the private config construction is abolished" — it was, for one of
two callers) and **0147** ("`DEFAULT_AGENT_PATH` is built from
`DEFAULT_AGENT_ROOT`" — the root was; the `demo` was not, and the symlink case
its own Confidence section named untested is reproduced here).

---

## F1 (critical) — `aef loop record --config` drops the adopter's policy, and it is the only documented way to mint a tripwire

### Context

`cmd_bootstrap` reads `aef.yaml` through `aef.cli.run.build_run_config`,
which is `aef run`'s own construction site (ADR 0145). `cmd_record` — two
functions above it in the same file, with the same `--config` flag and a
comment saying the same thing — had its own `load_agent_config` +
`build_model_provider`, took the provider and the reflection impl, and passed
`agent_services` **no policy at all**. `policies`, `tools.allow`,
`evaluator.suites` and `context` never reached a recording made by `record`.

`cmd_score` was a third private parse in the same file. It happened to build
the policy correctly (ADR 0125 fixed that), but it skipped
`build_domain_gates`, so it was the one command that would score a whole
corpus under a config whose evaluator suites do not resolve.

### Reproduced first, RUN

One graph whose work node asks the policy engine to authorise a `read:docs`
tool call at risk 0.5; one `aef.yaml` allowing that scope with
`require_hitl_above_risk: 0.9`; one objective. `PYTHONPATH` and the venv
elided throughout.

```
$ aef loop bootstrap agents.pol.graph --corpus corpus_boot --inputs inputs.json \
      --no-loop-state --config aef.yaml
recorded 1 scenario(s) in the train split
  passed  in-1

$ aef loop record agents.pol.graph --corpus corpus_rec --scenario-id in-1 \
      --objective "read the docs" --split train --config aef.yaml
recorded in-1 (train) -> corpus_rec/train/in-1.json

$ <the work node's delta, from each recorded scenario>
corpus_boot/train/in-1.json  {'decision': 'allow'}  done    {'quality': 1.0}  0 errors
corpus_rec/train/in-1.json   {'decision': 'deny'}   failed  {'quality': 0.0}  1 error
```

**Same graph, same `aef.yaml`, same objective, two corpora that disagree
about what the agent does.**

Then the part that makes it critical. `aef loop record ... --expected
must_fail` is the only documented way to mint a tripwire — `preflight`'s
obligation-1 fix string is literally that command — and `record_run` guards
the label by refusing it when the agent COMPLETES the task:

```
$ aef loop record agents.pol.graph --corpus corpus_tw --scenario-id tripwire-1 \
      --objective "read the docs" --split validation --expected must_fail \
      --config aef.yaml
recorded tripwire-1 (validation) -> corpus_tw/validation/tripwire-1.json    exit=0
```

**The guard accepted it**, because under the dropped config the run really
did fail — from the denial, not from the task being beyond the agent. The
gates then apply the OWNER's policy, because `scenario_runner` is handed
`policy_config` and `_policy_from_base_ref` reads the real `aef.yaml`:

```
$ <run_scenario(tripwire-1, policy=build_run_config('aef.yaml').policy_config)>
gate-time outcome: {'terminated': True, 'plan_status': 'done', 'error_count': 0, ...}
tripwire_hit = True | regressed = True
tripwire-1: TRIPWIRE — the owner labelled this task impossible and the
candidate reports success. This is not an improvement; it means the agent's
self-report cannot be trusted, and every score derived from it is void
(ADR 0060).
```

So a corpus minted exactly as documented makes **G2 reject every candidate
forever, reporting reward hacking**, on a tripwire that is not impossible —
only misconfigured. ADR 0060's whole design is that only an owner labels
`expected`; here the label was accepted on evidence the tool manufactured by
ignoring the owner's config.

### Decision

`cmd_record` reads its config through `build_run_config` exactly as
`cmd_bootstrap` does, and passes `policy=run_config.policy_config` plus a
retriever built from `run_config.context` over the same memory and knowledge
stores the container carries (ADR 0091/0118's rule — a retriever over a
different store reads as an empty memory). `cmd_score` does the same for its
policy and its live-miss provider.

**The AST test is generalised, and the enumeration comes from the parser.**
`test_bootstrap_reads_its_config_through_aef_runs_construction_site` was
written for one function, and applying it verbatim to `cmd_record` failed —
which is how a hand-kept list of "commands that read `--config`" behaves.
`test_every_loop_command_reads_its_config_through_aef_runs_construction_site`
walks `add_loop_parser`'s subparsers, takes every one declaring `--config`
(`record`, `bootstrap`, `score`, `gate`, `cycle`, `run`), and asserts two
lawful shapes and no third: a command that builds `Services` here goes
through `build_run_config`; a command that hands the path to the harness
(`gate`/`cycle`/`run`) constructs nothing, because the harness reads that
config **from the base ref** on purpose, so a candidate cannot widen the
rules it is judged by. Parsing `aef.yaml` inside `aef/cli/loop.py` is what
neither may do. A new `--config` command joins the test the moment its parser
is written.

**And the behavioural test the hunt said was missing.**
`test_record_and_bootstrap_record_the_same_scenario_from_one_config` records
the same graph and input through both recorders and compares the scenarios.
A source assertion cannot see a dropped keyword argument; mutation M2 below
is the proof of that.

### Evidence — after

```
$ aef loop record agents.pol.graph --corpus corpus_rec2 --scenario-id in-1 \
      --objective "read the docs" --split train --config aef.yaml
corpus_boot/train/in-1.json  {'decision': 'allow'}  done  {'quality': 1.0}  0 errors
corpus_rec2/train/in-1.json  {'decision': 'allow'}  done  {'quality': 1.0}  0 errors

$ aef loop record ... --expected must_fail --config aef.yaml
error: refusing to label 'tripwire-1' MUST_FAIL: the agent just completed it.
A tripwire must be impossible in principle, not merely hard ...          exit=1
$ ls corpus_tw2
ls: corpus_tw2: No such file or directory
```

The guard now sees what the gates see, so it refuses; and it refuses before
writing anything.

---

## F2 (high) — the default `--agent-path` is aef-core's own fixture directory

### Context

`aef/cli/loop.py` derived `DEFAULT_AGENT_PATH` as
`f"{DEFAULT_AGENT_ROOT}/demo/graph.py"` and `aef/harness/loop.py::cycle`
hardcoded `"agents/demo/graph.py"` outright. ADR 0147 claimed it had rebuilt
that constant from `DEFAULT_AGENT_ROOT` — and it had: it rebuilt the **root**
and kept the `demo`. `agents/demo/` is this repository's own fixture
directory and exists in no adopted repo.

### Reproduced first, RUN

A repo containing one raw-SDK agent, `aef adopt --dir .`, `aef migrate --dir
.`, commit. Nothing typed wrong, nothing omitted.

```
$ aef loop doctor --repo . --state loop-state --corpus corpus
  [--] reflect node routed to  no agent source at agents/demo/graph.py
  [--] blessed baseline        0 archived version(s)
       fix: aef loop bless --repo . --state loop-state --agent-path agents/demo/graph.py
  [--] model calls visible     no agent source at .../agents/demo/graph.py — nothing to scan
       fix: point --agent-path at the module that builds your graph; 'agents/demo/graph.py'
            is not a file under .

$ aef loop bless --repo . --state loop-state --agent-path agents/demo/graph.py
error: no agent source at agents/demo/graph.py in HEAD; nothing to bless.   exit=1
```

**The printed fix line cannot be run.** And with real failure memory present
and the base ref naming a commit that *does* contain
`agents/migrated/graph.py`:

```
$ aef loop cycle --repo . --state ../f2state --workdir ../f2work \
      --module agents.pol.graph --corpus corpus \
      --entrypoint agents.pol.graph:build_graph --memory ../f2state/memory.jsonl \
      --build-command true --base main
  preflight: 6 of 6 obligation(s) unmet (...)
  ledger verified: 0 entr(ies)
  no agent source at agents/demo/graph.py in main: no candidate            exit=0
```

**Exit 0 having done nothing** — ADR 0139's signature failure shape, reached
from the documented defaults. (The first run of this reproduction passed
`--base master` on a repo whose branch is `main`, which produces the same
line for a different reason; it was re-run against the real ref before being
believed. Stated because a reproduction that could have been an artefact of
the reproducer is not one.)

### Decision — where the shared constant lives, and why

`DEFAULT_AGENT_PATH = f"{DEFAULT_AGENT_ROOT}/migrated/graph.py"` moves into
**`aef/harness/zones.py`**, and `aef.cli.migrate.DEFAULT_MIGRATED_OUT`
becomes an alias for it. Both `aef/cli/loop.py` and `aef/harness/loop.py`
import it.

The alternative was to keep it in `aef/cli/migrate.py`, where
`DEFAULT_MIGRATED_OUT` already lived, and have the harness import that.
Rejected: **the harness does not import the CLI** — `preflight.py` says so
explicitly, and parses migrate's generated docstring rather than importing
`aef.cli.migrate` for exactly this reason. `zones.py` already owns
`DEFAULT_AGENT_ROOT`, is imported by both sides, and is the module that
answers "where is Zone A", which is the same question one segment deeper.
`DEFAULT_MIGRATED_OUT` keeps its name because `doctor`, `adopt`,
`adopt_loop`, `main` and the generated templates all read it.

The value is **what `aef migrate` writes**, because the default is read by a
repo that has run `adopt` then `migrate` and nothing else. That is the whole
content of the fix: one constant, so the writer and the default cannot
disagree.

### Evidence — after, same sequence

```
$ aef loop doctor --repo . --state ../f2astate --corpus corpus
  [OK] reflect node routed to  src_my_agent__run_agent() returns 'reflect' as its Route
  [--] blessed baseline        0 archived version(s)
       fix: aef loop bless --repo . --state ../f2astate --agent-path agents/migrated/graph.py
  [OK] model calls visible     1 reachable module(s), none imports a model SDK

$ aef loop bless --repo . --state ../f2astate --agent-path agents/migrated/graph.py
blessed agents/migrated/graph.py as baseline v1 for graph 'default'
$ find ../f2astate/archive -type f
  .../files/agents/README.md
  .../files/agents/migrated/graph.py

$ aef loop cycle ... --base main
  preflight: 4 of 6 obligation(s) unmet (corpus + tripwire, observations, halt channel,
    blessed baseline)
  the proposer produced nothing from the available evidence                exit=0
```

Two obligations go green that were red on identical evidence, the fix line
runs, and the cycle reaches the proposer. It still produces nothing, and that
is a **different, already-documented gap** — ADR 0139's requirement 2, a
module-level numeric constant the generated graph does not have. Not claimed
as closed here.

### The guard

`test_no_module_hardcodes_a_path_under_the_agent_root` AST-scans every module
under `aef/` for a module-level constant or a parameter default whose value
names a `.py` file under the agent root — **including the interpolated form**
`f"{DEFAULT_AGENT_ROOT}/…/x.py"`, because that is the exact shape the defect
took and a literal-only scan reads it as innocent. Exactly one site is
allowed. Prose is deliberately out of scope: help text and generated
documentation quote paths and globs by the dozen, and flagging those would
make the test noise. What is scanned is what a caller **silently gets**.

---

## F5 (medium) — `bless` accepts a Zone A symlink and archives the link target

### Context

ADR 0147's Confidence section: "a symlink inside Zone A pointing outside it
… was not tested." It is now, and it fails.

`_normalise` compares path spellings, and both sides of the containment check
come from `git ls-tree`, so a symlink passes it like any other entry.
`_zone_a_files` then does `git show <ref>:<path>`, and for mode `120000`
git's blob **is the link target string**.

### Reproduced first, RUN

```
$ git ls-tree -r HEAD
120000 blob 26a5ea3b…  agents/graph.py
100644 blob 4540fb49…  real/graph.py

$ aef loop bless --repo . --state ../f5state --agent-path agents/graph.py
blessed agents/graph.py as baseline v1 for graph 'default'
  G5 now has a reference point to measure drift against.               exit=0

$ cat ../f5state/archive/default/v000001/files/agents/graph.py
../real/graph.py
$ wc -c < ../f5state/archive/default/v000001/files/agents/graph.py
16
```

**The baseline contains the agent by name and none of it by content.** G5
measures every candidate's `structural_drift` against that, so every edit to
the real file is drift of zero and the file the loop is supposed to be
governing is not in the baseline at all.

The asymmetry is the seam: `aef/harness/candidate.py`'s `ESCAPE_MODES` already
treats a Zone A symlink or gitlink as a **security event** rather than a
rejection when a candidate ADDS one. Deny it landing, accept it as the thing
everything is measured against.

### Decision

`bless` refuses when the tree it would archive holds any entry git records in
`ESCAPE_MODES`, naming the paths and their kinds and pointing at the two real
remedies (replace with the file, or `--agent-root`). The list is **imported
from `candidate.py`, not re-written** — two lists of what counts as an escape
drifting apart is the ADR 0091 shape, and this pair had already drifted once.
`_zone_a_escapes` reads `ls-tree -r` rather than `list_tree`, because the mode
is the whole question and `list_tree` asks only for names.

The refusal goes after the existence, empty-tree and containment checks: "your
agent is not committed", "you have no Zone A", "your agent is somewhere else"
and "your agent is a link" are four problems with four remedies, and folding
any pair together loses the one an owner needs.

### Evidence — after

```
$ aef loop bless --repo . --state ../f5state --agent-path agents/graph.py
error: 'agents' at HEAD holds 1 entr(ies) git records as a symlink or submodule,
not a regular file: agents/graph.py (symlink). A baseline archives what `git show`
returns, and for those that is the LINK TARGET — so blessing here would record the
agent by name and none of it by content ...                             exit=1
$ ls ../f5state
ls: ../f5state: No such file or directory
```

Nothing archived, asserted in the test through `archive.versions(...) == ()`
rather than through the printed line.

---

## F6 (medium) — three call sites, one reachable node, and a report that says nothing

### Reproduced first, RUN

A repo with three raw-SDK call sites (`src/zeta.py`, `src/alpha.py`,
`src/middle.py`):

```
$ aef migrate --dir .
found 3 call site(s): 3 wrapped, 0 skipped
  ROUTED   src.alpha.run_alpha:4    ...
  ROUTED   src.middle.run_middle:4  ...
  ROUTED   src.zeta.run_zeta:4      ...
build_graph() wires <call site> -> reflect -> consolidate -> END.

$ grep entry_node agents/migrated/graph.py
        entry_node="src_alpha__run_alpha",

$ <executed with a stub provider>
nodes declared:  ['consolidate', 'reflect', 'src_alpha__run_alpha',
                  'src_middle__run_middle', 'src_zeta__run_zeta']
warnings from compile+run: []
node_path actually executed: ['src_alpha__run_alpha', 'reflect', 'consolidate']
```

Two of the three nodes never run. **Nothing anywhere says so**: the executor
emits no warning for a declared-but-unreachable node, `classify()` builds
`node_path` from the trace so G2 never sees them, and the report's sentence
was singular for any number of call sites. The entry is `node_ids[0]` — the
first call site the scan found, effectively alphabetical — not a node
anything chose.

### Decision

**Fix the report, not the graph.** The report is the surface an adopter reads
while migrating, and it is the only place this fact can arrive in time.
Choosing an edge order would be worse: how three call sites compose —
sequence, branch, or one entry that never calls the others — is a semantic
decision, nothing in the source says which, and a guessed order would be
silently wrong in a file the adopter is told is plumbing.

So the report names the entry node, lists every unreached one, and says the
composition is the half migrate will not do:

```
build_graph() wires src_alpha__run_alpha -> reflect -> consolidate -> END.
...
ONLY src_alpha__run_alpha RUNS. The other 2 generated node(s) are
declared, routed to reflect, and UNREACHABLE — a graph has one entry
and nothing reaches them from it:
  UNREACHED  src_middle__run_middle
  UNREACHED  src_zeta__run_zeta

This is the half of the migration that is yours. How your call sites
compose ... is a semantic decision, and nothing in your source says which; the
entry above is simply the first call site found. Nothing warns you
later: the executor runs an unreachable node zero times without
complaining, and the gates score only the path the trace took, so a
corpus recorded now pins the entry node alone. ...
```

The node id is computed by `node_id_for(site)`, **one function read by both
`render` and `report`**, so the report cannot name a node the graph does not
have. `test_the_reports_entry_node_is_the_graphs_entry_node` builds the real
generated module and compares. A single call site prints none of this — a
paragraph about dead nodes where there are none teaches adopters to skip it,
and that is its own test.

---

## F7 (low) — which error `build_run_config` reports first

### Reproduced first, RUN

One `aef.yaml` with two faults: `model_provider.fallback: ["openai"]` (no
adapter) and `evaluator.suites: ["nosuch.module:gate"]` (unimportable).

```
NEW first error: DomainGateError : evaluator suite 'nosuch.module:gate':
                 cannot import 'nosuch.module' (No module named 'nosuch')
OLD first error: UnsupportedProviderImplError : no ModelProvider adapter for
                 impl='openai' yet; only ('claude_code', 'codex', 'anthropic')
```

`git show 3320852:aef/cli/run.py` confirms the old order:
`build_model_provider` at line 124, `build_domain_gates` at line 133.
Extracting `build_run_config` (ADR 0145) reversed it, and nobody decided to.

### Decision

**Keep the new order and pin it: validate before constructing.**
`build_domain_gates` resolves names and builds nothing; `build_model_provider`
constructs a live provider object and, for `impl: anthropic`, imports a vendor
SDK to do it. The cheap, local, purely-declarative failure is the better one
to report first. `test_build_run_config_reports_the_evaluator_before_the
_provider` pins it, with `test_the_provider_error_still_arrives_when_the
_evaluator_is_fine` as the control that the reordering did not make the
second fault unreachable. The point is not that this order is obviously
right — it is that it stops being whichever statement a refactor leaves on
top.

---

## Mutations — 11 planted, 10 caught, 1 missed by design

Baseline: the five affected test files, 127 tests. Every mutation was
restored by copying back a file whose SHA-1 was recorded before the round and
re-checked after (`git checkout --` would have destroyed uncommitted work —
`INGEST_LOOP.md`'s rule). The driver asserted the anchor was present before
each substitution and that the file changed after, so a mutation cannot
silently no-op.

```
BASELINE                                                            127 passed
M1   record goes back to its own construction site        3 failed, 124 passed
M2   record calls build_run_config but drops the policy   2 failed, 125 passed
M3   score keeps its private parse of aef.yaml            1 failed, 126 passed
M4a  the ONE constant is renamed to `demo`                     127 passed (MISSED)
M4b  migrate's writer forks into a second derivation      2 failed, 125 passed
M5   a second hardcoded agent path comes back             2 failed, 125 passed
M6   bless stops refusing a Zone A symlink                1 failed, 126 passed
M7   the escape refusal is too broad                      6 failed, 121 passed
M8   the report stops naming the unreached nodes          2 failed, 125 passed
M9   the report names a different entry than build_graph  2 failed, 125 passed
M10  the provider is constructed before the evaluator     1 failed, 126 passed
AFTER                                                               127 passed
```

Three are worth naming.

**M2 is the control on the AST test.** `cmd_record` still calls
`build_run_config` — the source assertion is satisfied — and simply does not
pass `policy=`. The generalised AST test passes; the two behavioural tests
fail. A source assertion cannot see a dropped keyword argument, which is why
the behavioural comparison had to exist.

**M7 is the control on the F5 fix.** A refusal that is too broad refuses every
correct blessing, which is the failure mode a hasty version of this ships. Six
tests fail, including `test_bless_still_accepts_a_regular_file`.

**M4a was MISSED, and it should be.** Renaming the single constant to
`agents/demo/graph.py` makes the CLI, `migrate` and the harness all point at
`agents/demo/graph.py` together — ugly, but *consistent*, and there is no
disagreement left to detect. The defect was never the string; it was two
constants for one fact. M4b plants that instead, forking `DEFAULT_MIGRATED_OUT`
into a second derivation, and it is caught by both F2 tests. Reported here
rather than quietly dropped, because a mutation round that only lists its
successes is not evidence.

## Green bar

```
pytest -q          1973 passed, 17 skipped   (1990 collected, from 1976; +14, none removed)
mypy aef examples  no issues in 129 source files
ruff check .       All checks passed
ruff format --check aef tests examples   241 files already formatted
model calls made   0 — no live model call anywhere in this wave
```

Baseline collection count read by exporting `HEAD` with `git archive` into a
scratch tree and running `pytest --collect-only` there, rather than asserted.

## Consequences

- **A corpus recorded by `aef loop record --config` before this change may be
  wrong**, and nothing detects that retroactively. If it pinned a tool call
  the adopter's `aef.yaml` allows, it pinned a denial; if it was labelled
  `must_fail` on that basis, it is a tripwire the gates will hit forever.
  Re-record, or read the scenario's first delta and check whether the
  decisions match the config.
- **`aef loop score --config` now validates `evaluator.suites`** and builds
  the model provider whether or not `--cassette-miss live` is passed. The
  provider construction reads no credential for any of the three impls, so
  the practical change is that a config whose suites do not resolve now fails
  before the corpus is scored instead of after. A repo configured
  `impl: anthropic` without the optional extra installed will now see the
  import error here; it could not have run `aef run --config` either.
- **`--agent-root` still moves Zone A**, and the new default follows it
  nowhere: `DEFAULT_AGENT_PATH` is built from the default root. A repo that
  moves its agent root passes `--agent-path` as it did before, and the bless
  refusal names `agent_root` rather than a spelled tree.
- **Multi-call-site migration is still a manual composition step.** F6 fixed
  the report, not the graph, and the report now says so. An adopter who reads
  it and does nothing has the same single reachable node as before.
- **`agents/demo/` is no longer named by any default**, so this repo's own
  fixture agent is reached only by naming it. Nothing here changes the fixture.

## Confidence

**High** on all five reproductions: every command above was run against a
repo built for the reproduction, before and after, and the F1 chain was
carried all the way to `tripwire_hit = True` through the gates' own
`run_scenario` and `Comparison`, not inferred.

**High** on F1's fix, because the two tests fail for different reasons under
different mutations (M1 the construction site, M2 the dropped argument), so
neither is carrying the other.

**Medium** on the F2 guard's completeness. It scans module-level constants and
parameter defaults, which is where both instances of this defect lived; a
default computed at runtime, or assembled by `Path(...) / ...`, is invisible
to it and would need the behavioural test to catch it. The behavioural test
covers `aef migrate`'s own output and nothing else.

**Medium** on F5's scope. It refuses escape modes anywhere in the archived
tree, which is stronger than refusing them only at the agent path and matches
`check_modes`; whether an existing baseline somewhere already holds a link
target is **not measured** and nothing detects it retroactively — re-blessing
is rate-limited and owner-only by design (G5, ADR 0053).

**Low**, unchanged, on anything this says about a repo nobody wrote to be
scanned. Every fixture here was authored by this programme, which is
`READY_LOOP.md` K5's point and is still open.

---

## Errata to earlier ADRs

### ADR 0145 — "one construction site, two commands" covered one of two callers

Its Decision section says the private construction is replaced and
"both commands read the config here or not at all", and its Consequences say
"`aef run` and `aef loop bootstrap` cannot configure differently any more".
Both sentences are true and both are narrower than they read. **Three**
commands in `aef/cli/loop.py` read `--config` into services — `record`,
`bootstrap` and `score` — and 0145 changed one of them.

`test_bootstrap_reads_its_config_through_aef_runs_construction_site` was
written against `cmd_bootstrap` by name, and applying it verbatim to
`cmd_record` FAILED. The consequence 0145 correctly describes for a
bootstrap-made corpus — "a corpus recorded before this change under a
non-default `require_hitl_above_risk` pins behaviour the adopter's own runtime
does not have" — was still true of every `record`-made corpus the day it
shipped, including every tripwire, which is where it costs the most. That test
is now generalised over the parser's own list of `--config` commands (F1
above).

### ADR 0147 — the "last literal" and the untested symlink

Two corrections.

**The `DEFAULT_AGENT_PATH` claim.** 0147's Decision says
"`aef/cli/loop.py`'s `DEFAULT_AGENT_PATH` — the last place in that file that
spelled `agents` — is built from `DEFAULT_AGENT_ROOT` too." What was built
from `DEFAULT_AGENT_ROOT` was the ROOT; the rest of the path,
`demo/graph.py`, stayed spelled out, and it names this repository's own
fixture directory. `aef/harness/loop.py::cycle` still hardcoded
`"agents/demo/graph.py"` in full and 0147 does not mention it. The literal
that mattered was not the one removed (F2 above).

**The symlink.** 0147's Confidence says: "The check compares an agent path
against the file list of one tree at one ref; a symlink inside Zone A
pointing outside it … was not tested. Neither arises from `git ls-tree`
output, which is where both sides come from, but neither was run." The second
sentence is wrong on both halves. A symlink **does** arise from `git ls-tree`
output — as mode `120000` with the link target as its blob — and the case is
now run: `bless` accepted it and archived 16 bytes of `../real/graph.py` as
the baseline (F5 above). The reasoning that made it look safe is exactly the
reason it was not: both sides coming from `git ls-tree` is what makes a
symlink pass a containment check that compares names.


---

## Erratum on THIS ADR, added by ADR 0168 (fix wave G1b)

F2's Decision put one string behind every `--agent-path` default, and that
part holds. But the docstring it wrote onto `aef/cli/doctor.py::_graph_entries`
claimed more than derivation can buy:

> Every path here is derived from `DEFAULT_AGENT_ROOT` via `aef.cli.migrate`,
> so moving the agent root or migrate's default cannot leave this list naming a
> directory nothing writes to.

**True for one writer; false the day there were two.** ADR 0152 added a second
— one graph per prompt agent at `<agent root>/migrated/<module>/graph.py` —
while the glob here stayed `<agent root>/*/graph.py`, one level. Derivation kept
the ROOT correct and says nothing about the DEPTH.

Reproduced on the pilot clone with **nine** graphs on disk: `aef doctor` listed
two entries and obligation 6 passed on `agents/migrated/graph.py`, the call-site
stub whose `build_graph()` raises `NotImplementedError` and which makes no model
call at all. The eight graphs that do make one were never opened (ADR 0168, F3).

A shared constant proves that two names spell one string. It cannot prove that a
glob matches what another command writes — only running one into the other can.
Discovery is now one function (`aef.harness.zones.discover_graph_files`) and the
invariant is enforced behaviourally, by running the real `run_migrate` into the
real `_graph_entries` and asserting doctor's list contains every graph migrate
reported writing.
