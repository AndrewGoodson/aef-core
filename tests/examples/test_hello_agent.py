import uuid
from datetime import UTC, datetime

import pytest

from aef.kernel import END, Context, GraphExecutor, InMemoryDurabilityBackend, Services
from aef.observability.in_memory import InMemoryTracer
from aef.security.tool import PolicyConfig, PolicyEngine
from aef.services.eval.rule_based import RuleBasedEvaluator
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, Plan
from examples.hello_agent.graph import EchoModelProvider, build_graph, summarize_node
from examples.hello_agent.main import main


def _run() -> tuple[AEFState, Services]:
    services = Services(
        model_provider=EchoModelProvider(),
        memory=InMemoryMemoryStore(),
        tracer=InMemoryTracer(),
        durability=InMemoryDurabilityBackend(),
        policy_engine=PolicyEngine(PolicyConfig(allowed_scopes=frozenset({"web_search_ro"}))),
    )
    state = AEFState(run_id=str(uuid.uuid4()), agent_id="hello-agent", objective="test objective")
    executor = GraphExecutor(build_graph().compile(), services)
    result = executor.run(state)
    return result.final_state, services


def test_hello_agent_completes_with_a_done_plan_and_no_errors() -> None:
    final_state, _ = _run()
    assert final_state.plan is not None
    assert final_state.plan.status == "done"
    assert final_state.errors == []


def test_hello_agent_writes_to_memory() -> None:
    final_state, services = _run()
    memory = services.memory
    assert memory is not None
    records = memory.query("working", run_id=final_state.run_id)
    assert len(records) == 1


def test_hello_agent_calls_the_tool_when_scope_is_allowed() -> None:
    final_state, _ = _run()
    assert len(final_state.tool_results) == 1
    assert "results" in final_state.tool_results[0]


def test_hello_agent_denies_tool_call_when_scope_not_allowlisted() -> None:
    services = Services(
        model_provider=EchoModelProvider(),
        memory=InMemoryMemoryStore(),
        policy_engine=PolicyEngine(PolicyConfig(allowed_scopes=frozenset())),  # nothing allowed
    )
    state = AEFState(run_id=str(uuid.uuid4()), agent_id="hello-agent", objective="test")
    executor = GraphExecutor(build_graph().compile(), services)
    result = executor.run(state)

    assert result.final_state.tool_results == []
    assert len(result.final_state.errors) == 1


def test_hello_agent_emits_one_span_per_node() -> None:
    _, services = _run()
    tracer = services.tracer
    assert isinstance(tracer, InMemoryTracer)
    assert [s.name for s in tracer.spans] == [
        "aef.node.draft",
        "aef.node.search",
        "aef.node.summarize",
    ]


def test_hello_agent_evaluates_as_passed() -> None:
    final_state, _ = _run()
    record = RuleBasedEvaluator().evaluate(final_state)
    assert record.passed
    assert record.task_completion == 1.0
    assert record.cost_tokens > 0


def test_main_runs_without_raising(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    out = capsys.readouterr().out
    assert "final messages" in out
    assert "evaluation" in out


def test_summarize_node_preserves_existing_plan_subgoals_and_reusable_key() -> None:
    """StateDelta.plan fully replaces, never merges (see aef/state/delta.py).
    summarize_node must update status via Plan.model_copy(), not reconstruct
    a fresh Plan(...) — the naive version would silently drop subgoals and
    reusable_key. This is exactly the bug that shipped in this example
    before it was caught and fixed."""
    existing_plan = Plan(
        goal="find the answer",
        subgoals=[Plan(goal="search", status="done")],
        status="active",
        reusable_key="template-42",
    )
    state = AEFState(run_id="r1", agent_id="a1", objective="find the answer", plan=existing_plan)
    ctx = Context(
        run_id=state.run_id,
        graph_version="0.1.0",
        trace_id="t1",
        node_id="summarize",
        now=datetime.now(UTC),
    )
    services = Services(model_provider=EchoModelProvider())

    delta, route = summarize_node(state, ctx, services)

    assert route is END
    assert delta.plan is not None
    assert delta.plan.status == "done"
    assert delta.plan.subgoals == existing_plan.subgoals
    assert delta.plan.reusable_key == "template-42"
    assert delta.plan.goal == "find the answer"
