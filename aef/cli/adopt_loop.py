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
4. **At least one FAILING `aef run --memory <file>`**, pointed at the same
   file `aef loop cycle --memory` reads. Otherwise: the same line as 3.
   `aef loop bootstrap` cannot do this for you — it gives every input its own
   in-memory store, so nothing it learns survives the process.
5. **Scenarios in `corpus/`**, train or validation. Otherwise:
   `no corpus: G2/G3 will refuse for lack of evidence`
6. **A blessed baseline.** Otherwise G5 has no reference point for drift.
7. **`--entrypoint` on the cycle itself.** Otherwise:
   `no entrypoint configured: G2/G3 will refuse`

**`aef migrate` writes two of the first four, and cannot write the other
two.** It lands the graph at `{DEFAULT_MIGRATED_OUT}` (item 1, Zone A) and
wires `<call site> -> reflect -> consolidate -> END` (item 3). Items 2 and 4
are still yours, and neither is an oversight:

- **no module-level numeric constant** — item 2 is the shape the rule-based
  proposer mutates, and a generated wrapper has no number of its own to
  invent. Your node body is where one goes.
- **`aef migrate` cannot make a run fail** — item 4 is an observation, and
  ADR 0060's rule holds here as everywhere: the loop records what happened
  and never invents a failure.

The previous version of this paragraph said migrate writes *none* of the
four. That was true when ADR 0139 measured it and false the day ADR 0143
landed; it is corrected here rather than quietly deleted.

**Your first corpus cannot come from a model-calling graph unless you have a
credential.** The cassette the gates later replay from does not exist until
something makes the call once, so `aef loop bootstrap` on a routed node exits
1 with `no live provider to fall through to`. Either configure
`model_provider` in `aef.yaml` and record once for real, or start the loop on
a graph that calls no model. It is not a limitation you can document your way
around.

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
aef loop bootstrap <your.graph.module> --corpus corpus --inputs inputs.json
aef loop record <your.graph.module> --corpus corpus --scenario-id tripwire-1 \\
    --objective "<a task beyond this agent>" --split validation \\
    --expected must_fail --working-memory '{{"difficulty": 99}}'
aef run <your.graph.module> --objective "a task this agent fails" \\
    --working-memory '{{"difficulty": 99}}' \\
    --memory ~/.aef-loop-state/memory.jsonl
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

`aef loop bootstrap` prints the `aef loop record ... --expected must_fail`
line for you, with the objective and working memory already filled in — the
label itself stays yours, because only an owner can say a task *should* have
failed.

## Nothing merges automatically

**Tier-1 auto-merge is OFF.** A candidate that passes all six gates is
*escalated to you*, not merged. Turning it on is a deliberate source change,
not a config flag — see aef-core ADR 0045 for why that distinction is kept.

## Six things you must supply before the loop can approve anything

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
   without anyone choosing to.

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
the exact command to fix each. Work down its output until every line is OK.

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
