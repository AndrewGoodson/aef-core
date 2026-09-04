# ADR 0148: The first-day document, written from a terminal

## Status
Accepted. Increment **L6** of `INGEST_LOOP.md`; recorded in `IMPROVE_LOG.md`.
**No rubric dimension moves** — adoption readiness is not a scoring claim, and
the score stays 86.

## Context

`aef adopt` writes four documents an adopter reads as instructions —
`CLAUDE.md`/`AGENTS.md`, `AGENT_INTEGRATION.md`, `LOOP.md`, `AUTONOMY.md` —
and every one of them answers *what*. None answers **when**: here is the
sequence, here is what each step costs, here is what does not work until the
step before it has run. K4 of `READY_LOOP.md` was to write that and was never
written, because until L1–L5 the sequence did not exist to be written down.

It exists now, and the reason this ADR carries a rule rather than only a
document is that **three separate documents in this scaffold have told
adopters things that were false**, each one written from the source rather
than from a terminal:

- `LOOP.md` said `aef adopt` writes no `.gitignore` five hours after ADR 0142
  made it write one.
- ADR 0139 concluded that a model-calling graph "cannot get its first corpus"
  while `--config` — the flag that fixes it — had been sitting in the parser
  since ADR 0138, reachable only by reading `argparse` calls.
- ADR 0141's R4: `aef loop doctor`'s printed fix for the model-call obligation
  was `aef migrate --dir . --force`, which regenerates the same refusal, so
  the adopter loops forever.

**The rule for this increment: every command in the document was RUN, in a
scratch repo, and its real output pasted.** Nothing below is quoted from a
source file.

## Decision

### `FIRST_DAY.md`, shipped by `aef adopt` under the never-overwrite rule

The name is *when to read it*, which is the one thing the rest of the kit
does not say. `render_first_day_md` lives in `aef/cli/adopt_loop.py` beside
`render_loop_md`, interpolating `DEFAULT_AGENT_ROOT` and `DEFAULT_MIGRATED_OUT`
rather than spelling either out (ADR 0091). Seven sections, in the order an
adopter meets them:

1. what `aef adopt` gives you (17 files, listed) and what it explicitly does
   not — it read none of your code, wrote no node, no test, no scenario, and
   `pytest -q` exits 5;
2. `aef migrate` — where it writes, the ROUTED/WRAPPED choice and its
   criterion, and **if your function keeps its own client, the gates cannot
   replay it**, with `aef loop doctor`'s two-edit fix quoted (including the
   half nobody finds: deleting the import that keeps the module in the
   reachable set);
3. `aef loop bootstrap`, including `--memory` and `--config` — which **no
   generated document mentioned at all** — and that one of
   `--state`/`--no-loop-state` is mandatory;
4. the owner's one act, the `--expected must_fail` line bootstrap prints,
   quoted exactly as printed and run verbatim;
5. `bless` (with the ADR 0147 containment refusal) then `aef loop doctor`, and
   that **the six obligations are ADVISORY, not gating** (ADR 0141);
6. `aef loop cycle`, the gated ledger, and the one requirement still the
   adopter's — a module-level numeric constant — with what is measured about
   it and what is not;
7. what still needs a person, and that none of this has run against a repo
   this project did not write.

It joins `tests/test_prompt_surface.py`'s surface as `<adopt: FIRST_DAY.md>`
— a renderer, like `<adopt: CLAUDE.md>`, because the file exists only in
adopted repos — so text the model guide removes cannot come back in it, and
the verification instructions cannot be dropped from it.

### The already-false claims this closes, each verified by running

| # | Where | The claim | What running says |
|---|---|---|---|
| F1 | `AGENT_INTEGRATION.md` (root) | "`aef adopt` … writes **six** never-overwrite files" | it wrote **16** (17 with `FIRST_DAY.md`) |
| F2 | `render_agent_integration_md` | "Getting the loop to **five** green … `aef loop doctor` reports **five** obligations", and the list omitted `model calls visible` | doctor prints `Loop readiness — 6 things you must supply` and six rows |
| F3 | `render_agent_integration_md` | "with obligations unmet the gates refuse for lack of evidence" | ADR 0141: advisory; `cycle` printed `2 of 6 obligation(s) unmet … ADVISORY — this command does not refuse on them` and gated a candidate |
| F4 | `render_loop_md` item 4 | "`aef loop bootstrap` cannot do this for you — it gives every input its own in-memory store" | `bootstrap --memory` wrote 4 records; the same sequence without the flag left no file and the cycle went quiet |
| F5 | `render_loop_md` sequence block | `aef loop bootstrap <module> --corpus corpus --inputs inputs.json` | **exit 1** — one of `--state`/`--no-loop-state` is required (ADR 0141) |
| F6 | `render_loop_md` | the model-calling-graph paragraph never named `--config` | the command's own error names it; the document did not |
| F7 | `render_loop_md` | "Work down its output until every line is OK" under a heading promising the loop cannot approve anything without them | two obligations cannot be green on day one, and none of them gates |
| F8 | generated `aef.yaml` + `AGENT_INTEGRATION.md` | `--config` reaches `aef run` and `aef loop gate`/`cycle` | and `aef loop bootstrap`, since ADR 0145 |
| F9 | generated `aef_adapter.py` | `GraphExecutor(build_graph().compile(), services or Services())` | `ServiceNotConfiguredError: service 'critic'` on the documented path |

F9 is the second defect the seam hunt of this wave reported into this
increment, and it is a seam in the exact shape CLAUDE.md names: `adopt`'s shim
and `migrate`'s graph were each correct and each tested, and L2 (ADR 0143)
wired `reflect -> consolidate` into the graph the checklist tells the adopter
to point that shim at. Every other construction site in the repo goes through
`agent_services()`; this was the only bare `Services()` that shipped. Fixed to
`services or agent_services()`, with the reason in the shim's own comment, and
the regression test **executes** the shim rather than grepping it — an
assertion that the source names `agent_services` would pass on a shim that
imported it and never called it.

### A measurement that changes what the minimum means

ADR 0139 measured requirement 2 — a module-level numeric constant — by
removing it and getting `the proposer produced nothing from the available
evidence`. Re-measured here on **`aef migrate`'s own generated graph**, which
is the shape an adopter now actually has, the answer is different and the
document says so:

- a candidate **is** proposed. `RuleBasedProposer.propose_structural`'s
  `add_bounded_retry` applies to the failing node's body regardless of
  constants, and it emits its own `RETRY_ATTEMPTS = 3`;
- and then the **control cohort** cannot be built, so G2/G3 refuse:
  `could not build evidence (cannot build a control cohort for
  'agents/migrated/graph.py': no module-level numeric constants to mutate, so
  there is no null hypothesis to draw from)`.

So the requirement stands — for a different reason, in a different place, with
a different message. The constant is needed by the **cohort** at least as much
as by the proposer, which is why `FIRST_DAY.md` says the answer for
`--proposer llm` is **unmeasured and blocked on model quota** (INGEST_LOOP L4)
rather than assuming an LLM proposer escapes it: whatever proposes the
candidate, the thing that judges it is built by mutating constants.

## Evidence — every command RUN, output pasted

Scratch repo: fresh `git init`, one 8-line raw-SDK agent, `aef adopt`. Venv
python, `PYTHONPATH` = the worktree. **Zero model calls.**

### The sequence, against the final code

```
$ aef adopt --dir .
detected framework: raw_sdk
wrote .../CLAUDE.md ... (17 files)

$ aef migrate --dir .
scanned 3 Python file(s)
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 1 routed through Services.model_provider, 0 still calling your function
wrote agents/migrated/graph.py
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may propose changes to

$ aef loop bootstrap agents.migrated.graph --corpus corpus --inputs ../inputs.json \
      --state ../loop-state --memory ../loop-state/memory.jsonl
recorded 4 scenario(s) in the train split
  passed  bootstrap-1        passed  bootstrap-2
  FAILED  beyond-the-budget  FAILED  bootstrap-4
2 of 4 recorded run(s) FAILED.
  4 memory record(s) written to the durable store — what the graph's own reflect node
  observed, nothing bootstrap decided.
    aef loop record agents.migrated.graph --corpus corpus --scenario-id
      beyond-the-budget-tripwire --objective "a task past the retry budget"
      --working-memory "{\"difficulty\": 9, \"quality_needed\": 1}" --split validation
      --expected must_fail

$ <that line, verbatim>
recorded beyond-the-budget-tripwire (validation) -> corpus/validation/beyond-the-budget-tripwire.json
  3 node execution(s) pinned
  0 model call(s) pinned, 0 check(s)

$ aef loop bless --repo . --state ../loop-state --agent-path src/my_agent.py
error: src/my_agent.py exists at HEAD but is NOT inside the tree this would archive:
'agents' at HEAD holds 2 file(s) (agents/README.md, agents/migrated/graph.py). ...   exit=1

$ aef loop bless --repo . --state ../loop-state --agent-path agents/migrated/graph.py
blessed agents/migrated/graph.py as baseline v1 for graph 'default'

$ aef loop doctor --repo . --state ../loop-state --corpus corpus \
      --agent-path agents/migrated/graph.py
Loop readiness — 6 things you must supply
  [OK] corpus + tripwire       5 scenario(s), 1 tripwire(s)
  [OK] reflect node routed to  src_my_agent__run_agent() returns 'reflect' as its Route
  [--] observations            0 recorded run(s) at ../loop-state/observations.jsonl
  [--] halt channel            none — a halt would tell nobody
  [OK] blessed baseline        1 archived version(s)
  [OK] model calls visible     1 reachable module(s), none imports a model SDK
These are ADVISORY and this command is the only thing that reads them: ...      exit=1

$ aef loop cycle --repo . --state ../loop-state --workdir ../loop-state/work \
      --module agents.migrated.graph --corpus corpus \
      --entrypoint agents.migrated.graph:build_graph --memory ../loop-state/memory.jsonl \
      --agent-path agents/migrated/graph.py --build-command "python -m pytest -q"
  preflight: 2 of 6 obligation(s) unmet (observations, halt channel). ADVISORY — this
  command does not refuse on them; run `aef loop doctor` for each fix.
  ledger verified: 1 entr(ies)
  proposed cycle-20260904T170914-s0 on local branch loop/cycle-... (never pushed;
    proposer=rule_based)
  gated: reject — G3 rejected it: candidate does not beat the p95 of the random control
    cohort — this is the null hypothesis, not an improvement                    exit=1
```

`ledger.jsonl`'s `gated` entry from that run:

```
evidence: 7 corpus pass(es) (35 scenario execution(s)): 1 candidate + 1 incumbent
          + 5 random control(s); corpus records one graph ('adoptee');
          gating all 5 gated scenario(s)
  G0 pass  1 file(s), 28 line(s), all Zone A, no static-safety violations
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.098/0.500 from the blessed baseline
  G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
  G3 fail  candidate does not beat the p95 of the random control cohort
grounded_in: ["aee7ed42aff8 (memory): node 'src_my_agent__run_agent' raised"]
```

### F4 measured by removal — the same sequence with `--memory` deleted

```
$ aef loop bootstrap agents.migrated.graph --corpus corpus --inputs ../inputs.json \
      --state ../loop-state
recorded 4 scenario(s) in the train split
2 of 4 recorded run(s) FAILED.                                                  exit=0
    (no "memory record(s) written" line — --memory absent and --memory empty are
     different facts and print differently, ADR 0145)

$ ls ../loop-state/memory.jsonl
ls: ../loop-state/memory.jsonl: No such file or directory

$ aef loop cycle ... --memory ../loop-state/memory.jsonl
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle                         exit=0
```

Corpus identical, tripwire identical, baseline identical, and the cycle exits
**0 having done nothing** — the failure mode that reads as success.

### F5 — the invocation the generated `LOOP.md` printed

```
$ aef loop bootstrap agents.migrated.graph --corpus corpus --inputs ../inputs.json
error: bootstrap writes to corpus/, which is the evidence every behavioural gate is
measured against, so it must be able to see the kill switch (ADR 0069). Pass --state
<dir> — the same directory every other loop subcommand takes — or --no-loop-state if
there is genuinely no loop yet. Neither was given, and silence used to mean 'do not
check', which grew the corpus of a HALTED loop (ADR 0141).                      exit=1
```

The parser accepts it, so `test_every_emitted_aef_command_is_one_the_cli_accepts`
could not see this: the rule is enforced in the handler. The new test therefore
asserts the printed **invocation** carries one of the two flags, in addition to
parsing.

### F6 — a model-calling graph, and the error that now names the flag

```
$ aef loop bootstrap agents.migrated.graph --corpus corpus --inputs ../inputs.json \
      --no-loop-state              # before the semantics are supplied
recorded 0 scenario(s) in the train split
  ERRORED (nothing recorded)  bootstrap-1: ModelProviderError: cassette miss (key
    53bca5ad441e, model 'claude-sonnet-4-5', ...) and no live provider to fall through
    to: on_miss='live' needs an inner ModelProvider (model_provider.impl in aef.yaml,
    e.g. claude_code — ADR 0112)                                       ... (4 of 4)
NOTHING was recorded and the corpus is unchanged. ...
  This graph calls a model and no provider was configured ... Pass --config <aef.yaml>
  to bootstrap ...                                                              exit=1
```

**The live recording pass was NOT run** — no quota. `--config`'s wiring is
proved by ADR 0145's tests; the credential is not exercised here, and
`FIRST_DAY.md` says so in those words rather than implying it was.

### The unrouted form (section 2's load-bearing sentence)

A second scratch repo whose agent wraps its call in a retry loop:

```
$ aef migrate --dir .
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 0 routed through Services.model_provider, 1 still calling your function
  WRAPPED  src.my_agent.run_agent:4  (anthropic.Anthropic)
            -> calls src.my_agent.run_agent, unchanged
            NOT routed because its body loops — a retry, backoff or pagination policy
            that a single complete() call would silently drop
            the model call stays INVISIBLE to the harness: no policy check, no fallback,
            no RecordedCall to replay

$ aef loop doctor --repo . --state ../loop-state --corpus corpus \
      --agent-path agents/migrated/graph.py
  [--] model calls visible     src/my_agent.py:1 imports anthropic — the harness cannot see it
       fix: `aef migrate --dir . --force` will NOT fix this and will loop ... Two edits,
       both yours. (1) Rewrite that node's body ... (2) DELETE the
       `from src.my_agent import ...` line ...                                  exit=1
```

### The re-measurement of requirement 2

Fresh repo, full sequence, the two module-level constants **inlined** into the
node body and nothing else changed:

```
$ aef loop cycle ... --agent-path agents/migrated/graph.py
  ledger verified: 1 entr(ies)
  proposed cycle-20260904T164529-s0 on local branch loop/cycle-...
  gated: reject — G2 rejected it: gate raised TrustBoundaryError: scratch destination
    .../work/workspace must be empty. A gate that could not judge has not cleared this
    candidate.                                                                  exit=1
```

and the ledger, which is where the real reason is:

```
evidence: could not build evidence (cannot build a control cohort: cannot build a
          control cohort for 'agents/migrated/graph.py': no module-level numeric
          constants to mutate, so there is no null hypothesis to draw from);
          G2/G3 will refuse
  G0 pass  1 file(s), 28 line(s), all Zone A, no static-safety violations
  G1 pass  1 build command(s) succeeded against the merged workspace
  G2 fail  gate raised TrustBoundaryError: scratch destination .../workspace must be empty
```

and the candidate the proposer produced anyway:

```
+RETRY_ATTEMPTS = 3
...
+    for _attempt in range(RETRY_ATTEMPTS):
+        try:
             <the node body>
+        except Exception:
+            if _attempt == RETRY_ATTEMPTS - 1:
+                raise
```

Reproduced twice: once on a copy of a working repo, once on a repo built from
`git init` upward, same output both times.

### F9 reproduced — the generated shim on the documented path

```
$ python repro_shim.py <the adopted repo>      # aef_adapter.build_graph = migrate's graph
ServiceNotConfiguredError: service 'critic' was not configured on this Services
container; wire it in via config before any node that depends on it can run
```

after `services or Services()` became `services or agent_services()`:

```
$ python repro_shim.py <the adopted repo>
no error
```

### Every `aef` command in every generated document, through the real parser

```
FIRST_DAY.md: 14 command(s)
LOOP.md: 19 command(s)
corpus/README.md: 1 command(s)
AGENT_INTEGRATION.md: 7 command(s)
total checked: 41
```

The extractor is `tests/cli/test_pristine_adoption.py::_commands`, reused
rather than duplicated (a second copy of a rule is ADR 0091's drift). Its
coverage floor rises 15 → 30.

## Mutations

Ten, each perturbing a production value, each RUN, each restored from a
byte-identical backup whose SHA-1 was verified before and after (`git checkout
--` would have destroyed uncommitted work).

```
BASELINE                                                     96 passed
M1  adopt stops writing FIRST_DAY.md                         10 failed, 86 passed
M2  the shim goes back to a bare Services()                   4 failed, 92 passed
M3  LOOP.md item 4 claims bootstrap cannot leave memory       1 failed, 95 passed
M4  FIRST_DAY.md drops --config                               1 failed, 95 passed
M5  the obligations are described as gating again             1 failed, 95 passed
M6  FIRST_DAY.md drops the client-replay heading              1 failed, 95 passed
M7  FIRST_DAY.md generalises the constant to every proposer   1 failed, 95 passed
M8  LOOP.md prints the bootstrap invocation the CLI refuses   2 failed, 94 passed
M9  the prompt surface loses FIRST_DAY.md                     1 failed, 94 passed
M10 FIRST_DAY.md drops the verification instruction           1 failed, 95 passed
REVERTED                                                     96 passed
                                                             10/10 caught
```

**Three of them were MISSED on the first pass, and that is the finding worth
recording.** M4, M6 and M7 each perturbed a heading while the asserted token
survived elsewhere in the document — `--config` appeared in another paragraph,
"the gates cannot replay it" appeared in prose, and "unmeasured" appeared in
the preamble. Three tests were pinning **tokens rather than claims**, which is
the shape a documentation test fails in: it goes green on a document that no
longer says the thing. Strengthened to assert the load-bearing sentence, and
only then did all ten fail.

## Green bar

```
pytest -q          1985 passed, 1 skipped  (collected 1976 -> 1986; +10, none removed)
mypy aef examples  129 source files, no issues
ruff check .       All checks passed
ruff format --check aef tests examples   239 files already formatted
model calls made   0
```

`tests/cli/test_adopt.py` pins the exact written-file set and the idempotency
counts; both were updated **deliberately**, 16 → 17, with the reason in the
comment beside them — that count is the pin that makes "adopt quietly started
writing something" a failure rather than a discovery.

## Consequences

- **`FIRST_DAY.md` is the document that goes stale fastest**, because it is
  the only one that describes a sequence rather than a component. Five tests
  hold it to the CLI: every command parses, the bootstrap capability it claims
  is asserted off the real parser, the obligations' advisory status is
  asserted in three documents at once, and the prompt surface covers it.
- **The obligation count is now derived, not typed.**
  `test_loop_doctor_reports_all_six_and_exits_nonzero` reads the names out of
  `preflight.py`, so the next obligation cannot repeat F2. It previously
  asserted five while `preflight` declared six, which is how the one
  obligation an adopter cannot discover by being stuck could have vanished
  silently.
- **A defect this increment found and did not fix.** When the control cohort
  cannot be built, the cycle's summary line says `G2 rejected it: gate raised
  TrustBoundaryError: scratch destination .../workspace must be empty` — a
  scratch-directory red herring for a missing constant. The real reason is in
  the ledger's `evidence` note. It lives in `aef/harness/loop.py`, outside
  this increment's file scope; reported here with the reproduction above.
- **What is still not true.** Definition-of-done statement 1 — `git clone` to
  a gated candidate with no hand-written node — remains false by exactly one
  item: the module-level numeric constant, which is the semantics of a node
  and not plumbing. And nothing here has run against a repo this project did
  not write; the adoptee is a fixture, smaller each time and still authored.

## Confidence

**High** that every command in `FIRST_DAY.md` does what it says: each was run
against a fresh `git init` and its output pasted, and the whole sequence was
re-run end to end against the final code after every edit.

**High** on the nine false claims: each was reproduced by running the command
whose behaviour the text described.

**Moderate** on the re-measurement of requirement 2 being general. It was run
twice on one agent shape — migrate's routed node with a deterministic body
substituted. A graph whose failing node has a body `add_bounded_retry` cannot
transform would give ADR 0139's original message instead, which is why the
document names both.

**Low**, unchanged, on anything this says about a repo nobody wrote to be
scanned — and lower still on the `--config` live-recording pass, which has
never been executed by anyone.
