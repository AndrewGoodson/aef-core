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


def _stub_subclass_calling_super(interface: type, method_name: str, *args: Any) -> None:
    namespace = {
        method_name: lambda self, *a, **kw: getattr(interface, method_name)(self, *a, **kw)
    }
    concrete = type(f"_{interface.__name__}Stub", (interface,), namespace)
    instance = concrete()
    getattr(instance, method_name)(*args)


def test_mutation_proposer_stub_raises_when_super_is_called() -> None:
    with pytest.raises(NotImplementedError, match="Phase 4"):
        _stub_subclass_calling_super(MutationProposer, "propose", "graph-1")


def test_coordinator_stub_raises_when_super_is_called() -> None:
    with pytest.raises(NotImplementedError, match="Phase 5"):
        _stub_subclass_calling_super(Coordinator, "handoff", None)


def test_planner_stub_raises_when_super_is_called() -> None:
    with pytest.raises(NotImplementedError, match="Phase 2"):
        _stub_subclass_calling_super(Planner, "plan", None)


def test_critic_stub_raises_when_super_is_called() -> None:
    with pytest.raises(NotImplementedError, match="Phase 3"):
        _stub_subclass_calling_super(Critic, "critique", None)
