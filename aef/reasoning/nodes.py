"""`make_reflect_node` — the wiring that makes reflection actually reach
memory.

`Critic`/`Judge` produce values; nothing persists them. This factory builds
a real `Node` (fixed signature, DI-only, contract-compliant) that runs both
through `Services` and writes a `MemoryRecord(kind="failure"|"success")`,
which is the CoALA taxonomy the memory module's docstring commits to but
which nothing in the repo previously produced from a reflection.

Grounding the loop this way is the prerequisite for anything downstream
that learns from runs: a proposer can only cite failure/success memory if
something writes it.
"""

from __future__ import annotations

from aef.kernel.contracts import END, Context, Node, Route, Services, SideEffect
from aef.reasoning.rule_based_reflection import failure_signals
from aef.services.memory.base import MemoryKind, MemoryRecord
from aef.state import AEFState, StateDelta


def make_reflect_node(
    *,
    node_id: str = "reflect",
    version: str = "0.1.0",
    route: Route = END,
    memory_tags: tuple[str, ...] = (),
) -> Node:
    """A `Node` that critiques and judges the current state, appends the
    verbal feedback to `state.reflections`, and persists the whole thing to
    `Services.memory` as failure/success memory.

    `route` is where control goes afterwards; it defaults to `END` so the
    node is usable as a terminal reflection step with no configuration.
    """

    def reflect_fn(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        critique = services.require_critic().critique(state)
        judgment = services.require_judge().judge(state)
        # Same convention the Critic used — not a second opinion about what
        # counts as failure (see `failure_signals`).
        kind: MemoryKind = "failure" if failure_signals(state) else "success"

        services.require_memory().write(
            MemoryRecord(
                kind=kind,
                content={
                    "verbal_feedback": critique.verbal_feedback,
                    "grounded_in": list(critique.grounded_in),
                    "score": judgment.score,
                    "rubric": dict(judgment.rubric),
                    "rationale": judgment.rationale,
                    "node_id": ctx.node_id,
                    "graph_version": ctx.graph_version,
                    "objective": state.objective,
                },
                run_id=state.run_id,
                agent_id=state.agent_id,
                tags=memory_tags,
                created_at=ctx.now,
            )
        )

        # Deliberately does NOT write `judgment.score` into `state.scores`.
        # The Judge reads `state.scores`; feeding its own output back would
        # make a second reflection step judge its previous judgement — a
        # self-referential term the rubric was never written to weigh.
        return StateDelta(reflections=[critique.verbal_feedback]), route

    return Node(
        id=node_id,
        version=version,
        fn=reflect_fn,
        # The *output* is a pure function of state, but the node writes to
        # the memory store. `ReplayEngine` re-executes nodes declared
        # `deterministic=True` (replay.py) — declaring True here would append
        # a duplicate reflection to the store on every replay. Declared False
        # so replay trusts the record instead of repeating the I/O.
        deterministic=False,
        side_effects=SideEffect.IO,
        # `checkpoint_seq` distinguishes successive reflections within one
        # run (a graph may reflect more than once) while staying stable
        # across a retry of the same step, which is exactly the at-least-once
        # resume semantics the key exists for (docs/adr/0010).
        idempotency_key_fn=lambda s: f"{s.run_id}:{node_id}:{s.checkpoint_seq}",
    )
