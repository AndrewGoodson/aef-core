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


def render_loop_md(repo_name: str) -> str:
    return f"""# The self-rewiring loop in {repo_name}

Agents here may propose changes to their own code. An automated gate pipeline
judges every proposal before anything merges. This file says what works, what
does not yet, and what only you can decide.

## Nothing merges automatically

**Tier-1 auto-merge is OFF.** A candidate that passes all six gates is
*escalated to you*, not merged. Turning it on is a deliberate source change,
not a config flag — see aef-core ADR 0045 for why that distinction is kept.

## Three things you must supply before the loop can approve anything

1. **A corpus.** `corpus/` starts empty, and an empty corpus makes G2 and G3
   refuse — correctly: absence of evidence is not evidence of non-regression.

   ```
   aef loop record <your.graph.module> --corpus corpus \\
       --scenario-id <id> --objective "..." --split train
   ```

   Record scenarios that **fail** as well as ones that pass. A corpus where
   everything already passes cannot demonstrate an improvement.

   **Label at least one scenario `must_fail`.** Without a tripwire the gates
   cannot detect reward hacking: a one-line change making an agent always
   report success passed all six gates, because G2 and G3 both read the
   agent's own claim about itself. See `corpus/README.md`.

2. **Observations.** Post-merge monitoring reads `observations.jsonl`, and
   nothing writes it unless you pass `--observations` to your production
   runs. With no input, every monitoring window reports unobserved — which
   correctly rolls every change back. Monitoring with no input is a very
   expensive way to revert.

3. **Halt notification.** When the loop halts, it fails a CI job. If nobody
   watches that, nothing has told you. Wire a channel you actually read.

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

```
aef loop status  --repo . --state ~/.aef-loop-state
aef loop gate    --repo . --state ~/.aef-loop-state --head <branch> --workdir /tmp/loop
aef loop monitor --repo . --state ~/.aef-loop-state
aef loop digest  --repo . --state ~/.aef-loop-state
```

**`--state` must be outside this repository.** Inside, `git add -A` sweeps
the ledger and archive into candidate diffs, making the audit trail part of
what it audits. The driver refuses it.

Exit codes: `0` escalated · `1` rejected · `2` halted (do not retry).

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

      - run: pip install --upgrade pip && pip install -e ".[dev]"

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
            --network-isolated
        # 0 = escalated to you · 1 = rejected · 2 = halted, do not retry
"""


def render_loop_monitor_workflow(repo_name: str) -> str:
    repo = "${{ github.repository }}"
    weekly = "${{ github.event.schedule == '0 9 * * 1' }}"
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

      - run: pip install --upgrade pip && pip install -e ".[dev]"

      - uses: actions/cache@v4
        with:
          path: ~/.aef-loop-state
          key: loop-state-{repo}

      # Rollback-by-default: an ambiguous window reverts rather than waiting
      # for more data. Exit 2 means a change every gate passed still
      # regressed, so the gates have a blind spot.
      - run: aef loop monitor --repo . --state ~/.aef-loop-state

      - name: Weekly digest
        if: {weekly} || github.event_name == 'workflow_dispatch'
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
