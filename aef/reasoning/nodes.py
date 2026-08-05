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


def _failing_nodes(state: AEFState) -> list[str]:
    """Node ids that appended an error, in first-seen order.

    Order preserved rather than sorted: the first failure is usually the
    cause and the rest are consequences, and a set would throw that away.
    Entries with no `node_id` are skipped — an error whose origin was not
    recorded cannot be attributed to a node, and guessing is worse than
    omitting.
    """
    seen: list[str] = []
    for entry in state.errors:
        node_id = entry.get("node_id")
        if isinstance(node_id, str) and node_id and node_id not in seen:
            seen.append(node_id)
    return seen


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
                    # The node that OBSERVED the failure. Kept, and no longer
                    # the only one recorded — see `failing_nodes` below.
                    "node_id": ctx.node_id,
                    # The nodes that CAUSED it. `ctx.node_id` here is the
                    # reflect node, so a reader of this record could not tell
                    # which node had actually failed — the failing id sat in
                    # `state.errors[i]["node_id"]`, which this node read to
                    # build the feedback text and then discarded.
                    #
                    # A numeric proposer never needed it. A structural one
                    # cannot begin without it: "add a fallback to the flaky
                    # node" requires knowing which node was flaky (ADR 0096).
                    "failing_nodes": _failing_nodes(state),
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
