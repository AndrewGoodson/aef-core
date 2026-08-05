# ADR 0095: Confinement and honesty are different jobs

## Status
Accepted. Closes the regression ADR 0094 recorded against itself.

## Context

ADR 0094 moved the candidate's code into a worker process so it could no
longer author the evidence judging it. It bought that by dropping something
else, and said so:

> **Stated regression:** the worker is a plain subprocess, so `SandboxPolicy`
> rlimits/timeout are not applied to it.

`run_variant` accepted a `SandboxPolicy` and began with `del policy`. The one
process running agent-authored code had:

- no rlimits (`RLIMIT_AS`, `RLIMIT_FSIZE`)
- no process group, so nothing could kill its descendants
- a hand-rolled environment, so `SandboxPolicy.env_allowlist` — the thing
  that decides what a candidate can read a credential out of — did not apply
- no timeout of any kind

**Defence against a dishonest candidate had been traded for defence against a
runaway one.** Those are different jobs and the system needs both.

## Decision

The worker gets exactly the confinement a sandboxed command gets, from the
same code rather than a second copy — `sandbox.py` now exports
`child_preexec`, `scrubbed_env` and `kill_process_group`, and
`NodeWorkerSession` takes a `SandboxPolicy`. A parallel implementation would
drift, which is the defect ADR 0091 named.

**Plus one thing a long-lived worker needs and a one-shot command does not: a
per-step deadline.** `SandboxPolicy.timeout_s` bounds a whole command. A
worker answers many nodes over its life, and the parent is what waits — so a
node that never returns hangs *the gate*, the one process a candidate must
not be able to stop. `select` bounds each read; a timeout kills the worker's
process group and the scenario fails with the reason.

Verified by running, each with a control:

| Property | Result |
|---|---|
| Credentials reach the worker | `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY` → `None`; worker sees `HOME, LANG, PATH, PYTHONPATH, TMPDIR` |
| A node that sleeps 60s | gate returns in 2.1s, scenario fails with the reason |
| A grandchild that outlives its parent | killed with the group; marker never appears |
| An honest agent under full confinement | still passes 3 of 3 |

That last row is the one that matters most: confinement which rejects honest
agents is not confinement, it is a broken gate.

## What is still true

The two defences remain independent, and neither substitutes for the other:

- **Isolation (ADR 0094)** stops a candidate *bypassing* the judgement.
- **Confinement (this ADR)** stops a candidate *outliving or exhausting* the
  process judging it.

A candidate can still return a lying `StateDelta`. That is the node contract,
and it is what the corpus and `MUST_FAIL` tripwires judge (ADR 0060).

## Open

`sandbox.py` still states plainly that it enforces neither network egress nor
filesystem confinement, and that is unchanged — those need a container, a
seccomp filter or a separate UID, which is option (c) from the morning report
and a deployment decision rather than a code one. What this ADR closes is the
gap between what the harness *already had* and what the worker was *given*.

## Confidence
High: every property was reproduced by running against a real worker, and the
honest-agent control passes under the same policy. **Not claimed:** that the
per-step deadline is correctly defaulted. It falls back to
`SandboxPolicy.timeout_s`, which is a whole-command budget and therefore
generous for a single node; an owner whose nodes are fast should set it lower
and will get faster failures for it.
