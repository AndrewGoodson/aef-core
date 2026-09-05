"""Per-agent configuration schema — report §16, implemented verbatim plus
`evolution` (constraint #7: must stay disabled).

Every sub-model forbids unknown keys so a typo or a stale field fails
loudly at load time instead of being silently ignored (constraint from the
"## Config" section: "fail loudly with a readable error on unknown keys").
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# The retrievers that exist. Named here so `ContextConfig` can refuse anything
# else at LOAD time rather than at first use (ADR 0101).
CONTEXT_IMPLS: frozenset[str] = frozenset({"memory"})


class CommandProviderConfig(_StrictModel):
    """`model_provider.impl: command` — a harness described entirely here
    (ADR 0154). See `aef.providers.command_provider` for the security
    properties; this block is the whole interface an owner gets.

    Validation is delegated to `validate_template`, the same function
    `CommandProvider.__init__` calls, so a bad template fails at config-load
    time AND at construction time with the identical message. Two validators
    that could disagree is the drift ADR 0091 records.
    """

    argv: list[str]
    model_argv: list[str] = []
    system_argv: list[str] = []
    stdin: bool = False
    output: str = "stdout"
    output_pointer: str | None = None
    usage_pointer: str | None = None
    output_usage_pointer: str | None = None
    timeout_s: float = 600.0

    @model_validator(mode="after")
    def _template_must_be_runnable(self) -> CommandProviderConfig:
        # Imported here, not at module scope: `aef.config` must stay
        # importable without the optional vendor extras, which is what
        # `test_importing_aef_config_does_not_require_anthropic` pins.
        # `aef.providers.command_provider` imports no SDK, but the lazy
        # import keeps that guarantee independent of what it grows into.
        from aef.providers.command_provider import OUTPUT_MODES, validate_template

        validate_template(
            self.argv,
            model_argv=self.model_argv,
            system_argv=self.system_argv,
            stdin=self.stdin,
        )
        if self.output not in OUTPUT_MODES:
            raise ValueError(f"command.output={self.output!r} is not one of {sorted(OUTPUT_MODES)}")
        if self.output == "json_pointer" and self.output_pointer is None:
            raise ValueError(
                "command.output is 'json_pointer' but command.output_pointer is unset: "
                "there is nothing to follow, so every reply would be empty."
            )
        if self.output != "json_pointer" and self.output_pointer is not None:
            raise ValueError(
                f"command.output_pointer is set while command.output is {self.output!r}, "
                f"where it is never read; see docs/adr/0154."
            )
        if self.timeout_s <= 0:
            raise ValueError(f"command.timeout_s must be positive; got {self.timeout_s}")
        return self


class ModelProviderConfig(_StrictModel):
    impl: str
    model: str
    fallback: list[str] = []
    # Only `impl: command` reads this. Present-but-ignored is refused below
    # for the same reason `knowledge_graph.impl` is (ADR 0100).
    command: CommandProviderConfig | None = None

    @model_validator(mode="after")
    def _command_block_matches_the_impl(self) -> ModelProviderConfig:
        if self.impl == "command" and self.command is None:
            raise ValueError(
                "model_provider.impl is 'command' but no `command:` block is present. "
                "There is no argv template to run; see docs/adr/0154."
            )
        if self.impl != "command" and self.command is not None:
            raise ValueError(
                f"model_provider.command is set while impl is {self.impl!r}, which never "
                f"reads it. A block that validates and is ignored lets an owner believe a "
                f"harness is configured; set impl: command or remove the block."
            )
        if "command" in self.fallback:
            raise ValueError(
                "'command' cannot appear in model_provider.fallback: there is exactly one "
                "`command:` block, so a fallback entry would have no template of its own "
                "and would silently duplicate the primary."
            )
        return self


class MemoryConfig(_StrictModel):
    impl: str
    backend: str | None = None

    @field_validator("impl")
    @classmethod
    def _must_name_constructible_memory(cls, value: str) -> str:
        if value != "in_memory":
            raise ValueError(
                f"memory.impl={value!r} names no runtime builder. Implemented: in_memory. "
                "A config that names an unwired store would silently run against volatile "
                "in-memory storage; see docs/adr/0014."
            )
        return value

    @field_validator("backend")
    @classmethod
    def _reject_ignored_backend(cls, value: str | None) -> str | None:
        if value is not None:
            raise ValueError(
                f"memory.backend={value!r} is not wired and would be ignored. Remove it "
                "until a runtime builder supports durable memory configuration; see "
                "docs/adr/0014."
            )
        return value


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


class ContextConfig(_StrictModel):
    """Retrieval, the one Phase-2 interface Milestone 3's triage kept.

    `impl` is refused unless it names something that exists, for the same
    reason `knowledge_graph` is (ADR 0100): a block that validates while
    nothing reads it lets an owner believe retrieval is configured.
    """

    impl: str
    # Defaults to the run's own `AEFState.context_budget_tokens` when unset,
    # so the budget has ONE source unless an owner deliberately overrides it
    # for retrieval specifically.
    token_budget: int | None = None

    @field_validator("impl")
    @classmethod
    def _must_name_a_real_retriever(cls, value: str) -> str:
        if value not in CONTEXT_IMPLS:
            raise ValueError(
                f"context.impl={value!r} names no retriever. Implemented: "
                f"{', '.join(sorted(CONTEXT_IMPLS))}. A block naming an unbuilt backend "
                f"would validate and be ignored; see docs/adr/0101."
            )
        return value

    @field_validator("token_budget")
    @classmethod
    def _must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError(
                f"context.token_budget must be positive; got {value}. A zero budget admits "
                f"no chunk, so retrieval would silently return nothing."
            )
        return value


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
                "evolution.enabled=True is rejected: all seven Phase 4 safety mechanisms "
                "are implemented, but have not been validated against live traffic and real "
                "tenants. Enabling evolution remains an explicit owner decision; see "
                "docs/roadmap.md Phase 4 and docs/trust/promotion-trust-case.md"
            )
        return value


REFLECTION_IMPLS: frozenset[str] = frozenset({"rule_based", "llm"})


class ReflectionConfig(_StrictModel):
    """Which Critic/Judge the reflect node runs (ADR 0115). `llm` needs the
    run's model provider; `aef run` refuses at load if there is none, for the
    same reason `context.impl` refuses an unknown retriever: a block that
    validates while nothing can honour it lets an owner believe it is on."""

    impl: str = "rule_based"

    @field_validator("impl")
    @classmethod
    def _must_name_a_real_reflection(cls, value: str) -> str:
        if value not in REFLECTION_IMPLS:
            raise ValueError(f"reflection.impl={value!r} is not one of {sorted(REFLECTION_IMPLS)}")
        return value


# The containment modes a shadow run can be configured with (ADR 0161). The
# strings are the enum VALUES of `aef.harness.shadow.ContainmentMode`, and a
# test asserts the two sets are identical — two spellings of one security
# decision that could disagree is the drift ADR 0091 records. Named here
# rather than imported so `aef.config` keeps no dependency on `aef.harness`.
CONTAINMENT_MODES: frozenset[str] = frozenset({"auto", "fallback", "off"})


class ShadowConfig(_StrictModel):
    """How a shadow run is contained (ADR 0161).

    `auto` is the default and it does not fall back: a container when a
    runtime and a verified image are available, and a REFUSAL naming what was
    missing when they are not. The two non-default modes are owner statements
    and are recorded as such in the ledger — an owner who accepts an
    uncontained shadow says so in this file, and the run says so back.
    """

    containment: str = "auto"
    # The worker image. There is no default because there is no image this
    # repo can ship: it must contain the adopter's own `aef` and its
    # dependencies (trust case §2.1). `None` under `auto` is a refusal that
    # names the missing image, not a silent downgrade.
    image: str | None = None

    @field_validator("containment")
    @classmethod
    def _must_name_a_real_mode(cls, value: str) -> str:
        if value not in CONTAINMENT_MODES:
            raise ValueError(
                f"shadow.containment={value!r} is not one of {sorted(CONTAINMENT_MODES)}. "
                f"'auto' contains the candidate when a runtime and image are available and "
                f"refuses when they are not; 'fallback' and 'off' accept an uncontained "
                f"shadow and are recorded in the ledger as owner choices."
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
    context: ContextConfig | None = None
    reflection: ReflectionConfig = ReflectionConfig()
    evaluator: EvaluatorConfig = EvaluatorConfig()
    tools: ToolsConfig = ToolsConfig()
    policies: PoliciesConfig = PoliciesConfig()
    shadow: ShadowConfig = ShadowConfig()
    objectives: str
    evolution: EvolutionSettings = EvolutionSettings()
