"""Phase 2 interface stubs: hierarchical planning (report §6 / blueprint
Part 3). Meta-planner -> tactical planners -> constraint/risk validator,
producing a `Plan` subgraph (`aef.state.Plan`) with a `reusable_key` for
later promotion to a Plan Template. Not implemented in Phase 0/1 — nodes
that need a plan today build `aef.state.Plan` by hand.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from aef.state import AEFState, Plan


class PlanValidator(ABC):
    """Domain-specific hard gate a tactical plan must pass before admission
    to execution (blueprint §3.1) — e.g. a Financial Agent's Sharpe/PF/MaxDD
    gates, a Security Agent's blast-radius gate. Same interface, different
    per-agent constraint payload (report §16)."""

    @abstractmethod
    def validate(self, plan: Plan, state: AEFState) -> bool:
        raise NotImplementedError("PlanValidator is a Phase 2 interface; no backend is wired yet")


class Planner(ABC):
    @abstractmethod
    def plan(self, state: AEFState) -> Plan:
        raise NotImplementedError("Planner is a Phase 2 interface; no backend is wired yet")
