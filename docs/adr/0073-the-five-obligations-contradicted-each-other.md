# ADR 0073: The five obligations contradicted each other

## Status
Accepted. Phase 1 of the adopter-unblock run. Three defects, one of them a
direct contradiction between two documented requirements.

## Context
`LOOP.md` lists five things an adopter must supply. An adopter discovered
them one refusal at a time, in the worst possible order: run the loop, hit a
refusal, fix one thing, hit the next. Nothing reported them together, and one
of them could not be satisfied at all.

## Defect 1 — obligation 5 was unmeetable

`LOOP.md` told owners to archive a blessed baseline. **No command existed to
do it.** `archive.record` was called from exactly one place — the auto-merge
branch, unreachable while Tier-1 is off — so G5 refused every candidate
forever with "no owner-blessed baseline", and there was no way out.

Added `aef loop bless`. Blessing twice is **refused**: rebaselining is a
separate, rate-limited owner decision (G5, ADR 0053), and silently replacing
the baseline would reset the drift budget to zero without anyone choosing to.

## Defect 2 — obligation 2 made obligation 3 impossible

Obligation 2 tells an adopter to put a reflect node in their graph. Every
reflect node requires `critic` and `judge` on `Services`.

**`aef run` wired neither.** So the moment an adopter satisfied obligation 2,
`aef run` died with `ServiceNotConfiguredError` — and `aef run` is how
obligation 3 (observations) is satisfied. **Following one documented
requirement made another impossible.**

The same omission was in `aef loop record`, so an adopter could not record a
corpus scenario from the agent they had just been told to build either —
obligation 1 broken by the same cause.

Both now wire `RuleBasedCritic`/`RuleBasedJudge`, and `aef run --memory`
points the reflect node at a durable store the proposer can later read.

## Defect 3 — `doctor` printed a command the CLI rejects

The fix text read `aef loop bless <module> …`; `bless` takes no module and
argparse refused it. Same shape as ADR 0069's defect #10: a documented
command the tool does not accept. Now asserted by a test.

## The near-miss: the detector passed the trap it existed to catch

`doctor` checks that a node **routes** to the reflect node, because an `Edge`
does not wire it — the trap in ADR 0070. The first implementation scanned
every `Return` in the module and matched
`Edge(to_node="reflect")` **inside `build_graph`'s return statement**, so a
graph with an edge and no routing reported OK.

It was caught only by a planted-fault test built specifically to fail. The
detector now scans returns inside three-argument node functions only.

This is the second time in this program that an audit tool returned a false
negative on the exact property it was written to check (ADR 0063 was the
first). The rule in `reproduce-first` — *verify a detector against a planted
fault before trusting "nothing found"* — is now earning its place twice over.

## Consequences
- `aef loop doctor` reports all five obligations at once, each with the
  runnable command that fixes it, exiting non-zero until all five pass.
- **A fresh adopted repo was driven to all five green**, an end state nobody
  had reached. That path is now an integration test.
- `LOOP.md` leads with `doctor` rather than with the commands that will
  refuse.

## Confidence
High: every defect was found by being stuck while following the repo's own
instructions, and the fixed path was executed end to end. **Not claimed:**
that five is the complete set of obligations. Five is what has been
discovered by getting stuck five times, and the sixth will be found the same
way.
