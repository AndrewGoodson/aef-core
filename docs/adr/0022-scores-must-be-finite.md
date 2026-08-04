# ADR 0022: `AEFState.scores`/`StateDelta.scores` reject `inf`/`-inf`/`nan` at construction time

## Status
Accepted

## Context
Fresh logic read of `aef/state/schema.py` with adversarial test data
(unicode, deeply nested `Plan.subgoals`, very large integers — all of
which round-trip correctly and are now locked in by tests) surfaced a
real bug when the adversarial data included `float("inf")` in `scores`.

`scores: dict[str, float]` is the field a domain-specific evaluator
writes Sharpe/PF/MaxDD-style metrics into (report §16's own example is a
Financial Agent's gates). A division-by-zero in a real metric calculation
— zero volatility in a Sharpe ratio is the textbook case — produces `inf`
or `nan`. Reproduced directly: `AEFState(..., scores={"m": float("inf")}).model_dump_json()`
silently serializes to `{"scores":{"m":null}}` — standard JSON has no
`Infinity`/`NaN` literal, and pydantic-core follows the spec strictly
rather than emitting non-standard JSON. That checkpoint write succeeds
with no error or warning.

The failure doesn't stay silent forever, but it resurfaces in the worst
possible place: reloading that checkpoint (`AEFState.model_validate_json`,
used by every `DurabilityBackend.load_latest`/`load_checkpoint`, and
hence by `GraphExecutor.resume()`) raises a `ValidationError` — because
`null` isn't a valid value for a non-`Optional[float]` field — at a
checkpoint-load call site with no obvious connection back to whichever
node computed the bad score several steps (and possibly several process
restarts) earlier. A corrupted score is silent at the point that matters
for debugging and loud at a point that doesn't.

## Decision
Both `StateDelta.scores` and `AEFState.scores` gained a `field_validator`
rejecting any non-finite float, naming every offending key in the error.
`StateDelta`'s validator is the one that matters in the normal execution
path — a node's returned `StateDelta(scores={...})` is where a bad value
first exists, and it's ordinary pydantic construction (validators run).
`AEFState`'s validator is a second, independent guard for direct
`AEFState(...)` construction, which bypasses `StateDelta` entirely (and
matters because `StateDelta.apply()` uses `state.model_copy(update=...)`,
which does **not** re-run validators — so `AEFState`'s own validator alone
would not have caught the bug the normal `apply()` path produces; the two
guards close two different entry points, not the same one twice).

## Consequences
- A node whose metric calculation produces `inf`/`nan` now fails loudly
  at the moment it tries to return that `StateDelta`, with an error
  naming the exact key and a hint ("usually means a division by zero
  upstream") — not a mysterious `ValidationError` several steps later
  during an unrelated checkpoint load.
- Every existing call site in this repo that constructs `scores` already
  passes finite values (verified: full suite green, 258/258, no call site
  needed updating) — this is a pure tightening, not a behavior change for
  any correct existing usage.
- `math.isfinite()` is the check used (rejects both infinities and NaN in
  one call) — stdlib only, no new dependency.

## Alternatives Considered
- **Let pydantic's own null-rejection on reload be the error surface.**
  Rejected: that's the status quo this ADR fixes — the error arrives far
  from its cause, at a checkpoint-load site that has no way to know which
  upstream computation produced the bad value.
- **Clamp non-finite values to a large finite number instead of
  rejecting.** Rejected: silently substituting a different (wrong) number
  is worse than rejecting — a clamped Sharpe ratio of "9999" is exactly
  the kind of plausible-but-wrong value a domain gate could act on
  incorrectly with no error at all, the failure mode this whole session
  has been hunting down.

## Confidence
High — the corruption-then-delayed-crash sequence was reproduced exactly
as described before writing any fix, the fix closes both entry points
that could introduce the value (`StateDelta` construction and direct
`AEFState` construction), and the full test suite confirms no existing
code path was relying on non-finite scores working.
