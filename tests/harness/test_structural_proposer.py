"""A proposer that changes structure, not just numbers.

The judging apparatus — six gates, a control cohort, a tripwire corpus — was
built for changes far larger than "adjust a constant by 25%". This is the
first transformation that changes what the graph DOES (ADR 0096).

The four properties every transformation must hold, each traceable to a
defect this program actually found, are asserted here rather than assumed:
a readable diff, a citation that constrains the change, individual
revertibility, and no touching of HITL routing (ADR 0089).
"""

import difflib

import pytest

from aef.harness.outcome import classify
from aef.harness.proposer import MemoryEvidence, RuleBasedProposer
from aef.harness.transformations import (
    TransformationError,
    _assert_hitl_untouched,
    add_deterministic_fallback,
)
from aef.kernel import Edge, Graph, GraphExecutor, Node
from aef.reasoning.nodes import make_reflect_node
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

AGENT = """from aef.kernel import END, Edge, Graph, Node
from aef.state import Plan, StateDelta


def fetch(state, ctx, services):
    raise RuntimeError("upstream timed out")


def use_cache(state, ctx, services):
    return StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 0.8}), END


def build_graph():
    return Graph(
        id="demo", version="1",
        nodes={
            "fetch": Node(id="fetch", version="1", fn=fetch, deterministic=True),
            "use_cache": Node(id="use_cache", version="1", fn=use_cache, deterministic=True),
        },
        edges=[Edge(from_node="fetch", to_node="use_cache")],
        entry_node="fetch",
    )
"""


def _memory_blaming(node_id: str) -> InMemoryMemoryStore:
    """A REAL failing run, reflected into memory — not a hand-built record."""

    def failing(state, ctx, services):  # type: ignore[no-untyped-def]
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="failed"),
                errors=[{"node_id": node_id, "error": "upstream timed out"}],
            ),
            "reflect",
        )

    graph = Graph(
        id="demo",
        version="1",
        nodes={
            node_id: Node(id=node_id, version="1", fn=failing, deterministic=True),
            "reflect": make_reflect_node(),
        },
        edges=[Edge(from_node=node_id, to_node="reflect")],
        entry_node=node_id,
    )
    store = InMemoryMemoryStore()
    GraphExecutor(graph.compile(), agent_services(memory=store)).run(
        AEFState(run_id="prod-1", agent_id="demo", objective="fetch the thing")
    )
    return store


def _execute(source: str):  # type: ignore[no-untyped-def]
    namespace: dict[str, object] = {}
    exec(compile(source, "agent", "exec"), namespace)
    try:
        result = GraphExecutor(
            namespace["build_graph"]().compile(),
            agent_services(),  # type: ignore[operator]
        ).run(AEFState(run_id="t", agent_id="demo", objective="fetch"), record_trace=True)
    except Exception:
        return None
    return classify(result.final_state, result.trace, terminated=True)


# --------------------------------------------------------------------------
# The memory must say WHICH node failed
# --------------------------------------------------------------------------


def test_the_reflect_node_records_which_node_failed() -> None:
    """`ctx.node_id` inside the reflect node is `"reflect"` — the node that
    OBSERVED the failure. The failing node's id sat in
    `state.errors[i]["node_id"]`, which the reflect node read to build the
    feedback text and then discarded. A numeric proposer never needed it; a
    structural one cannot begin without it (ADR 0096)."""
    record = _memory_blaming("fetch").query(kind="failure", limit=1)[0]
    assert record.content["node_id"] == "reflect", "who observed it"
    assert record.content["failing_nodes"] == ["fetch"], "who caused it"


def test_an_error_with_no_recorded_origin_is_not_attributed() -> None:
    """Guessing which node produced an unattributed error is worse than
    omitting it."""
    from aef.reasoning.nodes import _failing_nodes

    state = AEFState(
        run_id="r",
        agent_id="a",
        objective="o",
        errors=[{"node_id": "a", "error": "x"}, {"error": "no origin"}, {"node_id": "a"}],
    )
    assert _failing_nodes(state) == ["a"]


# --------------------------------------------------------------------------
# The transformation
# --------------------------------------------------------------------------


def test_it_produces_a_two_token_diff() -> None:
    """Property 1: a diff a human can read, and one G0 can size."""
    change = add_deterministic_fallback(
        source=AGENT, failing_node="fetch", handler="use_cache", citation="mem-1"
    )
    changed = [
        line
        for line in difflib.unified_diff(
            AGENT.splitlines(), change.source.splitlines(), lineterm="", n=0
        )
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert len(changed) == 2, changed
    assert "fallback_node_id='use_cache'" in change.source


@pytest.mark.parametrize(
    ("name", "kwargs", "match"),
    [
        (
            "node the file does not declare",
            {"failing_node": "nope", "handler": "use_cache"},
            "does not declare",
        ),
        (
            "handler that does not exist",
            {"failing_node": "fetch", "handler": "invented"},
            "does not invent",
        ),
        ("fallback to itself", {"failing_node": "fetch", "handler": "fetch"}, "not a recovery"),
    ],
)
def test_it_refuses_what_it_cannot_justify(name, kwargs, match) -> None:  # type: ignore[no-untyped-def]
    """It does not invent a handler. An invented one would pass the gates by
    doing nothing, since the corpus only asks whether things still work."""
    with pytest.raises(TransformationError, match=match):
        add_deterministic_fallback(source=AGENT, citation="c", **kwargs)


def test_it_refuses_to_overwrite_an_existing_fallback() -> None:
    """Changing an existing fallback is a different operation with different
    evidence — property 3, one named operation, one coherent change."""
    once = add_deterministic_fallback(
        source=AGENT, failing_node="fetch", handler="use_cache", citation="c"
    )
    with pytest.raises(TransformationError, match="already declares a fallback"):
        add_deterministic_fallback(
            source=once.source, failing_node="fetch", handler="use_cache", citation="c"
        )


@pytest.mark.parametrize(
    ("name", "after"),
    [
        (
            "clears the flag",
            'from aef.kernel import Edge\nE = Edge(from_node="a", to_node="d", '
            "requires_human_approval=False)\n",
        ),
        (
            "removes the kwarg",
            'from aef.kernel import Edge\nE = Edge(from_node="a", to_node="d")\n',
        ),
        (
            "adds a gate",
            'from aef.kernel import Edge\nE = Edge(from_node="a", to_node="d", '
            "requires_human_approval=True)\n"
            'E2 = Edge(from_node="b", to_node="s", requires_human_approval=True)\n',
        ),
    ],
)
def test_no_transformation_may_touch_hitl_routing(name, after) -> None:  # type: ignore[no-untyped-def]
    """Property 4. ADR 0089 measured what this buys an attacker: a candidate
    that broke five scenarios and added `requires_human_approval=True`
    converted every regression into a G2 pass.

    Checked on the RESULT rather than trusted from the operation — a
    transformation that reasons about its own safety is the shape ADR 0080
    found hackable."""
    before = (
        'from aef.kernel import Edge\nE = Edge(from_node="a", to_node="d", '
        "requires_human_approval=True)\n"
    )
    with pytest.raises(TransformationError, match="human-approval routing"):
        _assert_hitl_untouched(before, after)


def test_an_unrelated_change_is_not_flagged() -> None:
    """The control. A guard that fires on everything is not a guard."""
    before = (
        'from aef.kernel import Edge\nE = Edge(from_node="a", to_node="d", '
        "requires_human_approval=True)\n"
    )
    _assert_hitl_untouched(before, before + "X = 1\n")


# --------------------------------------------------------------------------
# The proposer, and the acceptance test
# --------------------------------------------------------------------------


def test_the_citation_names_the_record_that_named_the_node() -> None:
    """Property 2. The previous rationale read "grounded in recorded
    failures" while the mutation was independent of what the failure said —
    a citation that does not constrain the change is decoration."""
    store = _memory_blaming("fetch")
    evidence = MemoryEvidence.from_store(store)
    (proposal,) = RuleBasedProposer().propose_from_memory(
        evidence, proposal_id="c1", path="agents/demo/graph.py", source=AGENT
    )

    assert "add_deterministic_fallback" in proposal.id
    assert "'fetch' raised" in proposal.rationale
    cited = {c.source for c in proposal.grounded_in}
    assert cited == {record_id for _, record_id in evidence.failing_nodes()}


def test_a_structural_repair_passes_where_the_incumbent_crashed() -> None:
    """MILESTONE 1 ACCEPTANCE. Not "did it produce a diff" — did the diff
    REPAIR the planted failure.

    The incumbent raises and the run dies. The proposal routes the failure to
    the existing handler, the run completes, and the error is still counted
    and reported — recovered, not erased (ADR 0076).
    """
    store = _memory_blaming("fetch")
    (proposal,) = RuleBasedProposer().propose_from_memory(
        MemoryEvidence.from_store(store),
        proposal_id="c1",
        path="agents/demo/graph.py",
        source=AGENT,
    )

    assert _execute(AGENT) is None, "the fixture must actually crash"

    after = _execute(proposal.proposed)
    assert after is not None, "the proposal did not repair the crash"
    assert after.passed
    assert after.error_count == 1, "the failure is still reported"
    assert after.recovered_errors == 1, "and marked as recovered"
    assert after.node_path == ("fetch", "use_cache")


def test_a_declared_fallback_that_takes_over_marks_the_error_recovered() -> None:
    """ADR 0076 added the marker and said plainly that nothing set it. The
    executor's fallback path is the one place that knows a node raised AND
    that control continued — and it is Zone B, so the marker keeps the
    unforgeability ADR 0080 found `recovered` lacked when agent code wrote
    it (ADR 0097).

    Without this a fallback that WORKS still scores as a failure, so the loop
    could never be rewarded for adding one."""
    outcome = _execute(
        add_deterministic_fallback(
            source=AGENT, failing_node="fetch", handler="use_cache", citation="c"
        ).source
    )
    assert outcome is not None
    assert outcome.recovered_errors == 1
    assert outcome.passed


def test_no_memory_means_no_structural_proposal() -> None:
    """The proposer does not speculate when it has learned nothing."""
    assert (
        RuleBasedProposer().propose_from_memory(
            MemoryEvidence(), proposal_id="c1", path="p", source=AGENT
        )
        == ()
    )


def test_a_record_written_before_the_field_existed_contributes_nothing() -> None:
    """Absence is "no structural proposal available", not an error."""
    from aef.services.memory.base import MemoryRecord

    evidence = MemoryEvidence(
        records=(MemoryRecord(kind="failure", content={"verbal_feedback": "x"}, run_id="r"),)
    )
    assert evidence.failing_nodes() == ()
