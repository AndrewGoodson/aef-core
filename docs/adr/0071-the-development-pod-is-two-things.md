# ADR 0071: The development pod is two things, deliberately

## Status
Accepted. Phase 2.

## Context
Ten defects had been found in this repo. **All by loop prompts; none by a
subagent.** A pod of six agents was designed, mirroring a working setup in
another repo. Most of it was cut before building.

## Decision

**Two artefacts:**

- `.claude/skills/reproduce-first/SKILL.md` — the verification method,
  extracted from seven loop prompts that each restated it. Construct the
  failing case and run it; report reproduced and suspected separately; assert
  every patch applied before and after; verify a detector against a planted
  fault before trusting "nothing found"; never weaken a control to make
  something pass; a test pinning wrong behaviour is worse than none.
- `.claude/agents/seam-hunter.md` — hunts **joins** between components that
  are each correct and each tested. Three of the ten defects lived there.

**Cut: adversary, claim-auditor, scribe, orchestrator.** Each duplicated a
lens a loop prompt already carries. A well-written prompt *is* an agent
definition; moving it to a file buys reuse, not capability, and is only worth
doing for something repeated many times. `reproduce-first` was repeated seven
times. The others were not repeated at all.

**Nothing under `agents/`.** That is Zone A — agent-writable, inside the
self-rewiring loop's blast radius. Development tooling lives in `.claude/`.

## The trial run, and what it returned

An agent definition that has never been run is a hypothesis about a prompt.
`seam-hunter` was invoked once, on the join between `aef loop monitor`, the
archive, and the ledger.

**It found three defects, all reproduced, on its first run** — recorded
separately as ADR 0072. Two were serious: a fabricated baseline that would
halt the loop on any agent below 95% live pass rate, and a rollback that
restored the change it was reverting.

That result is the strongest evidence available for keeping the agent and for
having cut the others: the seam lens found in one invocation what seven loop
prompts and a full green suite had not.

## Consequences
- The pod adds **breadth and discipline, not independence.** Every agent here
  is the same model reading the same repo. Genuine independence needs a
  different model or a human reading the diff, and this does not provide it.
- These are prompt definitions. They sit inert until invoked; nothing wakes
  up, schedules itself, or remembers.
- **Re-evaluate on every model upgrade.** A prompt tuned for one model can
  become a ceiling for a better one — if a newer model would find defects by
  an approach these definitions do not describe, the definitions are now the
  limit. Treat them as current best practice, not infrastructure.

## Confidence
High that two was the right number, on evidence: one earned its place by
being repeated seven times, the other by finding three defects immediately.
Medium on whether the cut agents stay cut — if a future run shows a prompt
repeatedly failing at adversarial construction or claim auditing, that is the
signal to build them.
