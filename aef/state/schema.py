"""Universal shared state schema — AEF research report §5, implemented verbatim
plus `schema_version` for migration support (constraint #4).

This is the ONE state shape every agent in the ecosystem shares. Per-agent
variation belongs in `working_memory` / `retrieved_context` payloads or in the
five allowed per-agent surfaces (Knowledge, Policies, Tools, Objectives,
Evaluation Metrics) — never in new top-level fields on this model.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CURRENT_SCHEMA_VERSION = "1.0.0"


class _StrictModel(BaseModel):
    """Base for all state types: unknown fields fail loudly rather than
    silently vanishing (blueprint §2.1 — "no untyped dict blobs")."""

    model_config = ConfigDict(extra="forbid")


class Provenance(_StrictModel):
    node_id: str
    graph_version: str
    model: str | None = None
    ts: datetime
    trace_id: str
    token_cost: int = 0


class Message(_StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    prov: Provenance


class Plan(_StrictModel):
    goal: str
    subgoals: list[Plan] = Field(default_factory=list)
    status: Literal["pending", "active", "done", "failed"] = "pending"
    reusable_key: str | None = None


class AEFState(_StrictModel):
    schema_version: str = CURRENT_SCHEMA_VERSION
    run_id: str
    agent_id: str
    objective: str
    messages: list[Message] = Field(default_factory=list)
    plan: Plan | None = None
    working_memory: dict[str, Any] = Field(default_factory=dict)
    context_budget_tokens: int = 8000
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint_seq: int = 0
    provenance: list[Provenance] = Field(default_factory=list)

    @field_validator("scores")
    @classmethod
    def _scores_must_be_finite(cls, value: dict[str, float]) -> dict[str, float]:
        # Same guard as StateDelta._scores_must_be_finite (aef/state/delta.py)
        # — kept here too since AEFState can be constructed directly, not
        # only via StateDelta.apply(). Belt-and-suspenders: apply() uses
        # model_copy(), which does NOT re-run validators, so this alone
        # would not have caught the bug StateDelta's validator exists for
        # (docs/adr/0022) — the two together close both entry points.
        non_finite = {k: v for k, v in value.items() if not math.isfinite(v)}
        if non_finite:
            raise ValueError(
                f"scores must be finite (no inf/-inf/nan) — got non-finite values for: "
                f"{sorted(non_finite)}"
            )
        return value


Plan.model_rebuild()
