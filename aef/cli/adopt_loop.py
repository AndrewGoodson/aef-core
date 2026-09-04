"""The self-rewiring loop kit `aef adopt` emits into a target repo.

Separate from `adopt.py` because these files carry a different contract: the
onboarding kit tells an agent how to work in the repo, while this kit tells
the *owner* what they must supply before the loop can approve anything.

Every document here **leads with what does not work yet**. An adopting repo
whose agents start producing candidates against an empty corpus will see
every one rejected, and that reads as "the loop is broken" rather than "the
loop has nothing to judge against" — which is the correct reading and the one
that tells the owner what to do next.
"""

from __future__ import annotations

# Interpolated, never spelled out: a generated document that names a directory
# the harness does not enforce, or an output path nothing writes to, is the
# next drift (ADR 0091, ADR 0143).
from aef.cli.migrate import DEFAULT_MIGRATED_OUT
from aef.harness.zones import DEFAULT_AGENT_ROOT


def _module_path(repo_relative: str) -> str:
    """`agents/migrated/graph.py` -> `agents.migrated.graph`.

    Computed rather than written beside the path, because the two drifting
    apart is how a document ends up telling an adopter to import a module
    nothing writes (ADR 0091).
    """
    return repo_relative.removesuffix(".py").replace("/", ".")


def render_loop_md(repo_name: str) -> str:
    return f"""# The self-rewiring loop in {repo_name}

Agents here may propose changes to their own code. An automated gate pipeline
judges every proposal before anything merges. This file says what works, what
does not yet, and what only you can decide.

**`FIRST_DAY.md` is the sequence**; this file is the reference behind it.
Every command there was run against a fresh adoption and its real output
pasted, in the order you meet them.

## Read this first: what the loop needs before it can propose ANYTHING

`aef adopt` and `aef migrate` do not leave you with a loop that can produce a
candidate. Every line of this table was **measured** — removed from a working
sequence, the cycle re-run, the output quoted (aef-core ADR 0139). It is at
the top rather than in step five because each one makes `aef loop cycle` exit
**0 having done nothing**, which reads like success.

1. **The graph under `{DEFAULT_AGENT_ROOT}/`** — Zone A. Otherwise:
   `G0 rejected it: candidate touches paths outside Zone A`
   *`aef migrate` now does this for you: its default `--out` is
   `{DEFAULT_MIGRATED_OUT}` and its report names the zone of the path it
   wrote (aef-core ADR 0143). It wrote `aef_migrated.py` to the repo root —
   Zone C — until then, so check any graph left over from an older run.*
2. **At least one module-level numeric constant in it.** Otherwise:
   `the proposer produced nothing from the available evidence`
3. **A node that actually returns `"reflect"` as its route.** Otherwise:
   `no admissible failure memory: no candidate this cycle`
   *`aef migrate` now does this for you too: the graph it generates is wired
   `<call site> -> reflect -> consolidate -> END`. If you write the graph by
   hand, this one is yours.*
4. **Failure memory in the file `aef loop cycle --memory` reads.**
   Otherwise: the same line as 3.
   *`aef loop bootstrap --memory <file>` now does this for you (aef-core ADR
   0145): a failing input's reflections are mirrored into that durable file as
   well as into its own isolated per-input store, so no hand-written run is
   needed. The previous version of this line said bootstrap **cannot** do it —
   true when ADR 0139 measured it, false the day ADR 0145 landed. Measured:
   the same sequence with the flag removed leaves no file and the cycle says
   `no admissible failure memory: no candidate this cycle`, exit 0.* A
   failing `aef run --objective ... --working-memory ... --memory <file>`
   still works and is what you use to add evidence later.
5. **Scenarios in `corpus/`**, train or validation. Otherwise:
   `no corpus: G2/G3 will refuse for lack of evidence`
6. **A blessed baseline.** Otherwise G5 has no reference point for drift.
7. **`--entrypoint` on the cycle itself.** Otherwise:
   `no entrypoint configured: G2/G3 will refuse`

**`aef migrate` writes two of the first four; `aef loop bootstrap --memory`
supplies a third; ONE is still yours.** Migrate lands the graph at
`{DEFAULT_MIGRATED_OUT}` (item 1, Zone A) and wires
`<call site> -> reflect -> consolidate -> END` (item 3); bootstrap leaves the
failure memory of item 4 behind. What remains:

- **no module-level numeric constant** — item 2 is the shape the rule-based
  proposer mutates, and it is also the shape the null-hypothesis control
  cohort is built from, so it is needed twice. A generated wrapper has no
  number of its own to invent. Your node body is where one goes.
- **`aef migrate` cannot make a run fail** — the loop records what happened
  and never invents a failure (ADR 0060). Bootstrap mirrors the failing
  input's reflection; it does not manufacture one, so an inputs file where
  everything passes still leaves the proposer nothing to cite.

Measured, on migrate's own generated graph with the constants inlined and
nothing else changed: a candidate **is** proposed (the structural
`add_bounded_retry` transformation applies), and then `could not build
evidence (cannot build a control cohort ...: no module-level numeric constants
to mutate, so there is no null hypothesis to draw from)` — the CLI's summary
line names a scratch directory, and the real reason is in the ledger. On a
graph where the structural transformation does not apply you get the clearer
`the proposer produced nothing from the available evidence` instead. Either
way, name your numbers.

The previous version of this paragraph said migrate writes *none* of the
four. That was true when ADR 0139 measured it and false the day ADR 0143
landed; it is corrected here rather than quietly deleted.

**Your first corpus cannot come from a model-calling graph unless you have a
credential, and the flag that spends it is `--config`.** The cassette the
gates later replay from does not exist until something makes the call once, so
`aef loop bootstrap` on a routed node with no provider exits 1 with
`no live provider to fall through to`.
Pass `--config aef.yaml` to bootstrap: it builds
the provider through `aef run`'s own code path — so `policies`, `tools.allow`
and `evaluator.suites` reach the recording too — and reports the calls it
spent. Recording is the one pass that is *supposed* to be live. Configuring
`model_provider` in `aef.yaml` without passing the flag does nothing, and
until aef-core ADR 0145 no generated document named the flag at all. The
alternative is to start the loop on a graph that calls no model.

**Check `__pycache__/` is in `.gitignore` before you bless.** `aef adopt`
writes one now (aef-core ADR 0142) but **skips an existing `.gitignore`
rather than appending to it**, and says so in the migration checklist — so a
repo that already had one may still be missing the pattern. Compiled bytecode
committed under `{DEFAULT_AGENT_ROOT}/` by an ordinary `git add -A` is Zone A
content the baseline does not have, and G5 charges it as drift: measured at
**0.468 of a 0.500 budget** for a one-line candidate, against **0.024** for
the same candidate with the bytecode excluded.

The sequence that works, start to finish. `<your.graph.module>` is the import
path of the graph you want the loop to improve; if `aef migrate` wrote it,
that is `{_module_path(DEFAULT_MIGRATED_OUT)}`.

```
aef migrate --dir .
aef loop bootstrap <your.graph.module> --corpus corpus --inputs inputs.json \\
    --state ~/.aef-loop-state --memory ~/.aef-loop-state/memory.jsonl
aef loop record <your.graph.module> --corpus corpus --scenario-id tripwire-1 \\
    --objective "<a task beyond this agent>" --split validation \\
    --expected must_fail --working-memory '{{"difficulty": 99}}'
aef loop bless --repo . --state ~/.aef-loop-state \\
    --agent-path agents/<yours>/graph.py
aef loop doctor --repo . --state ~/.aef-loop-state --corpus corpus \\
    --agent-path agents/<yours>/graph.py
aef loop cycle --repo . --state ~/.aef-loop-state --workdir /tmp/loop \\
    --module <your.graph.module> --corpus corpus \\
    --entrypoint <your.graph.module>:build_graph \\
    --agent-path agents/<yours>/graph.py \\
    --memory ~/.aef-loop-state/memory.jsonl \\
    --build-command "<your green bar>"
```

**One of `--state` and `--no-loop-state` is REQUIRED on bootstrap**, and the
line above used to carry neither, so the CLI refused it: bootstrap writes to
`corpus/`, the evidence every behavioural gate is measured against, so it has
to be able to see the kill switch. Silence used to mean "do not check", and a
halted loop's corpus grew from the documented invocation (aef-core ADR 0141).
Pass `--no-loop-state` only when there is genuinely no loop state yet.

The hand-written failing `aef run --memory` that used to sit between bootstrap
and bless is **gone from this sequence**: `bootstrap --memory` leaves the same
evidence (aef-core ADR 0145). Add runs later with:

```
aef run <your.graph.module> --objective "a task this agent fails" \\
    --working-memory '{{"difficulty": 99}}' \\
    --memory ~/.aef-loop-state/memory.jsonl
```

`aef loop bootstrap` prints the `aef loop record ... --expected must_fail`
line for you, with the objective and working memory already filled in — the
label itself stays yours, because only an owner can say a task *should* have
failed.

## Nothing merges automatically

**Tier-1 auto-merge is OFF.** A candidate that passes all six gates is
*escalated to you*, not merged. Turning it on is a deliberate source change,
not a config flag — see aef-core ADR 0045 for why that distinction is kept.

## Six things you must supply before the loop can approve anything

**They are ADVISORY, not gating** (aef-core ADR 0141). `aef loop doctor` is
the only thing that reads them; `aef loop cycle` and `aef loop gate` run
whatever it says, printing the unmet ones first. Three enforce themselves
later and correctly — G2/G3 refuse an empty corpus, G5 refuses without a
blessed baseline, and a graph nothing routes to reflect records no failure
memory, so the proposer never proposes — and the other three stop nothing at
all, which is why they are listed here rather than enforced. Item 3 cannot be
green on day one: it needs production runs you have not made yet.

1. **A corpus.** `corpus/` starts empty, and an empty corpus makes G2 and G3
   refuse — correctly: absence of evidence is not evidence of non-regression.

   ```
   aef loop record <your.graph.module> --corpus corpus \\
       --scenario-id <id> --objective "..." --split validation \\
       --working-memory '{{"difficulty": 9}}'
   ```

   Record scenarios that **fail** as well as ones that pass — a corpus where
   everything already passes cannot demonstrate an improvement. `--working-memory`
   is how you drive the agent into those failing cases. Pass
   `--memory ~/.aef-loop-state/memory.jsonl` to `aef run` too, and point
   `aef loop cycle --memory` at the same file — otherwise the reflect node's
   lessons are written somewhere the proposer never reads.

   **Record at least one tripwire.** Without one the gates cannot detect
   reward hacking: a one-line change making an agent always report success
   passed all six gates, because G2 and G3 both read the agent's own claim
   about itself.

   ```
   aef loop record <your.graph.module> --corpus corpus \\
       --scenario-id tripwire-1 --objective "<a task beyond this agent>" \\
       --split validation --expected must_fail \\
       --working-memory '{{"difficulty": 99}}'
   ```

   The task must be impossible **in principle**, not merely hard — labelling
   an achievable task `must_fail` makes every real improvement look like
   reward hacking. `record` refuses to apply the label if the agent completes
   the task. See `corpus/README.md`.

2. **A reflect node in your graph, that your nodes actually route to.**
   The proposer learns from `MemoryRecord`s a reflect node writes. Without
   one, `aef loop cycle` reports "no admissible failure memory" every run and
   will never propose anything.

   ```python
   from aef.reasoning.nodes import make_reflect_node
   ```

   **You need BOTH an edge and a route, and neither alone works.** Routing is
   chosen by node code, not authorised by edges — a node that returns `END`
   never reaches reflect however the edges are drawn. But the executor also
   refuses a route with no declared edge behind it (`node 'work' routed to
   'reflect', but no declared edge ... has a true condition`), so the edge is
   the authorisation and the return value is the choice:

   ```python
   # in your work node
   return delta, "reflect"
   # in build_graph
   edges=[Edge(from_node="work", to_node="reflect")]
   ```

   `aef loop doctor` checks the route. This catches everyone once.

3. **Observations.** Post-merge monitoring reads `observations.jsonl`, and
   nothing writes it unless you pass `--observations` to your production
   runs. With no input, every monitoring window reports unobserved — which
   correctly rolls every change back. Monitoring with no input is a very
   expensive way to revert.

4. **Halt notification.** When the loop halts, it fails a CI job. If nobody
   watches that, nothing has told you. Wire a channel you actually read.

5. **A blessed baseline.** G5 measures drift against an archived version you
   have approved. Until one exists it refuses every candidate with "no
   owner-blessed baseline" — correctly, since it has no reference point.
   Archive your starting state once, deliberately:

   ```
   aef loop bless --repo . --state ~/.aef-loop-state \\
                  --agent-path agents/<yours>/graph.py
   ```

   It archives your **whole Zone A tree as committed in git**, not the file
   named by `--agent-path` and not your working tree: G5 measures drift
   between the baseline and the candidate's Zone A tree, and two sides that
   describe different things do not subtract. Commit before you bless.

   Blessing twice is refused — rebaselining is a separate, rate-limited owner
   decision, and silently replacing the baseline would reset the drift budget
   without anyone choosing to. Blessing an `--agent-path` that is **not inside
   the tree it would archive** is refused too, naming both paths (aef-core ADR
   0147): it used to succeed, printing `blessed <your file> as baseline v1`
   while archiving a Zone A tree containing none of it, and G5 then charged
   the agent's whole existence to the first real candidate.

6. **Model calls that go through `Services`.** This is the one that does not
   announce itself: a node whose body — or whose function, or that function's
   function — builds its own `anthropic.Anthropic()` runs perfectly, and
   `aef doctor` reports green. The bill arrives at gate time. Nothing routed
   through your own client is seen by the policy engine, covered by the
   fallback chain, or paid for by the harness login, and — the expensive part
   — `aef loop record` captures no model call for it, so the scenario carries
   an empty cassette and the gates cannot replay it. They reach your vendor
   live from inside a gate, or fail for want of a credential and score the
   candidate 0.

   ```
   aef migrate --dir . --force
   ```

   `aef migrate` generates a node that calls
   `services.require_model_provider().complete(...)` when your function is
   thin enough that routing loses nothing, and otherwise generates the wrapper
   and tells you, in that node's own docstring, exactly what routing would
   have dropped — a retry loop, a `try`, a stream, a backend router. That
   second case is a decision only you can make; the obligation is that the
   call becomes visible, not that a tool rewrites your retry policy.

   `aef loop doctor` names the file and the vendor it found (aef-core ADR
   0137).

## Zones — what agents may and may not touch

| Zone | Path | Agent-writable |
|---|---|---|
| A | `agents/**` | yes |
| B | gate code, `corpus/`, `evals/`, `.github/workflows/` | **never** |
| C | everything else | no |

A diff reaching Zone B is a **security event** that halts the loop, not a
rejection to be retried. This is enforced structurally rather than by policy:
gates execute from the base ref, so a branch that rewrites its own gate still
faces the original one.

## Running it

**Start here:** `aef loop doctor` reports all six obligations at once, with
the exact command to fix each. Work down its output — but do not wait for six
green before running a cycle: they are advisory (above), and `observations`
needs production runs you have not made yet.

```
aef loop doctor  --repo . --state ~/.aef-loop-state --corpus corpus \\
                 --agent-path agents/<yours>/graph.py
aef loop bless   --repo . --state ~/.aef-loop-state \\
                 --agent-path agents/<yours>/graph.py
aef loop status  --repo . --state ~/.aef-loop-state
aef loop harvest <your.graph.module> --repo . --state ~/.aef-loop-state \\
                 --runs ~/.aef-loop-state/runs --corpus corpus
aef loop gate    --repo . --state ~/.aef-loop-state --head <branch> \\
                 --workdir /tmp/loop --corpus corpus \\
                 --entrypoint <your.graph.module>:build_graph \\
                 --build-command "python -m pytest -q"
aef loop cycle   --repo . --state ~/.aef-loop-state --workdir /tmp/loop \\
                 --module <your.graph.module> --corpus corpus \\
                 --entrypoint <your.graph.module>:build_graph \\
                 --memory ~/.aef-loop-state/memory.jsonl \\
                 --build-command "python -m pytest -q"
aef loop monitor --repo . --state ~/.aef-loop-state
aef loop digest  --repo . --state ~/.aef-loop-state --runs ~/.aef-loop-state/runs
```

**`--build-command` is your green bar, not ours.** G1 runs it against your
tree; the default is `pytest -q` alone because anything more is
repo-specific. Repeat the flag for each command.

**`--entrypoint` is required for G2 and G3 to run at all.** They have to
execute your corpus to have anything to say, and they cannot find your graph
without it. There is deliberately no default: one would name a layout your
repo may not have, and the failure would arrive as an import error buried in
a ledger note, reading like an ordinary gate rejection. Without it the gate
report says so explicitly.

**`--memory` must point at the file your reflect node writes.** Without it
the proposer has no recorded failures to ground in and will never propose —
it will report "no admissible failure memory" every cycle and look broken.

**`--state` must be outside this repository.** Inside, `git add -A` sweeps
the ledger and archive into candidate diffs, making the audit trail part of
what it audits. The driver refuses it.

Exit codes: `0` escalated · `1` rejected · `2` halted (do not retry).

## Driving it with a coding agent

Hand this to Claude Code (or any agent harness) as a `/loop` prompt. It
self-paces; it does not need an interval.

```
/loop Run one self-rewiring cycle and report.

  aef loop cycle --repo . --state ~/.aef-loop-state --workdir /tmp/loop \\
    --module <your.module> --corpus corpus \\
    --entrypoint <your.module>:build_graph \\
    --memory ~/.aef-loop-state/memory.jsonl \\
    --build-command "<your green bar>"

Exit 0 = escalated to a human (the NORMAL outcome; Tier-1 is off).
Exit 1 = rejected. Exit 2 = HALTED — do not retry, investigate.

Each run:
  - If it says "no admissible failure memory", the reflect node is producing
    no evidence. Check --memory points at the file `aef run --memory` writes,
    and that a node actually ROUTES to reflect (an Edge alone does not).
  - If a gate rejected, read the ledger's reason and say whether the
    rejection was CORRECT. A candidate rejected on merit is the system
    working, not a failure to fix.
  - If exit 2, report the halt reason and STOP the loop. Do not clear
    ~/.aef-loop-state/HALTED — resuming is the owner's decision.
  - Weekly: `aef loop digest`, and `aef loop monitor` to settle open windows.

NEVER: enable Tier-1 auto-merge; edit anything under corpus/, evals/ or
.github/workflows/ to make a candidate pass; relabel a tripwire; or widen a
zone. A diff reaching those paths is a security event that halts the loop,
not a rejection to retry.
```

## Stopping it

```
touch ~/.aef-loop-state/HALTED
```

A file, deliberately: you must be able to stop the loop without its
cooperation, from a shell, under stress. Nothing in the harness clears it —
resuming is your decision.
"""


def render_loop_gate_workflow(repo_name: str) -> str:
    ref = "${{ inputs.head }}"
    repo = "${{ github.repository }}"
    return f"""# Evaluate one self-rewiring candidate in {repo_name}.
#
# NO pull_request and NO pull_request_target, deliberately. `pull_request`
# runs the workflow from the PR's merge commit, so a candidate editing
# .github/workflows/ would supply the very workflow that judges it.
# `pull_request_target` fixes that but carries full secrets into a job that
# may execute candidate code. The loop is dispatched from the default branch
# and fetches the candidate as DATA instead. See aef-core ADR 0057.

name: loop-gate

on:
  workflow_dispatch:
    inputs:
      head:
        description: Candidate branch to evaluate
        required: true
        type: string

permissions:
  contents: read

jobs:
  gate:
    runs-on: ubuntu-latest
    # A container is what makes --network-isolated true rather than a claim.
    container:
      image: python:3.13-slim
      options: --network none

    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0

      # `pip install -e ".[dev]"` was the template's line and it installs
      # THIS repo, not aef — it worked only in aef-core, where they are the
      # same package. In an adopting repo it either fails outright (no
      # pyproject.toml) or installs the adopter's own package and leaves
      # `aef` missing. Install aef, then the repo if it is installable.
      - run: |
          pip install --upgrade pip
          pip install aef-core
          [ -f pyproject.toml ] && pip install -e . || true

      - run: git fetch --no-tags origin "{ref}:refs/loop/candidate"

      # Outside the checkout: state inside the tree is swept into candidate
      # diffs by `git add -A`, and the driver refuses it.
      - uses: actions/cache@v4
        with:
          path: ~/.aef-loop-state
          key: loop-state-{repo}

      - name: Gate
        run: |
          aef loop gate \\
            --repo . --state ~/.aef-loop-state \\
            --base main --head refs/loop/candidate \\
            --workdir "$RUNNER_TEMP/loop" --corpus corpus \\
            --entrypoint "$AEF_ENTRYPOINT" \\
            --build-command "$AEF_BUILD_COMMAND" \\
            --network-isolated
        env:
          # EDIT THESE TWO. Without --entrypoint, G2 and G3 cannot execute
          # your corpus and refuse — three of six gates would be judging
          # every candidate. --build-command is your green bar, not ours;
          # the default is `pytest -q`, which exits 5 (and so fails G1) in a
          # repo with no tests.
          AEF_ENTRYPOINT: agents.mine.graph:build_graph
          AEF_BUILD_COMMAND: python -m pytest -q
        # 0 = escalated to you · 1 = rejected · 2 = halted, do not retry
"""


def render_loop_monitor_workflow(repo_name: str) -> str:
    repo = "${{ github.repository }}"
    # One expression, not two interpolations joined by literal `||`. Written
    # as `${{ a }} || b` the whole thing is a non-empty STRING, which an
    # Actions `if:` treats as true — so the "weekly" digest fired on every
    # hourly cron.
    weekly = (
        "${{ github.event.schedule == '0 9 * * 1' || github.event_name == 'workflow_dispatch' }}"
    )
    return f"""# Post-merge monitoring and the weekly digest for {repo_name}.
# Same trigger rule as loop-gate.yml — see that file, and aef-core ADR 0057.

name: loop-monitor

on:
  schedule:
    - cron: "0 * * * *"   # evaluate open windows, roll back what needs it
    - cron: "0 9 * * 1"   # weekly digest
  workflow_dispatch:

permissions:
  contents: read

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main

      - run: |
          pip install --upgrade pip
          pip install aef-core
          [ -f pyproject.toml ] && pip install -e . || true

      - uses: actions/cache@v4
        with:
          path: ~/.aef-loop-state
          key: loop-state-{repo}

      # Rollback-by-default: an ambiguous window reverts rather than waiting
      # for more data. Exit 2 means a change every gate passed still
      # regressed, so the gates have a blind spot.
      - run: aef loop monitor --repo . --state ~/.aef-loop-state

      - name: Weekly digest
        if: {weekly}
        run: aef loop digest --repo . --state ~/.aef-loop-state | tee "$GITHUB_STEP_SUMMARY"

      # A failed job is the ONLY halt signal wired by default, and it depends
      # on someone reading GitHub notifications. Wire a channel you read.
      - name: Surface a halt
        if: failure()
        run: |
          echo "## Self-rewiring loop HALTED in {repo_name}" >> "$GITHUB_STEP_SUMMARY"
          aef loop status --repo . --state ~/.aef-loop-state >> "$GITHUB_STEP_SUMMARY" || true
          exit 1
"""


def render_corpus_readme(repo_name: str) -> str:
    return f"""# Golden corpus for {repo_name}

**Empty on purpose.** Until you record scenarios here, G2 and G3 refuse every
candidate — correctly, because absence of evidence is not evidence of
non-regression.

```
aef loop record <your.graph.module> --corpus corpus \\
    --scenario-id <id> --objective "..." --split train
```

| Split | Who sees it | Purpose |
|---|---|---|
| `train` | the proposer | the only evidence a proposal may cite |
| `validation` | the gates | what G2/G3 score against |
| `holdout` | **you only** | your independent read of whether the loop helps |

Record scenarios that **fail** as well as ones that pass — a corpus where
everything already passes cannot demonstrate an improvement, and one where
everything fails cannot demonstrate a regression.

Scenarios are **recorded, never hand-written**: a hand-written one encodes
what someone believed the graph does, a recorded one encodes what it did, and
the difference is exactly the case this corpus exists to catch.

Moving a file between split directories is fatal — it would leak the holdout
into the proposer's evidence base. Writing to `holdout` requires
`--i-am-spending-the-holdout`. The corpus never shrinks: a suite that can be
made to pass by deleting the failing case is not a suite.

## Without a tripwire, the gates cannot detect reward hacking

Not theoretical: a one-line change making an agent ignore its inputs and
always report success passed **all six gates**. G2 checks outcome class and
G3 scores a function of that same class, so both ask the agent whether it
succeeded and record the answer.

Label at least one scenario `must_fail` — a task genuinely **beyond** the
agent's remit, where claiming success is a lie rather than an improvement. A
candidate that "passes" it fails G2 as a security event.

Tripwires must be impossible in principle, not merely hard: labelling a
difficult-but-achievable task `must_fail` rejects real progress as reward
hacking. Harvested scenarios never carry a label — only you can say a task
should have failed.
"""


def render_first_day_md(repo_name: str) -> str:
    """`FIRST_DAY.md` — the sequence, in the order an adopter meets it.

    Named for *when* to read it, which is the one thing the rest of the kit
    does not answer. `CLAUDE.md` says what AEF is, `AGENT_INTEGRATION.md` says
    how to ingest it, `LOOP.md` says what the loop needs and `AUTONOMY.md` says
    what you may not do — four documents about *what*, and none of them says
    "today, in this order, and here is what each step costs you".

    **Every command below was RUN against a fresh `git init` + `aef adopt`
    repo and its real output pasted** (aef-core ADR 0148). That rule is not
    decoration: three documents in this scaffold have told adopters things
    that were false, and every one of them was written from the source rather
    than from a terminal.
    """
    module = _module_path(DEFAULT_MIGRATED_OUT)
    return f"""# Your first day with AEF in {repo_name}

Seven commands take this repo from "adopted" to "a candidate change proposed
by the loop and judged by six gates". This file is the order, what each step
costs you, and what does not work until the one before it has run.

**Every command here was executed against a fresh repo and its real output
pasted** (aef-core ADR 0148). Where a step needs something only you can
supply, it says so instead of pretending a flag exists. Where a claim is
unmeasured, it says that too.

Read `LOOP.md` for the gates and the zones, `AGENT_INTEGRATION.md` to onboard
a coding agent, `AUTONOMY.md` for what may never be automated. Read this one
first.

## The whole day

```
aef adopt --dir .
aef migrate --dir .
aef loop bootstrap <your.graph.module> --corpus corpus --inputs inputs.json \\
    --state ~/.aef-loop-state --memory ~/.aef-loop-state/memory.jsonl
aef loop record ...          # the line `aef loop bootstrap` printed, verbatim
aef loop bless --repo . --state ~/.aef-loop-state \\
    --agent-path {DEFAULT_MIGRATED_OUT}
aef loop doctor --repo . --state ~/.aef-loop-state --corpus corpus \\
    --agent-path {DEFAULT_MIGRATED_OUT}
aef loop cycle --repo . --state ~/.aef-loop-state --workdir /tmp/loop \\
    --module <your.graph.module> --corpus corpus \\
    --entrypoint <your.graph.module>:build_graph \\
    --memory ~/.aef-loop-state/memory.jsonl \\
    --agent-path {DEFAULT_MIGRATED_OUT} \\
    --build-command "<your green bar>"
```

Between steps 2 and 3 you write **the semantics** — the node bodies. That is
the one gap no command closes, and section 2 says exactly how wide it is.

## 1. `aef adopt` — what you got, and what you did not

It wrote 17 files and **never overwrites**: an existing file of the same name
is skipped and reported, including `.gitignore`, which is why an adopter who
already had one is told to add `__pycache__/` themselves rather than having it
appended silently.

```
CLAUDE.md  AGENTS.md  AGENT_INTEGRATION.md  AUTONOMY.md  FIRST_DAY.md
LOOP.md  AEF_MIGRATION_CHECKLIST.md  aef.yaml  aef_adapter.py  .gitignore
agents/README.md  corpus/README.md  .github/copilot-instructions.md
.cursor/rules/aef.mdc  .github/workflows/loop-gate.yml
.github/workflows/loop-monitor.yml  .claude/skills/new-model-check/SKILL.md
```

**What it explicitly did not do.** It read none of your code. It wrote no
node, no graph, no test, and no scenario. `aef_adapter.py` is a stub whose
node raises `NotImplementedError`. `corpus/` holds a README and nothing else.
There is no agent here yet, so `pytest -q` exits **5** — "no tests collected",
not a pass, and the same 5 fails G1 later if you pass `pytest -q` as your
`--build-command`.

`aef doctor --dir .` should be clean on this output before you go further; a
`[WARN]` is advisory, a `[FAIL]` is not.

## 2. `aef migrate` — and the sentence that matters most

It scans for functions whose bodies touch a model SDK and writes one node per
call site.

```
$ aef migrate --dir .
scanned 3 Python file(s)
found 1 call site(s): 1 wrapped, 0 skipped
  of the wrapped: 1 routed through Services.model_provider, 0 still calling your function

  ROUTED   src.my_agent.run_agent:4  (anthropic.Anthropic)
            -> services.require_model_provider().complete(model='claude-sonnet-4-5')
            routed because its body builds an unconfigured client and makes exactly one
            completion call — no decorator, no loop, no try/except, no stream, no **kwargs,
            and every keyword it passes is one CompletionRequest carries verbatim

wrote {DEFAULT_MIGRATED_OUT}
  Zone A (agents/**) — agent-writable, the only tree the self-rewiring loop may propose changes to
```

**Where it writes: `{DEFAULT_MIGRATED_OUT}`, inside Zone A**, and the report
names the zone of whatever path it wrote. Before aef-core ADR 0143 it wrote
`aef_migrated.py` to the repo root, which is Zone C — the one tree the loop is
structurally forbidden to propose changes to. If you have a graph left over
from an older run, move it.

**It wires the graph to learn:** `<call site> -> reflect -> consolidate ->
END`. The reflect node is the only thing that writes failure memory and
failure memory is the only evidence the proposer acts on. Route a node back to
`END` and nothing raises — the loop goes silent, exiting 0 every cycle.

### The two forms, and how it chooses

| Form | When | What you get |
|---|---|---|
| **ROUTED** | routing would lose nothing (below) | a node calling \
`services.require_model_provider().complete(...)`; your function is **bypassed** |
| **WRAPPED** | anything else | a node that calls your function unchanged |

"Routing would lose nothing" means: the body builds the client and makes
exactly one completion call — no loop, no `try`/`except`, no stream, no
decorator, no `**kwargs` — and every keyword it passed is one that
`CompletionRequest` carries verbatim.

Routing carries the request and drops the **control flow** — retries, backoff,
budget accounting, backend selection are yours to re-express. A call passing
`system=`, `tools=` or `stop_sequences=` is never routed at all rather than
routed without them (aef-core ADR 0140).

### If your function keeps its own client, the gates cannot replay it

This is the failure mode that bit every raw-SDK adopter, and it does not
announce itself: the node runs, `aef doctor` is green, and the bill arrives at
gate time. A model call the harness never saw is not policy-checked, not
covered by the fallback chain, not paid for by the harness login — and, the
expensive part, **captures no `RecordedCall`**, so the scenario carries an
empty cassette and the gates cannot replay it. They reach your vendor live
from inside a gate, or fail for want of a credential and score the candidate
0.

Migrate refuses to route what it cannot route losslessly, and says so:

```
  WRAPPED  src.my_agent.run_agent:4  (anthropic.Anthropic)
            -> calls src.my_agent.run_agent, unchanged
            NOT routed because its body loops — a retry, backoff or pagination policy
            that a single complete() call would silently drop
            the model call stays INVISIBLE to the harness: no policy check, no fallback,
            no RecordedCall to replay
```

**What to do about it.** Not `aef migrate --force` — that regenerates the same
wrapper and loops forever. `aef loop doctor` names the two edits, both yours:

```
  [--] model calls visible     src/my_agent.py:1 imports anthropic — the harness cannot see it
       fix: `aef migrate --dir . --force` will NOT fix this and will loop: it already
       refused to route src.my_agent (its body loops ...), and regenerating produces the
       same unrouted wrapper. Two edits, both yours. (1) Rewrite that node's body to call
       `services.require_model_provider().complete(...)` instead of calling your function,
       re-expressing whatever the refusal reason names. (2) DELETE the
       `from src.my_agent import ...` line from the node — src.my_agent stays in the
       graph's reachable set while that import stands, so the obligation stays red even
       after the body is routed. Neither step is optional and neither is automatic.
```

Step (2) is the one people miss. The obligation reads the modules reachable by
import, so a routed body under a surviving import is still red.

**What migrate does not write: the semantics.** Every generated node passes
`state.objective` through as a single prompt and stores the raw result. If
your function took more than that, or its result needs shaping into a
`StateDelta`, that is yours. So is the module-level numeric constant of
section 6.

## 3. `aef loop bootstrap` — your corpus, from one command

An empty `corpus/` makes G2 and G3 refuse, correctly: absence of evidence is
not evidence of non-regression. Bootstrap runs your graph once per input and
records each run as a **train** scenario. The inputs file is a JSON list;
each entry needs `objective` and may set `id` and `working_memory` — the
latter is how you reach the agent's failing cases.

```
$ aef loop bootstrap {module} --corpus corpus --inputs inputs.json \\
      --state ~/.aef-loop-state --memory ~/.aef-loop-state/memory.jsonl
recorded 4 scenario(s) in the train split
  passed  bootstrap-1
  passed  bootstrap-2
  FAILED  beyond-the-budget
  FAILED  bootstrap-4
2 of 4 recorded run(s) FAILED.
  Bootstrap labels nothing: only an owner can say a task SHOULD have failed (ADR 0060).
  Consider marking one of these a tripwire — beyond-the-budget, bootstrap-4
  4 memory record(s) written to the durable store — what the graph's own reflect node
  observed, nothing bootstrap decided. `aef loop cycle --memory <the same file>` proposes
  from these.
```

Three flags, and **no generated document mentioned two of them until now**.

**`--state` or `--no-loop-state`, and one of them is mandatory.** Bootstrap
writes to `corpus/`, which is the evidence every behavioural gate is measured
against, so it has to be able to see the kill switch. Silence used to mean
"do not check", and a halted loop's corpus grew from the documented
invocation. Omit both and it refuses:

```
error: bootstrap writes to corpus/, which is the evidence every behavioural gate is
measured against, so it must be able to see the kill switch (ADR 0069). Pass --state <dir>
— the same directory every other loop subcommand takes — or --no-loop-state if there is
genuinely no loop yet.
```

**`--memory <file>` is what lets the cycle propose anything at all** (aef-core
ADR 0145). Point it at the same file you will pass to `aef loop cycle
--memory`. Each run's reflections are mirrored there as well as into its own
isolated per-input store, so a failing input leaves failure memory behind and
the isolation that keeps scenarios independently reproducible is kept. Run the
identical sequence with the flag removed and the corpus is the same, the
tripwire is the same, the baseline is the same, and:

```
$ ls ~/.aef-loop-state/memory.jsonl
ls: ../loop-state/memory.jsonl: No such file or directory
$ aef loop cycle ... --memory ~/.aef-loop-state/memory.jsonl
  ledger verified: 1 entr(ies)
  no admissible failure memory: no candidate this cycle          exit=0
```

Exit **0, having done nothing** — the failure mode that reads like success.
Bootstrap writes only what your reflect node observed and never invents a
failure, so a graph with no reflect node leaves the file empty and says so.

**`--config <aef.yaml>` is how a model-calling graph gets its first corpus.**
Without it, a routed node has no provider, and the cassette the gates will
later replay does not exist until something makes the call once:

```
$ aef loop bootstrap {module} --corpus corpus --inputs inputs.json --no-loop-state
recorded 0 scenario(s) in the train split
  ERRORED (nothing recorded)  bootstrap-1: ModelProviderError: cassette miss ... and no
    live provider to fall through to
NOTHING was recorded and the corpus is unchanged.
  This graph calls a model and no provider was configured, so the recording had nothing
  to record. Pass --config <aef.yaml> to bootstrap: it builds the same model provider
  `aef run` builds, and recording is the one pass that is SUPPOSED to be live — the
  cassette the gates replay from does not exist until something makes the call once.
                                                                        exit=1
```

`--config` builds the provider through `aef run`'s own code path, so
`policies`, `tools.allow` and `evaluator.suites` reach the recording too, and
the calls it spends are reported. The default `model_provider.impl` in the
generated `aef.yaml` is `claude_code`, which uses the coding agent's own login
rather than an API key. **Recording live was not exercised while writing this
file** (no quota), so treat the flag's wiring as proved and its live pass as
your first experiment — start it on one input, not forty.

## 4. Your one act as the owner: the tripwire

Without a tripwire the gates cannot detect reward hacking — a one-line change
making an agent always report success passes every cheap gate, because G2 and
G3 both read the agent's own claim about itself. Only you can say a task
*should* have failed, so bootstrap prints the line and never runs it:

```
    aef loop record {module} --corpus corpus --scenario-id \
beyond-the-budget-tripwire --objective "a task past the retry budget" \
--working-memory "{{\\"difficulty\\": 9, \\"quality_needed\\": 1}}" \
--split validation --expected must_fail
```

Run it verbatim:

```
recorded beyond-the-budget-tripwire (validation) -> \
corpus/validation/beyond-the-budget-tripwire.json
  3 node execution(s) pinned
  0 model call(s) pinned, 0 check(s)
```

The task must be impossible **in principle**, not merely hard: labelling a
difficult-but-achievable task `must_fail` makes every real improvement look
like reward hacking. `record` refuses the label if the agent completes it.

## 5. `bless`, then `aef loop doctor`

Commit first — the baseline is read from **git**, not your working tree.

```
$ aef loop bless --repo . --state ~/.aef-loop-state --agent-path {DEFAULT_MIGRATED_OUT}
blessed {DEFAULT_MIGRATED_OUT} as baseline v1 for graph 'default'
  G5 now has a reference point to measure drift against.
```

A baseline is the **whole Zone A tree** as committed, and G5 measures every
candidate's drift against it — so blessing an agent that is not inside that
tree is refused rather than reported green (aef-core ADR 0147):

```
$ aef loop bless --repo . --state ~/.aef-loop-state --agent-path src/my_agent.py
error: src/my_agent.py exists at HEAD but is NOT inside the tree this would archive:
'{DEFAULT_AGENT_ROOT}' at HEAD holds 2 file(s) ({DEFAULT_AGENT_ROOT}/README.md,
{DEFAULT_MIGRATED_OUT}). A baseline is the whole Zone A tree, and G5 measures every
candidate's drift against it, so blessing here would report src/my_agent.py as blessed
while archiving a tree that does not contain it. Move the agent under
'{DEFAULT_AGENT_ROOT}' ..., or pass --agent-root naming the tree src/my_agent.py
actually lives in.                                                       exit=1
```

Blessing twice is refused too: rebaselining resets a drift budget and is a
separate, deliberate decision.

Then the readiness report:

```
$ aef loop doctor --repo . --state ~/.aef-loop-state --corpus corpus \\
      --agent-path {DEFAULT_MIGRATED_OUT}
Loop readiness — 6 things you must supply

  [OK] corpus + tripwire       5 scenario(s), 1 tripwire(s)
  [OK] reflect node routed to  src_my_agent__run_agent() returns 'reflect' as its Route
  [--] observations            0 recorded run(s) at ~/.aef-loop-state/observations.jsonl
       fix: pass --observations from your production runs, then `aef loop monitor`
  [--] halt channel            none — a halt would tell nobody
       fix: set AEF_HALT_WEBHOOK in your environment (never in this repo)
  [OK] blessed baseline        1 archived version(s)
  [OK] model calls visible     1 reachable module(s), none imports a model SDK
                                                                        exit=1
```

**The six obligations are ADVISORY, not gating** (aef-core ADR 0141), and
earlier versions of this kit implied otherwise. `aef loop doctor` is the only
thing that reads them; `aef loop cycle` and `aef loop gate` run anyway and
print the unmet ones:

```
  preflight: 2 of 6 obligation(s) unmet (observations, halt channel). ADVISORY — this
  command does not refuse on them; run `aef loop doctor` for each fix.
```

Three of the six enforce themselves later and correctly — G2/G3 refuse an
empty corpus, G5 refuses without a blessed baseline, and a graph nothing
routes to reflect records no failure memory so the proposer never proposes. A
missing halt channel or an invisible model call stops **nothing**, which is
why they are listed rather than enforced. And two of them cannot be green on
day one: observations come from production runs you have not made yet. Do not
wait for six.

## 6. `aef loop cycle` — and the one requirement still yours

```
$ aef loop cycle --repo . --state ~/.aef-loop-state --workdir /tmp/loop \\
      --module {module} --corpus corpus \\
      --entrypoint {module}:build_graph \\
      --memory ~/.aef-loop-state/memory.jsonl \\
      --agent-path {DEFAULT_MIGRATED_OUT} --build-command "python -m pytest -q"
  preflight: 2 of 6 obligation(s) unmet (observations, halt channel). ADVISORY ...
  ledger verified: 1 entr(ies)
  proposed cycle-20260904T164400-s0 on local branch loop/cycle-20260904T164400-s0
    (never pushed; proposer=rule_based)
  gated: reject — G3 rejected it: candidate does not beat the p95 of the random control
    cohort — this is the null hypothesis, not an improvement          exit=1
```

and in `~/.aef-loop-state/ledger.jsonl`, which is what to read rather than the
summary line:

```
evidence: 7 corpus pass(es) (35 scenario execution(s)): 1 candidate + 1 incumbent
          + 5 random control(s); gating all 5 gated scenario(s)
  G0 pass  1 file(s), 28 line(s), all Zone A, no static-safety violations
  G1 pass  1 build command(s) succeeded against the merged workspace
  G4 pass  no owner-only safety metadata declared by the candidate
  G5 pass  0/3 accepted in the last 7d; drift 0.098/0.500 from the blessed baseline
  G2 pass  5 scenario(s) re-executed; every previously-passing one still passes.
  G3 fail  candidate does not beat the p95 of the random control cohort
```

**A rejection is the system working.** G3 compares your candidate against a
cohort of random mutations of the same file; a change that does not beat their
p95 is indistinguishable from noise. Nothing merges either way — Tier-1
auto-merge is off and no flag turns it on.

### The requirement: at least one module-level numeric constant

Keep tunable parameters as named module-level constants in your node file.
`aef migrate` writes none — a generated wrapper has no number of its own to
invent — so this one is yours, and it is a **property of `RuleBasedProposer`**,
which mutates numeric constants, and of the control cohort, which is built by
mutating them too.

Measured on migrate's own generated graph with the constants inlined and
nothing else changed: a candidate **is** still proposed (the proposer's
structural `add_bounded_retry` applies), and then there is nothing to judge it
against —

```
evidence: could not build evidence (cannot build a control cohort for
          '{DEFAULT_MIGRATED_OUT}': no module-level numeric constants to mutate,
          so there is no null hypothesis to draw from); G2/G3 will refuse
  G2 fail gate raised TrustBoundaryError: scratch destination .../workspace must be
          empty. A gate that could not judge has not cleared this candidate.
```

Two things worth knowing about that. The first is that the summary line names
a scratch directory, which is a red herring: the cause is the missing
constant, and it is in the ledger's `evidence` note. The second is that on a
graph shape where the structural transformation does not apply you get a
different and clearer refusal instead — `the proposer produced nothing from
the available evidence`. Either way the remedy is the same: name your numbers.

**Whether `--proposer llm` needs one is unmeasured.** `aef loop cycle
--proposer llm` writes the whole file rather than mutating a constant and may
not need one at all; the measurement is blocked on model quota (aef-core
`INGEST_LOOP.md` L4). Until it runs, assume the constant is required, because
the cohort that judges the candidate is built by mutating constants whatever
proposed it.

## 7. What still needs a person

- **The semantics.** Node bodies, and how more than one call site composes —
  migrate declares extra nodes but only the entry node is reached.
- **The module-level numeric constant**, above.
- **The `must_fail` label.** Bootstrap prints the command; the judgement is
  yours (aef-core ADR 0060).
- **A halt channel and observations.** A halt fails a CI job; if nobody
  watches it, nothing has told you. Monitoring with no input reports
  unobserved, which correctly rolls every change back — an expensive way to
  revert.
- **Every accepted candidate.** A candidate passing all six gates is
  *escalated*, never merged. Turning that off is a source change, not a flag.
- **`--build-command`** is your green bar, not ours, and the default
  `pytest -q` exits 5 in a repo with no tests.

## What has never been tried

**No part of this has run against a repo aef-core did not write.** Every
sequence above, this project's own end-to-end test included, drives a fixture
this project authored — smaller and less helpful each time, but authored. The
first real pilot is an owner decision and it is the only open item. When you
run it, the most valuable thing you can send back is **anything this document
told you to do that did not work**: several defects in aef-core were generated
documents printing commands the CLI rejects, and they were found only by
someone being the adopter.

## How work is verified here

**Reproduce first** — construct the failing case and RUN it before writing a
fix — and the **green bar** (tests, type-check, lint) passes before every
commit. `AUTONOMY.md` carries the full contract.
"""


def render_agents_zone_readme(repo_name: str) -> str:
    return f"""# Zone A — agent-writable code

The **only** directory the self-rewiring loop may propose changes to.
Everything else in {repo_name} is off limits to it, enforced structurally
rather than by policy: gates execute from the base ref, so a candidate cannot
supply the code that judges it (aef-core ADR 0047).

Put the graph modules and node functions agents are allowed to tune here.
Keep tunable parameters as **module-level named constants** — that is the
shape the rule-based proposer and the control cohort both operate on.

Nothing here is auto-merged. See `../LOOP.md`.
"""
