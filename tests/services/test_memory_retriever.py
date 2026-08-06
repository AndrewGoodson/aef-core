"""Milestone 3: the one Phase-2 interface that survived triage, exercised.

3c's bar is "a test that RUNS it, not one that asserts it exists". The file
this replaces (`tests/test_phase2_5_stubs.py`, for the deleted interfaces)
asserted precisely the latter — that calling a stub raised
`NotImplementedError` — which is what a promise looks like when it is tested.

So the last test here drives `run_graph_module` end to end: a real
`aef.yaml`, a real memory store with real records, a real node that calls
`services.retriever` and writes what it got into state.
"""

from pathlib import Path

import pytest

from aef.config import build_retriever, load_agent_config
from aef.services.context.memory_retriever import (
    CHARS_PER_TOKEN,
    MemoryRetriever,
    estimate_tokens,
)
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore

CONFIG = """
model_provider:
  impl: anthropic
  model: claude-sonnet

memory:
  impl: in_memory

context:
  impl: memory
  token_budget: {budget}

objectives: "retrieve what went wrong before"
"""


def _store(*records: tuple[str, dict[str, object]]) -> InMemoryMemoryStore:
    memory = InMemoryMemoryStore()
    for kind, content in records:
        memory.write(
            MemoryRecord(kind=kind, content=content, agent_id="a", id=content["id"])  # type: ignore[arg-type]
        )
    return memory


def _retriever(memory: InMemoryMemoryStore) -> MemoryRetriever:
    return MemoryRetriever(memory=memory, agent_id="a")


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def test_the_relevant_record_outranks_the_irrelevant_one() -> None:
    memory = _store(
        ("failure", {"id": "r1", "note": "the fetch node raised a timeout"}),
        ("failure", {"id": "r2", "note": "unrelated parsing problem in the writer"}),
    )
    chunks = _retriever(memory).retrieve("fetch node timeout", token_budget=1000)
    assert [c.metadata["record_id"] for c in chunks][0] == "r1"


def test_a_record_sharing_no_vocabulary_is_not_returned_at_all() -> None:
    """A zero-overlap record is dropped rather than ranked last. Returning it
    would spend budget on something the query gave no reason to want."""
    memory = _store(("failure", {"id": "r1", "note": "completely different subject"}))
    assert _retriever(memory).retrieve("xylophone", token_budget=1000) == []


def test_ranking_is_a_stable_total_order() -> None:
    """Two runs of a deterministic node must retrieve the same context in the
    same order, or `ReplayEngine` reports a determinism violation that is
    really a sort-order artefact (constraint #1)."""
    memory = _store(
        *[("failure", {"id": f"r{i}", "note": "the fetch node raised"}) for i in range(8)]
    )
    first = [c.source for c in _retriever(memory).retrieve("fetch raised", token_budget=1000)]
    second = [c.source for c in _retriever(memory).retrieve("fetch raised", token_budget=1000)]
    assert len(first) == 8, "the fixture did not produce competing records"
    assert first == second


def test_only_the_declared_kinds_are_read() -> None:
    """`working` is this run's own scratch, which the node already has."""
    memory = _store(
        ("failure", {"id": "r1", "note": "the fetch node raised"}),
        ("working", {"id": "r2", "note": "the fetch node raised"}),
        ("success", {"id": "r3", "note": "the fetch node raised"}),
    )
    got = {c.metadata["record_id"] for c in _retriever(memory).retrieve("fetch", token_budget=1000)}
    assert got == {"r1", "r3"}


# --------------------------------------------------------------------------
# The budget — the reason this interface survived triage at all
# --------------------------------------------------------------------------


def test_the_budget_actually_binds() -> None:
    """`context_budget_tokens` has shipped since Phase 0 with a default of
    8000 and nothing has ever read it to bound anything (ADR 0101)."""
    memory = _store(
        *[
            ("failure", {"id": f"r{i}", "note": "the fetch node raised " + "x " * 40})
            for i in range(6)
        ]
    )
    unbounded = _retriever(memory).retrieve("fetch node raised", token_budget=100_000)
    assert len(unbounded) == 6, "the fixture does not produce enough to prune"

    bounded = _retriever(memory).retrieve("fetch node raised", token_budget=60)
    assert 0 < len(bounded) < len(unbounded)
    assert sum(c.token_estimate for c in bounded) <= 60


def test_a_large_low_ranked_chunk_does_not_block_a_small_one_behind_it() -> None:
    """Prune, do not stop. Stopping at the first oversized chunk turns "fit as
    much of the best as fits" into "stop at the first thing too big"."""
    memory = _store(
        ("failure", {"id": "big", "note": "fetch timeout " + "padding " * 100}),
        ("failure", {"id": "small", "note": "fetch timeout"}),
    )
    chunks = _retriever(memory).retrieve("fetch timeout", token_budget=40)
    assert [c.metadata["record_id"] for c in chunks] == ["small"]


def test_a_non_positive_budget_is_an_error_not_an_empty_list() -> None:
    """An empty result would be indistinguishable from an empty memory."""
    memory = _store(("failure", {"id": "r1", "note": "fetch"}))
    for budget in (0, -1):
        with pytest.raises(ValueError, match="must be positive"):
            _retriever(memory).retrieve("fetch", token_budget=budget)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"candidates_per_kind": 0}, "candidates_per_kind must be positive"),
        ({"candidates_per_kind": -1}, "candidates_per_kind must be positive"),
        ({"max_token_budget": 0}, "max_token_budget must be positive"),
        ({"max_token_budget": -1}, "max_token_budget must be positive"),
    ],
)
def test_invalid_retriever_limits_fail_at_construction(
    kwargs: dict[str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        MemoryRetriever(memory=InMemoryMemoryStore(), agent_id="a", **kwargs)


def test_a_chunk_never_costs_zero_tokens() -> None:
    """A zero-cost chunk lets an unbounded number through a finite budget."""
    assert estimate_tokens("") == 1
    assert estimate_tokens("a") == 1
    assert estimate_tokens("a" * CHARS_PER_TOKEN) == 1
    assert estimate_tokens("a" * (CHARS_PER_TOKEN + 1)) == 2


def test_the_estimate_rounds_up_so_the_budget_binds_early() -> None:
    """A retriever that overshoots a budget it claims to enforce is worse than
    one that admits a chunk fewer."""
    for length in range(1, 40):
        text = "a" * length
        assert estimate_tokens(text) * CHARS_PER_TOKEN >= len(text)


# --------------------------------------------------------------------------
# Reachable from aef.yaml, and reached by a node that RUNS
# --------------------------------------------------------------------------


def test_no_context_block_means_no_retriever() -> None:
    """An unconfigured agent gets none rather than a default whose ranking it
    never chose."""
    assert build_retriever(None, memory=InMemoryMemoryStore()) is None


def test_the_config_block_builds_the_retriever(tmp_path: Path) -> None:
    path = tmp_path / "aef.yaml"
    path.write_text(CONFIG.format(budget=500))
    config = load_agent_config(path)
    assert config.context is not None
    memory = _store(("failure", {"id": "r1", "note": "the fetch node raised"}))
    retriever = build_retriever(config.context, memory=memory, agent_id="a")
    assert retriever is not None
    assert retriever.retrieve("fetch", token_budget=500)


def test_an_unbuilt_impl_is_refused_at_load_time(tmp_path: Path) -> None:
    """A block naming a backend nobody wrote would validate and be ignored —
    the defect this whole milestone is about (ADR 0092, 0100, 0101)."""
    path = tmp_path / "aef.yaml"
    path.write_text(CONFIG.format(budget=500).replace("impl: memory", "impl: pinecone"))
    with pytest.raises(Exception, match="names no retriever"):
        load_agent_config(path)


def test_a_zero_token_budget_is_refused_at_load_time(tmp_path: Path) -> None:
    path = tmp_path / "aef.yaml"
    path.write_text(CONFIG.format(budget=0))
    with pytest.raises(Exception, match="must be positive"):
        load_agent_config(path)


AGENT = """
from aef.kernel import END, Graph, Node
from aef.state import StateDelta


def recall(state, ctx, services):
    chunks = services.retriever.retrieve(state.objective, token_budget=state.context_budget_tokens)
    return StateDelta(
        retrieved_context=[
            {"source": c.source, "content": c.content, "tokens": c.token_estimate} for c in chunks
        ],
    ), END


def build_graph():
    return Graph(
        id="recaller",
        version="0.1.0",
        nodes={"recall": Node(id="recall", version="0.1.0", fn=recall, deterministic=True)},
        edges=[],
        entry_node="recall",
    )
"""


def test_a_node_reaches_the_retriever_through_a_real_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole milestone's bar, in one run: configured in `aef.yaml`,
    injected via `Services`, called by a node, and its output in state.

    Not `assert Services has a retriever slot` — that assertion passed for
    every one of the five interfaces triage deleted.
    """
    from aef.cli.run import run_graph_module

    (tmp_path / "recaller.py").write_text(AGENT)
    monkeypatch.syspath_prepend(str(tmp_path))

    memory_path = tmp_path / "memory.jsonl"
    from aef.harness.memory_store import FileMemoryStore

    store = FileMemoryStore(path=memory_path)
    store.write(
        MemoryRecord(
            kind="failure",
            content={"note": "the fetch node raised a timeout"},
            agent_id="recaller-agent",
        )
    )
    store.write(
        MemoryRecord(
            kind="failure", content={"note": "utterly unrelated"}, agent_id="recaller-agent"
        )
    )

    config = tmp_path / "aef.yaml"
    config.write_text(CONFIG.format(budget=500))

    state = run_graph_module(
        "recaller",
        agent_id="recaller-agent",
        objective="fetch node timeout",
        config_path=config,
        memory_path=memory_path,
    )
    sources = [c["source"] for c in state.retrieved_context]
    assert sources, "the node retrieved nothing — the retriever never reached it"
    assert all(s.startswith("memory:failure:") for s in sources)
    assert any("timeout" in c["content"] for c in state.retrieved_context)


def test_without_a_context_block_the_same_node_gets_no_retriever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control. If the node retrieved with no config block, the test above
    would prove nothing about the config reaching anything."""
    from aef.cli.run import run_graph_module

    (tmp_path / "recaller2.py").write_text(AGENT.replace('id="recaller"', 'id="recaller2"'))
    monkeypatch.syspath_prepend(str(tmp_path))

    config = tmp_path / "aef.yaml"
    no_context = CONFIG.format(budget=500).replace(
        "context:\n  impl: memory\n  token_budget: 500\n\n", ""
    )
    assert "context:" not in no_context, "the control still configures a retriever"
    config.write_text(no_context)

    with pytest.raises(AttributeError):
        run_graph_module(
            "recaller2",
            agent_id="recaller-agent",
            objective="fetch node timeout",
            config_path=config,
        )


def test_the_configured_budget_is_a_CEILING_a_node_cannot_exceed(tmp_path: Path) -> None:
    """`context.token_budget` would otherwise be a config field nothing reads
    — the exact defect this milestone removes. It is a ceiling rather than a
    default because a node is entitled to ask and an owner is entitled to
    decide (ADR 0101).
    """
    memory = _store(
        *[
            ("failure", {"id": f"r{i}", "note": "the fetch node raised " + "x " * 40})
            for i in range(6)
        ]
    )
    generous = MemoryRetriever(memory=memory, agent_id="a")
    capped = MemoryRetriever(memory=memory, agent_id="a", max_token_budget=60)

    asked = 100_000
    assert len(generous.retrieve("fetch node raised", token_budget=asked)) == 6
    admitted = capped.retrieve("fetch node raised", token_budget=asked)
    assert 0 < len(admitted) < 6
    assert sum(c.token_estimate for c in admitted) <= 60


def test_the_ceiling_never_raises_a_smaller_request(tmp_path: Path) -> None:
    """A ceiling that also acted as a floor would silently widen a node that
    deliberately asked for less."""
    memory = _store(
        *[("failure", {"id": f"r{i}", "note": "fetch raised " + "x " * 40}) for i in range(6)]
    )
    capped = MemoryRetriever(memory=memory, agent_id="a", max_token_budget=100_000)
    tight = capped.retrieve("fetch raised", token_budget=60)
    assert sum(c.token_estimate for c in tight) <= 60


# --------------------------------------------------------------------------
# The adversarial round for this milestone. Both REPRODUCED first.
# --------------------------------------------------------------------------


def test_agent_id_must_be_chosen_rather_than_defaulted() -> None:
    """REPRODUCED: with `agent_id` defaulting to `None` this read EVERY
    agent's memory, so a retriever built without thinking about it handed one
    agent another's recorded failures. `None` still means "all agents" — what
    changed is that it must be chosen.
    """
    with pytest.raises(TypeError):
        MemoryRetriever(memory=InMemoryMemoryStore())  # type: ignore[call-arg]


def test_scoping_to_an_agent_excludes_another_agents_memory() -> None:
    """The behaviour the required argument protects, sent down the wire."""
    memory = InMemoryMemoryStore()
    memory.write(
        MemoryRecord(kind="failure", content={"note": "fetch secret"}, agent_id="theirs", id="t")
    )
    memory.write(
        MemoryRecord(kind="failure", content={"note": "fetch mine"}, agent_id="mine", id="m")
    )

    scoped = MemoryRetriever(memory=memory, agent_id="mine").retrieve("fetch", token_budget=1000)
    assert [c.metadata["record_id"] for c in scoped] == ["m"]

    everyone = MemoryRetriever(memory=memory, agent_id=None).retrieve("fetch", token_budget=1000)
    assert len(everyone) == 2, "the control is wrong: agent_id=None must still mean all agents"


def test_the_candidate_cap_bounds_the_ANSWER_not_only_the_work() -> None:
    """The first draft of `candidates_per_kind`'s comment claimed it bounded
    only the work. It does not: the store returns most-recent-first, so a
    relevant record past the cap is never scored and can never be returned.
    Pinned so the limitation stays stated rather than drifting back into a
    comfortable claim."""
    memory = InMemoryMemoryStore()
    memory.write(
        MemoryRecord(kind="failure", content={"note": "fetch node raised"}, agent_id="a", id="old")
    )
    for i in range(60):
        memory.write(
            MemoryRecord(kind="failure", content={"note": f"fetch node raised {i}"}, agent_id="a")
        )

    retrieved = MemoryRetriever(memory=memory, agent_id="a", candidates_per_kind=50).retrieve(
        "fetch node raised", token_budget=100_000
    )
    assert "old" not in {c.metadata["record_id"] for c in retrieved}
    assert len(retrieved) <= 50

    lifted = MemoryRetriever(memory=memory, agent_id="a", candidates_per_kind=200).retrieve(
        "fetch node raised", token_budget=100_000
    )
    assert "old" in {c.metadata["record_id"] for c in lifted}, (
        "the control is wrong: the record must be reachable at a higher cap"
    )


def test_content_that_json_cannot_serialise_does_not_break_retrieval() -> None:
    """A memory record is whatever a node wrote. A retriever that raises on
    one bad record makes every later one unreachable."""

    class Weird:
        def __repr__(self) -> str:
            return "<weird>"

    memory = InMemoryMemoryStore()
    memory.write(
        MemoryRecord(
            kind="failure", content={"note": "fetch", "obj": Weird()}, agent_id="a", id="w"
        )
    )
    assert MemoryRetriever(memory=memory, agent_id="a").retrieve("fetch", token_budget=1000)
