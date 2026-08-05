# ADR 0074: The gates the CLI could not reach

## Status
Accepted. Phase 2 of the overnight run — the systematic seam sweep. Three
independent seam-hunter invocations; two of them reproduced the same pair of
defects from different directions, which is what made me look hardest at
them.

## The headline

**G2 and G3 had never executed from a real command.** Not once. Every proof
that the six-gate pipeline works came from `test_evidence_loop.py`, which
hand-builds its own `LoopConfig` and fills in two fields
`aef.cli.loop._config` never set. No test imported `_config`. So the suite
was green against a configuration no user could produce.

Reproduced through the shipping CLI, on a repo built the way the docs
prescribe, with a baseline `aef loop bless` had just created:

```
G0: pass  G1: pass  G4: pass
G5: fail -- no owner-blessed baseline to measure drift against
```

Three gates ran. G5 failed because `config.now_for_gates` was `None`, and the
pipeline is fail-fast in canonical order `G0,G1,G4,G5,G2,G3`. The two most
expensive gates — the corpus re-execution and the null-hypothesis cohort, the
entire behavioural half of the pipeline — never ran, and the refusal blamed a
baseline sitting in the archive.

## The eight defects

**1. A second, unwired clock.** `gate()` receives `now` and stamps every
ledger entry with it. `_gates_with_evidence` ignored it and read
`LoopConfig.now_for_gates`, which only tests set. The field is deleted; `now`
is threaded from the caller. There is now one clock.

**2. G5's refusal misnamed its own cause.** One message covered "no baseline"
and "no clock", and it named the baseline. An operator would go create a
baseline they already had. Two failures, two messages.

**3. A cohort failure disabled three gates.** The `SuiteError` handler
returned *before* `baseline = _blessed_baseline(config)`, so G5 lost its
evidence too and then reported a missing baseline. A cohort failure is not
evidence about the baseline. G5 is wired before the cohort is attempted.

**4. `entrypoint` defaulted to a layout nothing has.**
`agents.graph:build_graph` — not this repo, not anything `aef adopt` writes,
which prescribes `agents/<yours>/graph.py`. No `--entrypoint` flag existed.
G2/G3 died on `ModuleNotFoundError` buried in a ledger note and the run read
as an ordinary rejection. This is **ADR 0069 defect 3 one field over**: a
default that assumes a layout, failing silently. There is now no default, a
`--entrypoint` flag on `gate` and `cycle`, and an explicit refusal naming the
flag.

**5. The drift metric subtracted two different questions.** `bless` archived
the single `--agent-path` file; `_candidate_files` returned only the files the
candidate changed; `structural_drift` unions the two key sets. So every
blessed file the candidate left alone counted as fully deleted, and the
**first candidate after a blessing** was rejected for 0.583 drift it had not
caused. Both sides now describe the whole Zone A tree.

**6. `bless` read the working tree; every gate reads git.** Found by running
the fixed version: an uncommitted `__pycache__` appeared on one side of the
metric only and charged **0.430 drift for a two-line change**. A baseline
blessed from a dirty tree also records a state that exists nowhere in
history, so nothing can be compared against it reproducibly. `bless` now
reads `HEAD` and refuses an uncommitted agent.

**7. The control cohort carried the candidate's changes.**
`build_candidate_workspace` overlays the *whole* candidate diff; only
`targets[0]` was then replaced with a mutated incumbent file. On a two-file
candidate every control kept the candidate's changes to the other file, so
all five scored identically to the candidate, p95 rose to meet it, and **G3
could never pass**. The comment in `suite.py` documents this exact failure
being found and fixed for the single-file case — the fix had been applied to
one file. Controls are now materialised from the incumbent.

**8. One security incident was reported as two.** `security_event` was
written on the `GATED` entry and again on the `REJECTED` entry; the digest
counts one per entry carrying the key. The `GATED` entry now records
`security_gates` — which gate raised it — and the count comes from one place.

## Obligation 1 had the same hole obligation 5 had

ADR 0073 fixed obligation 5: LOOP.md required a blessed baseline and no
command could create one. Obligation 1 turned out to be broken the same way.

`preflight` told adopters to "label one MUST_FAIL" and **no shipped command
could write the label**: `harvest` hardcodes `UNSPECIFIED`, and `aef loop
record` had no flag. Worse, `record` ran the agent with an empty working
memory every time, so every recordable scenario landed on the happy path —
a tripwire was unreachable even in principle. This repo's own two tripwires
are hand-committed JSON, which nothing documents.

`record` now takes `--expected` and `--working-memory`, and **refuses
`must_fail` on a task the agent completes**: a tripwire must be impossible in
principle, not merely hard, or every real improvement reads as reward
hacking.

## What this bought

Verified end to end through the shipping CLI, on a repo built from the docs:

```
G0: pass  G1: pass  G4: pass
G5: pass -- 0/3 accepted in the last 7d; drift 0.027/0.500
G2: pass -- 6 scenario(s) re-executed; every previously-passing one still passes
G3: pass -- candidate mean 0.8333 beats the control cohort's p95 of 0.5
```

First six-gate pass from a real command. Then the reward hack — one line
making the agent ignore its inputs and always report success:

```
G0/G1/G4/G5: pass          (it is smaller, cheaper and faster than the honest change)
G2: fail -- 1 tripwire scenario(s) the owner labelled impossible now report success
security_gates: ['G2']     exit 2, loop HALTED
```

The containment chain — tripwire catches what the cheap gates reward, one
incident counted once, loop halts rather than retries — works from the
command line for the first time.

## The pattern, again

Seven of these eight are seam defects: each component was correct and tested.
The new rule, now encoded as `tests/harness/test_gate_wiring.py`:

> A test that constructs the object under test itself cannot see a defect in
> how the shipping caller constructs it. Where the seam is the caller, the
> test has to start at the caller.

Also generalised: three separate defects have now been "a tool prints a
command the CLI rejects" (#10, #18, and the tripwire fix above). There is now
a test that parses **every** fix string `doctor` emits through the real
parser, rather than a third test for a third instance.

## Consequences
- `--entrypoint` is **required** for G2/G3. Adopters upgrading must add it;
  without it the gate report says so in those words.
- `bless` archives the whole Zone A tree from git. An existing single-file
  baseline will over-report drift and should be re-blessed against a fresh
  state directory.
- `LoopConfig.now_for_gates` is gone.

## Confidence
High on all eight: each was reproduced by running the shipping CLI, and the
fixed path was executed end to end including the adversarial case. **Not
claimed:** that the sweep is complete. Three joins were swept in depth;
three more (proposer→workspace→G0, reflect→memory→proposer, adopt-emitted
workflows→CLI) are recorded as unswept, along with five lower-severity
findings this ADR does not fix — rollback ordering with two open merges,
halt criteria 3 and 4 having no caller, `check_never_shrinks` having no
production caller, `BLESSED` missing from the digest, and G3 collapsing to
"beats the incumbent" when the control cohort has zero variance.
