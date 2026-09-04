# ADR 0143: `aef migrate` writes into Zone A, and wires the loop it generates

## Status
Accepted. Increments **L1** and **L2** of `INGEST_LOOP.md`; recorded in
`IMPROVE_LOG.md`. **No rubric dimension moves** — this is adoption readiness,
not a scoring claim, and the score stays 86.

Both defects were measured by ADR 0139 (K3) and both were left there: L1
because it lived outside K3's file scope, and again in fix wave E (ADR 0142),
which could only change what `aef adopt` *says* because `migrate.py` belonged
to another worker that night. This closes both, in the command rather than in
the documentation.

## Context

`aef migrate` does the mechanical half of converting an adopting repo's model
call sites into nodes. ADR 0139 measured the four things that make
`aef loop cycle` **exit 0 having done nothing** in a freshly adopted repo.
Two of them are properties of what `migrate` itself writes:

1. **It wrote to the repo root, which is Zone C.** `run_migrate` hardcoded
   `out = root / "aef_migrated.py"`. The repo root is the one tree the loop
   is structurally forbidden to propose changes to, and neither the command's
   report nor anything `aef adopt` generated said so.
2. **The graph it generated had one node routed to `END`.** Nothing wrote
   failure memory; the proposer reads failure memory and nothing else; so the
   cycle went quiet, with exit 0, which reads as success.

Everything else about the command was already careful — a falsification
clause it honours (ADR 0137), a routable predicate derived from the request
type (ADR 0140), a `--force` that preserves an edited file. The output landed
somewhere the loop could never use, and did nothing when it ran.

## Decision

### L1 — an `--out`, defaulting inside Zone A

`aef/cli/migrate.py` gains two module-level constants and a threaded flag:

```python
DEFAULT_MIGRATED_OUT = f"{DEFAULT_AGENT_ROOT}/migrated/graph.py"
LEGACY_MIGRATED_OUT = "aef_migrated.py"
```

`DEFAULT_MIGRATED_OUT` is **derived from `aef.harness.zones.DEFAULT_AGENT_ROOT`,
never spelled out**, and it is the single place that answers "where does the
generated graph go". `aef/cli/doctor.py`, `aef/cli/adopt.py` and
`aef/cli/adopt_loop.py` all import it rather than re-deriving; a test fails if
a literal replaces the derivation. A second hardcoded `agents` is the drift
ADR 0091 is about, and the repo root was that drift's most expensive form.

`run_migrate(..., out=None)` resolves a relative `--out` against the repo root
and an absolute one as given, **creates parent directories**, and keeps ADR
0140's two rules — never overwrite, and `--force` backs up a file that differs
— against whatever path `out` names rather than against one hardcoded name.

`report()` now names the **zone** of the path it wrote, answered by
`zones.inspect_path` — the classifier G0 itself uses — rather than by a string
comparison. Writing into Zone C is still possible and is still reported as
what it costs, in the gate's own words, at the moment of writing rather than
at the end of a cycle three commands later.

`LEGACY_MIGRATED_OUT` is a **named** constant, not a stray literal: a repo
migrated before this ADR keeps a root-level `aef_migrated.py`, and dropping it
from `aef doctor`'s discovery would have silently stopped the model-call
advisory firing there. That is exactly the shape of the defect ADR 0141 fixed
in the other direction, so it is not repeated.

**No `__init__.py` is generated, and that is measured rather than assumed.**
The instruction was to check. Five layouts were built and imported as
`agents.migrated.graph` — no `__init__.py` anywhere, `agents/__init__.py`
only, `agents/migrated/__init__.py` only, both, and both alongside a sibling
regular package — and all five imported cleanly (Python's namespace packages).
So `migrate` creates directories and nothing else; the whole K3 sequence,
including `aef run agents.migrated.graph`, then runs against a tree with no
`__init__.py` in it.

### L2 — the generated graph is wired to learn

`build_graph()` now emits `<call site> -> reflect -> consolidate -> END`,
exactly the shape `agents/summary/graph.py` uses: every generated node's route
changes from `END` to `"reflect"`, each gets an `Edge` to it,
`make_reflect_node(route="consolidate")` and `make_consolidate_node(route=END)`
join the node map. Only the entry node is reached automatically; with more
than one call site the rest are declared, routed and unreachable, which the
generated docstring says, because how an adopter's call sites compose is a
semantic decision this command has no basis to make.

The generated module docstring, `build_graph`'s own docstring and the CLI
report all state the thing that is otherwise invisible: **this tail is what
makes the repo learn, and removing it makes the loop silently inert** — not
an error, `exit 0` with `no admissible failure memory: no candidate this
cycle`, every cycle.

### L2's falsification clause, honoured

> *if wiring reflect changes what the node returns to an adopter's caller, or
> breaks the single-node graphs the current tests pin, that is a documented
> trade — do it and say what changed, or don't and say why.*

**The node's return value to the caller does not change**, and this is
measured rather than argued (below): the same generated node under identical
inputs leaves the same answer in `state.working_memory["<node id>"]`, byte for
byte, with and without the tail.

**What does change is the `Services` the graph requires**, and the tail is
shipped anyway with the change stated in three places:

```
route END       bare Services()  -> OK, answer='a stubbed answer'
reflect wired   bare Services()  -> ServiceNotConfiguredError: service 'critic'
                                    was not configured on this Services container
```

Reflect needs `critic`, `judge` and `memory`; consolidate needs `knowledge`.
`aef.services.runtime.agent_services()` defaults all four, so `aef run`,
`aef loop bootstrap`, `aef loop cycle` and every gate re-execution are
unaffected — which is why the K3 end-to-end sequence runs unchanged. A caller
who hand-builds `Services(model_provider=...)` and executes the generated
graph gets `ServiceNotConfiguredError` where it previously ran. That is a real
break in the adapter's contract with such a caller, it is stated in the
generated `build_graph` docstring and in the report, and a test pins both
halves of it.

The trade was taken rather than refused because the alternative is a
generator whose entire output is inert in the system it generates for: without
the tail the file `aef migrate` writes can never produce a candidate, and the
failure mode is a green light. **No test pinned a single-node generated
graph**; `test_both_generated_forms_are_importable` asserts
`graph.entry_node in graph.nodes`, which the wired graph satisfies.

## Evidence — reproduced by RUNNING, before anything changed

All commands from the worktree; `PYTHONPATH=$PWD`, `python` = the repo venv.
**Zero model calls.**

### L1 reproduced — the generated file is in the one tree the loop cannot touch

`scratchpad/repro_l1.py`: fresh `git init`, one 8-line raw-SDK agent,
`aef adopt`, `aef migrate --dir .`, commit, then a candidate branch whose only
change is one line appended to the generated file, run through the harness's
own `inspect_candidate`:

```
$ aef migrate --dir .
  ROUTED   src.my_agent.run_agent:4  (anthropic.Anthropic)
wrote .../l1repo/aef_migrated.py
EXIT=0

files matching *.py at the repo ROOT: ['aef_adapter.py', 'aef_migrated.py']
does agents/migrated/graph.py exist?  False

$ inspect_candidate(repo, base, loop/candidate)
  changed paths: ('aef_migrated.py',)
  allowed: False
  REJECT: aef_migrated.py: Zone C (core) — not under the agent root 'agents';
          only Zone A is agent-writable
```

The report says nothing about any of it.

### L1 after

Same script against the changed command (`scratchpad/after_l1_l2.py`):

```
$ aef migrate --dir .
wrote .../afterrepo/agents/migrated/graph.py
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop
  may propose changes to

files matching *.py at the repo ROOT: ['aef_adapter.py']
agents/migrated/graph.py exists: True
__init__.py written anywhere under agents/: []

$ inspect_candidate(repo, base, loop/candidate)
  changed paths: ('agents/migrated/graph.py',)
  allowed: True
   agents/migrated/graph.py: Zone A (agent-writable)
```

### L2 reproduced — one node, routed to END, and a cycle that says so

`scratchpad/repro_l2.py`, same fixture:

```
$ build_graph() from the generated module
  nodes : ['src_my_agent__run_agent']
  edges : []
  entry : src_my_agent__run_agent
  routes in the generated source:
    return StateDelta(working_memory={key: result.content}), END
  "reflect" appears in the generated source: False
  make_reflect_node imported: False

$ aef run aef_migrated --memory <state>/memory.jsonl
  EXIT= 1
  stderr: service 'model_provider' was not configured ...
  memory.jsonl exists: False

$ aef loop cycle --memory <state>/memory.jsonl
preflight: 5 of 6 obligation(s) unmet (corpus + tripwire, reflect node routed
  to, observations, halt channel, blessed baseline). ADVISORY ...
  ledger verified: 0 entr(ies)
  no admissible failure memory: no candidate this cycle
  EXIT= 0
```

**Exit 0, having done nothing** — ADR 0139's signature failure shape, arrived
at from the generator's side this time.

### L2 measured — the tail writes the memory the proposer reads

`aef run` cannot show this without a credential (the routed node asks for a
model provider and the run aborts before reaching reflect — quoted above). So
the graph was **executed** with a stub provider and a durable
`FileMemoryStore`, once with the tail and once with the route mutated back to
`END`, everything else identical (`scratchpad/l2_memory_proof.py`, and the
same measurement as `test_the_reflect_tail_actually_writes_failure_memory`):

```
route END (before)       nodes=['src_my_agent__ask']
                         answer in working_memory: 'a stubbed answer'
                         memory.jsonl records=0 kinds=[]

reflect wired (after)    nodes=['consolidate', 'reflect', 'src_my_agent__ask']
                         answer in working_memory: 'a stubbed answer'
                         memory.jsonl records=1 kinds=['success']
```

**0 records -> 1 record, and the caller's answer is unchanged.** That second
line is the falsification clause answered with a measurement.

### K3's end-to-end test — what was deleted, and what remains

`test_an_adopted_repo_gates_a_candidate_end_to_end` now gates **migrate's own
output**, at migrate's own path, with migrate's own wiring.

**Deleted** (all four were hand-written before):

- the whole `MINIMUM_AGENT` graph module hand-placed at `agents/mine/graph.py`;
- its `from aef.reasoning.nodes import make_reflect_node`,
  `make_reflect_node(route=END)` and `Edge(from_node="work", to_node="reflect")`
  — **the test no longer writes an `Edge`, a reflect node, or a route anywhere**;
- the hand-created `agents/__init__.py` and `agents/mine/__init__.py`, measured
  unnecessary above;
- the hand-chosen Zone A location — the agent path is now `DEFAULT_MIGRATED_OUT`,
  and the test asserts its zone with `zones.inspect_path`, the classifier G0 uses.

**Kept, because they are still genuinely the adopter's:**

- the **two module-level numeric constants** (`RETRY_BUDGET`,
  `QUALITY_THRESHOLD`) — ADR 0139's item 2, the shape `RuleBasedProposer`
  mutates. A generated wrapper has no number of its own to invent;
- a **node body that can fail without a credential** — item 4 needs a *failing*
  run and this sequence has none. The test replaces migrate's routed body,
  verbatim and with before/after assertions on every substitution, and asserts
  `services.require_model_provider().complete(` is gone;
- the **failing `aef run --memory`**, the **tripwire line run verbatim** from
  bootstrap's own output, `bless`, `doctor`, `--entrypoint`, and
  `tests/test_smoke.py` for G1's build command;
- **step 2 unchanged** — bootstrapping the migrated, model-calling graph still
  exits 1 with `no live provider to fall through to`, which is why the body has
  to be replaced at all.

The gate assertions are unchanged and were **strengthened**, not relaxed: the
verdict is read from `ledger.jsonl` (`"rejected" in kinds`,
`"accepted" not in kinds`, `gates["G3"]["outcome"] == "fail"`) rather than from
the CLI line. A test demanding an acceptance could be satisfied by weakening G3.

Its ledger, run:

```
GATED summary: ran G0, G1, G4, G5, G2, G3; passed=False
  G0 pass  1 file(s), 28 line(s), all Zone A, no static-safety violations
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.098/0.500 from the blessed baseline
  G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
  G3 fail  candidate does not beat the p95 of the random control cohort —
           this is the null hypothesis, not an improvement
evidence: 7 corpus pass(es) (35 scenario execution(s)): 1 candidate + 1
          incumbent + 5 random control(s); corpus records one graph
          ('adoptee'); gating all 5 gated scenario(s)
rejected - G3 rejected it: ...
```

`G0 pass ... all Zone A` is L1's whole point, arrived at by the gate rather
than asserted here. Drift is 0.098/0.500 against 0.024 for the old
hand-written agent — the generated file is larger, and the headroom is still
80%.

### Surfaces updated, every one derived rather than spelled out

| Surface | Before | After |
|---|---|---|
| `run_migrate` | `out = root / "aef_migrated.py"` | `--out`, default `DEFAULT_MIGRATED_OUT`, parents created |
| `report()` | said nothing about the zone | names it, via `zones.inspect_path` |
| `aef migrate --force` help | "overwrite an existing aef_migrated.py" | names the `.bak` behaviour, no filename |
| `aef doctor --agent-path` help | listed `aef_migrated.py` | lists `DEFAULT_MIGRATED_OUT`, the agent-root glob, and `LEGACY_MIGRATED_OUT` as the pre-0143 path |
| `doctor._graph_entries` | literal `"aef_migrated.py"` at the root | `DEFAULT_MIGRATED_OUT` + `LEGACY_MIGRATED_OUT`, deduped against the glob |
| generated `CLAUDE.md`/`AGENTS.md` | "it writes `aef_migrated.py` to the repo **root**" | writes to `{DEFAULT_MIGRATED_OUT}`, with the old behaviour kept as the reason to check an older graph |
| migration checklist | same claim | same correction |
| generated `LOOP.md` items 1 and 3 | the adopter's job | annotated: migrate does these now |
| generated `LOOP.md` paragraph | "`aef migrate` writes none of the first four" | "writes two of the first four", and why it cannot write items 2 and 4 |

## Mutations — 11 planted, 11 caught, every one reverted

Each perturbs a production value, runs the five CLI test modules, and is
restored from a byte-identical backup verified with `shasum` (never
`git checkout --`; a worker lost a pass to that).

```
BASELINE                                                        149 passed
CAUGHT  M1  the default output goes back to the repo root         6 failed
CAUGHT  M2  --out is accepted and ignored                         4 failed
CAUGHT  M3  parent directories are no longer created             11 failed, 2 errors
CAUGHT  M4  report() stops naming the zone                        4 failed
CAUGHT  M5  the routed node routes to END again                   4 failed
CAUGHT  M6  build_graph drops the reflect/consolidate tail        6 failed
CAUGHT  M7  doctor stops discovering migrate's output             3 failed
CAUGHT  M8  doctor forgets the pre-0143 output path               3 failed
CAUGHT  M9  the generated docstring drops the silent warning      1 failed
CAUGHT  M10 LOOP.md claims migrate writes none of the four        1 failed
CAUGHT  M11 the checklist stops naming migrate's output path      1 failed
REVERTED                                                        149 passed
```

M8 is the control for `LEGACY_MIGRATED_OUT`: without it the constant could be
deleted as dead weight and nobody would notice until an older adopter's
advisory went quiet.

## A defect found on the way, fixed here

The generated `LOOP.md` said **"Add `__pycache__/` to `.gitignore` before you
bless. `aef adopt` does not write one."** ADR 0142 made `aef adopt` write one
five hours earlier and did not update this file, so the scaffold's own
document contradicted the scaffold. Corrected to what is true and is the part
that still matters: adopt writes one, **skips an existing `.gitignore` rather
than appending to it**, and says so in the checklist — so a repo that already
had a `.gitignore` may still be missing the pattern. The measured drift
numbers stay, and the test pinning them is unchanged.

## Wrong predictions, recorded as wrong

1. **I expected the generated packages to need `__init__.py`.** The task said
   check rather than assume, and checking was the right instruction: five
   layouts, all five imported, and the K3 sequence then ran end to end against
   a tree with none. Writing them would have been scaffold nobody needs, in
   Zone A, from a command that had not been asked for it.
2. **I expected K3's hand-written agent to disappear entirely.** It did not.
   L1 and L2 remove *placement* and *wiring*; items 2 and 4 of the measured
   minimum are semantics, and a migrated model-calling node cannot supply a
   credential-free failing run. What the test hand-writes is now exactly the
   half migrate's own report has always said is yours — which is a smaller and
   more honest claim than "no hand-written node", and definition-of-done
   statement 1 is not yet true.
3. **I expected wiring reflect to be free.** It is not: it moves four services
   from optional to required for anyone hand-building `Services`. Measured,
   shipped, and stated in the generated file rather than discovered later.

## Consequences

- **`aef migrate`'s output is now inside the loop's blast radius on purpose.**
  A candidate touching it is a proposal rather than a rejection, and
  `aef loop bless --agent-path <migrate's output>` archives a tree that
  contains it.
- **The generated graph produces evidence.** The one thing the proposer reads
  is written by every run of it.
- **Two of ADR 0139's four minimum items move from the adopter to the tool**,
  and the generated `LOOP.md` says which two remain and why neither is an
  oversight (a wrapper has no constant of its own; ADR 0060 forbids inventing
  a failure).
- **`aef loop bless` is still wrong in the way K3 reported** — it checks
  `path_exists_at(ref, agent_path)` and then archives the Zone A tree, two
  different questions. L1 makes it harder to reach and does not fix it; that
  is L5 (`aef/harness/preflight.py`, another worker's file tonight).
- **The generated file carries two now-unused imports** in the K3 test's
  patched copy (`CompletionRequest`, `ProviderMessage`), because the test
  replaces the body and not the header. Harmless — G1 runs `pytest`, not
  `ruff` — and named here rather than found later.

## Confidence

**High** on both reproductions and both fixes. Each was run before and after,
against the harness's own classifier and the harness's own executor rather
than against a mock; each is pinned by a test; each test has a mutation behind
it; and the K3 end-to-end sequence goes from `git init` to six executing gates
with the changed command in the middle.

**High** on the anti-drift derivation. `DEFAULT_MIGRATED_OUT` is computed from
`DEFAULT_AGENT_ROOT`, a test fails if a literal replaces it, and every
document that names the path interpolates the constant.

**Medium** on the `Services` trade being the right call. It is a real break
for a caller who builds `Services` by hand, it is not detectable at import
time, and the only mitigation shipped is documentation in three places plus a
test. The measurement says every path *this repo* drives goes through
`agent_services`; a repo that does not was not run.

**Medium** on multi-call-site repos. Every generated node routes to `reflect`
and gets an edge, but only the entry node is reached — as before this change,
where `edges=[]` left every node but the entry unreachable too. Nothing here
makes a two-call-site migration *worse*, and nothing here makes it work; that
is the semantic decision the command refuses to make and the generated
docstring now says so out loud.

**Low**, unchanged, on anything this says about a repo nobody wrote to be
scanned. The adoptee is still a fixture this repo authored. That is
`READY_LOOP.md` K5 and no test here closes it.
