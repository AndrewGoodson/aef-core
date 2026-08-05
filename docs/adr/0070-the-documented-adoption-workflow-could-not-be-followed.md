# ADR 0070: The documented adoption workflow could not be followed

## Status
Accepted. Phase 1 — running `aef adopt` and then following `LOOP.md`
literally, for the first time.

## Context
Adoption had only ever had a smoke-level pass: `aef adopt` was run, the file
count was checked, and nothing followed the instructions those files contain.
Defect #10 (ADR 0069) lived in exactly that gap — G1's defaults assumed
aef-core's own tree, so every candidate in every adopting repo was rejected
forever, silently.

This pass executed the whole documented sequence verbatim in a fresh repo.
All six commands ran. Two things stopped an adopter from actually using them.

## Defect — `aef run` could not produce a failing run

`LOOP.md` instructs: *"Record scenarios that fail as well as ones that pass —
a corpus where everything already passes cannot demonstrate an improvement."*

`aef run` accepted only `--objective`. There was **no way to seed
`working_memory`**, so an adopter could not drive their agent into a failing
case, could not record one, and therefore could not harvest anything. The
first instruction in the workflow could not be carried out with the tools the
workflow provides.

Added `--working-memory` (a JSON object). Verified by producing a failing run
and harvesting it: *"promoted 1 run(s) to the train split"*.

## Defect (documentation) — the reflect-node requirement was unstated

`aef loop cycle` reported *"no admissible failure memory: no candidate this
cycle"* and would have forever. The proposer learns from `MemoryRecord`s a
**reflect node** writes, and `LOOP.md` never said the agent needs one.

Worse, the obvious way to add one does not work: **an `Edge` to a reflect
node does not route to it.** Routing is chosen by node code, not authorised
by edges (ADR 0047), so a work node returning `END` never reaches reflect
however the edges are drawn. This catches everyone once — it caught me, in
this repo, while building the very test that found it.

`LOOP.md` now lists **five** obligations, not three, and states the trap
explicitly with the `return delta, "reflect"` fix.

## Near-miss worth recording

The `LOOP.md` edit introduced an f-string collision: the literal
`{"...": ...}` inside `render_loop_md`'s template raised
`ValueError: Format specifier missing precision`, which would have made
`aef adopt` **crash outright** for every adopter. The integration test caught
it on its first run.

That is the case for the test in one line: the defect was in a *rendered
document*, not in logic, and no unit test of the surrounding code would have
executed it.

## Consequences
- `tests/cli/test_adoption_sequence.py` performs the whole documented
  workflow against a real adopted repo — adopt, status, run, harvest, cycle,
  monitor, digest — with assertions at each step. An instruction that stops
  working now fails here rather than in someone else's repo.
- A second test asserts `LOOP.md` still names all five obligations, the
  reflect-node trap, and `--working-memory`. Documentation that drifts from
  the code is a defect the same as any other.
- **All six commands work verbatim as written.** That claim is now tested
  rather than asserted.

## Confidence
High: every step was executed, and the two defects were found by being stuck,
not by inspection. **Not claimed:** that an adopter will succeed. The
sequence runs, and G5 still refuses until a blessed baseline is archived and
G3 until a control cohort exists — both documented, neither exercised by an
adopter yet.
