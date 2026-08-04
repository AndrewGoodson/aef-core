# ADR 0027: `OtelTracer`'s nested spans are now actually parent/child in the real SDK

## Status
Accepted

## Context
Adversarial pass on `aef/observability/otel_tracer.py` using a real
`opentelemetry-sdk` `TracerProvider` + `InMemorySpanExporter` (not a mock —
the actual installed SDK, same technique as every other finding this
session: run real code, don't reason from source alone).

`Tracer.span()`'s default implementation (`aef/observability/base.py`)
calls `start_span()`, yields, and calls `end()` — `OtelTracer` only ever
implemented `start_span()`, inheriting that default. Reproduced directly:

```python
with tracer.span("parent"):
    with tracer.span("child"):
        pass
```

produced two spans in the real exporter with **`child.parent is None`** —
no parent/child relationship at all, despite the Python code visibly
nesting them. Root cause: the real OTel SDK's `Tracer.start_span()`
creates a span but does not attach it to the SDK's active-context
mechanism (`opentelemetry.context`) — only `start_as_current_span()`
(or an explicit `context.attach(set_span_in_context(span))`) does that.
Every span this codebase creates via nested `tracer.span()` calls — most
concretely `GraphExecutor._execute_node`'s per-node span wrapping
`_record_emergent_routing`'s nested span for HITL-flagged emergent
routing (ADR 0011) — would export to a real backend (Jaeger, Honeycomb,
anything) as unrelated root spans with no visible relationship, silently
discarding exactly the nesting a trace viewer needs to answer "what
happened during this specific node's execution."

`InMemoryTracer`/`InMemorySpan` have no equivalent bug: they don't model
parent/child relationships at all (a flat list of recorded spans), so
there was nothing to silently break there — the gap only existed in the
real adapter, the one place a wrong answer wouldn't show up in any test
that doesn't spin up the actual SDK and inspect real exported span
objects (which is exactly why it went unnoticed: `test_otel_tracer.py`
already asserted per-span attributes/exceptions correctly but never
asserted `.parent` on anything).

## Decision
`OtelTracer` now overrides `span()` (rather than relying on the ABC's
default) to explicitly attach the started span to the OTel context via
`otel_context.attach(set_span_in_context(s.raw))` before yielding, and
`otel_context.detach(token)` in `finally` — matching what
`start_as_current_span` does internally, while keeping the exact same
exception-recording/end-ordering contract the base class's default
implementation already had (record on `BaseException`, re-raise, `end()`
in `finally`), so `InMemoryTracer`'s and `OtelTracer`'s behavior stay
symmetric from a caller's point of view. `OtelSpan` gained a `raw`
property exposing the wrapped real span, needed to build the context.

## Consequences
- Nested spans now correctly parent in real exported traces — confirmed
  directly: `child.parent.span_id == parent.context.span_id`, and a
  sibling span created after the nested one closes correctly re-parents
  to the outer span, not the just-closed nested one.
- Context is correctly restored on exit, including the exception path
  (confirmed: a span created after an exception inside a prior span has
  no leaked parent) — the `detach()` happens in `finally`, symmetric with
  `end()`.
- 281/281 tests (up from 278/278), mypy --strict clean, ruff clean. Three
  new tests assert real parent/child span IDs via the actual SDK +
  in-memory exporter, not a mock.
- No behavior change for `InMemoryTracer` or any caller-visible API — this
  is purely a correctness fix in how `OtelTracer` talks to the real SDK's
  context mechanism.

## Alternatives Considered
- **Delegate entirely to `self._tracer.start_as_current_span()`** instead
  of manually attaching/detaching context around `start_span()`. Rejected:
  `start_as_current_span` has its own default exception-recording and
  span-status-setting behavior that would either double up with or
  diverge from the existing `record_exception` call already made by the
  base contract, and this codebase's own `Tracer`/`Span` interface — not
  the OTel SDK's own opinions — is what should define that contract
  uniformly across `InMemoryTracer` and `OtelTracer`. Manual
  attach/detach keeps `OtelTracer` a thin, predictable adapter instead of
  inheriting a different exception-handling policy for one backend.
- **Leave `InMemoryTracer` unchanged (no parent-tracking).** Correct as
  is: nothing about this bug or its fix required `InMemoryTracer` to model
  parent/child spans — it never claimed to, and nothing in this repo reads
  span nesting through it today.

## Confidence
High — the bug was reproduced with the real, installed `opentelemetry-sdk`
against a real `InMemorySpanExporter` (not a mock or hypothetical), the
fix was verified against the same real exporter to confirm correct
parent/child linkage, sibling re-parenting, and context cleanup on both
the normal and exception exit paths, and the new tests assert on the
actual SDK's `ReadableSpan.parent`/`.context.span_id` fields rather than
this codebase's own wrapper types.
