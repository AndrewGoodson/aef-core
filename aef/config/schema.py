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

    @field_validator("impl")
    @classmethod
    def _no_builder_exists(cls, value: str) -> str:
        # Same treatment `extends` got, for the same reason (ADR 0084): a
        # field that validates any string and is read by nothing lets an
        # owner believe a knowledge graph is attached when no code has ever
        # constructed one. `aef/services/knowledge_graph/` is a typed
        # interface with `NotImplementedError` bodies (Phase 2), so there is
        # nothing for any `impl` to name.
        #
        # The DESIGN reason this is a refusal rather than a builder, stated
        # because the milestone asked for one and not for an excuse: a
        # knowledge-graph adapter needs a retrieval contract the node
        # signature does not yet carry. `Services` hands a node its
        # dependencies, and a KG is only useful if a node can ASK it
        # something — which means a query interface, a result shape the
        # context engine can budget, and a provenance story for retrieved
        # facts. None of those three exist. Building a constructor before
        # them produces a service nothing can call, which is the defect
        # class ADR 0092 named (ADR 0100).
        raise ValueError(
            f"knowledge_graph.impl={value!r} names a builder that does not exist — "
            f"aef/services/knowledge_graph/ is a typed interface with no implementation "
            f"(Phase 2), so this block would be silently ignored. Remove it until a "
            f"knowledge graph is wired; see docs/adr/0100."
        )


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

    @field_validator("extends")
    @classmethod
    def _inheritance_is_not_implemented(cls, value: str) -> str:
        # Nothing resolves a base config — not a missing one, and not a
        # present one either. The field validated any string, so
        # `extends: production-base` loaded clean and silently inherited
        # nothing: an owner could believe a shared policy applied when no
        # code had ever read it. Rejecting the non-default is the smallest
        # honest answer until inheritance exists (ADR 0014, ADR 0084).
        if value != "_base":
            raise ValueError(
                f"config inheritance is not implemented, so extends={value!r} would be "
                f"silently ignored — nothing resolves a base config. Inline the settings "
                f"you need, or leave extends at its default '_base'."
            )
        return value

    model_provider: ModelProviderConfig
    memory: MemoryConfig
    knowledge_graph: KnowledgeGraphConfig | None = None
    evaluator: EvaluatorConfig = EvaluatorConfig()
    tools: ToolsConfig = ToolsConfig()
    policies: PoliciesConfig = PoliciesConfig()
    objectives: str
    evolution: EvolutionSettings = EvolutionSettings()
