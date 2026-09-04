"""I4 of the improve loop — curation: demote, never delete (ADR 0116).

**The metric was fixed before anything was measured**: *live-lesson
coverage* — of the lessons that are STILL recurring, how many are represented
in the retrieved set under a given `context_budget_tokens`. ACE's playbook
finding is that contexts collapse when stale strategies crowd out live ones;
the consolidated layer (ADR 0110) fixed crowding by near-duplicates, and this
measures the other crowding: lessons the agent has already stopped needing.

Rig: `LESSONS[:3]` are RESOLVED — they fail R times, then succeed Q times.
`LESSONS[3:]` are LIVE — they fail R times, then fail Q more times. Every
entry is lexically identical in relevance to the query, so without curation
which three fit a tight budget is a tie broken by id. With curation the
retriever demotes entries by `runs_since_last_seen`.

Falsification conditions, stated in advance: if curated live coverage is not
higher than uncurated at any tight budget, the knob stays 0. If it costs
total coverage at a generous budget, the knob stays 0. If half-life makes no
difference across the sweep, the mechanism is decoration and stays 0.

Measured (see the test bodies for the assertions that pin these):

```
live coverage out of 3, budget 400, R=3, Q=4:   hl=0 -> 2   hl=2 -> 3   hl=5 -> 3   hl=10 -> 3
total coverage out of 6, budget 2000:            6 at every half-life
```

Predicted before running: hl=0 -> 1. Measured: 2. The id tie-break happened to
favour two live lessons; the mechanism's gain is one lesson at this budget,
not two, and that is the number recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aef.kernel import END, Context, Edge, Graph, GraphExecutor, Node, Route, Services
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.context.base import RetrievedChunk
from aef.services.context.memory_retriever import MemoryRetriever
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState, Plan, StateDelta

LESSONS = ("fetch", "parse", "auth", "settle", "notify", "reconcile")
RESOLVED = LESSONS[:3]
LIVE = LESSONS[3:]
QUERY = "node timed out error failure settle the invoice"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _node(node_id: str, *, fails: bool) -> Node:
    def fn(s: AEFState, c: Context, sv: Services) -> tuple[StateDelta, Route]:
        if fails:
            return (
                StateDelta(errors=[{"node_id": node_id, "error": f"{node_id} timed out"}]),
                "reflect",
            )
        return (
            StateDelta(plan=Plan(goal=s.objective, status="done"), scores={"quality": 1.0}),
            "reflect",
        )

    return Node(id=node_id, version="1", fn=fn, deterministic=True)


class _Ticking:
    """A clock that advances one minute per read, so records order in time."""

    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> datetime:
        self.ticks += 1
        return T0 + timedelta(minutes=self.ticks)


def _build(r: int, q: int) -> tuple[InMemoryMemoryStore, InMemoryKnowledgeStore]:
    memory, knowledge = InMemoryMemoryStore(), InMemoryKnowledgeStore()
    services = Services(
        memory=memory,
        knowledge=knowledge,
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
        clock=_Ticking(),
    )

    def run(lesson: str, *, fails: bool, run_id: str) -> None:
        nodes = [
            _node(lesson, fails=fails),
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
        GraphExecutor(graph.compile(), services).run(
            AEFState(run_id=run_id, agent_id="a1", objective="settle the invoice")
        )

    # Phase 1: every lesson fails R times.
    for i in range(r):
        for lesson in LESSONS:
            run(lesson, fails=True, run_id=f"{lesson}-p1-{i}")
    # Phase 2: resolved lessons succeed Q times; live lessons keep failing.
    for i in range(q):
        for lesson in RESOLVED:
            run(lesson, fails=False, run_id=f"{lesson}-p2-{i}")
        for lesson in LIVE:
            run(lesson, fails=True, run_id=f"{lesson}-p2-{i}")
    return memory, knowledge


def _covered(chunks: list[RetrievedChunk], lessons: tuple[str, ...]) -> set[str]:
    return {
        lesson
        for chunk in chunks
        if chunk.source.startswith("knowledge:failure:")
        for lesson in lessons
        if f'"{lesson}"' in chunk.content or f"{lesson}>" in chunk.content
    }


def _retrieve(r: int, q: int, budget: int, half_life: int) -> list[RetrievedChunk]:
    memory, knowledge = _build(r, q)
    retriever = MemoryRetriever(
        memory=memory,
        agent_id="a1",
        knowledge=knowledge,
        # Records off: this isolates the entry-vs-entry ranking the knob acts on.
        kinds=(),
        staleness_half_life=half_life,
    )
    return retriever.retrieve(QUERY, token_budget=budget)


def _live_coverage(r: int, q: int, budget: int, half_life: int) -> int:
    return len(_covered(_retrieve(r, q, budget, half_life), LIVE))


# ---------------------------------------------------------------------------
# The mechanism, on its own
# ---------------------------------------------------------------------------
def test_runs_since_last_seen_counts_only_later_runs_of_the_same_agent() -> None:
    _, knowledge = _build(r=2, q=3)
    by_sig = {e.signature: e for e in knowledge.query("failure", agent_id="a1", limit=50)}
    # Phase 2 is 3 rounds x 6 runs = 18 runs after phase 1, plus the rest of the
    # resolved lesson's own last round: fetch is followed by 5, parse by 4, auth by 3.
    assert {ln: by_sig[f"failure:{ln}"].runs_since_last_seen for ln in RESOLVED} == {
        "fetch": 23,
        "parse": 22,
        "auth": 21,
    }
    # A live lesson's last failure is followed only by the live runs after it in
    # its round: settle by 2, notify by 1, reconcile by none.
    assert {ln: by_sig[f"failure:{ln}"].runs_since_last_seen for ln in LIVE} == {
        "settle": 2,
        "notify": 1,
        "reconcile": 0,
    }


def test_the_field_costs_no_retrieval_budget() -> None:
    """ADR 0110 measured that a longer rendered entry loses coverage at tight
    budgets. Staleness is metadata, so it must not be rendered."""
    chunks = _retrieve(r=2, q=2, budget=2000, half_life=0)
    assert chunks
    assert all("runs_since" not in c.content for c in chunks)
    assert all("runs_since_last_seen" in c.metadata for c in chunks)


# ---------------------------------------------------------------------------
# The A/B
# ---------------------------------------------------------------------------
def test_with_no_resolution_curation_changes_no_coverage() -> None:
    """Control: when every lesson is still live, the number of lessons
    covered is identical at every budget. What DOES change is the tie-break
    among equally relevant live lessons — recency instead of id — which is
    the mechanism working as stated, not a leak. Predicted before running:
    identical order. Measured: identical coverage, different order."""
    for budget in (200, 400, 800):
        memory, knowledge = _build(r=3, q=0)
        off = MemoryRetriever(
            memory=memory, agent_id="a1", knowledge=knowledge, kinds=(), staleness_half_life=0
        )
        on = MemoryRetriever(
            memory=memory, agent_id="a1", knowledge=knowledge, kinds=(), staleness_half_life=5
        )
        assert len(_covered(off.retrieve(QUERY, token_budget=budget), LESSONS)) == len(
            _covered(on.retrieve(QUERY, token_budget=budget), LESSONS)
        ), budget


def test_curation_buys_live_coverage_under_a_tight_budget() -> None:
    """THE finding of this increment. At a budget that fits three of six
    identically-relevant entries, the uncurated retriever's choice is a tie
    broken by id and admits two live lessons; curation admits all three."""
    off = _live_coverage(r=3, q=4, budget=400, half_life=0)
    on = _live_coverage(r=3, q=4, budget=400, half_life=5)
    assert off == 2, off
    assert on == 3, on


def test_the_half_life_sweep() -> None:
    """Any positive half-life wins here because the gap between live and
    resolved is large (18 runs vs <3). Recorded so the default is a measured
    number, not a preference."""
    by_hl = {hl: _live_coverage(r=3, q=4, budget=400, half_life=hl) for hl in (0, 2, 5, 10)}
    assert by_hl == {0: 2, 2: 3, 5: 3, 10: 3}, by_hl


def test_curation_never_costs_total_coverage_at_a_generous_budget() -> None:
    """Demote, never delete: with room for everything, everything is there."""
    for hl in (0, 2, 5, 10):
        chunks = _retrieve(r=3, q=4, budget=2000, half_life=hl)
        assert _covered(chunks, LESSONS) == set(LESSONS), hl


def test_stale_entries_are_demoted_not_dropped() -> None:
    chunks = _retrieve(r=3, q=4, budget=2000, half_life=5)
    order = [c.metadata["signature"] for c in chunks if c.source.startswith("knowledge:failure:")]
    live = [s for s in order if s.split(":")[1] in LIVE]
    resolved = [s for s in order if s.split(":")[1] in RESOLVED]
    assert len(live) == 3 and len(resolved) == 3
    # Every live entry ranks above every resolved one.
    assert order.index(live[-1]) < order.index(resolved[0])
