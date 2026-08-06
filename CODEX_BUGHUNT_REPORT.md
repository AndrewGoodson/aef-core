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

## Round 2 — deny-by-default policy and HITL routing

### Looked at

`aef/security/tool.py`, `aef/kernel/contracts.py`, the executor's gated-edge
resolution, audit-writer failure behaviour, scope/name/risk ordering, and the
policy and executor regression suites.

### Confirmed and fixed

`PolicyEngine.__init__()` selected injected dependencies with boolean `or`.
A valid caller-supplied `AuditLogWriter` whose domain-defined truthiness was
false was silently replaced by an in-memory writer. The policy decision still
returned normally, but the supplied durable audit received no entry.

Expected: dependency injection distinguishes only “not supplied” (`None`) from
an explicit implementation. It must not interpret a dependency's truthiness.

Reproduction before the fix:

```text
decision= allow
uses_supplied_writer= False
supplied_entries= 0

pytest -q tests/security/test_tool.py::test_explicit_falsey_audit_log_dependency_is_honored
FAILED: engine.audit_log is an unexpected InMemoryAuditLogWriter
```

Fix: use explicit `is not None` selection for the config, audit writer, and
clock dependencies. The regression supplies a falsey writer and verifies both
object identity and the actual appended record. All 18 policy tests pass.

This contradicts the DI-only service contract and the “full audit trail” claim
in `CLAUDE.md`: prior to the fix, a valid explicit audit dependency could be
ignored without error.

### Confirmed, intentionally not changed

HITL approval keys are ambiguous. `hitl_approval_key("a->b", "c")` and
`hitl_approval_key("a", "b->c")` both serialize as `a->b->c`. A compiled graph
with the gated edge `("a", "b->c")` accepted an approval minted for the
different edge `("a->b", "c")` and executed the destination node:

```text
wrong_edge_approval= a->b->c
gated_edge_key= a->b->c
crossed= True
```

This violates ADR 0011's claim that approvals are edge-specific and explicit.
It is a safety-relevant authorization collision. No fix or regression test was
committed because the bug-hunt brief's hard stop says not to alter routing into
a HITL-gated edge. The owner should choose a collision-free approval identity
and migration policy before unattended use with caller-controlled node IDs.

### Ruled out

- A tool/call name mismatch is denied before forbidden-name, scope, and risk
  checks, and the denial is audited.
- Missing scopes and scope-less tools remain deny-by-default.
- Non-finite and out-of-range risks and HITL thresholds are rejected at
  construction, including the maximum-risk/maximum-valid-threshold boundary.
- A writer exception propagates instead of returning an unaudited decision.
- Without the delimiter collision, an approval for a different ordinary edge
  is rejected and ungated edges remain unaffected.

### Suspected, not changed in this round

`InMemoryAuditLogWriter` stores `ToolCall.arguments` by reference, so caller
mutation may rewrite audit history. Reserved for the shared-mutable-state
round; not yet reproduced here.
