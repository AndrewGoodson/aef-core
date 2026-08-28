"""`MemoryRetriever` + consolidated knowledge (ADR 0110, increment I3).

Entries and raw records compete under ONE budget, scored by the SAME function.
The knowledge boost is a thumb on the scale and is tested as one — including
that setting it to zero removes it entirely, which is the honest kill if I4's
A/B does not justify it.
"""

from datetime import UTC, datetime

import pytest

from aef.services.context.memory_retriever import MemoryRetriever
from aef.services.knowledge.base import KnowledgeEntry
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore

T1 = datetime(2026, 1, 1, tzinfo=UTC)


def _memory(*contents: dict[str, object]) -> InMemoryMemoryStore:
    store = InMemoryMemoryStore()
    for i, content in enumerate(contents):
        store.write(
            MemoryRecord(
                kind="failure", content=content, run_id=f"r{i}", agent_id="a1", created_at=T1
            )
        )
    return store


def _knowledge(*, occurrences: int = 2, content: dict[str, object] | None = None):
    store = InMemoryKnowledgeStore()
    store.upsert(
        KnowledgeEntry(
            signature="failure:fetch",
            kind="failure",
            content=content if content is not None else {"lesson": "fetch times out"},
            agent_id="a1",
            source_record_ids=tuple(f"src{i}" for i in range(occurrences)),
            first_seen=T1,
            last_seen=T1,
        )
    )
    return store


# ---------------------------------------------------------------------------
# The no-regression claim, asserted rather than assumed
# ---------------------------------------------------------------------------
def test_without_a_knowledge_store_behaviour_is_unchanged() -> None:
    memory = _memory({"lesson": "fetch times out"}, {"lesson": "parse failed"})
    before = MemoryRetriever(memory=memory, agent_id="a1")
    after = MemoryRetriever(memory=memory, agent_id="a1", knowledge=None)

    a = before.retrieve("fetch times out", token_budget=8000)
    b = after.retrieve("fetch times out", token_budget=8000)
    assert [c.source for c in a] == [c.source for c in b]
    assert all(not c.source.startswith("knowledge:") for c in a)


# ---------------------------------------------------------------------------
# Entries compete
# ---------------------------------------------------------------------------
def test_entries_are_retrieved_alongside_records() -> None:
    retriever = MemoryRetriever(
        memory=_memory({"lesson": "fetch times out"}),
        agent_id="a1",
        knowledge=_knowledge(),
    )
    chunks = retriever.retrieve("fetch times out", token_budget=8000)
    sources = [c.source for c in chunks]
    assert any(s.startswith("knowledge:failure:") for s in sources)
    assert any(s.startswith("memory:failure:") for s in sources)


def test_the_boost_lifts_an_entry_above_an_identical_record() -> None:
    """Same content, so the lexical score is identical and the ONLY thing
    separating them is the thumb on the scale."""
    shared: dict[str, object] = {"lesson": "fetch times out"}
    retriever = MemoryRetriever(
        memory=_memory(shared),
        agent_id="a1",
        knowledge=_knowledge(content=shared),
        knowledge_boost=1.0,
    )
    chunks = retriever.retrieve("fetch times out", token_budget=8000)
    assert chunks[0].source.startswith("knowledge:")


def test_zero_boost_removes_the_thumb_entirely() -> None:
    """The honest kill. At 0.0 an entry competes on exactly the same terms as
    a record, so an identical pair ties and falls to the id tie-break."""
    shared: dict[str, object] = {"lesson": "fetch times out"}
    retriever = MemoryRetriever(
        memory=_memory(shared),
        agent_id="a1",
        knowledge=_knowledge(content=shared),
        knowledge_boost=0.0,
    )
    chunks = retriever.retrieve("fetch times out", token_budget=8000)
    scores = [c.relevance_score for c in chunks]
    assert scores[0] == pytest.approx(scores[1])


def test_a_better_evidenced_entry_outranks_a_thinner_one() -> None:
    knowledge = InMemoryKnowledgeStore()
    for signature, n in (("failure:thin", 2), ("failure:thick", 40)):
        knowledge.upsert(
            KnowledgeEntry(
                signature=signature,
                kind="failure",
                content={"lesson": "fetch times out"},
                agent_id="a1",
                source_record_ids=tuple(f"{signature}-{i}" for i in range(n)),
                first_seen=T1,
                last_seen=T1,
            )
        )
    chunks = MemoryRetriever(
        memory=InMemoryMemoryStore(), agent_id="a1", knowledge=knowledge
    ).retrieve("fetch times out", token_budget=8000)
    assert chunks[0].source == "knowledge:failure:failure:thick"


# ---------------------------------------------------------------------------
# Filters and budget
# ---------------------------------------------------------------------------
def test_thinly_evidenced_entries_are_not_worth_budget() -> None:
    retriever = MemoryRetriever(
        memory=InMemoryMemoryStore(),
        agent_id="a1",
        knowledge=_knowledge(occurrences=2),
        knowledge_min_occurrences=5,
    )
    assert retriever.retrieve("fetch times out", token_budget=8000) == []


def test_the_budget_still_binds_across_both_sources() -> None:
    """The whole point of one budget: knowledge must not be a second, unbounded
    channel into the context window."""
    retriever = MemoryRetriever(
        memory=_memory({"lesson": "fetch times out badly"}),
        agent_id="a1",
        knowledge=_knowledge(),
    )
    unbounded = retriever.retrieve("fetch times out", token_budget=8000)
    assert len(unbounded) == 2

    tight = retriever.retrieve("fetch times out", token_budget=12)
    spent = sum(c.token_estimate for c in tight)
    assert spent <= 12
    assert len(tight) < 2


def test_an_entry_carries_its_provenance_to_the_reader() -> None:
    """A consolidated lesson a reader cannot trace back to executions is the
    thing ADR 0101 deleted GraphStore for tolerating."""
    chunks = MemoryRetriever(
        memory=InMemoryMemoryStore(), agent_id="a1", knowledge=_knowledge(occurrences=3)
    ).retrieve("fetch times out", token_budget=8000)
    metadata = chunks[0].metadata
    assert metadata["occurrence_count"] == 3
    assert len(metadata["source_record_ids"]) == 3
    assert 0.0 < metadata["confidence"] < 1.0


def test_another_agents_knowledge_is_never_retrieved() -> None:
    retriever = MemoryRetriever(
        memory=InMemoryMemoryStore(), agent_id="someone-else", knowledge=_knowledge()
    )
    assert retriever.retrieve("fetch times out", token_budget=8000) == []


# ---------------------------------------------------------------------------
# Determinism and validation
# ---------------------------------------------------------------------------
def test_retrieval_is_stable_across_identical_calls() -> None:
    retriever = MemoryRetriever(
        memory=_memory({"lesson": "fetch times out"}, {"lesson": "fetch failed"}),
        agent_id="a1",
        knowledge=_knowledge(),
    )
    a = retriever.retrieve("fetch times out", token_budget=8000)
    b = retriever.retrieve("fetch times out", token_budget=8000)
    assert [c.source for c in a] == [c.source for c in b]


def test_negative_boost_is_refused() -> None:
    with pytest.raises(ValueError, match="knowledge_boost must be non-negative"):
        MemoryRetriever(memory=InMemoryMemoryStore(), agent_id="a1", knowledge_boost=-1.0)


def test_min_occurrences_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="knowledge_min_occurrences must be at least 1"):
        MemoryRetriever(memory=InMemoryMemoryStore(), agent_id="a1", knowledge_min_occurrences=0)
