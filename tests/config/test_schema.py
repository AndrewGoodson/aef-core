from pathlib import Path

import pytest
from pydantic import ValidationError

from aef.config import (
    AgentConfig,
    AgentConfigError,
    EvolutionSettings,
    PoliciesConfig,
    load_agent_config,
)

CONFIG_DIR = Path(__file__).parent.parent.parent / "aef" / "config"


def test_example_config_loads_and_validates() -> None:
    config = load_agent_config(CONFIG_DIR / "agent.example.yaml")
    assert config.extends == "_base"
    assert config.model_provider.impl == "anthropic"
    assert config.evolution.enabled is False


def test_azure_sec_config_loads_with_expected_security_posture() -> None:
    config = load_agent_config(CONFIG_DIR / "agent.azure_sec.yaml")
    assert config.policies.require_hitl_above_risk == 0.7
    assert "resource_delete" in config.policies.forbid
    assert config.tools.creds == "managed_identity"
    assert set(config.tools.allow) == {"az_cli_ro", "kql_query"}
    assert config.evolution.enabled is False


def test_policies_config_rejects_non_finite_hitl_threshold() -> None:
    """A NaN require_hitl_above_risk would silently disable the HITL gate
    for every tool call once wired into aef.security.tool.PolicyConfig
    (risk > NaN is always False) — see docs/adr/0025."""
    with pytest.raises(ValidationError, match="finite"):
        PoliciesConfig(require_hitl_above_risk=float("nan"))


def test_unknown_top_level_key_rejected() -> None:
    raw = {
        "model_provider": {"impl": "anthropic", "model": "claude-sonnet"},
        "memory": {"impl": "in_memory"},
        "objectives": "x",
        "not_a_real_field": True,
    }
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(raw)


def test_unknown_nested_key_rejected() -> None:
    raw = {
        "model_provider": {"impl": "anthropic", "model": "claude-sonnet", "bogus": 1},
        "memory": {"impl": "in_memory"},
        "objectives": "x",
    }
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(raw)


def test_evolution_enabled_true_rejected_at_validation() -> None:
    with pytest.raises(ValueError, match="Phase 4 gate criteria"):
        EvolutionSettings(enabled=True)


def test_evolution_defaults_to_disabled() -> None:
    assert EvolutionSettings().enabled is False


def test_missing_required_field_rejected() -> None:
    raw = {"memory": {"impl": "in_memory"}, "objectives": "x"}  # missing model_provider
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(raw)


def test_load_agent_config_missing_file_raises_readable_error() -> None:
    with pytest.raises(AgentConfigError, match="cannot read"):
        load_agent_config(CONFIG_DIR / "does_not_exist.yaml")


def test_load_agent_config_invalid_yaml_raises_readable_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("model_provider: [unclosed")
    with pytest.raises(AgentConfigError, match="invalid YAML"):
        load_agent_config(bad_file)


def test_load_agent_config_validation_error_lists_field_paths(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("objectives: x\nmystery_field: true\n")
    with pytest.raises(AgentConfigError, match="mystery_field"):
        load_agent_config(bad_file)
