import pytest

from aef.kernel import (
    CostModel,
    Node,
    NodeContractError,
    ServiceNotConfiguredError,
    Services,
    SideEffect,
)
from aef.kernel.contracts import END, Edge
from aef.state import StateDelta


def _noop_fn(state, ctx, services):
    return StateDelta(), END


def test_pure_node_needs_no_idempotency_key() -> None:
    node = Node(id="n1", version="1.0.0", fn=_noop_fn, deterministic=True)
    assert node.side_effects is SideEffect.PURE


def test_non_pure_node_without_idempotency_key_rejected() -> None:
    with pytest.raises(NodeContractError):
        Node(
            id="n1",
            version="1.0.0",
            fn=_noop_fn,
            deterministic=True,
            side_effects=SideEffect.MUTATING,
        )


def test_non_pure_node_with_idempotency_key_accepted() -> None:
    node = Node(
        id="n1",
        version="1.0.0",
        fn=_noop_fn,
        deterministic=False,
        side_effects=SideEffect.IO,
        idempotency_key_fn=lambda state: state.run_id,
    )
    assert node.idempotency_key_fn is not None


def test_edge_targets_normalizes_single_and_fanout() -> None:
    single = Edge(from_node="a", to_node="b")
    fanout = Edge(from_node="a", to_node=("b", "c"))
    assert single.targets == ("b",)
    assert fanout.targets == ("b", "c")


def test_services_require_helpers_raise_when_unconfigured() -> None:
    services = Services()
    with pytest.raises(ServiceNotConfiguredError):
        services.require_model_provider()
    with pytest.raises(ServiceNotConfiguredError):
        services.require_memory()
    with pytest.raises(ServiceNotConfiguredError):
        services.require_durability()


def test_services_default_clock_returns_aware_datetime() -> None:
    services = Services()
    now = services.clock()
    assert now.tzinfo is not None


def test_cost_model_defaults() -> None:
    cm = CostModel()
    assert cm.tokens == 0
    assert cm.dollars_per_call == 0.0


def test_edges_with_default_condition_are_equal() -> None:
    assert Edge(from_node="a", to_node="b") == Edge(from_node="a", to_node="b")


def test_edges_with_separately_defined_but_source_identical_conditions_are_equal() -> None:
    """Two lambdas defined at the same source location (e.g. two separate
    calls to the same build_graph() function) must compare equal even
    though they're different objects — this is what makes Graph.diff()
    correctly treat a rebuilt-but-unchanged graph as unchanged instead of
    reporting a phantom edge change on every rebuild (docs/adr/0020)."""

    def build_edge() -> Edge:
        return Edge(from_node="a", to_node="b", condition=lambda state: True)

    e1 = build_edge()
    e2 = build_edge()
    assert e1.condition is not e2.condition  # genuinely different objects
    assert e1 == e2
    assert hash(e1) == hash(e2)


def test_edges_with_genuinely_different_conditions_are_not_equal() -> None:
    e1 = Edge(from_node="a", to_node="b", condition=lambda state: True)
    e2 = Edge(from_node="a", to_node="b", condition=lambda state: False)
    assert e1 != e2


def test_edges_differing_only_by_priority_are_not_equal() -> None:
    assert Edge(from_node="a", to_node="b", priority=1) != Edge(
        from_node="a", to_node="b", priority=2
    )


def test_edge_not_equal_to_non_edge() -> None:
    assert Edge(from_node="a", to_node="b") != "not an edge"


def test_edges_are_usable_in_a_set() -> None:
    e1 = Edge(from_node="a", to_node="b")
    e2 = Edge(from_node="a", to_node="b")
    assert len({e1, e2}) == 1
