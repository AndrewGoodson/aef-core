import pytest

from aef.kernel import END, Edge, Graph, GraphValidationError, Node
from aef.state import StateDelta


def _fn(state, ctx, services):
    return StateDelta(), END


def _node(node_id: str, version: str = "1.0.0") -> Node:
    return Node(id=node_id, version=version, fn=_fn, deterministic=True)


def test_valid_graph_passes_validation() -> None:
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b")},
        edges=[Edge(from_node="a", to_node="b")],
        entry_node="a",
    )
    graph.validate()  # should not raise


def test_unknown_entry_node_rejected() -> None:
    graph = Graph(id="g1", version="1.0.0", nodes={"a": _node("a")}, edges=[], entry_node="missing")
    with pytest.raises(GraphValidationError):
        graph.validate()


def test_edge_to_unknown_node_rejected() -> None:
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a")},
        edges=[Edge(from_node="a", to_node="ghost")],
        entry_node="a",
    )
    with pytest.raises(GraphValidationError):
        graph.validate()


def test_unknown_fallback_node_rejected() -> None:
    bad_node = Node(id="a", version="1.0.0", fn=_fn, deterministic=True, fallback_node_id="ghost")
    graph = Graph(id="g1", version="1.0.0", nodes={"a": bad_node}, edges=[], entry_node="a")
    with pytest.raises(GraphValidationError):
        graph.validate()


def test_compile_returns_validated_graph() -> None:
    graph = Graph(id="g1", version="1.0.0", nodes={"a": _node("a")}, edges=[], entry_node="a")
    compiled = graph.compile()
    assert compiled.graph is graph


def test_compile_rejects_an_invalid_graph() -> None:
    """compile() must run validate() — a mutation removing that call would
    let an invalid graph compile silently and only misbehave at execution.
    This pins the compile-validates guarantee through .compile() itself, not
    just via a direct .validate() call."""
    graph = Graph(id="g1", version="1.0.0", nodes={"a": _node("a")}, edges=[], entry_node="missing")
    with pytest.raises(GraphValidationError):
        graph.compile()


def test_edges_from_sorted_by_priority_descending() -> None:
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b"), "c": _node("c")},
        edges=[
            Edge(from_node="a", to_node="b", priority=1),
            Edge(from_node="a", to_node="c", priority=5),
        ],
        entry_node="a",
    )
    ordered = graph.edges_from("a")
    assert [e.to_node for e in ordered] == ["c", "b"]


def test_edges_from_ties_preserve_declaration_order() -> None:
    """Equal-priority edges must resolve deterministically. Python's sorted()
    stability guarantee is what makes this correct — verified directly
    rather than assumed, since this was previously untested."""
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b"), "c": _node("c"), "d": _node("d")},
        edges=[
            Edge(from_node="a", to_node="b", priority=5),
            Edge(from_node="a", to_node="c", priority=5),
            Edge(from_node="a", to_node="d", priority=5),
        ],
        entry_node="a",
    )
    ordered = graph.edges_from("a")
    assert [e.to_node for e in ordered] == ["b", "c", "d"]


def test_edges_from_mixed_priorities_and_ties() -> None:
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b"), "c": _node("c"), "d": _node("d")},
        edges=[
            Edge(from_node="a", to_node="b", priority=1),
            Edge(from_node="a", to_node="c", priority=5),
            Edge(from_node="a", to_node="d", priority=5),
        ],
        entry_node="a",
    )
    ordered = graph.edges_from("a")
    assert [e.to_node for e in ordered] == ["c", "d", "b"]


def test_nodes_mapping_is_immutable() -> None:
    graph = Graph(id="g1", version="1.0.0", nodes={"a": _node("a")}, edges=[], entry_node="a")
    with pytest.raises(TypeError):
        graph.nodes["z"] = _node("z")  # type: ignore[index]


def test_diff_detects_added_removed_and_version_changed_nodes() -> None:
    g1 = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b", "1.0.0")},
        edges=[],
        entry_node="a",
    )
    g2 = Graph(
        id="g",
        version="1.1.0",
        nodes={"a": _node("a"), "b": _node("b", "2.0.0"), "c": _node("c")},
        edges=[],
        entry_node="a",
    )
    diff = g1.diff(g2)
    assert diff.nodes_added == {"c"}
    assert diff.nodes_removed == frozenset()
    assert diff.nodes_changed == {"b"}
    assert not diff.is_empty


def test_diff_of_identical_graph_is_empty() -> None:
    graph = Graph(id="g", version="1.0.0", nodes={"a": _node("a")}, edges=[], entry_node="a")
    assert graph.diff(graph).is_empty


def test_diff_of_freshly_rebuilt_graph_with_custom_edge_conditions_is_empty() -> None:
    """Calling the same build function twice produces different lambda
    objects for any edge condition — diff() must not treat that as a real
    change. Regression test for a real bug: it did, before this fix
    (docs/adr/0020)."""

    def build() -> Graph:
        return Graph(
            id="g",
            version="1.0.0",
            nodes={"a": _node("a"), "b": _node("b")},
            edges=[Edge(from_node="a", to_node="b", condition=lambda state: True)],
            entry_node="a",
        )

    g1, g2 = build(), build()
    assert g1.diff(g2).is_empty


def test_diff_detects_a_genuinely_different_edge_condition() -> None:
    g1 = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b")},
        edges=[Edge(from_node="a", to_node="b", condition=lambda state: True)],
        entry_node="a",
    )
    g2 = Graph(
        id="g",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b")},
        edges=[Edge(from_node="a", to_node="b", condition=lambda state: False)],
        entry_node="a",
    )
    diff = g1.diff(g2)
    assert not diff.is_empty
    assert len(diff.edges_added) == 1
    assert len(diff.edges_removed) == 1


def test_visualize_produces_mermaid_flowchart() -> None:
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b")},
        edges=[Edge(from_node="a", to_node="b")],
        entry_node="a",
    )
    mermaid = graph.visualize()
    assert mermaid.startswith("flowchart TD")
    assert '["a (entry)"]' in mermaid
    assert '["b"]' in mermaid
    assert "n0 --> n1" in mermaid


def test_visualize_escapes_a_node_id_that_would_break_mermaid_syntax() -> None:
    """Reproduces a real, confirmed bug: a node id containing `"]` followed
    by more Mermaid syntax used to break out of its own label and inject
    arbitrary extra flowchart statements — this module's own docstring
    says the output gets "pasted straight into docs/PRs." See docs/adr/0028."""
    evil_id = 'node"]; evil_injection --> pwned'
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={evil_id: _node(evil_id), "b": _node("b")},
        edges=[Edge(from_node=evil_id, to_node="b")],
        entry_node=evil_id,
    )
    mermaid = graph.visualize()
    lines = mermaid.splitlines()

    # Exactly 4 lines: header, 2 node declarations, 1 edge — no extra
    # statement injected from inside the malicious node id.
    assert len(lines) == 4
    assert "evil_injection" not in [line.split('"', 1)[0].strip() for line in lines]
    # The raw double quote never appears unescaped inside a label.
    assert "#quot;" in mermaid
    assert 'node"]' not in mermaid


def test_visualize_escapes_newlines_in_a_node_id() -> None:
    multiline_id = "line1\nline2"
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={multiline_id: _node(multiline_id)},
        edges=[],
        entry_node=multiline_id,
    )
    mermaid = graph.visualize()
    assert len(mermaid.splitlines()) == 2  # header + one node line, not split by the embedded \n
    assert "\n" not in mermaid.splitlines()[1]


def test_visualize_gives_the_same_two_nodes_the_same_id_across_node_and_edge_lines() -> None:
    """The synthetic Mermaid id assigned per real node id must be
    consistent between a node's own declaration line and every edge line
    referencing it — otherwise the diagram silently disconnects."""
    graph = Graph(
        id="g1",
        version="1.0.0",
        nodes={"a": _node("a"), "b": _node("b")},
        edges=[Edge(from_node="a", to_node="b")],
        entry_node="a",
    )
    mermaid = graph.visualize()
    node_lines = [line for line in mermaid.splitlines() if line.strip().startswith("n0[")]
    assert len(node_lines) == 1
    assert "n0 --> n1" in mermaid
