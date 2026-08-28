"""`make_consolidate_node` — the wiring that makes consolidation reach the
knowledge store (ADR 0110, increment I3).

The acceptance property: a **real** `GraphExecutor` run over a graph that
reflects and then consolidates produces `KnowledgeEntry`s queryable back out of
a real `InMemoryKnowledgeStore`. Real graph, real executor, real stores — never
a mock of the thing under test.
"""

from datetime import UTC, datetime

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
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.knowledge.consolidate import RuleBasedConsolidator
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, StateDelta


def _state(run_id: str = "r1", **overrides: object) -> AEFState:
    defaults: dict[str, object] = {
        "run_id": run_id,
        "agent_id": "a1",
        "objective": "settle the invoice",
    }
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


def _services(
    memory: InMemoryMemoryStore | None = None,
    knowledge: InMemoryKnowledgeStore | None = None,
    **overrides: object,
) -> Services:
    defaults: dict[str, object] = {
        "memory": memory if memory is not None else InMemoryMemoryStore(),
        "knowledge": knowledge if knowledge is not None else InMemoryKnowledgeStore(),
        "critic": RuleBasedCritic(),
        "judge": RuleBasedJudge(rubric={"quality": 1.0}),
    }
    defaults.update(overrides)
    return Services(**defaults)  # type: ignore[arg-type]


def _failing_node(node_id: str = "fetch") -> Node:
    """A node that records an error, so reflection writes failure memory
    attributed to it — which is what `default_signature` keys on."""

    def fn(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        return StateDelta(errors=[{"node_id": node_id, "error": "timeout"}]), "reflect"

    return Node(id=node_id, version="1", fn=fn, deterministic=True)


def _graph(consolidate: Node | None = None) -> Graph:
    nodes = [
        _failing_node(),
        make_reflect_node(route="consolidate"),
        consolidate if consolidate is not None else make_consolidate_node(route=END),
    ]
    return Graph(
        id="g",
        version="1.0.0",
        nodes={n.id: n for n in nodes},
        edges=[
            Edge(from_node="fetch", to_node="reflect"),
            Edge(from_node="reflect", to_node="consolidate"),
        ],
        entry_node="fetch",
    )


# ---------------------------------------------------------------------------
# The acceptance property
# ---------------------------------------------------------------------------
def test_two_real_runs_produce_a_queryable_knowledge_entry() -> None:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = _services(memory, knowledge)
    executor = GraphExecutor(_graph().compile(), services)

    executor.run(_state(run_id="r1"))
    assert knowledge.query("failure") == [], "one run is an episode, not knowledge"

    executor.run(_state(run_id="r2"))
    entries = knowledge.query("failure")
    assert len(entries) == 1
    assert entries[0].signature == "failure:fetch"
    assert entries[0].occurrence_count == 2
    assert entries[0].agent_id == "a1"


def test_a_third_run_extends_rather_than_duplicates() -> None:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    executor = GraphExecutor(_graph().compile(), _services(memory, knowledge))
    for run_id in ("r1", "r2", "r3"):
        executor.run(_state(run_id=run_id))

    entries = knowledge.query("failure")
    assert len(entries) == 1
    assert entries[0].occurrence_count == 3


def test_agents_do_not_pool_their_knowledge_through_a_shared_store() -> None:
    """The shared-store seam. Two agents, one knowledge store, one run each:
    neither reaches the threshold, and nothing is written."""
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    executor = GraphExecutor(_graph().compile(), _services(memory, knowledge))
    executor.run(_state(run_id="r1", agent_id="a1"))
    executor.run(_state(run_id="r2", agent_id="a2"))
    assert knowledge.query("failure") == []


# ---------------------------------------------------------------------------
# Contract compliance
# ---------------------------------------------------------------------------
def test_node_declares_its_side_effects_honestly() -> None:
    node = make_consolidate_node()
    assert node.side_effects is SideEffect.IO
    assert node.deterministic is False
    assert node.idempotency_key_fn is not None


def test_idempotency_key_is_stable_per_step_and_distinct_across_steps() -> None:
    node = make_consolidate_node()
    assert node.idempotency_key_fn is not None
    first = node.idempotency_key_fn(_state(checkpoint_seq=3))
    again = node.idempotency_key_fn(_state(checkpoint_seq=3))
    later = node.idempotency_key_fn(_state(checkpoint_seq=4))
    assert first == again
    assert first != later


def test_missing_knowledge_service_raises_a_named_error() -> None:
    node = make_consolidate_node()
    services = _services(knowledge=None)
    services = Services(
        memory=services.memory, critic=services.critic, judge=services.judge, knowledge=None
    )
    ctx = Context(
        run_id="r1", graph_version="1", trace_id="t", node_id="consolidate", now=services.clock()
    )
    with pytest.raises(ServiceNotConfiguredError, match="knowledge"):
        node.fn(_state(), ctx, services)


def test_the_node_writes_nothing_to_state() -> None:
    """Its product lives in the knowledge store. A summary copied onto state
    would be a second, staler account of what was consolidated."""
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    executor = GraphExecutor(_graph().compile(), _services(memory, knowledge))
    executor.run(_state(run_id="r1"))
    result = executor.run(_state(run_id="r2"))
    assert result.final_state.working_memory == {}


def test_a_custom_consolidator_is_honoured() -> None:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    node = make_consolidate_node(consolidator=RuleBasedConsolidator(min_occurrences=3))
    executor = GraphExecutor(_graph(consolidate=node).compile(), _services(memory, knowledge))
    executor.run(_state(run_id="r1"))
    executor.run(_state(run_id="r2"))
    assert knowledge.query("failure") == [], "threshold of 3 not yet met"
    executor.run(_state(run_id="r3"))
    assert len(knowledge.query("failure")) == 1


def test_agent_services_supplies_a_knowledge_store_by_default() -> None:
    """Parity: a graph with a consolidate node must not work under one
    construction path and raise ServiceNotConfiguredError under another —
    the ADR 0073/0075/0079/0091 shape."""
    from aef.services.runtime import agent_services

    assert isinstance(agent_services().knowledge, InMemoryKnowledgeStore)


def test_the_default_knowledge_store_is_throwaway_not_shared() -> None:
    """Two calls to the factory must not hand back one store: a gate
    re-execution writing into the adopter's knowledge would mutate the
    evidence a later proposal is built from."""
    from aef.services.runtime import agent_services

    assert agent_services().knowledge is not agent_services().knowledge


def test_a_run_consolidates_only_its_own_agent() -> None:
    """Found by a planted fault the first draft of this file MISSED.

    Passing `agent_id=None` inside the node is indistinguishable from
    `state.agent_id` in a single-agent test, so every assertion here passed
    with the fault in place. The difference is containment: with `None`, agent
    a1 merely RUNNING causes entries to be written about agent a2, out of a2's
    records, at a moment a2 did nothing. Knowledge would then appear for an
    agent that has not executed — attributed correctly, but authored by
    somebody else's run.

    It also silently caps recall: a shared memory store read across agents
    fills `candidates_per_kind` with other agents' records.
    """
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()

    # a2 already has enough history to consolidate, but never runs here.
    for run_id in ("a2-r1", "a2-r2"):
        memory.write(
            MemoryRecord(
                kind="failure",
                content={
                    "failing_nodes": ["fetch"],
                    "verbal_feedback": "timeout",
                    "objective": "settle the invoice",
                },
                run_id=run_id,
                agent_id="a2",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

    executor = GraphExecutor(_graph().compile(), _services(memory, knowledge))
    executor.run(_state(run_id="a1-r1", agent_id="a1"))

    assert knowledge.get(("a2", "failure:fetch")) is None, "a1's run wrote knowledge about a2"
