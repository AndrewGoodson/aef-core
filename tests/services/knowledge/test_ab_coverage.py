"""I4 — the A/B that was allowed to delete this layer (ADR 0110).

**The metric was fixed before anything was measured**: *distinct-lesson
coverage* — how many distinct failure signatures are represented in the
retrieved set under a given `context_budget_tokens`. Chosen because
consolidation's entire mechanism is collapsing R near-duplicate records about
one recurring failure into a single entry; if that works, the freed budget buys
coverage of OTHER lessons, and if coverage does not move, the layer is surface
area for nothing.

Falsification conditions, also stated in advance: coverage equal or worse at
every R>=2 kills the layer; an advantage appearing only at implausibly high R
is reported as weak rather than as a win; and R=1 must show NO change, since no
entries exist there — a control against a rigged rig.

Corpus is built from **real `GraphExecutor` runs** through reflect ->
consolidate, not hand-assembled records, so the measurement is end-to-end.

Measured, 6 lessons, coverage out of 6 (raw -> wiki):

```
budget   R=1      R=2      R=3      R=5      R=10
   200   1 -> 1   1 -> 3   1 -> 3   1 -> 3   1 ->  2
   400   3 -> 3   2 -> 6   1 -> 6   1 -> 6   1 ->  5
   800   6 -> 6   5 -> 6   4 -> 6   3 -> 6   1 ->  6
  2000   6 -> 6   6 -> 6   6 -> 6   6 -> 6   5 ->  6
```

Two things in that table, and the second is the more interesting one. Wiki
never loses. And **raw-records-only DEGRADES as experience accumulates** —
at budget 800 it falls 6 -> 5 -> 4 -> 3 -> 1 as R rises, because near-duplicate
records about one failure crowd out every other lesson. More experience makes
the un-consolidated agent retrieve worse. Wiki holds at 6.

The knob did not survive. See `test_the_boost_buys_no_coverage_at_any_setting`.
"""

from datetime import UTC, datetime

from aef.kernel import END, Context, Edge, Graph, GraphExecutor, Node, Route, Services
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.context.base import RetrievedChunk
from aef.services.context.memory_retriever import MemoryRetriever
from aef.services.knowledge.base import KnowledgeEntry
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, StateDelta

LESSONS = ("fetch", "parse", "auth", "settle", "notify", "reconcile")
QUERY = "node timed out error failure settle the invoice"
T = datetime(2026, 1, 1, tzinfo=UTC)


def _failing(node_id: str) -> Node:
    def fn(s: AEFState, c: Context, sv: Services) -> tuple[StateDelta, Route]:
        return (
            StateDelta(errors=[{"node_id": node_id, "error": f"{node_id} timed out"}]),
            "reflect",
        )

    return Node(id=node_id, version="1", fn=fn, deterministic=True)


def _build(k: int, r: int) -> tuple[InMemoryMemoryStore, InMemoryKnowledgeStore]:
    """`k` distinct lessons, each failing across `r` runs. Real executor."""
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = Services(
        memory=memory,
        knowledge=knowledge,
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
        clock=lambda: T,
    )
    for lesson in LESSONS[:k]:
        nodes = [
            _failing(lesson),
            make_reflect_node(route="consolidate"),
            make_consolidate_node(route=END),
        ]
        graph = Graph(
            id="g",
            version="1.0.0",
            nodes={n.id: n for n in nodes},
            edges=[
                Edge(from_node=lesson, to_node="reflect"),
                Edge(from_node="reflect", to_node="consolidate"),
            ],
            entry_node=lesson,
        )
        executor = GraphExecutor(graph.compile(), services)
        for i in range(r):
            executor.run(
                AEFState(run_id=f"{lesson}-{i}", agent_id="a1", objective="settle the invoice")
            )
    return memory, knowledge


def _covered(chunks: list[RetrievedChunk]) -> set[str]:
    """A lesson counts as covered when a retrieved chunk names its node."""
    return {
        lesson
        for chunk in chunks
        for lesson in LESSONS
        if f'"{lesson}"' in chunk.content or f"{lesson}>" in chunk.content
    }


def _coverage(k: int, r: int, budget: int, boost: float = 0.0) -> tuple[int, int]:
    memory, knowledge = _build(k, r)
    raw = MemoryRetriever(memory=memory, agent_id="a1")
    wiki = MemoryRetriever(memory=memory, agent_id="a1", knowledge=knowledge, knowledge_boost=boost)
    return (
        len(_covered(raw.retrieve(QUERY, token_budget=budget))),
        len(_covered(wiki.retrieve(QUERY, token_budget=budget))),
    )


# ---------------------------------------------------------------------------
# The control — proves the rig is not rigged
# ---------------------------------------------------------------------------
def test_with_no_recurrence_the_wiki_changes_nothing() -> None:
    """R=1 produces no entries, so both arms must be identical. If this ever
    diverges, every other number in this file is measuring an artefact.

    The PRECONDITION is asserted, not just the consequence — a planted fault
    (consolidator threshold lowered to 1) showed why. Entries were produced at
    R=1, and this test still passed, because the retriever's own independent
    `knowledge_min_occurrences=2` filtered them back out. The equality held for
    a reason that had nothing to do with the claim in the docstring, so the
    control was confirming itself rather than the layer.
    """
    _, knowledge = _build(6, 1)
    assert knowledge.query("failure", agent_id="a1", limit=999) == [], (
        "one occurrence produced knowledge — the control's premise is false"
    )

    for budget in (200, 400, 800, 2000):
        raw, wiki = _coverage(6, 1, budget)
        assert raw == wiki, f"budget={budget}: arms diverged with zero entries"


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------
def test_consolidation_buys_coverage_under_a_tight_budget() -> None:
    raw, wiki = _coverage(6, 5, 400)
    assert (raw, wiki) == (1, 6)


def test_the_wiki_never_covers_less() -> None:
    for budget in (200, 400, 800, 2000):
        for r in (1, 2, 3, 5, 10):
            raw, wiki = _coverage(6, r, budget)
            assert wiki >= raw, f"wiki LOST at budget={budget}, R={r}: {wiki} < {raw}"


def test_unconsolidated_retrieval_degrades_as_experience_accumulates() -> None:
    """The mechanism, isolated. Near-duplicate records about one recurring
    failure crowd out every other lesson, so MORE experience makes the
    un-consolidated agent retrieve WORSE. Consolidation is what stops it."""
    raw_by_r = {r: _coverage(6, r, 800)[0] for r in (2, 3, 5, 10)}
    assert raw_by_r[2] > raw_by_r[5] > raw_by_r[10]

    wiki_by_r = {r: _coverage(6, r, 800)[1] for r in (2, 3, 5, 10)}
    assert set(wiki_by_r.values()) == {6}


# ---------------------------------------------------------------------------
# The knob did not survive
# ---------------------------------------------------------------------------
def test_the_boost_buys_no_coverage_at_any_setting() -> None:
    """THE finding of I4. Every measured coverage number is identical at boost
    0.0, 0.5, 1.0 and 3.0 — so the entire advantage comes from consolidation
    collapsing duplicates, and none of it from the thumb on the scale.

    A knob that changes ordering but never changes the metric the layer is
    justified by is not a tuning parameter, it is an unjustified default. It is
    now 0.0, which ADR 0110 named in advance as the honest kill for it.
    """
    for budget in (200, 400, 800):
        for r in (2, 3, 5, 10):
            at = {boost: _coverage(6, r, budget, boost)[1] for boost in (0.0, 0.5, 1.0, 3.0)}
            assert len(set(at.values())) == 1, f"budget={budget}, R={r}: boost mattered: {at}"


def test_a_raised_boost_walks_a_stale_entry_toward_displacing_a_fresh_record() -> None:
    """The risk ADR 0110 named, measured rather than asserted. A well-evidenced
    but loosely-related entry against a precisely-matching fresh record: the
    record scores 0.833, and the entry climbs 0.200 -> 0.291 -> 0.382 -> 0.745
    as boost goes 0 -> 0.5 -> 1 -> 3. It does not win here, but it is closing,
    and it buys no coverage on the way (see the test above)."""
    memory = InMemoryMemoryStore()
    memory.write(
        MemoryRecord(
            kind="failure",
            content={"lesson": "auth token expired refresh it"},
            run_id="r9",
            agent_id="a1",
            created_at=T,
        )
    )
    knowledge = InMemoryKnowledgeStore()
    knowledge.upsert(
        KnowledgeEntry(
            signature="failure:old",
            kind="failure",
            content={"lesson": "auth was slow once expired maybe"},
            agent_id="a1",
            source_record_ids=tuple(f"s{i}" for i in range(40)),
            first_seen=T,
            last_seen=T,
        )
    )

    query = "auth token expired refresh it"
    entry_scores = []
    for boost in (0.0, 0.5, 1.0, 3.0):
        chunks = MemoryRetriever(
            memory=memory, agent_id="a1", knowledge=knowledge, knowledge_boost=boost
        ).retrieve(query, token_budget=8000)
        by_source = {c.source.split(":")[0]: c.relevance_score for c in chunks}
        assert by_source["memory"] > by_source["knowledge"], (
            f"boost={boost} let a stale entry displace a precisely-relevant record"
        )
        entry_scores.append(by_source["knowledge"])

    assert entry_scores == sorted(entry_scores)
    assert entry_scores[-1] > 3 * entry_scores[0]


def test_the_shipped_default_is_the_measured_one() -> None:
    """Guards the conclusion itself: raising this default again should require
    re-running the A/B, not just editing a number."""
    assert MemoryRetriever(memory=InMemoryMemoryStore(), agent_id="a1").knowledge_boost == 0.0
