from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aef.kernel import END, Context, Graph, GraphExecutor, Node, Route, Services
from aef.observability import semconv
from aef.observability.otel_tracer import OtelTracer
from aef.state import AEFState, Message, Provenance, StateDelta


def _make_provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_start_span_emits_a_real_otel_span_with_attributes() -> None:
    provider, exporter = _make_provider()
    tracer = OtelTracer(provider.get_tracer("aef-test"))

    with tracer.span("aef.node.demo", {"aef.run_id": "r1"}) as span:
        span.set_attribute("extra", "value")

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "aef.node.demo"
    attributes = finished[0].attributes
    assert attributes is not None
    assert attributes["aef.run_id"] == "r1"
    assert attributes["extra"] == "value"


def test_span_context_manager_records_exception_and_reraises() -> None:
    provider, exporter = _make_provider()
    tracer = OtelTracer(provider.get_tracer("aef-test"))

    try:
        with tracer.span("aef.node.boom"):
            raise ValueError("boom")
    except ValueError:
        pass

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    events = finished[0].events
    assert any(e.name == "exception" for e in events)


def test_record_exception_accepts_base_exception_not_just_exception() -> None:
    """The real OTel Span.record_exception accepts BaseException directly
    (confirmed via inspect.signature) — SystemExit/KeyboardInterrupt-style
    exceptions must be recorded too, not silently dropped."""
    provider, exporter = _make_provider()
    tracer = OtelTracer(provider.get_tracer("aef-test"))

    span = tracer.start_span("aef.node.exiting")
    span.record_exception(SystemExit("shutting down"))
    span.end()

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    events = finished[0].events
    assert any(e.name == "exception" for e in events)


def test_graph_executor_emits_gen_ai_span_per_node_with_real_otel_sdk() -> None:
    provider, exporter = _make_provider()
    tracer = OtelTracer(provider.get_tracer("aef-test"))

    def _llm_fn(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        prov = Provenance(
            node_id=ctx.node_id,
            graph_version=ctx.graph_version,
            ts=ctx.now,
            trace_id=ctx.trace_id,
            model="claude-x",
            token_cost=17,
        )
        delta = StateDelta(
            messages=[Message(role="assistant", content="hi", prov=prov)],
            provenance=[prov],
        )
        return delta, END

    node = Node(id="llm", version="1.0.0", fn=_llm_fn, deterministic=False)
    graph = Graph(id="g", version="1.0.0", nodes={"llm": node}, edges=[], entry_node="llm")
    executor = GraphExecutor(graph.compile(), Services(tracer=tracer))
    executor.run(AEFState(run_id="r1", agent_id="a1", objective="test"))

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    span = finished[0]
    assert span.name == "aef.node.llm"
    attributes = span.attributes
    assert attributes is not None
    assert attributes[semconv.AEF_NODE_ID] == "llm"
    assert attributes[semconv.AEF_NODE_DETERMINISTIC] is False
    assert attributes[semconv.GEN_AI_USAGE_OUTPUT_TOKENS] == 17
    assert attributes[semconv.GEN_AI_RESPONSE_MODEL] == "claude-x"
