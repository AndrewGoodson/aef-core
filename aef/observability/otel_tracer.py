"""Real `Tracer` adapter backed by the OpenTelemetry SDK (report §17). This
module (and no other outside `providers/`/`services/*/adapters/`) is allowed
to import `opentelemetry` directly (constraint #3) — `kernel/` only ever
sees the vendor-neutral `Tracer` interface.

AEF does not configure a `TracerProvider` or exporter here: which exporter
to use (console, OTLP, Jaeger, ...) is a deployment decision. Callers build
their own `TracerProvider`, get an `opentelemetry.trace.Tracer` from it, and
hand it to `OtelTracer`.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.trace import Span as OtelSpanAPI
from opentelemetry.trace import Tracer as OtelTracerAPI
from opentelemetry.trace import get_tracer

from aef.observability.base import Span, Tracer


class OtelSpan(Span):
    def __init__(self, span: OtelSpanAPI) -> None:
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)

    def record_exception(self, exc: BaseException) -> None:
        if isinstance(exc, Exception):
            self._span.record_exception(exc)

    def end(self) -> None:
        self._span.end()


class OtelTracer(Tracer):
    def __init__(
        self, otel_tracer: OtelTracerAPI | None = None, *, instrumentation_name: str = "aef"
    ) -> None:
        self._tracer = otel_tracer or get_tracer(instrumentation_name)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        span = self._tracer.start_span(name, attributes=attributes)
        return OtelSpan(span)
