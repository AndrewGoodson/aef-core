# ADR 0108: The graph that remembers, and the rule that was a proxy

## Status
Accepted. Milestone 1 of the mind-graph program, plus the resolution of a
HARD-STOP raised during it.

## Part 1 — Accumulation

A snapshot forgets. `aef/dash/memory.py` remembers where nodes sat, how often
each path has ever been taken, when each was last taken, and when each node
was first seen.

**Everything is derived from `Provenance`**, which the executor already writes
per node execution. The load-bearing observation: *consecutive provenance
entries within one run ARE the edge traversals.* No new collection, no new
field — which HARD-STOP #8 forbids.

**Not recoverable, and reported rather than papered over:** `Provenance` has no
error field, so per-node error rate reads UNKNOWN from this source.

### Two quantities, never collapsed

The requirement was that "never fired" and "stopped firing" must not render the
same. The guarantee is to stop conflating them into one number:

- `traversals` — cumulative, **never decays**, drawn as THICKNESS
- `last_traversed` — a timestamp, drawn as BRIGHTNESS via `liveness()`, which
  returns **None** when the path has never fired

`liveness()` returning `None` rather than `0.0` is the whole design. A `0.0`
would render identically to "abandoned", and those are different claims: one is
a measurement, the other an absence. Measured across three generations:

```
edge                       traversals  liveness   reads as
classify->enrich                  351      0.86   LIVE (thick, bright)
classify->fetch_invoice            30      0.00   ABANDONED (thick, dim)
reflect->classify                   0      none   NEVER FIRED (thin, dashed)
```

Positions are rounded to one decimal so the file does not churn; a memory file
that differs on every write cannot be diffed, so nobody notices the change that
mattered. A corrupt memory file **raises** rather than starting fresh —
starting fresh would erase the history and redraw it as a graph that has simply
never seen much, which is absence-looking-like-health one layer down.

## Part 2 — `<button>` was a proxy, and it caught the wrong thing

`FORBIDDEN_HTML_CONSTRUCTS` banned `<button`, `onclick=` and `onchange=` as
stand-ins for "a control". The first page needing to switch between views
tripped it, and the test went red.

The property being protected is a **write path**: a page that can approve a
candidate or release the kill switch is an unaudited control plane reachable by
anyone who can open a file. A tab that changes which locally-loaded data is
drawn writes nothing, requests nothing, stores nothing. The proxy was catching
*interactivity*.

This was raised as a HARD-STOP and **not** resolved by deleting the entry —
that is the "weaken a control to make something pass" move this program
forbids. It was resolved by the owner supplying an external specification whose
constraint list bans `<form` and says nothing about `<button`.

**Replaced, not trimmed** (ADR 0093's precedent), and the replacement is
stricter where it counts. It adds `sessionStorage`, `indexedDB`, external
`src=`/`href=`/`@import`/`url(http...)` references, and `Math.random`.

That last one **caught a live violation**: `mind.py` seeded edge particle
phases with `Math.random()`, so identical data drew a different picture on
every load — quietly incompatible with the persisted-layout property Part 1
exists to provide. Now a golden-ratio sequence over the edge index.

Swapping `<button>` for `<div role="tab">` was considered and rejected: it
would pass the test while changing nothing real, which is evasion dressed as
compliance.

## The adversarial round — six reproduced

1. **A node with `runs=0` could declare itself `healthy`.** The milestone's own
   central rule, unenforced. On a graph this is worse than on a panel: an
   un-instrumented node still draws as a perfectly nice circle, and there is no
   empty space to notice.
2. **A non-finite position** serialised as bare `Infinity`/`NaN`, which is not
   valid JSON — `JSON.parse` throws and the **entire page renders blank** from
   one coordinate.
3. **Negative traversals** reach the canvas as `Math.log1p(-5)` = NaN, so
   `lineWidth` is NaN and the edge **silently vanishes**.
4. **Duplicate node ids** — the layout indexes by id, so one node is discarded
   and its edges re-pointed, leaving a graph that looks whole and is not.
5. **Liveness outside [0, 1]** — alpha clamps silently, so it renders as an
   ordinary line meaning nothing.
6. **`traversals=0` with a non-None liveness** — breaks the invariant the whole
   encoding rests on.

Plus one found while patching: the design pass renamed the CSS variable
`--hitl` to `--warn`, but the JS still read `css('--hitl')`, which returns `""`
— and `strokeStyle = ""` silently keeps the previous colour, so the
approval-gate ring drew in the wrong one.

And one structural fix: validation lived in `to_payload()`, so an invalid graph
could be constructed and passed around, failing only if it was ever serialised.
Moved to `__post_init__`.

## Consequences

24 new tests. The next milestone (drill-down) inherits a contract where the
visual encoding cannot claim something the data does not, and where the layout
is reproducible from the data alone.
