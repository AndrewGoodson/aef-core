# ADR 0086: Resume must not invent a state that never existed

## Status
Accepted. Phase 3 round 1, sweeping `aef/kernel` and `aef/state` — never
examined before, and the layer CLAUDE.md calls the actual safety property
being tested.

## A torn checkpoint silently skipped a completed node

`load_latest` walks newest-first and falls back past a corrupt checkpoint to
the highest readable one (ADR 0031). **The cursor is not rewound.** It still
names the node due to run *after* the checkpoint that could not be read.

`resume()` paired the two:

```
clean run     : ['A ran', 'B ran', 'C ran']
torn seq 3    ->  load_latest rewinds to seq 2, cursor still says C
resume        : ['A ran', 'C ran']     <- B silently skipped
```

No error. No warning. And the resume then overwrote the torn file, so the
evidence disappeared. This is precisely the scenario ADR 0031's fallback was
built for — *"disk fault, manual edit, a pre-atomic-write legacy crash"* — so
it is live code with a designed-for trigger.

`resume()` already holds both numbers. It now compares them and **refuses**:
the work between the rewound state and the newest recorded checkpoint is
lost, and continuing would produce a final state that never existed. A run
that cannot be resumed honestly should not be resumed.

The existing test stopped one assertion short: it asserted
`recovered.checkpoint_seq == 1` and never read the cursor or called
`resume()`.

## `run_id` was used verbatim as a directory name

```
backend root: .../tmp.../checkpoints
files written: ['.../T/escaped/cursor.json', '.../T/escaped/0.json']
escaped the backend root: True
```

`AEFState.run_id` had no validator and `_run_dir` joined it onto the root.
Two layers now: the schema rejects anything that is not a single path
segment, and the backend enforces containment at its own boundary — because
the backend is public API an adopter calls directly, and containment cannot
rest on callers passing well-formed ids.

Given this repo's containment posture, a control that depends on every caller
being careful is not a control.

## Confidence
High: both were reproduced by running, both fixes were re-run against the
failing case, and each has a control asserting the guard does *not* fire on
the healthy path — a refusal that rejects intact runs would be worse than the
defect.

**Not claimed:** that this sweep is complete. It surfaced six further
findings this ADR does not address, three of them substantive: `ReplayEngine`
never validates the state chain (a trace whose node ids chain correctly
replays clean with forged `scores`/`errors`/`objective`); `StateDelta.apply`
is shallow-pure only, so a node mutating a nested structure rewrites the
trace records that are supposed to be history; and the ADR 0022 NaN guard
covers `scores` but not `working_memory`, the field the schema designates for
per-agent data. Each is recorded here as open.
