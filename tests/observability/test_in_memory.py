from aef.observability.in_memory import InMemoryTracer


def test_start_span_records_name_and_attributes() -> None:
    tracer = InMemoryTracer()
    span = tracer.start_span("demo", {"k": "v"})
    span.end()
    assert tracer.spans[0].name == "demo"
    assert tracer.spans[0].attributes == {"k": "v"}


def test_start_span_snapshots_nested_attributes() -> None:
    attributes = {"request": {"attempt": 1}}
    tracer = InMemoryTracer()
    tracer.start_span("demo", attributes)

    attributes["request"]["attempt"] = 2

    assert tracer.spans[0].attributes == {"request": {"attempt": 1}}


def test_set_attribute_after_start_updates_recorded_span() -> None:
    tracer = InMemoryTracer()
    span = tracer.start_span("demo")
    span.set_attribute("added_later", 42)
    assert tracer.spans[0].attributes == {"added_later": 42}


def test_set_attribute_snapshots_nested_value() -> None:
    value = {"attempt": 1}
    tracer = InMemoryTracer()
    span = tracer.start_span("demo")
    span.set_attribute("request", value)

    value["attempt"] = 2

    assert tracer.spans[0].attributes == {"request": {"attempt": 1}}


def test_span_not_ended_until_end_called() -> None:
    tracer = InMemoryTracer()
    span = tracer.start_span("demo")
    assert tracer.spans[0].ended is False
    span.end()
    assert tracer.spans[0].ended is True


def test_record_exception_appends_to_recorded_span() -> None:
    """RecordedSpan.exceptions had no test verifying it before this — it's
    write-only from InMemorySpan.record_exception's perspective without a
    reader proving the data is actually correct."""
    tracer = InMemoryTracer()
    span = tracer.start_span("demo")
    exc = ValueError("boom")
    span.record_exception(exc)
    assert tracer.spans[0].exceptions == [exc]


def test_record_exception_accepts_base_exception_not_just_exception() -> None:
    tracer = InMemoryTracer()
    span = tracer.start_span("demo")
    exc = SystemExit("shutting down")
    span.record_exception(exc)
    assert tracer.spans[0].exceptions == [exc]


def test_span_context_manager_records_exception_and_ends_on_error() -> None:
    tracer = InMemoryTracer()
    try:
        with tracer.span("demo"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert len(tracer.spans[0].exceptions) == 1
    assert isinstance(tracer.spans[0].exceptions[0], ValueError)
    assert tracer.spans[0].ended is True


def test_multiple_spans_are_independent() -> None:
    tracer = InMemoryTracer()
    tracer.start_span("a").record_exception(ValueError("a-error"))
    tracer.start_span("b")
    assert len(tracer.spans[0].exceptions) == 1
    assert len(tracer.spans[1].exceptions) == 0
