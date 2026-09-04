# ADR 0141: The obligation and the guards

## Status

Accepted. Fix wave D of the ready loop — the seam hunt of the K1/K2 merge
(`c2d14b1`, `ca572ea`). Eight findings, every one reproduced by running a
command before anything was changed, plus one suspected item confirmed as a
narrower defect than it was reported as. **No rubric dimension moves**; this
wave repairs claims and guards, it does not add capability.

Two of the findings make sentences in ADRs 0137 and 0138 **false as written**.
Both ADRs get an erratum; neither is rewritten, because they are dated records.

## Context

Three of ten defects in this program lived in seams. This wave is four seams
and four guards, and the pattern in all eight is the same one CLAUDE.md names:
a control that reads as present and is not. A vendor list that answers the
wrong question. A fix string that loops. A kill switch whose enforcement the
caller opts into. A rate limit charged to the wrong command. A readiness flag
nothing reads. An advisory keyed on the artefact of a different command. A
never-shrinks ledger nobody writes and nobody checks.

## Reproduced first — every command, with its output

`PYTHONPATH` and the venv elided from every invocation below.

### R9 — obligation 6 used the constraint #3 list, and ADR 0137's claim about it was false

A repo whose graph reaches a module doing `import psycopg2`:

```
$ cat .scratch/s6/mygraph.py
from db import fetch
$ cat .scratch/s6/db.py
import psycopg2
from opentelemetry import trace
from google.cloud import storage
...

>>> model_calls_are_visible(Path(".scratch/s6"), "mygraph.py")
(False, 'db.py:1 imports psycopg2 (+2 more) — the harness cannot see it')
```

The obligation calls `scan_file`, which defaults to `VENDOR_TOP_LEVEL_MODULES`
(19 names). `aef migrate` correctly uses `MODEL_SDK_ROOTS` (5). So a Postgres
driver, an OTel exporter, a Neo4j client and a Temporal SDK each blocked the
adopter permanently, and the printed fix told them to route a database
connection through `services.require_model_provider().complete(...)`.

**ADR 0137 states, under Confidence: "It over-reports nothing (a false positive
requires a real vendor import in a real reachable file)."** It over-reports on
14 of the 19 names — every one that is not a model SDK.

### R4 — the fix string does not fix it, and loops forever

`.scratch/s5` is the adoptee ADR 0137's falsification clause deliberately
creates: a function whose body is a retry loop, so `aef migrate` refuses to
route it and generates the unrouted wrapper.

```
$ aef loop doctor --repo . --state ../s5-state --corpus corpus \
      --agent-path aef_migrated.py
  [--] model calls visible     src/my_agent.py:3 imports anthropic — the harness cannot see it
       fix: aef migrate --dir . --force. Route the call through the container: ...
EXIT=1

$ aef migrate --dir . --force
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 0 routed through Services.model_provider, 1 still calling your function
  WRAPPED  src.my_agent.run_agent:6  (anthropic.Anthropic)
            NOT routed because its body loops — a retry, backoff or pagination policy ...

$ aef loop doctor ...      # the printed fix, run
  [--] model calls visible     src/my_agent.py:3 imports anthropic — the harness cannot see it
       fix: aef migrate --dir . --force. ...
```

Byte-identical. The only real remedy — hand-route the node body **and** delete
the `from src.my_agent import run_agent` line that keeps the module in the
reachable set — is stated nowhere, and the second half is stated nowhere at all.

### R5 — the kill switch is bypassed by omitting `--state`, which is the documented invocation

```
$ cat state/HALTED
G6 tripwire fired -- loop halted by the harness

$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json --state state
HALTED: the self-rewiring loop is halted: G6 tripwire fired ...
EXIT=2 ;  corpus/train: 0

$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json
recorded 2 scenario(s) in the train split
EXIT=0 ;  corpus/train: 2
```

`cmd_bootstrap` read `if getattr(args, "state", None):` — a guard whose
enforcement is opt-in by the caller, on a flag ADR 0138 made optional. **ADR
0138's own Evidence block shows the command without `--state`.** `cmd_harvest`
gets this right because `--state` is required there.

### R6 — bootstrap silently exhausts harvest's daily rate limit

`READY_LOOP.md`'s K5 pilot sequence is adopt → bootstrap → run for real →
harvest. Run exactly that:

```
$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json   # 12 inputs
recorded 12 scenario(s) in the train split
corpus/train: 12

$ aef loop harvest agents.mine.graph --runs state/runs --corpus corpus --state state
promoted 0 run(s) to the train split
  3 held back by the daily rate limit: 0678ebaf-..., 11971617-..., 433adbf5-...
EXIT=0 ;  corpus/train: 12
```

Every real production failure dropped, exit 0, and the message names a rule
with no arithmetic — a run held back by a budget something *else* consumed
reads exactly like one held back by harvest's own volume. `already_today`
counted every scenario with `recorded_at > cutoff`; `bootstrap` stamps
`recorded_at = now` on all of its.

### R7 — nothing consumes `Preflight.ready`, and ADR 0137's claim about it is false

```
$ grep -rn "\.ready\b\|preflight(" aef/
aef/cli/loop.py:692:    result = preflight(
aef/cli/loop.py:702:    return EXIT_OK if result.ready else EXIT_REJECTED
aef/harness/preflight.py:65:            if self.ready
```

One reader: `cmd_doctor`. On the same repo, in sequence:

```
$ aef loop doctor --repo . --state ../r7-state --corpus corpus \
      --agent-path agents/mine/graph.py --graph-id mine
  [--] model calls visible     agents/mine/vendor_helper.py:2 imports anthropic
EXIT=1

$ aef loop cycle --repo . --state ../r7-state --workdir ../r7-work ...
  ledger verified: 6 entr(ies)
  proposed cycle-20260904T142538-0 on local branch loop/cycle-...
  gated: reject — G0 rejected it: 1 static-safety violation(s)
EXIT=0
```

**ADR 0137 §2 states: "`Preflight.ready` is false while it stands, so the gates
refuse."** The gates do not refuse; nothing outside `aef loop doctor` has ever
asked. `Preflight.render()` said the same thing in its closing line.

### R8 — `aef doctor`'s advisory only fires when `aef_migrated.py` exists

The documented adoption path — `aef adopt`, wire `aef_adapter.py`, write nodes
under `agents/**` — produces no `aef_migrated.py`. On a repo that followed it,
with `agents/mine/vendor_helper.py` doing `import anthropic`:

```
$ aef doctor --dir .
[OK]   python_version: 3.13
[OK]   claude_md_present: .../CLAUDE.md
[WARN] adapter_importable: ... still the generated stub, not wired yet
[OK]   agent_config:.../aef.yaml: valid
[WARN] advisory:...:empty_objectives: ...
EXIT=0
$ ls aef_migrated.py
ls: aef_migrated.py: No such file or directory
```

Nothing about the model call. The check was keyed on the artefact of a
different command — the fixture shape ADR 0137 was built against.

### R12 — `corpus.check_never_shrinks` has no production caller (pre-existing)

```
$ grep -rn "check_never_shrinks" aef/
aef/harness/corpus.py:293:def check_never_shrinks(...)          # definition
aef/harness/loop.py:269:    archive.check_never_shrinks(...)    # the ARCHIVE's, a different function
aef/harness/archive.py:248:def check_never_shrinks(...)
```

And nothing calls `save_manifest`, so no `corpus/manifest.json` has ever been
written: even where the check ran it would have compared against an empty
ledger and passed vacuously. Reproduced end to end:

```
$ aef loop score agents.mine.graph:build_graph --corpus corpus
  train  n=6  mean=0.6667 ...
      0.0000  hard-1     0.0000  hard-2

$ rm corpus/train/hard-1.json corpus/train/hard-2.json

$ aef loop score agents.mine.graph:build_graph --corpus corpus
  train  n=4  mean=1.0000 stdev=0.0000
EXIT=0
```

`recorder.refuse_existing_ids` justifies its own rule by citing this guard:
*"Silently replacing a scenario is how a corpus stops binding: the entry that
used to fail is gone, and `check_never_shrinks` cannot tell."* The citation
rested on something that never ran.

### The suspected item — confirmed, but narrower than reported

`cmd_bootstrap` catches only `BootstrapError`/`RecorderError`, and
`refuse_existing_ids` → `load_corpus` raises `CorpusError` on any malformed
scenario. It does **not** produce a traceback: `main()` has a catch-all. What
it produces is worse in a quieter way:

```
$ aef loop bootstrap agents.mine.graph --corpus corpus --inputs inputs.json
error: malformed scenario payload: 'graph_id'
EXIT=1
```

No file named, on a corpus that may hold forty of them, and exit 1 (the
catch-all) rather than this command's own rejection code. Reported reproduced
as a *naming* defect, not as the traceback it was suspected to be.

## Decision

### R9 — `roots` is a parameter, and a test pins which caller passes which

`scan_source`/`scan_file`/`scan_tree` take `roots`, defaulting to
`VENDOR_TOP_LEVEL_MODULES` — the question the scanner was written to ask about
*this* repo. `model_calls_are_visible` passes `MODEL_SDK_ROOTS` explicitly.
Constraint #3 keeps the full list where it belongs.

Two tests, because neither alone is enough. A behavioural one
(`test_a_non_model_vendor_import_does_not_block_the_adopter`, parameterised over
all 14 non-model names, with its inverse over the model SDKs), and a source
one: `test_the_preflight_obligation_scans_model_sdks_and_nothing_wider` parses
`preflight.py` and asserts every `scan_file` call inside
`model_calls_are_visible` passes `roots=MODEL_SDK_ROOTS`. A source assertion is
usually a smell; here the property **is** the wiring, and no behavioural test
of either component can see which list crossed the boundary.

`google` deliberately stays in `MODEL_SDK_ROOTS` and therefore stays blocking.
`vendor_scan.py` already records that trade: without it a Gemini client
construction is not seen at all. It predates this wave and is not the defect.

### R4 — the fix names the remedy that applies, and says when migrate cannot help

`aef migrate` writes its decision into every generated node's own docstring
(`UNROUTED wrapper for \`src.my_agent.run_agent\`` / `Not routed because ...`).
`preflight._migrate_refusals` parses that back from the configured graph, and
the obligation prints one of two messages:

- **migrate has not looked at this module** — run `aef migrate --dir . --force`
  and read its report, which names its own choice per call site;
- **migrate has already refused it** — quoting the refusal reason, saying
  plainly that re-running migrate *will not fix this and will loop*, and naming
  **both** edits: rewrite the body to `services.require_model_provider()
  .complete(...)`, and delete the `from <module> import ...` line, because the
  module stays reachable while that import stands and the obligation stays red
  even after the body is routed.

Read from the docstring, not by importing `aef.cli.migrate`: the harness does
not import the CLI, and the generated file is what the adopter has in hand.

### R5 — one of `--state` / `--no-loop-state` is required

Discovery is impossible by construction — `LOOP.md` requires `--state` to be
*outside* the repository, so there is nothing in the repo to find. Requiring
`--state` outright breaks day one, which is what ADR 0138 correctly protected.

So the assertion becomes explicit. `--no-loop-state` means "there is no loop
state directory yet"; silence is a refusal naming both flags. The escape hatch
is deliberate and has precedent (`--i-am-spending-the-holdout`): an owner who
types it while a loop is halted is lying, which is different from a tool that
guessed. `aef loop bootstrap --help` and ADR 0138's erratum carry the flag. The
generated `LOOP.md` and `AGENT_INTEGRATION.md` never documented `bootstrap` at
all — checked, not assumed — which is a separate gap, and one `READY_LOOP.md`
K4's first-day document is the place to close.

### R6 — `Scenario.source`, and the limit charges only harvest

`Source` (`unspecified`/`bootstrap`/`harvest`/`record`) rides on the scenario
and round-trips; absent in every pre-0141 file, which is exactly what
`UNSPECIFIED` means, so legacy corpora load unchanged. `harvest` counts only
`Source.HARVEST` against `daily_limit`. The rule's own justification — *one bad
deploy can produce thousands of failing runs* — is a statement about what this
command writes.

The held-back line now carries its arithmetic and says what did not count:

```
  2 held back by the daily rate limit: real-2, real-3
      the limit is 2 HARVESTED scenario(s) per 24h; 0 had been harvested before
      this run and 2 were promoted by it
      (4 from bootstrap today, which do NOT count against it — the limit is on
      this command's own promotions, ADR 0141)
```

**Residual, stated:** a scenario written by a *pre-0141* harvest inside the same
24 hours loads as `UNSPECIFIED` and is not charged. That window closes as soon
as one harvest runs on this version, and the alternative — charging
`UNSPECIFIED` — reinstates the defect for hand-recorded scenarios.

### R7 — the obligations are advisory; the ADR and the surfaces are corrected

**Decided against making `cycle`/`gate` refuse.** Four reasons, in order of
weight:

1. **A refusal could only live in the CLI, so the claim would still be false.**
   Obligation 4 is knowable only at that boundary — `_halt_notifier` reads
   `AEF_HALT_WEBHOOK` there on purpose, and its docstring says why: *"Never read
   inside the harness: a module that reaches for the environment itself is one
   the candidate is closer to influencing."* `harness.loop.cycle()` is
   importable and is what `aef loop run` and the tests drive. A control that
   binds on one of two entry points is decoration.
2. **Three of the six already enforce themselves, later and correctly.** G2/G3
   refuse an empty corpus, G5 refuses without a blessed baseline, and a graph
   nothing routes to reflect records no failure memory, so the proposer never
   proposes. An earlier second refusal adds no safety.
3. **It would break the documented first-day sequence.** Obligations 1–5 have
   always been advisory. `READY_LOOP.md` K3 is adopt → migrate → bootstrap →
   bless → cycle, and no production observations exist at that point, so
   obligation 3 is red by construction on the very sequence the loop is trying
   to make work.
4. **Strengthening five long-advisory controls is an owner's decision**, not a
   fix wave's side effect — the same rule that keeps `tier1_enabled` off a flag.

What is not optional is that the surfaces stop lying. `Preflight.render()`'s
closing line now says which obligations enforce themselves and which do not,
`preflight.py`'s module docstring records the correction, and
`cmd_cycle`/`cmd_gate` print the unmet ones before running:

```
  preflight: 5 of 6 obligation(s) unmet (corpus + tripwire, observations,
  halt channel, blessed baseline, model calls visible). ADVISORY — this command
  does not refuse on them; run `aef loop doctor` for each fix.
```

ADR 0137 gets an erratum. A `test_the_warning_is_advisory_and_says_so` asserts
the function contains no `return EXIT`, so turning it into a refusal is a
deliberate act against a test rather than a drift.

### R8 — the advisory is keyed on the graph

`run_doctor(target_dir, *, agent_path=None)`. An explicit `--agent-path` — the
same flag `aef loop doctor` takes — wins outright. Otherwise every entry the
adoption contract names, that exists, is scanned: `aef_adapter.py` (the
documented shim, which doctor already parses for another check),
`aef_migrated.py` (migrate's output, when it is there), and each
`agents/*/graph.py`, which is what `--agent-path` defaults into. One check per
entry, still advisory, still never failing `aef doctor`'s exit code.

### R12 — the ledger is written by the act that admits, and three commands read it

Two halves, and the first is why the second was vacuous:

- **`save_scenario` records the id in `corpus/manifest.json`.** A union, never a
  regeneration: a manifest rebuilt from the corpus on disk would forget
  precisely the scenario that had just been deleted.
- **`harness/loop.py::_preflight` calls `corpus.check_never_shrinks`** beside
  the archive check that was already there, on every `cycle`, `gate` and `run`;
  and `cmd_score` refuses a shrunken corpus, because a metric read over a corpus
  that lost its failing cases is not the same metric.

The baseline is read **from the base ref** when the corpus is tracked inside the
repo, falling back to the working tree otherwise. The fallback is weaker — a
candidate deleting the scenario *and* its manifest entry in one commit passes it
— and is a fallback for corpora that live outside the repository, not the
design. Retiring a scenario deliberately means editing `manifest.json`, which is
a visible, reviewable act in git rather than a silent `rm`.

### The suspected item

`cmd_bootstrap` catches `CorpusError` and returns its own rejection code;
`corpus.load_scenario` prefixes the path onto `from_payload`'s message, as every
other refusal in that module already did.

## After — the same commands

```
R9   obligation 6 : True | 2 reachable module(s), none imports a model SDK
     constraint #3 still sees them: ['psycopg2', 'opentelemetry', 'neo4j']

R4   fix: `aef migrate --dir . --force` will NOT fix this and will loop: it
     already refused to route src.my_agent (its body loops — a retry, backoff
     or pagination policy that a single complete() call would silently drop),
     and regenerating produces the same unrouted wrapper. Two edits, both
     yours. (1) Rewrite that node's body to call
     `services.require_model_provider().complete(...)` ... (2) DELETE the
     `from src.my_agent import ...` line from the node — src.my_agent stays in
     the graph's reachable set while that import stands ...

R5   WITH --state    : HALTED ... EXIT=2   corpus/train: 0
     WITHOUT --state : error: ... Pass --state <dir> ... or --no-loop-state
                       ... EXIT=1   corpus/train: 0

R6   bootstrap 12 -> corpus/train: 12
     harvest    -> promoted 3 run(s) to the train split   corpus/train: 15

R7   preflight: 5 of 6 obligation(s) unmet (...). ADVISORY — this command does
     not refuse on them; run `aef loop doctor` for each fix.
       ledger verified: 6 entr(ies)
       proposed ... gated: reject

R8   [OK]   model_calls_visible:aef_adapter.py: 1 reachable module(s), none
            imports a model SDK
     [WARN] model_calls_visible:agents/mine/graph.py:
            agents/mine/vendor_helper.py:2 imports anthropic ...

R12  error: corpus shrank: 2 previously-admitted scenario(s) are gone:
     ['hard-1', 'hard-2']. A suite that can be made to pass by deleting the
     failing case is not a suite.

SUS  error: .../corpus/train/broken.json: malformed scenario payload:
     'graph_id'        (exit = this command's rejection code)
```

## Mutations — 13 planted, 13 caught, every one reverted

```
CAUGHT  M1  R9  obligation 6 takes the scanner's DEFAULT list again  15 failed, 39 passed
CAUGHT  M2  R4  the fix never learns migrate already refused          1 failed, 39 passed
CAUGHT  M3  R5  omitting --state silently skips the kill switch       2 failed,  7 passed
CAUGHT  M4  R6  the daily limit charges every source again            3 failed, 21 passed
CAUGHT  M5  R6  the held-back line stops saying why                   1 failed, 23 passed
CAUGHT  M6  R7  cycle stops reporting unmet obligations               1 failed, 17 passed
CAUGHT  M7  R7  render claims the gates refuse again                  1 failed, 39 passed
CAUGHT  M8  R8  the advisory is keyed on migrate's artefact again     1 failed, 20 passed
CAUGHT  M9  R8  agents/*/graph.py stops being discovered              1 failed, 20 passed
CAUGHT  M10 R12 nothing writes the never-shrinks ledger again         2 failed, 41 passed
CAUGHT  M11 R12 the loop preflight stops checking the corpus          2 failed, 16 passed
CAUGHT  M12 R12 the manifest is regenerated instead of unioned        2 failed, 35 passed
CAUGHT  M13 SUS a malformed scenario stops naming its file            2 failed, 44 passed

$ git diff --exit-code      # working tree vs the staged work
0   (every mutation reverted byte-for-byte)
```

## Green bar

```
pytest -q          1918 passed, 1 skipped  (from 1875; +43, none removed)
mypy aef examples  129 files clean
ruff check .       clean
ruff format --check aef tests examples   239 files already formatted
calls made: 0 — no live model call anywhere in this wave
```

## Erratum (2026-09-04, merge of waves C and D)

R4's fix parses `aef migrate`'s generated docstring to tell "migrate has not
looked at this" from "migrate looked and refused". Wave C (ADR 0140) rewrote
that docstring in the same session: the dotted name moved off the first line
into a `Wraps \`...\`` line. Both branches were green, the merge was textually
clean, and the full suite passed — while `_migrate_refusals` parsed **nothing**
and every refusal silently fell back to the generic fix this increment exists
to replace.

It was invisible because this file's own fixture, `_unrouted_graph`, is a HAND
COPY of migrate's template whose docstring claimed that copying it "verbatim"
meant a change to the real template would fail here. A duplicate cannot detect
drift from the thing it duplicates — ADR 0091's finding, in the helper written
to prevent it.

Fixed at merge time: the parser reads the `Wraps` line, the fixture matches the
real format, its docstring no longer claims a guarantee it cannot give, and
`test_the_generated_docstring_is_a_contract_between_migrate_and_preflight` runs
the real `aef migrate` and reads its real output back through the real parser.
Mutation-checked by restoring the old marker: 2 failed.

## Consequences

- **A `psycopg2` import no longer blocks adoption**, and constraint #3 is
  unchanged for this repo. One scanner, one list per question, and a test
  pinning which caller asks which — the ADR 0091 drift shape, closed at the
  call site rather than at the list.
- **The obligation-6 fix string is actionable in both cases**, including the
  one migrate's falsification clause deliberately creates, which had no
  documented remedy at all.
- **A halted loop's corpus cannot grow from either invocation.** The escape
  hatch is a sentence an owner types, not silence a tool interprets.
- **The K5 pilot sequence works**: bootstrap no longer eats the budget the
  first real harvest needs, and the rate-limit line says what spent it.
- **Two false ADR claims are corrected by erratum** rather than by rewriting
  the record. The surfaces that repeated them say what is true instead.
- **`check_never_shrinks` runs.** `recorder.refuse_existing_ids`' citation now
  rests on a guard with production callers, and the manifest it compares
  against is written by the same act that admits a scenario.
- **The obligations stay advisory, deliberately and in writing.** Making them
  blocking remains available and is an owner's decision; the reasoning above is
  what that decision would have to argue against.

## Confidence

**High** on all eight reproductions and on R9, R4, R5, R6 and the suspected
item: each was run before and after, and each is pinned by a test whose
mutation was executed and failed.

**High** on R7 being *reported* correctly now, and on the reasoning for leaving
it advisory. **Medium** on that being the right long-term answer: an adopter who
ignores the warning is in exactly the position ADR 0137 described, and the only
thing that changed is that they were told. The case for blocking gets stronger
the moment a real repo runs this.

**Medium** on R12's coverage. The base-ref read is the strong form and only
applies to a corpus tracked inside the repository; the working-tree fallback
does not stop a candidate that deletes a scenario and its manifest entry
together. No CI job reads either yet — `corpus.py`'s docstring claimed one did,
and that claim is corrected there rather than made true here.

**Medium** on R8's discovery list. It names the three entries the adoption
contract names and will miss a graph an adopter put somewhere else — for which
`--agent-path` now exists on `aef doctor`, and did not before.

**Not measured:** any repo but the fixtures. Every reproduction here ran against
repos this program constructed, which is the gap `READY_LOOP.md` K5 names for
the whole loop.
