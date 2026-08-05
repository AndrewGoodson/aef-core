# ADR 0097: The marker nothing set

## Status
Accepted. Found while building Milestone 1's acceptance test, which is the
only reason it was found at all.

## Context

ADR 0076 added `RECOVERED_KEY` so a run that recovered from a transient error
would stop being scored identically to one that gave up. It closed with:

> **Not claimed:** that anything currently *sets* the marker. Nothing in this
> repo does.

That was honest and it was also the whole problem. Milestone 1's first
structural transformation gives a failing node a `fallback_node_id` — the
AEF-native answer to "this node raises". Running the acceptance test:

```
INCUMBENT    CRASHED  RuntimeError: upstream timed out
PROPOSED     passed=False  plan=done  path=['fetch', 'use_cache']
```

The repair **worked** — the crash became a completed run through the
fallback — and scored as a failure, because the executor's fallback path
appends an error entry and nothing marked it recovered.

So the loop could produce the fix and could never be rewarded for it. G3 would
see no improvement; G2 would see a scenario that still does not pass. **The
first structural repair the proposer can make was unscoreable.**

## Decision

The executor sets the marker when a declared fallback takes over.

That is the one place in the system which knows both that a node raised *and*
that control continued anyway. It is Zone B, so the marker keeps the property
ADR 0080 found `recovered` lacked when agent code wrote it: a candidate cannot
set it about itself.

`RECOVERED_KEY` moved from `aef/harness/outcome.py` to `aef/state/schema.py`.
The kernel needs it now, the gates already did, and **the kernel must not
import the harness** — a layering inversion is how you get a kernel that
cannot be used without the thing built on top of it.

After:

```
PROPOSED  passed=True  errors=1  recovered=1  path=['fetch', 'use_cache']
```

The error is still counted and still reported. Recovered, not erased — "the
agent recovered from one failure" and "the agent had no failures" remain
different facts, which is what ADR 0076 built the separate counter for.

## Why this was invisible for two nights

Ten adversarial rounds did not find it, and the reason is worth recording: it
is not a defect in anything that existed. Every consumer of `recovered` was
correct. The executor's fallback path was correct. **The gap was between a
capability nobody had exercised and a marker nobody had set**, and it became
visible the instant something tried to use both at once.

That is the argument for acceptance tests that demand a *repair* rather than
a *diff*. Milestone 1 could have shipped a proposer that produced a
well-formed, well-cited, gate-passing change that the scoring could not
reward, and every test would have been green.

## Confidence
High: reproduced before and after by running the same agent both ways, with
the incumbent's crash as the control. **Not claimed:** that this is the only
place a recovery goes unmarked. A node that catches its own exception and
continues is recovering too, and nothing marks that — it is agent-side, so
the marker there would be agent-written, which ADR 0080 showed is worthless.
Recovery that the *harness* can see is now marked; recovery only the agent
can see is not, and probably should not be.
