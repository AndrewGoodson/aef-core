"""Every Phase 2-5 interface must be a real ABC (cannot be instantiated
without implementing its contract) and must raise NotImplementedError with
a message pointing at the phase/roadmap when a stub subclass calls through
to the base implementation. This file exercises that contract across all of
them in one place rather than duplicating boilerplate per module."""

from __future__ import annotations

from typing import Any

import pytest

from aef.coordination.base import Coordinator
from aef.evolution.engine import (
    ArchiveStore,
    CanaryController,
    EvalGate,
    EvolutionConfig,
    MutationProposer,
)
from aef.reasoning.planner import Planner, PlanValidator
from aef.reasoning.reflection import Critic, Judge
from aef.services.context.base import Retriever
from aef.services.kg.base import GraphStore
from aef.services.optimizers.base import Optimizer
from aef.services.tokens.base import TokenOptimizer

ABSTRACT_INTERFACES: list[type] = [
    Coordinator,
    ArchiveStore,
    CanaryController,
    EvalGate,
    MutationProposer,
    PlanValidator,
    Planner,
    Critic,
    Judge,
    Retriever,
    GraphStore,
    Optimizer,
    TokenOptimizer,
]


@pytest.mark.parametrize("interface", ABSTRACT_INTERFACES)
def test_interface_cannot_be_instantiated_directly(interface: type) -> None:
    with pytest.raises(TypeError):
        interface()  # type: ignore[call-arg]


def test_evolution_disabled_by_default() -> None:
    assert EvolutionConfig().enabled is False


def test_evolution_cannot_be_enabled_without_the_gate_criteria() -> None:
    with pytest.raises(NotImplementedError, match="Phase 4 gate criteria"):
        EvolutionConfig(enabled=True)


def _stub_subclass_calling_super(
    interface: type, method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> None:
    # Override EVERY abstract method so the subclass is concrete (interfaces
    # with more than one abstract method would otherwise stay abstract and
    # fail to instantiate) — but only the method under test forwards to the
    # base implementation, so it's the one whose NotImplementedError we check.
    namespace: dict[str, Any] = {
        name: (lambda self, *a, **kw: None) for name in interface.__abstractmethods__
    }
    namespace[method_name] = lambda self, *a, **kw: getattr(interface, method_name)(self, *a, **kw)
    concrete = type(f"_{interface.__name__}Stub", (interface,), namespace)
    instance = concrete()
    getattr(instance, method_name)(*args, **kwargs)


# (interface, representative abstract method, positional args, kwargs, phase substring).
# Covers ALL 13 interfaces — a stub calling through to any base method must hit
# NotImplementedError, not a body that quietly grew a real return value.
STUB_SUPER_CALLS: list[tuple[type, str, tuple[Any, ...], dict[str, Any], str]] = [
    (Coordinator, "handoff", (None,), {}, "Phase 5"),
    (ArchiveStore, "archive", ("g", "v"), {}, "Phase 4"),
    (CanaryController, "promote", ("g", "v"), {}, "Phase 4"),
    (EvalGate, "check", (None,), {}, "Phase 4"),
    (MutationProposer, "propose", ("graph-1",), {}, "Phase 4"),
    (PlanValidator, "validate", (None, None), {}, "Phase 2"),
    (Planner, "plan", (None,), {}, "Phase 2"),
    (Critic, "critique", (None,), {}, "Phase 3"),
    (Judge, "judge", (None,), {}, "Phase 3"),
    (Retriever, "retrieve", ("q",), {"token_budget": 100}, "Phase 2"),
    (GraphStore, "upsert_entity", (None,), {}, "Phase 2"),
    (Optimizer, "propose", ([],), {}, "Phase 3"),
    (TokenOptimizer, "compress", ("text",), {"token_budget": 100}, "Phase 2"),
]


@pytest.mark.parametrize(("interface", "method", "args", "kwargs", "phase"), STUB_SUPER_CALLS)
def test_stub_raises_notimplemented_when_super_is_called(
    interface: type, method: str, args: tuple[Any, ...], kwargs: dict[str, Any], phase: str
) -> None:
    with pytest.raises(NotImplementedError, match=phase):
        _stub_subclass_calling_super(interface, method, args, kwargs)
