"""Per-agent configuration schema — report §16, implemented verbatim plus
`evolution` (constraint #7: must stay disabled).

Every sub-model forbids unknown keys so a typo or a stale field fails
loudly at load time instead of being silently ignored (constraint from the
"## Config" section: "fail loudly with a readable error on unknown keys").
"""

from __future__ import annotations

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
