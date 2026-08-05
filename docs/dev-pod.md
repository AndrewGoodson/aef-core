# The development pod

Tooling for developing **this** repo. Deliberately small.

| | What it is | When to reach for it |
|---|---|---|
| `.claude/skills/reproduce-first/` | The verification method, extracted from seven loop prompts | Any verification, audit, or fix |
| `.claude/agents/seam-hunter.md` | An agent that hunts joins between correct components | Something is green but does not work; you are wiring two modules |

## Why only two

Ten defects were found in this repo. **All of them by loop prompts, none by a
subagent.** Four more agents were designed — adversary, claim-auditor, scribe,
and an orchestrator — and cut, because each duplicated a lens a loop prompt
already carries. A well-written prompt *is* an agent definition; it just
lives in a message instead of a file. Moving it to a file buys reuse, not
capability, and is only worth doing for something repeated many times.

`reproduce-first` earned its place: it was copy-pasted into seven prompts.
`seam-hunter` earned a trial: seams hid three of the ten defects and are the
category most often missed.

Build the others when a prompt demonstrably cannot do the job — not before.

## What this is NOT

**Not independence.** Every agent here is the same model reading the same
repo. It adds breadth and discipline, not a second opinion. If you want
genuine independence, the lever is a different model or a human reading the
diff.

**Not autonomy.** These are prompt definitions. They sit inert until
something invokes them. Nothing here wakes up, schedules itself, or
remembers.

**Not for `agents/`.** That directory is Zone A — agent-writable, inside the
self-rewiring loop's blast radius. Development tooling lives in `.claude/`
and must stay there.

## Re-evaluate on every model upgrade

A prompt tuned for one model can become a ceiling for a better one. If a
newer model would find defects by an approach these definitions do not
describe, the definitions are now the limit. Treat them as current best
practice, not infrastructure.
