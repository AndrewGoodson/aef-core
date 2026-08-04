# ADR 0039: Replay trusts fallback records instead of re-executing them

## Status
Accepted

## Context
Round-2 cross-component flow audit found a High-severity seam that ADR 0036
exposed. After 0036, when a node raises and declares a `fallback_node_id`,
`_execute_node` returns a synthesized `error_delta` with `route =
fallback_node_id`, and the executor records that as a normal
`NodeExecutionRecord` in the trace.

If that node is declared `deterministic=True`, `ReplayEngine.replay()`
re-executes `node.fn(...)` to verify determinism (re-run, compare the
`StateDelta` and `Route`). But the original invocation *raised* — so
re-execution raises the same exception again, and there is no `try`/`except`
around that call. The raw original exception propagates straight out of
`replay()`.

Reproduced directly: a graph `boom -> safe` where `boom` is
`deterministic=True`, raises `ValueError("boom detonated")`, and declares
`fallback_node_id="safe"`. The run completes fine (fallback fires, error
recorded), the trace is well-formed and passes chain validation (the
recorded route is the fallback target, which equals the next record's
node_id — ADR 0023's check passes), but `replay(trace)` raises
`ValueError: boom detonated` instead of reconstructing the final state. The
non-deterministic variant replays fine, proving the trace itself is valid
and the crash is specific to the deterministic re-execution path.

Replay's core contract is that any trace a real `run(record_trace=True)`
produces is replayable. ADR 0036 taught the *executor* to emit fallback
records; the *replay engine* predated it and was never taught to handle
them.

## Decision
`NodeExecutionRecord` gained an `is_fallback: bool = False` field, set to
`True` by the executor exactly when the record is the error/fallback path
(the node raised and fell back). `ReplayEngine.replay()` now skips the
determinism re-execution for a record where `is_fallback` is true — the
recorded `error_delta` + fallback route are replayed verbatim, exactly as a
non-deterministic node's recorded output already is. A fallback record is
inherently untrustworthy to re-run: the node raised, so re-executing it
only raises again; its "output" (the recorded error and fallback route) is
what must be replayed.

## Consequences
- A trace containing a deterministic node's fallback step now replays
  correctly, reconstructing the same final state the run produced
  (confirmed: `replayed == result.final_state`, with the recorded error
  present). Replay's "any real trace is replayable" contract holds again.
- The determinism guarantee for the *success* path is unchanged — a
  non-fallback deterministic record is still re-executed and compared, so a
  lying-deterministic node is still caught (that test is untouched and
  green).
- `is_fallback` defaults to `False`, so every existing hand-constructed
  trace and existing test record is unaffected.
- 318/318 tests (one new: a deterministic-node fallback trace round-trips
  through run -> replay), mypy --strict clean, ruff clean.

## Alternatives Considered
- **Wrap replay's re-execution in try/except and, on exception, trust the
  recorded delta.** Rejected: it conflates "this node legitimately fell
  back" with "this node now raises on replay for a *different* reason" (e.g.
  a real determinism violation that manifests as a new exception) — the
  latter should still surface, not be silently trusted. An explicit
  `is_fallback` marker distinguishes the recorded-error path precisely.
- **Don't record the fallback step in the trace at all.** Rejected: the
  fallback step is a real super-step that produced state (the recorded
  error) and advanced the run to the handler — omitting it would make the
  trace an incomplete, non-replayable account of what happened.
- **Make the fallback node's determinism irrelevant by forbidding
  `deterministic=True` on any node with a `fallback_node_id`.** Rejected:
  over-restrictive — a node can be genuinely deterministic on its success
  path and still have an error handler; the two are orthogonal, and the fix
  is to replay the recorded error path, not to ban the combination.

## Confidence
High — the crash was reproduced before the fix (with the non-deterministic
variant proving the trace is well-formed), the fix was verified to
reconstruct the exact run final state, and it reuses the existing
"trust recorded output" mechanism replay already applies to
non-deterministic nodes rather than inventing new replay behavior.
