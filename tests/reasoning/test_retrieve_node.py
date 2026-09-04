"""The retrieve node and the outcome signal it enables (ADR 0118).

Reproduce-first: `Retriever` had no production caller — no node in any graph
asked `Services.retriever` for anything, so `context_budget_tokens` governed
nothing in a real run. The first test pins the fix end to end through the
real executor; the rest pin the signal: which lessons were in context, and
whether the run then avoided or repeated the failure they describe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aef.kernel import END, Context, Edge, Graph, GraphExecutor, Node, Route, Services
from aef.kernel.contracts import ServiceNotConfiguredError
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node, make_retrieve_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.context.memory_retriever import MemoryRetriever
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, Plan, StateDelta

T0 = datetime(2026, 9, 3, tzinfo=UTC)


class _Ticking:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> datetime:
        self.n += 1
        return T0 + timedelta(minutes=self.n)


def _work(node_id: str, *, fails: bool) -> Node:
    def fn(s: AEFState, c: Context, sv: Services) -> tuple[StateDelta, Route]:
        if fails:
            return StateDelta(
                errors=[{"node_id": node_id, "error": f"{node_id} timed out"}]
            ), "reflect"
        return StateDelta(
            plan=Plan(goal=s.objective, status="done"), scores={"quality": 1.0}
        ), "reflect"

    return Node(id=node_id, version="1", fn=fn, deterministic=True)


def _graph(node_id: str, *, fails: bool) -> Graph:
    nodes = [
        make_retrieve_node(route=node_id),
        _work(node_id, fails=fails),
        make_reflect_node(route="consolidate"),
        make_consolidate_node(route=END),
    ]
    return Graph(
        id="g",
        version="1",
        nodes={n.id: n for n in nodes},
        edges=[
            Edge(from_node="retrieve", to_node=node_id),
            Edge(from_node=node_id, to_node="reflect"),
            Edge(from_node="reflect", to_node="consolidate"),
        ],
        entry_node="retrieve",
    )


def _services(memory: InMemoryMemoryStore, knowledge: InMemoryKnowledgeStore) -> Services:
    return Services(
        memory=memory,
        knowledge=knowledge,
        retriever=MemoryRetriever(memory=memory, agent_id="a1", knowledge=knowledge),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
        clock=_Ticking(),
    )


def _run(
    services: Services, node_id: str, *, fails: bool, run_id: str, budget: int = 8000
) -> AEFState:
    return (
        GraphExecutor(_graph(node_id, fails=fails).compile(), services)
        .run(
            AEFState(
                run_id=run_id,
                agent_id="a1",
                objective="fetch timed out; settle the invoice",
                context_budget_tokens=budget,
            )
        )
        .final_state
    )


# ---------------------------------------------------------------------------
# The defect: nothing called the retriever
# ---------------------------------------------------------------------------
def test_retrieve_node_puts_ranked_context_on_state_within_the_state_budget() -> None:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = _services(memory, knowledge)
    for i in range(2):
        _run(services, "fetch", fails=True, run_id=f"r{i}")
    final = _run(services, "fetch", fails=True, run_id="r2")
    assert final.retrieved_context, "nothing retrieved: the retriever still has no caller"
    assert all(c["token_estimate"] > 0 for c in final.retrieved_context)
    assert sum(c["token_estimate"] for c in final.retrieved_context) <= final.context_budget_tokens
    sources = {c["source"] for c in final.retrieved_context}
    assert any(s.startswith("knowledge:failure:") for s in sources)


def test_the_state_budget_is_the_one_enforced() -> None:
    """A budget too small for any chunk retrieves nothing — the planted fault
    that shows `context_budget_tokens` now governs a real run."""
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = _services(memory, knowledge)
    for i in range(2):
        _run(services, "fetch", fails=True, run_id=f"r{i}")
    starved = _run(services, "fetch", fails=True, run_id="r2", budget=1)
    assert starved.retrieved_context == []


def test_an_unconfigured_retriever_is_a_named_refusal() -> None:
    services = Services(critic=RuleBasedCritic(), judge=RuleBasedJudge(rubric={"quality": 1.0}))
    with pytest.raises(ServiceNotConfiguredError, match="retriever"):
        GraphExecutor(_graph("fetch", fails=True).compile(), services).run(
            AEFState(run_id="r", agent_id="a1", objective="o")
        )


# ---------------------------------------------------------------------------
# The signal: which lessons were in context, and what happened next
# ---------------------------------------------------------------------------
def test_reflection_records_the_lessons_that_were_in_context() -> None:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = _services(memory, knowledge)
    for i in range(2):
        _run(services, "fetch", fails=True, run_id=f"r{i}")
    _run(services, "fetch", fails=True, run_id="r2")
    record = memory.query("failure", run_id="r2", limit=1)[0]
    assert record.content["retrieved_signatures"] == ["failure:fetch"]
    early = memory.query("failure", run_id="r0", limit=1)[0]
    assert early.content["retrieved_signatures"] == []  # nothing consolidated yet


def test_tally_counts_helpful_and_harmful_from_what_was_shown() -> None:
    """Lesson in context, same failure recurs -> harmful. Lesson in context,
    run succeeds -> helpful. Lesson not in context -> counts nothing."""
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = _services(memory, knowledge)
    # Two failures establish the lesson; neither had it in context.
    _run(services, "fetch", fails=True, run_id="r0")
    _run(services, "fetch", fails=True, run_id="r1")
    # Three runs with the lesson in context: two fail again, one succeeds.
    _run(services, "fetch", fails=True, run_id="r2")
    _run(services, "fetch", fails=True, run_id="r3")
    _run(services, "fetch", fails=False, run_id="r4")
    entry = next(
        e
        for e in knowledge.query("failure", agent_id="a1", limit=10)
        if e.signature == "failure:fetch"
    )
    assert (entry.helpful, entry.harmful) == (1, 2)
    # And the tally travels with retrieved chunks and into skill drafts.
    from aef.harness.skills import render_skill

    draft = render_skill(entry)
    assert "(helpful): 1" in draft and "(harmful): 2" in draft
    final = _run(services, "fetch", fails=True, run_id="r5")
    chunk = next(
        c for c in final.retrieved_context if c["source"] == "knowledge:failure:failure:fetch"
    )
    assert (chunk["metadata"]["helpful"], chunk["metadata"]["harmful"]) == (1, 2)


def test_tally_is_agent_scoped() -> None:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = _services(memory, knowledge)
    for i in range(3):
        _run(services, "fetch", fails=True, run_id=f"r{i}")
    # Another agent's run with the same signature in context must not count.
    from aef.services.memory.base import MemoryRecord

    memory.write(
        MemoryRecord(
            kind="failure",
            content={"failing_nodes": ["fetch"], "retrieved_signatures": ["failure:fetch"]},
            run_id="other-1",
            agent_id="a2",
            created_at=T0 + timedelta(hours=1),
        )
    )
    _run(services, "fetch", fails=False, run_id="r3")
    # Consolidate ACROSS agents (agent_id=None reads every agent's records and
    # groups by each record's own agent), which is the only path where the
    # tally's own scoping does any work — with a single-agent query the store
    # filter hides a missing check, and a mutation removing it passed.
    from aef.services.knowledge.consolidate import RuleBasedConsolidator

    fresh = InMemoryKnowledgeStore()
    RuleBasedConsolidator().consolidate(memory, fresh, agent_id=None)
    entry = next(
        e for e in fresh.query("failure", agent_id="a1", limit=10) if e.signature == "failure:fetch"
    )
    assert (entry.helpful, entry.harmful) == (1, 1)
