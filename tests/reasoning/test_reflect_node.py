"""`make_reflect_node` — the wiring that makes reflection reach memory.

The acceptance property for this slice: a **real** `GraphExecutor` run
produces failure/success memory records that are queryable back out via
`MemoryStore.query()`. Everything here runs against real objects — a real
graph, a real executor, a real `InMemoryMemoryStore` — never a mock.
"""

import pytest

from aef.kernel import (
    END,
    Context,
    Edge,
    Graph,
    GraphExecutor,
    Node,
    Route,
    ServiceNotConfiguredError,
    Services,
    SideEffect,
)
from aef.kernel.replay import ReplayEngine
from aef.reasoning.nodes import make_reflect_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, StateDelta


def _state(**overrides: object) -> AEFState:
    defaults: dict[str, object] = {"run_id": "r1", "agent_id": "a1", "objective": "obj"}
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


def _services(memory: InMemoryMemoryStore | None = None, **overrides: object) -> Services:
    defaults: dict[str, object] = {
        "memory": memory if memory is not None else InMemoryMemoryStore(),
        "critic": RuleBasedCritic(),
        "judge": RuleBasedJudge(rubric={"quality": 1.0}),
    }
    defaults.update(overrides)
    return Services(**defaults)  # type: ignore[arg-type]


def _graph(reflect: Node, *, seed: Node | None = None) -> Graph:
    if seed is None:
        return Graph(
            id="reflect_only",
            version="0.1.0",
            nodes={reflect.id: reflect},
            edges=[],
            entry_node=reflect.id,
        )
    return Graph(
        id="seeded",
        version="0.1.0",
        nodes={seed.id: seed, reflect.id: reflect},
        edges=[Edge(from_node=seed.id, to_node=reflect.id)],
        entry_node=seed.id,
    )


# --------------------------------------------------------------------------
# Services DI slots — the concrete gap this slice closes
# --------------------------------------------------------------------------


def test_services_carries_critic_and_judge_slots() -> None:
    # Without these, constraint #2 (DI-only, no globals) makes a Critic
    # unwireable into any node at all.
    services = _services()
    assert services.critic is not None
    assert services.judge is not None


def test_critic_and_judge_default_to_none_like_every_other_backend() -> None:
    assert Services().critic is None
    assert Services().judge is None


def test_require_critic_raises_when_unconfigured() -> None:
    with pytest.raises(ServiceNotConfiguredError, match="critic"):
        Services().require_critic()


def test_require_judge_raises_when_unconfigured() -> None:
    with pytest.raises(ServiceNotConfiguredError, match="judge"):
        Services().require_judge()


# --------------------------------------------------------------------------
# The node contract
# --------------------------------------------------------------------------


def test_reflect_node_declares_io_and_carries_an_idempotency_key() -> None:
    # A non-pure node with no idempotency_key_fn raises NodeContractError at
    # construction; this pins that the factory supplies one rather than
    # declaring itself pure to dodge the requirement.
    node = make_reflect_node()
    assert node.side_effects is SideEffect.IO
    assert node.idempotency_key_fn is not None


def test_reflect_node_is_declared_non_deterministic_because_it_writes() -> None:
    # Its *output* is a pure function of state, but ReplayEngine re-executes
    # deterministic nodes — declaring True would repeat the memory write on
    # every replay. See the replay test below for the property this protects.
    assert make_reflect_node().deterministic is False


def test_idempotency_key_is_stable_for_the_same_input_state() -> None:
    node = make_reflect_node()
    assert node.idempotency_key_fn is not None
    state = _state()
    assert node.idempotency_key_fn(state) == node.idempotency_key_fn(state)


def test_idempotency_key_differs_across_steps_of_one_run() -> None:
    # A graph that reflects twice must not collide the two writes.
    node = make_reflect_node()
    assert node.idempotency_key_fn is not None
    first = node.idempotency_key_fn(_state(checkpoint_seq=0))
    second = node.idempotency_key_fn(_state(checkpoint_seq=1))
    assert first != second


# --------------------------------------------------------------------------
# End-to-end through a real GraphExecutor
# --------------------------------------------------------------------------


def test_a_real_run_writes_a_success_record_queryable_from_memory() -> None:
    memory = InMemoryMemoryStore()
    executor = GraphExecutor(_graph(make_reflect_node()).compile(), _services(memory))

    executor.run(_state(scores={"quality": 1.0}))

    records = memory.query("success", run_id="r1")
    assert len(records) == 1
    assert records[0].agent_id == "a1"
    assert records[0].content["score"] == pytest.approx(1.0)


def test_a_real_run_writes_a_failure_record_when_errors_were_recorded() -> None:
    memory = InMemoryMemoryStore()
    executor = GraphExecutor(_graph(make_reflect_node()).compile(), _services(memory))

    executor.run(_state(errors=[{"error": "boom"}]))

    assert memory.query("success", run_id="r1") == []
    failures = memory.query("failure", run_id="r1")
    assert len(failures) == 1
    assert "boom" in failures[0].content["verbal_feedback"]
    assert failures[0].content["grounded_in"] == ["errors[0]"]


def test_a_failing_tool_call_alone_produces_a_failure_record() -> None:
    memory = InMemoryMemoryStore()
    executor = GraphExecutor(_graph(make_reflect_node()).compile(), _services(memory))

    executor.run(_state(tool_results=[{"error": "timeout"}]))

    assert len(memory.query("failure", run_id="r1")) == 1


def test_the_reflection_lands_on_state_not_only_in_memory() -> None:
    executor = GraphExecutor(_graph(make_reflect_node()).compile(), _services())
    result = executor.run(_state(errors=[{"error": "boom"}]))

    assert len(result.final_state.reflections) == 1
    assert "boom" in result.final_state.reflections[0]


def test_reflect_node_does_not_write_the_judgment_into_state_scores() -> None:
    # Writing it back would make a second reflect step judge its own prior
    # output — a self-referential score the rubric was never meant to read.
    result = GraphExecutor(_graph(make_reflect_node()).compile(), _services()).run(
        _state(scores={"quality": 0.5})
    )
    assert result.final_state.scores == {"quality": 0.5}


def test_reflection_records_the_signals_a_downstream_proposer_needs() -> None:
    memory = InMemoryMemoryStore()
    GraphExecutor(_graph(make_reflect_node()).compile(), _services(memory)).run(
        _state(errors=[{"error": "boom"}], scores={"quality": 0.25})
    )
    content = memory.query("failure", run_id="r1")[0].content
    assert set(content) >= {"verbal_feedback", "grounded_in", "score", "rubric", "rationale"}


def test_memory_tags_are_carried_onto_the_record() -> None:
    memory = InMemoryMemoryStore()
    node = make_reflect_node(memory_tags=("reflection", "v1"))
    GraphExecutor(_graph(node).compile(), _services(memory)).run(_state())

    assert memory.query("success", run_id="r1", tags=("reflection",))


def test_reflecting_on_a_prior_nodes_output_sees_that_output() -> None:
    # The realistic wiring: reflect runs *after* work, and must see the
    # errors that work produced, not the pristine initial state.
    def failing_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        return StateDelta(errors=[{"node_id": ctx.node_id, "error": "downstream boom"}]), "reflect"

    seed = Node(id="work", version="0.1.0", fn=failing_node, deterministic=True)
    memory = InMemoryMemoryStore()
    graph = _graph(make_reflect_node(), seed=seed)
    GraphExecutor(graph.compile(), _services(memory)).run(_state())

    failures = memory.query("failure", run_id="r1")
    assert len(failures) == 1
    assert "downstream boom" in failures[0].content["verbal_feedback"]


def test_a_run_with_no_critic_configured_fails_loudly() -> None:
    executor = GraphExecutor(_graph(make_reflect_node()).compile(), Services(memory=None))
    with pytest.raises(ServiceNotConfiguredError):
        executor.run(_state())


def test_route_is_configurable_and_defaults_to_end() -> None:
    assert make_reflect_node().fn(_state(), _ctx(), _services())[1] is END
    assert make_reflect_node(route="next").fn(_state(), _ctx(), _services())[1] == "next"


def _ctx() -> Context:
    from datetime import UTC, datetime

    return Context(
        run_id="r1",
        graph_version="0.1.0",
        trace_id="t1",
        node_id="reflect",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )


# --------------------------------------------------------------------------
# Replay: the property that justifies deterministic=False
# --------------------------------------------------------------------------


def test_replay_does_not_repeat_the_memory_write() -> None:
    # ReplayEngine re-executes nodes declared deterministic=True. reflect is
    # declared False precisely so replaying a trace does not append a second
    # copy of every reflection to the store.
    memory = InMemoryMemoryStore()
    services = _services(memory)
    compiled = _graph(make_reflect_node()).compile()

    result = GraphExecutor(compiled, services).run(_state(), record_trace=True)
    assert len(memory.query("success", run_id="r1")) == 1

    ReplayEngine(compiled, services).replay(result.trace)
    assert len(memory.query("success", run_id="r1")) == 1
