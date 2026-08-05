"""Reflection -> proposer grounding: the wire that makes this self-learning.

`make_reflect_node` has written failure/success memory since M0 and nothing
read it, so the system recorded lessons and never used one. These tests run
the real reflect node through a real GraphExecutor into a real memory store,
then propose from what it recorded.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.corpus import Corpus, Scenario, Split
from aef.harness.proposer import (
    CitationKind,
    MemoryEvidence,
    ProposalError,
    RuleBasedProposer,
)
from aef.kernel import Context, Edge, Graph, GraphExecutor, Node, Route, Services
from aef.reasoning.nodes import make_reflect_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, StateDelta

SOURCE = "RETRY_LIMIT = 3\nTIMEOUT_S = 2.5\n"


def _state(run_id: str = "r1", **overrides: object) -> AEFState:
    defaults: dict[str, object] = {
        "run_id": run_id,
        "agent_id": "demo",
        "objective": "obj",
    }
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


def _services(memory: InMemoryMemoryStore) -> Services:
    return Services(
        memory=memory,
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
    )


def _record_a_real_failure(memory: InMemoryMemoryStore, run_id: str = "r1") -> None:
    """Run a real graph whose work node fails, through a real reflect node."""

    def failing(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        return StateDelta(errors=[{"node_id": ctx.node_id, "error": "timed out twice"}]), "reflect"

    work = Node(id="work", version="0.1.0", fn=failing, deterministic=True)
    reflect = make_reflect_node()
    graph = Graph(
        id="g",
        version="0.1.0",
        nodes={"work": work, "reflect": reflect},
        edges=[Edge(from_node="work", to_node="reflect")],
        entry_node="work",
    )
    GraphExecutor(graph.compile(), _services(memory)).run(_state(run_id))


# --------------------------------------------------------------------------
# ACCEPTANCE — a recorded failure produces a grounded proposal citing it
# --------------------------------------------------------------------------


def test_a_recorded_failure_becomes_citable_evidence() -> None:
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory)

    evidence = MemoryEvidence.from_store(memory)

    assert evidence.records, "the reflect node wrote nothing the proposer can read"
    assert "timed out twice" in evidence.records[0].content["verbal_feedback"]


def test_a_recorded_failure_produces_a_proposal_that_cites_it() -> None:
    """THE acceptance property: the loop learns from its own runs."""
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory)
    evidence = MemoryEvidence.from_store(memory)

    proposals = RuleBasedProposer().propose_from_memory(
        evidence, proposal_id="p1", path="agents/demo/graph.py", source=SOURCE
    )

    assert proposals
    for proposal in proposals:
        assert proposal.grounded_in
        assert all(c.kind is CitationKind.MEMORY for c in proposal.grounded_in)
        assert proposal.grounded_in[0].source in evidence.ids


def test_the_rationale_traces_back_to_the_recorded_feedback() -> None:
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory)

    proposals = RuleBasedProposer().propose_from_memory(
        MemoryEvidence.from_store(memory),
        proposal_id="p1",
        path="agents/demo/graph.py",
        source=SOURCE,
    )
    assert "timed out twice" in proposals[0].rationale


def test_no_recorded_failures_produces_no_proposal() -> None:
    # The proposer does not fall back to speculating when it has learned
    # nothing.
    assert (
        RuleBasedProposer().propose_from_memory(
            MemoryEvidence(), proposal_id="p1", path="a.py", source=SOURCE
        )
        == ()
    )


def test_an_ungrounded_proposal_is_still_impossible() -> None:
    with pytest.raises(ProposalError):
        RuleBasedProposer().propose(
            proposal_id="p1", path="a.py", source=SOURCE, citations=(), rationale="hunch"
        )


# --------------------------------------------------------------------------
# The leak the split exists to prevent, by proxy
# --------------------------------------------------------------------------


def _corpus(**splits: Split) -> Corpus:
    scenarios = tuple(
        Scenario(
            id=sid,
            split=split,
            graph_id="g",
            graph_version="1",
            initial_state=_state(sid),
            trace=(),
            recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        for sid, split in splits.items()
    )
    return Corpus(root=Path("/nowhere"), scenarios=scenarios)


@pytest.mark.parametrize("split", [Split.VALIDATION, Split.HOLDOUT])
def test_memory_from_a_gated_split_run_is_excluded(split: Split) -> None:
    """A reflect node running over a holdout scenario writes a record whose
    run_id IS that scenario's id. Citing it leaks the holdout by proxy — the
    split check on scenarios would never see it."""
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory, run_id="secret")

    evidence = MemoryEvidence.from_store(memory, _corpus(secret=split))

    assert evidence.records == ()
    assert evidence.excluded, "the record should be reported as excluded, not silently dropped"


def test_memory_from_a_train_run_is_admissible() -> None:
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory, run_id="known")
    assert MemoryEvidence.from_store(memory, _corpus(known=Split.TRAIN)).records


def test_memory_from_a_production_run_is_admissible() -> None:
    # A production run has an arbitrary run_id appearing in no split, and
    # production experience is exactly what this exists to learn from.
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory, run_id="prod-8f21")
    assert MemoryEvidence.from_store(memory, _corpus(other=Split.HOLDOUT)).records


def test_citing_an_inadmissible_record_is_refused() -> None:
    memory = InMemoryMemoryStore()
    _record_a_real_failure(memory, run_id="secret")
    evidence = MemoryEvidence.from_store(memory, _corpus(secret=Split.HOLDOUT))

    with pytest.raises(ProposalError, match="not admissible"):
        evidence.cite("anything")


def test_a_memory_citation_carrying_a_split_is_refused() -> None:
    # A split on a memory citation would look like a check while checking
    # nothing — admissibility depends on the RUN, which MemoryEvidence decides.
    from aef.harness.proposer import Citation

    with pytest.raises(ProposalError, match="carries no split"):
        RuleBasedProposer().propose(
            proposal_id="p1",
            path="a.py",
            source=SOURCE,
            citations=(Citation(source="m1", split=Split.TRAIN, kind=CitationKind.MEMORY),),
            rationale="r",
        )


@pytest.mark.parametrize("split", [Split.VALIDATION, Split.HOLDOUT])
def test_a_scenario_citation_outside_train_is_still_refused(split: Split) -> None:
    from aef.harness.proposer import Citation

    with pytest.raises(ProposalError, match="train split only"):
        RuleBasedProposer().propose(
            proposal_id="p1",
            path="a.py",
            source=SOURCE,
            citations=(Citation(source="s9", split=split),),
            rationale="r",
        )
