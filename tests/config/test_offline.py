"""Provider absence must be intentional and must survive runtime construction."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from aef.cli.doctor import _config_advisories
from aef.cli.run import build_run_config
from aef.config.factory import build_model_provider
from aef.config.schema import AgentConfig

OFFLINE = {"model_provider": None, "memory": {"impl": "in_memory"}, "objectives": "Check data"}


def test_explicit_offline_config_builds_without_provider(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline construction attempted to build a provider")

    monkeypatch.setattr("aef.config.factory._build_single", forbidden)
    config = AgentConfig.model_validate(OFFLINE)
    assert build_model_provider(config.model_provider) is None
    path = tmp_path / "aef.yaml"
    path.write_text("model_provider: null\nmemory: {impl: in_memory}\nobjectives: Check data\n")
    runtime = build_run_config(path)
    assert runtime.model_provider is None
    assert runtime.reflection_model is None
    assert runtime.reflection == "rule_based"
    assert _config_advisories(path, config) == []


@pytest.mark.parametrize(
    "extra", [{"reflection": {"impl": "llm"}}, {"gates": {"live_model_calls": True}}]
)
def test_offline_config_rejects_settings_that_need_a_provider(extra) -> None:
    with pytest.raises(ValidationError, match="model_provider"):
        AgentConfig.model_validate({**OFFLINE, **extra})
