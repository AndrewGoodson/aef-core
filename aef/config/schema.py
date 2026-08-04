"""Per-agent configuration schema — report §16, implemented verbatim plus
`evolution` (constraint #7: must stay disabled).

Every sub-model forbids unknown keys so a typo or a stale field fails
loudly at load time instead of being silently ignored (constraint from the
"## Config" section: "fail loudly with a readable error on unknown keys").
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelProviderConfig(_StrictModel):
    impl: str
    model: str
    fallback: list[str] = []


class MemoryConfig(_StrictModel):
    impl: str
    backend: str | None = None


class KnowledgeGraphConfig(_StrictModel):
    impl: str
    ontology: str | None = None


class EvaluatorConfig(_StrictModel):
    suites: list[str] = []


class ToolsConfig(_StrictModel):
    allow: list[str] = []
    sandbox: str | None = None
    creds: str | None = None


class PoliciesConfig(_StrictModel):
    require_hitl_above_risk: float = 0.0
    forbid: list[str] = []

    @field_validator("require_hitl_above_risk")
    @classmethod
    def _must_be_in_range(cls, value: float) -> float:
        # Mirrors the runtime guard on aef.security.tool.PolicyConfig at
        # config-load time (a config that loads clean must not construct an
        # invalid runtime PolicyConfig once policies are wired — Phase 2, ADR
        # 0014). A NaN threshold makes `risk > threshold` silently False for
        # every risk; a threshold >= 1.0 makes the gate unreachable since risk
        # is capped at 1.0 (ADR 0025/0035). Bound to [0.0, 1.0).
        if not math.isfinite(value):
            raise ValueError(
                f"require_hitl_above_risk must be finite (no inf/-inf/nan) — got {value!r}"
            )
        if not (0.0 <= value < 1.0):
            raise ValueError(
                f"require_hitl_above_risk must be within [0.0, 1.0) so the HITL gate stays "
                f"reachable (risk is capped at 1.0) — got {value!r}"
            )
        return value


class EvolutionSettings(_StrictModel):
    """Mirrors `aef.evolution.engine.EvolutionConfig`. Kept as a separate,
    plain (non-raising) model here so a config file with `enabled: true`
    fails with a normal, readable pydantic ValidationError at load time
    rather than an exception from deep inside the evolution engine."""

    enabled: bool = False

    @field_validator("enabled")
    @classmethod
    def _must_stay_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "evolution.enabled=True is rejected in Phase 0/1 — none of the Phase 4 "
                "gate criteria are implemented yet; see docs/roadmap.md Phase 4 and "
                "aef.evolution.engine for the full list"
            )
        return value


class AgentConfig(_StrictModel):
    extends: str = "_base"
    model_provider: ModelProviderConfig
    memory: MemoryConfig
    knowledge_graph: KnowledgeGraphConfig | None = None
    evaluator: EvaluatorConfig = EvaluatorConfig()
    tools: ToolsConfig = ToolsConfig()
    policies: PoliciesConfig = PoliciesConfig()
    objectives: str
    evolution: EvolutionSettings = EvolutionSettings()
