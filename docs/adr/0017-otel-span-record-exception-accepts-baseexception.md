# ADR 0017: `OtelSpan.record_exception` accepts `BaseException`, matching the real OTel SDK and `InMemorySpan`

## Status
Accepted

## Context
Auditing `aef/observability/` in full (not just what `executor.py` happens
to call) surfaced two things:

1. `OtelSpan.record_exception` had an `isinstance(exc, Exception)` guard,
   silently no-op-ing for `BaseException` subtypes that aren't
   `Exception` (`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`).
   `Span.record_exception`'s own ABC signature (`aef/observability/base.py`)
   takes `exc: BaseException`, and `Tracer.span()`'s context manager
   catches `BaseException` broadly and calls `record_exception`
   unconditionally — so the two `Tracer` implementations disagreed on
   whether a `SystemExit` raised inside a traced span actually gets
   recorded: `InMemorySpan` always does, `OtelSpan` silently didn't.
   Checked the real SDK directly (`inspect.signature(Span.record_exception)`)
   rather than assuming: it accepts `BaseException` with no restriction,
   so the guard wasn't matching real API constraints, either — it was an
   unnecessary restriction this codebase added on its own.
2. `RecordedSpan.exceptions` (`aef/observability/in_memory.py`) was
   write-only across the entire test suite: `InMemorySpan.record_exception`
   appends to it, but nothing anywhere — not even a test — ever read it.
   The executor's fallback-node path (`GraphExecutor._execute_node`) does
   call `span.record_exception(exc)` when a node fails and falls back, but
   no test verified that actually happens; the existing fallback test used
   `Services()` with no tracer configured at all.

## Decision
Removed the `isinstance` guard in `OtelSpan.record_exception` — it now
passes every `BaseException` straight through, matching both the real
SDK's own signature and `InMemorySpan`'s existing (correct) behavior.

Added direct test coverage for `InMemoryTracer`/`RecordedSpan` that didn't
exist before (a new `tests/observability/test_in_memory.py`): recording,
attribute updates, the ended flag, exception recording for both
`Exception` and non-`Exception` `BaseException`s, and the context-manager
error path. Added a real OTel-SDK test proving `SystemExit` is recorded
(not just `ValueError`). Added an executor-level test proving the
fallback path's `span.record_exception` call actually lands on the
correct node's span with the correct exception, closing the
kernel-to-observability verification gap the audit found.

## Consequences
- A node that raises `SystemExit`/`KeyboardInterrupt` inside a traced span
  now gets that exception recorded identically whether the tracer is
  `InMemoryTracer` (tests/examples) or `OtelTracer` (production) — no
  behavioral surprise moving from one to the other.
- `RecordedSpan.exceptions` is a genuinely verified test-assertion surface
  now, not just a field that happens to accumulate data nobody checks.

## Alternatives Considered
- **Keep the `Exception`-only filter, reasoning that `BaseException`
  subtypes like `SystemExit` "shouldn't" be recorded as errors.**
  Rejected: the real OTel SDK makes no such distinction, and neither does
  this codebase's own `Tracer.span()` context manager, which already
  catches and records every `BaseException` uniformly — the filter was an
  inconsistency with the rest of the module, not a deliberate policy.

## Confidence
High — the fix aligns two implementations of the same interface that had
silently diverged, verified against the real OTel SDK's actual signature
rather than assumption, with direct tests for both the previously-inert
`RecordedSpan.exceptions` field and the specific `BaseException` behavior.
