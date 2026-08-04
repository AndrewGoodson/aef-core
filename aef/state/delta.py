"""`StateDelta` — the partial-update half of a node's fixed return type
`StateDelta + Route` (constraint #2). Application is a pure function of
`(StateDelta, AEFState) -> AEFState`: no I/O, no clock reads beyond what the
caller supplies via `Provenance.ts`, fully reproducible for replay.

State is append-mostly (report §5): list-valued fields concatenate, dict-valued
fields merge with the delta taking priority, scalar fields override only when
the delta sets them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aef.state.schema import AEFState, Message, Plan, Provenance


class StateDelta(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    # Full REPLACE, not merge, when set — unlike the list/dict fields below.
    # A node updating one field of an existing plan (e.g. just its status)
    # must start from `state.plan.model_copy(update={...})`, not construct a
    # fresh `Plan(...)`, or it will silently drop subgoals/reusable_key. See
    # examples/hello_agent/graph.py's summarize_node for the safe pattern.
    plan: Plan | None = None
    working_memory: dict[str, Any] = Field(default_factory=dict)
    context_budget_tokens: int | None = None
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    def apply(self, state: AEFState) -> AEFState:
        return state.model_copy(
            update={
                "messages": [*state.messages, *self.messages],
                "plan": self.plan if self.plan is not None else state.plan,
                "working_memory": {**state.working_memory, **self.working_memory},
                "context_budget_tokens": (
                    self.context_budget_tokens
                    if self.context_budget_tokens is not None
                    else state.context_budget_tokens
                ),
                "retrieved_context": [*state.retrieved_context, *self.retrieved_context],
                "tool_results": [*state.tool_results, *self.tool_results],
                "reflections": [*state.reflections, *self.reflections],
                "scores": {**state.scores, **self.scores},
                "errors": [*state.errors, *self.errors],
                "provenance": [*state.provenance, *self.provenance],
                "checkpoint_seq": state.checkpoint_seq + 1,
            }
        )
