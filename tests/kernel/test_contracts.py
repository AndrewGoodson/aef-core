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
