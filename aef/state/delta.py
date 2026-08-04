"""`StateDelta` — the partial-update half of a node's fixed return type
`StateDelta + Route` (constraint #2). Application is a pure function of
`(StateDelta, AEFState) -> AEFState`: no I/O, no clock reads beyond what the
caller supplies via `Provenance.ts`, fully reproducible for replay.

State is append-mostly (report §5): list-valued fields concatenate, dict-valued
fields merge with the delta taking priority, scalar fields override only when
the delta sets them.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field, field_validator

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
    context_budget_tokens: int | None = Field(default=None, gt=0)
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    @field_validator("scores")
    @classmethod
    def _scores_must_be_finite(cls, value: dict[str, float]) -> dict[str, float]:
        # AEFState.scores is exactly where a Financial Agent's Sharpe/PF/
        # MaxDD-style domain gates land (report §16) — a division-by-zero
        # in a real metric calculation (e.g. zero volatility) produces inf
        # or nan. `model_dump_json()` silently rewrites both as JSON `null`
        # on the very first checkpoint write (confirmed directly, not
        # assumed — standard JSON has no Infinity/NaN literal), so a
        # corrupted score would look like a perfectly valid, merely-absent
        # one on every subsequent load: a domain gate reading
        # `state.scores.get("sharpe", 0)` would silently see a default
        # instead of an error, potentially flipping a pass/fail decision
        # with no signal anything went wrong. Reject at construction time
        # instead — the node that computed the bad value is what should
        # fail loudly, not a checkpoint several steps later. See docs/adr/0022.
        non_finite = {k: v for k, v in value.items() if not math.isfinite(v)}
        if non_finite:
            raise ValueError(
                f"scores must be finite (no inf/-inf/nan) — got non-finite values for: "
                f"{sorted(non_finite)}. A non-finite score usually means a division by "
                f"zero upstream (e.g. zero volatility in a Sharpe ratio) — fix the "
                f"computation, don't pass the result through."
            )
        return value

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
