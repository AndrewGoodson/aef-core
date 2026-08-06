"""Milestone 1's acceptance tests, plus the six defects its adversarial round
reproduced, plus the tests `mind.py` shipped without.

The central property is that the graph ACCUMULATES and that its visual
encoding cannot say something the data does not. Both are checked by building
real memory across generations and asserting on what comes out, never by
inspecting source.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aef.dash import memory as M
from aef.dash.contract import FORBIDDEN_HTML_CONSTRUCTS, PanelState
from aef.dash.mind import MindEdge, MindGraph, MindNode, render_mind

DAY0 = datetime(2026, 7, 1, tzinfo=UTC)
TOPO = ("ingest", "classify", "enrich", "reflect", "emit")
EDGES = (
    ("ingest", "classify"),
    ("classify", "enrich"),
    ("enrich", "reflect"),
    ("reflect", "emit"),
    ("reflect", "classify"),
)


def _hot_run(at: datetime) -> M.RunTrace:
    return M.RunTrace(["ingest", "classify", "enrich", "reflect", "emit"], at, [10, 40, 15, 5, 8])


def _seeded(days: int = 10) -> M.GraphMemory:
    mem = M.empty("billing-agent", at=DAY0)
    traces = [_hot_run(DAY0 + timedelta(days=d)) for d in range(days)]
    return M.observe(
        mem,
        traces,
        at=DAY0 + timedelta(days=days),
        declared_nodes=TOPO,
        declared_edges=EDGES,
    )


# --------------------------------------------------------------------------
# 1a/1b/1c — it accumulates, and the three edge states stay distinct.
# --------------------------------------------------------------------------


def test_consecutive_provenance_entries_are_the_edge_traversals() -> None:
    """The claim the whole module rests on: no new collection was needed."""
    trace = M.RunTrace(["a", "b", "c"], DAY0)
    assert trace.edges() == (("a", "b"), ("b", "c"))


def test_traversals_accumulate_across_generations() -> None:
    first = _seeded(10)
    assert first.edges[("ingest", "classify")].traversals == 10
    second = M.observe(first, [_hot_run(DAY0 + timedelta(days=11))], at=DAY0 + timedelta(days=11))
    assert second.edges[("ingest", "classify")].traversals == 11, "memory must add, not replace"


def test_a_declared_but_never_executed_edge_is_never_fired_not_stale() -> None:
    """The distinction the encoding exists for. `reflect -> classify` is
    declared in the topology and no run takes it."""
    mem = _seeded(10)
    never = mem.edges[("reflect", "classify")]
    assert never.traversals == 0
    assert never.last_traversed is None
    assert M.liveness(never, now=DAY0 + timedelta(days=10)) is None, (
        "never-fired must be None, not 0.0 — a 0.0 renders identically to abandoned"
    )


def test_an_abandoned_path_is_thick_and_dim_not_absent() -> None:
    """A path used heavily and then stopped must stay THICK (traversals never
    decay) while going dim (liveness → 0). That is what distinguishes it from
    one never taken."""
    mem = _seeded(10)
    much_later = DAY0 + timedelta(days=90)
    abandoned = mem.edges[("classify", "enrich")]
    assert abandoned.traversals == 10, "cumulative count must not decay"
    live = M.liveness(abandoned, now=much_later)
    assert live == 0.0, "and the recency must go to zero"
    # The two together are what make it legible.
    never = mem.edges[("reflect", "classify")]
    assert M.liveness(never, now=much_later) is None
    assert never.traversals == 0
    assert (abandoned.traversals, live) != (never.traversals, M.liveness(never, now=much_later))


def test_a_node_that_never_ran_still_appears() -> None:
    """Omitting it would hide the thing an operator most needs to see: a node
    nothing ever reaches."""
    mem = M.observe(
        M.empty("g", at=DAY0), [], at=DAY0, declared_nodes=("orphan",), declared_edges=()
    )
    assert "orphan" in mem.nodes
    assert mem.nodes["orphan"].total_runs == 0


def test_out_of_order_traces_do_not_move_a_birthday() -> None:
    """`first_seen` uses min(), not "keep what we had" — a late-arriving old
    trace must not redate the node, or the Evolution view draws the wrong
    history."""
    mem = M.observe(M.empty("g", at=DAY0), [_hot_run(DAY0 + timedelta(days=5))], at=DAY0)
    assert mem.nodes["ingest"].first_seen == DAY0 + timedelta(days=5)
    older = M.observe(mem, [_hot_run(DAY0)], at=DAY0)
    assert older.nodes["ingest"].first_seen == DAY0


# --------------------------------------------------------------------------
# 1a/1d — positions survive, and the file stays byte-stable.
# --------------------------------------------------------------------------


def test_positions_survive_a_save_load_round_trip_byte_identically(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mem = M.remember_positions(_seeded(10), {"ingest": (100.0, 200.0), "emit": (400.0, 300.0)})
    M.save(mem, tmp_path)
    first = (tmp_path / M.MEMORY_FILENAME).read_text()

    reloaded = M.load(tmp_path, "billing-agent", at=DAY0)
    assert reloaded.nodes["ingest"].x == 100.0
    assert reloaded.nodes["ingest"].y == 200.0
    M.save(reloaded, tmp_path)
    assert (tmp_path / M.MEMORY_FILENAME).read_text() == first, (
        "a memory file that churns on every write cannot be diffed, so nobody notices the "
        "change that mattered"
    )


def test_positions_are_rounded_so_the_file_does_not_churn() -> None:
    mem = M.remember_positions(_seeded(2), {"ingest": (100.123456789, 200.987654321)})
    assert mem.nodes["ingest"].x == 100.1
    assert mem.nodes["ingest"].y == 201.0


def test_a_node_with_no_remembered_position_is_new_and_relaxes_in() -> None:
    mem = M.remember_positions(_seeded(2), {"ingest": (10.0, 10.0)})
    assert mem.nodes["ingest"].placed is True
    assert mem.nodes["emit"].placed is False


def test_new_since_names_exactly_the_nodes_that_arrived() -> None:
    mem = _seeded(10)
    later = DAY0 + timedelta(days=20)
    grown = M.observe(
        mem,
        [M.RunTrace(["enrich", "retry_guard", "reflect"], later)],
        at=later,
        declared_nodes=(*TOPO, "retry_guard"),
    )
    assert grown.new_since(DAY0 + timedelta(days=11)) == ("retry_guard",)


def test_a_corrupt_memory_file_raises_rather_than_starting_fresh(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Starting fresh would erase the history and redraw it as a graph that
    has simply never seen much — absence looking like health, one layer down."""
    (tmp_path / M.MEMORY_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(M.MemoryError_, match="Refusing to start fresh"):
        M.load(tmp_path, "g", at=DAY0)


def test_memory_for_a_different_graph_is_refused(tmp_path) -> None:  # type: ignore[no-untyped-def]
    M.save(_seeded(2), tmp_path)
    with pytest.raises(M.MemoryError_, match="remembers graph"):
        M.load(tmp_path, "some-other-agent", at=DAY0)


def test_an_unknown_memory_version_is_refused_not_migrated() -> None:
    payload = json.loads(_seeded(2).to_json())
    payload["version"] = 999
    with pytest.raises(M.MemoryError_, match="not 1"):
        M.GraphMemory.from_payload(payload)


# --------------------------------------------------------------------------
# The six defects the adversarial round reproduced.
# --------------------------------------------------------------------------


def test_a_node_with_zero_runs_cannot_claim_to_be_healthy() -> None:
    """The milestone's central rule, and it was unenforced. On a graph an
    un-instrumented node still draws as a perfectly nice circle — there is no
    empty space to notice."""
    with pytest.raises(ValueError, match="has no health to report"):
        MindNode("ghost", "ghost", state=PanelState.HEALTHY.value, runs=0)
    with pytest.raises(ValueError, match="has no health to report"):
        MindNode("ghost", "ghost", state=PanelState.DEGRADED.value, runs=0)
    # UNKNOWN is the only honest reading, and it is allowed.
    assert MindNode("ghost", "ghost", state=PanelState.UNKNOWN.value, runs=0).runs == 0


def test_negative_traversals_are_refused_because_the_edge_would_vanish() -> None:
    """`Math.log1p(-5)` is NaN, `lineWidth = NaN` draws nothing, and the edge
    disappears with no message."""
    with pytest.raises(ValueError, match="negative count reaches the canvas as NaN"):
        MindEdge("a", "b", traversals=-5)


def test_liveness_outside_the_unit_interval_is_refused() -> None:
    with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
        MindEdge("a", "b", traversals=1, liveness=7.5)


def test_zero_traversals_with_a_liveness_is_refused() -> None:
    """The invariant the encoding rests on: never-fired is None, never 0.0."""
    with pytest.raises(ValueError, match="Never-fired must be None"):
        MindEdge("a", "b", traversals=0, liveness=0.0)


def test_duplicate_node_ids_are_refused() -> None:
    """The layout indexes by id, so a duplicate silently discards one node and
    re-points its edges — leaving a graph that looks whole and is not."""
    with pytest.raises(ValueError, match="duplicate node ids"):
        MindGraph("t", (MindNode("dup", "first"), MindNode("dup", "second")), ())


def test_a_non_finite_position_is_refused_before_it_reaches_json() -> None:
    """`json.dumps` emits bare `Infinity`/`NaN`, which `JSON.parse` rejects —
    one bad coordinate renders the entire page empty."""
    node = M.NodeMemory("x", DAY0, DAY0)
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="non-finite position"):
            node.with_position(bad, 1.0)
        with pytest.raises(ValueError, match="non-finite position"):
            node.with_position(1.0, bad)


def test_the_emitted_memory_json_is_always_parseable() -> None:
    """The property behind the two tests above, checked end to end."""
    mem = M.remember_positions(_seeded(5), {"ingest": (1.5, 2.5)})
    assert json.loads(mem.to_json())["nodes"][0]["node_id"] == "classify"


# --------------------------------------------------------------------------
# The tests mind.py shipped without.
# --------------------------------------------------------------------------


def _hostile_graph() -> MindGraph:
    return MindGraph(
        title="</script><img src=x onerror=alert(1)>",
        caption='x"] --> evil[[pwned',
        nodes=(
            MindNode('x"] --> evil[[', "breakout", state=PanelState.UNKNOWN.value, runs=0),
            MindNode("sep break", "u2028", state=PanelState.UNKNOWN.value, runs=0),
        ),
        edges=(MindEdge('x"] --> evil[[', "sep break"),),
    )


def test_no_hostile_string_survives_into_the_rendered_page() -> None:
    """Built from THE REAL strings, never a paraphrase. Twice in the
    predecessor program a detector passed its own planted fault and was still
    wrong, both times because the fault was a paraphrase."""
    page = render_mind([_hostile_graph()])
    assert "<img src=x onerror" not in page
    assert "</script><img" not in page
    assert " " not in page, "U+2028 is a JS line terminator json.dumps leaves raw"


def test_the_rendered_page_still_parses_its_own_payload() -> None:
    """Escaping that produced invalid JSON would be a different failure with
    the same symptom — a blank page."""
    page = render_mind([_hostile_graph()])
    blob = page.split('id="mind-data">', 1)[1].split("</script>", 1)[0]
    assert isinstance(json.loads(blob), list)


def test_the_page_contains_no_construct_from_the_read_only_list() -> None:
    """Imported from contract.py rather than re-listed — two lists nobody
    compares drift (ADR 0091)."""
    page = render_mind([_hostile_graph()]).lower()
    present = [c for c in FORBIDDEN_HTML_CONSTRUCTS if c.lower() in page]
    assert present == [], present


def test_an_edge_to_a_node_that_does_not_exist_is_refused() -> None:
    """Every layout engine drops a dangling edge silently, which makes an
    incomplete graph look finished."""
    with pytest.raises(ValueError, match="do not exist"):
        MindGraph("t", (MindNode("a", "a"),), (MindEdge("a", "ghost"),))
