"""The one place that decides what a Zone A node may rely on.

This exists because the same defect happened four times. ADR 0073 found that
`aef run` wired no `critic`/`judge`, so following LOOP.md obligation 2 made
obligation 3 impossible. ADR 0075 found the gate runner had the same gap —
the fix had been applied to two of three construction sites. ADR 0079 found
`policy_engine` missing at all four. ADR 0089 found a deep-copy raise doing
the same thing by a different route.

Every time, the symptom was identical: a service the node needs is absent in
the gate path, `scenario_runner` swallows the `ServiceNotConfiguredError`,
and candidate, incumbent and all five cohort members score 0.0 — so G3
rejects every candidate forever while `aef loop doctor` reports the agent
green.

Fixing it service-by-service has not worked, because the failure is drift
between two lists nobody compares. So there is now one list (ADR 0091).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from aef.kernel import DurabilityBackend, Services
from aef.observability.base import Tracer
from aef.observability.in_memory import InMemoryTracer
from aef.providers.base import ModelProvider
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.security.tool import PolicyConfig, PolicyEngine
from aef.services.eval.rule_based import RuleBasedEvaluator
from aef.services.memory.base import MemoryStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState

DEFAULT_RUBRIC: dict[str, float] = {"quality": 1.0}


class _EphemeralDurability(DurabilityBackend):
    """Satisfies `require_durability()` without imposing serialisability.

    The gate discards these checkpoints, so the only thing JSON-encoding them
    achieves is rejecting agent state that a production run accepts (ADR 0093).
    """

    def __init__(self) -> None:
        self._states: dict[str, dict[int, AEFState]] = {}
        self._cursors: dict[str, str | None] = {}

    def save_checkpoint(self, state: AEFState) -> None:
        self._states.setdefault(state.run_id, {})[state.checkpoint_seq] = state

    def load_latest(self, run_id: str) -> AEFState | None:
        run = self._states.get(run_id)
        return run[max(run)] if run else None

    def load_checkpoint(self, run_id: str, checkpoint_seq: int) -> AEFState | None:
        return self._states.get(run_id, {}).get(checkpoint_seq)

    def list_checkpoints(self, run_id: str) -> list[int]:
        return sorted(self._states.get(run_id, {}))

    def save_cursor(self, run_id: str, next_node: str | None) -> None:
        self._cursors[run_id] = next_node

    def load_cursor(self, run_id: str) -> str | None:
        return self._cursors.get(run_id)


def agent_services(
    *,
    memory: MemoryStore | None = None,
    durability: DurabilityBackend | None = None,
    tracer: Tracer | None = None,
    model_provider: ModelProvider | None = None,
    policy: PolicyConfig | None = None,
    judge_rubric: dict[str, float] | None = None,
    clock: Callable[[], datetime] | None = None,
    audit_log: object | None = None,
) -> Services:
    """Everything a Zone A node may `require_*`, with working defaults.

    Callers override what legitimately differs between a production run and a
    gate re-execution — a durable memory store versus a throwaway one, a real
    clock versus a scenario's pinned one — and inherit the rest, so the two
    paths cannot silently diverge in what an agent is allowed to depend on.

    `model_provider` defaults to `None` and that is deliberate: the gate
    sandbox has no credentials, and a node that calls a model is
    `deterministic=False` and unreplayable anyway. It is the one service the
    two paths genuinely differ on, so it is the one the caller must pass.
    """
    return Services(
        model_provider=model_provider,
        memory=memory if memory is not None else InMemoryMemoryStore(),
        tracer=tracer if tracer is not None else InMemoryTracer(),
        # In-memory by default, not absent. A node calling
        # `require_durability()` worked under `aef run` and raised in the
        # gate — the same divergence in the last service still standing
        # (ADR 0091). Throwaway for the same reason memory is: a gate
        # re-execution must not write to the adopter's checkpoint store.
        #
        # NON-SERIALISING. `InMemoryDurabilityBackend` JSON-encodes every
        # checkpoint, so making it the default re-killed the state ADR 0089
        # had just made legal: a `threading.Lock` or open handle in
        # `working_memory` raised `PydanticSerializationError` on the first
        # super-step, and `scenario_runner` turned that into a uniform 0.0 —
        # the ADR 0075/0079/0089 shape a fourth time (ADR 0093). Nothing
        # reads these checkpoints; encoding them bought a constraint and no
        # capability.
        durability=durability if durability is not None else _EphemeralDurability(),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric=dict(judge_rubric or DEFAULT_RUBRIC)),
        evaluator=RuleBasedEvaluator(),
        policy_engine=PolicyEngine(policy, audit_log=audit_log),  # type: ignore[arg-type]
        # `Services.clock` has its own default; only override when the caller
        # has a reason (a scenario's pinned clock, so replay observes exactly
        # what the recording did — ADR 0048).
        **({"clock": clock} if clock is not None else {}),  # type: ignore[arg-type]
    )
