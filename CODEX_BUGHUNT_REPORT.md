# Codex 10-round adversarial bug hunt

Branch: `codex/bughunt-10x`

Base: `b7e926a6a369a59bd0d5b23b6fcf211da6e5d52c`

## Baseline

The documented environment (`source .venv/bin/activate`) started green:

- `pytest -q`: 1398 passed
- `mypy --strict aef`: 107 source files clean
- `ruff check .`: clean
- `ruff format --check aef tests examples`: 192 files formatted
- `cd mindgraph && python tools/verify`: 287 checks passed
- `cd mindgraph && python tools/verify --self-test`: 29 detections passed

An initial invocation of `.venv/bin/pytest -q` without activating the virtual
environment produced 18 subprocess failures because child processes resolved a
different `python`. That was an invalid test environment, not a product defect.

## Round 1 — replay determinism and checkpoint round-trips

### Looked at

`aef/kernel/replay.py`, `executor.py`, `durability.py`, their checkpoint/cursor
tests, deterministic replay, fallback-route verification, corrupt-checkpoint
rewind, and HITL resumption.

### Confirmed and fixed

`FileDurabilityBackend.load_cursor()` accepted schema-invalid but syntactically
valid JSON. `{"next_node": 7}` and `{}` returned `None`, the same value used for
a completed run; arrays and strings leaked `AttributeError`. A real
`GraphExecutor.resume()` probe therefore silently returned the last checkpoint
without executing the pending node.

Expected: external cursor corruption raises the named
`CorruptedCheckpointError`; it must never become a completed-run signal.

Reproduction before the fix:

```text
pytest -q tests/kernel/test_durability.py -k invalid_schema
4 failed: two DID NOT RAISE CorruptedCheckpointError; two raised AttributeError
```

Fix: validate that the decoded cursor is an object containing `next_node`, and
that its value is a string or null. The regression test covers numeric,
missing, array, and scalar payloads. After the fix, all 18 cursor tests pass.

### Ruled out

- Deterministic nodes are re-executed against the recorded input state.
- Replay verifies both ordinary and fallback routes.
- Trace records deep-copy state and delta snapshots.
- Latest-checkpoint recovery falls back past corrupt newest checkpoints but
  still fails loudly when none are loadable.
- HITL resume preserves the pending route and does not re-run the gated node.

### Suspected, not yet reproduced

Read operations in `FileDurabilityBackend` do not consistently use the same
run-id containment helper as writes. Reserved for the boundary-values round;
no change made in this round.
