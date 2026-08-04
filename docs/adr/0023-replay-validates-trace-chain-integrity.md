# ADR 0023: `ReplayEngine.replay()` validates trace chain integrity before replaying

## Status
Accepted

## Context
Fresh logic read of `aef/kernel/replay.py` beyond existing test coverage,
with adversarial trace construction (same approach as ADR 0022): hand-build
a `Sequence[NodeExecutionRecord]` by hand rather than only trusting traces
produced by `GraphExecutor.run(record_trace=True)`.

`replay()`'s type signature accepts any `Sequence[NodeExecutionRecord]`, but
the implementation never checked that consecutive records actually form a
path through the graph. Reproduced directly: build a graph with node `a`
routing to either `b` or `c`, then hand-assemble a trace where record 0 is
`a` (recording `route="b"`) followed by record 1 for node `c` — i.e. a
reordered/corrupted/tampered trace. `replay()` accepted this silently,
applied both records' deltas in sequence, and returned a nonsensical merged
final state with zero error or warning.

Two further malformed shapes have the same problem: a record routing to
`END` with more records still following it in the sequence (contradicts its
own claim of being the last step), and a record whose route is a fan-out
tuple (`replay()` has no fan-out support at all — same limitation as the
live executor, ADR 0007 — so a fan-out route reaching replay can only come
from a hand-built or corrupted trace).

A live `GraphExecutor.run(record_trace=True)` can never itself produce any
of these three shapes — routing is validated as it happens. But `replay()`
doesn't require its input come from a live run; nothing enforces that
invariant at the boundary, so a hand-assembled, reordered, truncated, or
otherwise corrupted trace (e.g. read back from an untrusted or manually
edited durability store) was replayed as if it were legitimate.

## Decision
Added `MalformedTraceError` and a `_validate_chain()` method on
`ReplayEngine`, run once at the start of `replay()` immediately after the
existing empty-trace check and before any node is replayed. For every
record except the last: a fan-out route is always rejected; an `END` route
is rejected unless it's the final record; otherwise the route must equal
the next record's `node_id`, or the record is rejected as reordered/
corrupted. The last record is exempt from the "route must equal next
node_id" check by construction (there is no next record), and its route is
explicitly allowed to be a non-`END`, even non-existent, node id — this
supports replaying a **partial** trace, e.g. one captured up to a crash,
without forcing every replayable trace to have reached completion.

## Consequences
- A reordered, hand-tampered, or otherwise corrupted trace now fails fast
  with `MalformedTraceError` naming the exact record and the mismatch,
  instead of silently producing a wrong final state with no error.
- Legitimate traces — anything actually produced by
  `GraphExecutor.run(record_trace=True)` — are provably unaffected: full
  suite (263/263) passes unchanged, since a live run's routing is already
  validated at execution time and always forms a valid chain.
- Partial traces (crash-truncated runs) remain replayable — the last
  record's route is intentionally not required to be `END` or to name a
  real node, since the point of replaying a partial trace is to inspect
  state as of the crash, not to require the run had finished.
- Fan-out traces are rejected at replay time with a clear error pointing at
  ADR 0007, rather than proceeding through logic that was never built to
  handle fan-out.

## Alternatives Considered
- **Validate the trace only against the live graph's actual edges** (i.e.
  check `route` names an edge that exists in `self._graph`), not just that
  consecutive records chain to each other. Rejected for this pass: replay
  is explicitly allowed to run against a graph whose edges have since
  changed (that's a separate, softer failure mode — a `route` that no
  longer corresponds to a live edge is a graph-drift question, not a
  trace-corruption question) — conflating the two would reject legitimate
  historical traces just because the graph evolved. The chain-integrity
  check added here is orthogonal and correct regardless of edge drift; a
  graph-drift check can be layered on separately if it turns out to matter.
- **Silently truncate at the first malformed record and replay only the
  valid prefix.** Rejected: matches the same reasoning as ADR 0022 —
  silently discarding data and proceeding is worse than a loud, precise
  error, especially for something as security/audit-relevant as a replay
  engine.

## Confidence
High — the corrupted-trace-produces-wrong-silent-output bug was reproduced
directly with a hand-built adversarial script before writing any fix, the
fix was verified to catch all three malformed shapes (reordered/corrupted,
mid-trace `END`, fan-out) while explicitly preserving the
partial-trace-replay capability, and the full suite (263/263, up from
258/258) confirms zero regressions against every existing legitimate trace.
