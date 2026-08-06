"""Every REMAINING Phase 2-5 interface must be a real ABC and must raise
NotImplementedError when a stub subclass calls through to the base.

This file used to cover thirteen. Milestone 3's triage (ADR 0101) deleted four
— `GraphStore`, `TokenOptimizer`, `Planner`, `PlanValidator` — because a stub
unimplemented across five phases is a promise, and a test asserting that a
promise still raises is the most a promise can ever be tested for.

`Retriever` stays in the list and is no longer only that: it now has a real
implementation, exercised by `tests/services/test_memory_retriever.py`
against a running node. The list below is what has NOT yet earned that."""

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
from aef.reasoning.reflection import Critic, Judge
from aef.services.context.base import Retriever
from aef.services.optimizers.base import Optimizer

ABSTRACT_INTERFACES: list[type] = [
    Coordinator,
    ArchiveStore,
    CanaryController,
    EvalGate,
    MutationProposer,
    Critic,
    Judge,
    Retriever,
    Optimizer,
]


@pytest.mark.parametrize("interface", ABSTRACT_INTERFACES)
def test_interface_cannot_be_instantiated_directly(interface: type) -> None:
    with pytest.raises(TypeError):
        interface()  # type: ignore[call-arg]


def test_evolution_disabled_by_default() -> None:
    assert EvolutionConfig().enabled is False


def test_evolution_rejection_names_the_missing_live_evidence() -> None:
    with pytest.raises(
        NotImplementedError,
        match="implemented, but have not been validated against live traffic and real tenants",
    ):
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
# Covers ALL 9 remaining interfaces — a stub calling through to any base method must hit
# NotImplementedError, not a body that quietly grew a real return value.
STUB_SUPER_CALLS: list[tuple[type, str, tuple[Any, ...], dict[str, Any], str]] = [
    (Coordinator, "handoff", (None,), {}, "Phase 5"),
    (ArchiveStore, "archive", ("g", "v"), {}, "Phase 4"),
    (CanaryController, "promote", ("g", "v"), {}, "Phase 4"),
    (EvalGate, "check", (None,), {}, "Phase 4"),
    (MutationProposer, "propose", ("graph-1",), {}, "Phase 4"),
    (Critic, "critique", (None,), {}, "Phase 3"),
    (Judge, "judge", (None,), {}, "Phase 3"),
    (Retriever, "retrieve", ("q",), {"token_budget": 100}, "Phase 2"),
    (Optimizer, "propose", ([],), {}, "Phase 3"),
]


@pytest.mark.parametrize(("interface", "method", "args", "kwargs", "phase"), STUB_SUPER_CALLS)
def test_stub_raises_notimplemented_when_super_is_called(
    interface: type, method: str, args: tuple[Any, ...], kwargs: dict[str, Any], phase: str
) -> None:
    with pytest.raises(NotImplementedError, match=phase):
        _stub_subclass_calling_super(interface, method, args, kwargs)
