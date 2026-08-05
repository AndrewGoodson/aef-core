"""Phase-4 criterion 1: **shadow execution against live traffic before
promotion eligibility.**

> The candidate runs alongside the incumbent on real input; only its
> DIVERGENCE is recorded; nothing it returns reaches a user.

This is the criterion that most changes the evidence available, because it is
the only one that observes a candidate on traffic the corpus never captured.
The corpus is recorded past; shadow is the present.

## The part that cannot be paraphrased away

Running a candidate on live input means its nodes actually execute. A node
declaring `side_effects=EXTERNAL_CALL` makes that call — for real, on real
input, twice, because the incumbent made it too. "Nothing it returns reaches a
user" says nothing about what it *does* on the way.

So shadow execution here is **refused** for any graph whose candidate nodes
declare a side effect this harness cannot suppress, and suppression is not
invented for the occasion: it is the existing `PolicyEngine`, deny-by-default,
with an empty scope set. A tool call the candidate attempts is denied and
recorded as a denial. A node that reaches around the policy to do I/O directly
is outside what any of this can see, and that is stated rather than covered
over — it is the same boundary G0's static scan has always had.

`ShadowRunner.observe` therefore returns **the incumbent's state, always**.
The candidate's is compared and dropped. There is no code path in which a
caller can accidentally return the shadow result: the type it gets back does
not contain one.

## Only divergence is recorded

Not both traces. A shadow log that stores every candidate output is a second
copy of production data with none of its access controls, and it grows without
bound while answering a question — *did these differ, and where* — that a
diff answers in a fraction of the space.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aef.harness.container import ContainerRuntime
from aef.harness.isolated import NodeWorkerSession, graph_from
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
from aef.kernel.contracts import Services, SideEffect
from aef.kernel.executor import GraphExecutor
from aef.kernel.graph import Graph
from aef.security.tool import PolicyConfig, PolicyEngine
from aef.state import AEFState

# Fields compared between the two final states. Deliberately not "everything":
# `checkpoint_seq` and `provenance` differ by construction on any two runs, so
# including them would report every observation as divergent and the signal
# would be noise within one run.
COMPARED_FIELDS: tuple[str, ...] = (
    "working_memory",
    "retrieved_context",
    "tool_results",
    "errors",
    "plan",
    "scores",
)


class ShadowError(RuntimeError):
    pass


class UnsuppressableSideEffectError(ShadowError):
    """The candidate declares an effect shadowing cannot contain.

    Fatal rather than a warning: the alternative is running it and finding
    out, on live input, which is the one thing shadow execution exists to
    avoid.
    """


@dataclass(frozen=True)
class Divergence:
    """Where the two runs differed. Empty means they agreed."""

    fields: tuple[str, ...] = ()
    incumbent_path: tuple[str, ...] = ()
    candidate_path: tuple[str, ...] = ()
    candidate_failed: str = ""
    policy_denials: int = 0

    @property
    def diverged(self) -> bool:
        return bool(self.fields or self.routing_diverged or self.candidate_failed)

    @property
    def routing_diverged(self) -> bool:
        return self.incumbent_path != self.candidate_path


@dataclass(frozen=True)
class ShadowObservation:
    """One live request, observed.

    `state` is the INCUMBENT's, and it is the only state here. A candidate
    result a caller could reach for is a candidate result that eventually
    reaches a user.
    """

    state: AEFState
    divergence: Divergence

    @property
    def agreed(self) -> bool:
        return not self.divergence.diverged


@dataclass(frozen=True)
class ShadowReport:
    """Accumulated evidence. What promotion eligibility is read from."""

    observations: int = 0
    divergences: int = 0
    candidate_failures: int = 0
    diverging_fields: dict[str, int] = field(default_factory=dict)

    @property
    def divergence_rate(self) -> float:
        # Zero observations is not zero divergence. Returning 0.0 would make
        # "never ran" indistinguishable from "always agreed", and the second
        # is the one that earns promotion.
        if self.observations == 0:
            raise ShadowError(
                "no observations: a divergence rate over zero live requests is not 0.0, it "
                "is undefined, and reporting it as 0.0 makes 'never ran' look like 'always "
                "agreed'"
            )
        return self.divergences / self.observations

    def with_observation(self, observation: ShadowObservation) -> ShadowReport:
        fields = dict(self.diverging_fields)
        for name in observation.divergence.fields:
            fields[name] = fields.get(name, 0) + 1
        return ShadowReport(
            observations=self.observations + 1,
            divergences=self.divergences + (0 if observation.agreed else 1),
            candidate_failures=self.candidate_failures
            + (1 if observation.divergence.candidate_failed else 0),
            diverging_fields=fields,
        )


def _suppressed_services(base: Services) -> Services:
    """The candidate's services: everything readable, nothing actable.

    `PolicyConfig()` with no allowed scopes is the engine's own
    deny-by-default (constraint #6), reused rather than reimplemented. A
    bespoke "shadow mode" flag would be a second security decision to keep in
    agreement with the first, which is how the two service lists drifted
    (ADR 0091).
    """
    return Services(
        model_provider=base.model_provider,
        memory=base.memory,
        retriever=base.retriever,
        evaluator=base.evaluator,
        critic=base.critic,
        judge=base.judge,
        tracer=base.tracer,
        tools=base.tools,
        policy_engine=PolicyEngine(PolicyConfig()),
        optimizer=base.optimizer,
        durability=base.durability,
        # NOT inherited. An approval the incumbent was granted is an approval
        # for the incumbent's call, and handing it to a candidate lets the
        # shadow cross a gate the owner opened for something else.
        hitl_approvals=frozenset(),
        clock=base.clock,
    )


def assert_shadowable(graph: Graph) -> None:
    """Refuse a graph whose effects shadowing cannot contain."""
    offenders = [
        node.id for node in graph.nodes.values() if node.side_effects is SideEffect.MUTATING
    ]
    if offenders:
        raise UnsuppressableSideEffectError(
            f"node(s) {', '.join(sorted(offenders))} declare side_effects=mutating. Shadow "
            f"execution runs the candidate on LIVE input, so a mutating node mutates — for "
            f"real, a second time, alongside the incumbent's. The policy engine denies tool "
            f"calls; it cannot un-write a write."
        )


def _field_value(state: AEFState, name: str) -> Any:
    value = getattr(state, name)
    return value.model_dump() if hasattr(value, "model_dump") else value


def _compare(incumbent: AEFState, candidate: AEFState) -> tuple[str, ...]:
    return tuple(
        name
        for name in COMPARED_FIELDS
        if _field_value(incumbent, name) != _field_value(candidate, name)
    )


@dataclass(frozen=True)
class ShadowRunner:
    """Runs both, returns one.

    `max_steps` is passed to both executors from one value so a divergence
    cannot be an artefact of the candidate having been given more room.
    """

    incumbent: Graph
    candidate: Graph
    max_steps: int = 1000

    def __post_init__(self) -> None:
        # At construction, not at first request. A runner that can never
        # legally run is a configuration error, and finding out on live
        # traffic is finding out too late (the same reasoning as
        # `SandboxPolicy.__post_init__`).
        assert_shadowable(self.candidate)

    def observe(self, state: AEFState, services: Services) -> ShadowObservation:
        """Serve `state` from the incumbent; compare the candidate silently."""
        incumbent_result = GraphExecutor(
            self.incumbent.compile(), services, max_steps=self.max_steps
        ).run(state.model_copy(deep=True), record_trace=True)

        shadow_services = _suppressed_services(services)
        failed = ""
        candidate_state: AEFState | None = None
        candidate_path: tuple[str, ...] = ()
        try:
            candidate_result = GraphExecutor(
                self.candidate.compile(), shadow_services, max_steps=self.max_steps
            ).run(state.model_copy(deep=True), record_trace=True)
            candidate_state = candidate_result.final_state
            candidate_path = tuple(r.node_id for r in (candidate_result.trace or ()))
        except Exception as exc:  # noqa: BLE001
            # A candidate that raises is a divergence, not an outage. The
            # incumbent has already produced the answer this request is served
            # from, and letting the shadow's failure propagate would make
            # observing a candidate more dangerous than not observing it.
            failed = f"{type(exc).__name__}: {exc}"

        incumbent_path = tuple(r.node_id for r in (incumbent_result.trace or ()))
        divergence = Divergence(
            fields=_compare(incumbent_result.final_state, candidate_state)
            if candidate_state is not None
            else (),
            incumbent_path=incumbent_path,
            candidate_path=candidate_path,
            candidate_failed=failed,
            policy_denials=sum(
                1 for e in (candidate_state.errors if candidate_state else []) if _is_denial(e)
            ),
        )
        return ShadowObservation(state=incumbent_result.final_state, divergence=divergence)


def _is_denial(entry: dict[str, Any]) -> bool:
    from aef.harness.outcome import POLICY_DENIED_KEY

    return bool(entry.get(POLICY_DENIED_KEY))


def contained_candidate_graph(
    entrypoint: str,
    *,
    workdir: Path,
    runtime: ContainerRuntime,
    sandbox: SandboxPolicy | None = None,
    read_only_mounts: dict[str, str] | None = None,
) -> tuple[Graph, NodeWorkerSession]:
    """The candidate, as a graph whose nodes execute INSIDE a container.

    Closes the bypass the trust case demonstrated (§2.1). Suppression by
    `PolicyEngine` denies tool CALLS; a node that imported `pathlib` and wrote
    to disk was never making one, and it wrote. A container has no network and
    a read-only root, so the same node now fails at the filesystem instead of
    succeeding quietly.

    **The inverted control is why this is worth doing rather than just
    sandboxing the whole run.** The parent keeps state, routing and the step
    count; the worker evaluates one node and returns `(delta, route)`. A
    contained candidate therefore cannot forge the final state a shadow
    comparison reads — which matters more here than in the gate, because a
    forged "identical" state hides a divergence and makes the candidate look
    SAFER than it is (ADR 0094).

    Returns the graph and the session, because the caller must close the
    session: an unclosed one leaves a container running, which is ADR 0093's
    defect in its third location.
    """
    session = NodeWorkerSession(
        entrypoint,
        workdir=workdir,
        sandbox=sandbox or SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED),
        container=runtime,
        read_only_mounts=read_only_mounts,
    )
    try:
        graph = graph_from(session)
        # Still refused, container or not. Containment stops a node reaching
        # the host; it does not stop a MUTATING node mutating whatever it was
        # declared to mutate, and shadowing runs it on live input.
        assert_shadowable(graph)
    except BaseException:
        session.close()
        raise
    return graph, session
