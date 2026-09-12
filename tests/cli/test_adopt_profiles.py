"""Offline onboarding and workflow creation are separate, explicit choices."""

from pathlib import Path

import pytest

from aef.cli.adopt import run_adopt
from aef.cli.run import build_run_config


def test_default_adoption_writes_no_workflows(tmp_path: Path) -> None:
    run_adopt(tmp_path)
    assert not (tmp_path / ".github/workflows").exists()


def test_offline_profile_is_providerless_and_has_applicable_instructions(tmp_path: Path) -> None:
    run_adopt(tmp_path, profile="offline")
    assert build_run_config(tmp_path / "aef.yaml").model_provider is None
    assert not (tmp_path / "LOOP.md").exists()
    for name in ("CLAUDE.md", "AGENTS.md", "GROK.md", "AGENT_INTEGRATION.md", "FIRST_DAY.md"):
        text = (tmp_path / name).read_text()
        assert "offline" in text
        assert "aef loop cycle" not in text
        assert "AGENT_INTEGRATION.md" in text or "Evidence learning protocol" in text
    checklist = (tmp_path / "AEF_MIGRATION_CHECKLIST.md").read_text()
    assert "model login" not in checklist
    assert "replay" in checklist


def test_workflows_require_explicit_model_profile_opt_in(tmp_path: Path) -> None:
    run_adopt(tmp_path, profile="model", with_workflows=True)
    assert (tmp_path / ".github/workflows/loop-monitor.yml").is_file()
    assert (tmp_path / ".github/workflows/loop-gate.yml").is_file()


def test_invalid_profile_combination_refuses_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="model"):
        run_adopt(tmp_path, profile="offline", with_workflows=True)
    assert list(tmp_path.iterdir()) == []


def test_profile_selection_does_not_reconfigure_an_existing_install(tmp_path: Path) -> None:
    run_adopt(tmp_path, profile="model", with_workflows=True)
    existing = {
        name: (tmp_path / name).read_bytes()
        for name in (
            "aef.yaml",
            "AGENT_INTEGRATION.md",
            "FIRST_DAY.md",
            ".github/workflows/loop-monitor.yml",
            ".github/workflows/loop-gate.yml",
        )
    }
    run_adopt(tmp_path, profile="offline")
    for name, content in existing.items():
        assert (tmp_path / name).read_bytes() == content
    # The refreshed entry block must not claim the preserved config is offline.
    entry = (tmp_path / "AGENTS.md").read_text()
    assert "Existing configuration and workflows are preserved" in entry
    assert "check the adoption report" in entry
