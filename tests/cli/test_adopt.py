from pathlib import Path

from aef.cli.adopt import detect_framework, render_migration_checklist, run_adopt


def test_detect_langgraph(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("from langgraph.graph import StateGraph\n")
    assert detect_framework(tmp_path) == "langgraph"


def test_detect_crewai(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("import crewai\nfrom crewai import Agent\n")
    assert detect_framework(tmp_path) == "crewai"


def test_detect_raw_sdk(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("import anthropic\nclient = anthropic.Anthropic()\n")
    assert detect_framework(tmp_path) == "raw_sdk"


def test_detect_none(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    assert detect_framework(tmp_path) == "none"


def test_detect_langgraph_takes_priority_over_raw_sdk(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("import anthropic\nfrom langgraph.graph import StateGraph\n")
    assert detect_framework(tmp_path) == "langgraph"


def test_detect_ignores_venv_directory(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv" / "site-packages" / "langgraph"
    venv_dir.mkdir(parents=True)
    (venv_dir / "__init__.py").write_text("import langgraph\n")
    (tmp_path / "real_code.py").write_text("def f():\n    pass\n")
    assert detect_framework(tmp_path) == "none"


def test_run_adopt_writes_all_four_artifacts(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("import openai\n")
    result = run_adopt(tmp_path)

    assert result.framework == "raw_sdk"
    written_names = {p.name for p in result.written_files}
    assert written_names == {
        "CLAUDE.md",
        "aef.yaml",
        "aef_adapter.py",
        "AEF_MIGRATION_CHECKLIST.md",
    }
    for path in result.written_files:
        assert path.exists()
    assert (tmp_path / "CLAUDE.md").read_text().startswith("#")


def test_run_adopt_never_overwrites_existing_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# my own notes, do not touch\n")
    result = run_adopt(tmp_path)

    assert (tmp_path / "CLAUDE.md").read_text() == "# my own notes, do not touch\n"
    skipped_names = {p.name for p in result.skipped_files}
    assert "CLAUDE.md" in skipped_names


def test_run_adopt_never_overwrites_existing_aef_yaml(tmp_path: Path) -> None:
    (tmp_path / "aef.yaml").write_text("custom: true\n")
    run_adopt(tmp_path)
    assert (tmp_path / "aef.yaml").read_text() == "custom: true\n"


def test_run_adopt_is_idempotent_on_second_run(tmp_path: Path) -> None:
    first = run_adopt(tmp_path)
    second = run_adopt(tmp_path)
    assert len(first.written_files) == 4
    assert len(second.written_files) == 0
    assert len(second.skipped_files) == 4


def test_checklist_nonempty_for_every_framework() -> None:
    for framework in ("langgraph", "crewai", "raw_sdk", "none"):
        checklist = render_migration_checklist(framework)
        assert len(checklist) > 0
        assert all(isinstance(item, str) and item for item in checklist)


def test_detect_from_requirements_txt_with_no_imports_yet(tmp_path: Path) -> None:
    """A freshly-scaffolded repo: langgraph declared as a dependency but no
    code has imported it yet. This is exactly the adoption-path moment
    aef adopt should get right, not report as 'none' until code catches up."""
    (tmp_path / "requirements.txt").write_text("langgraph==0.2.0\nrequests\n")
    (tmp_path / "app.py").write_text("def main():\n    pass\n")
    assert detect_framework(tmp_path) == "langgraph"


def test_detect_from_pyproject_toml_dependency(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["crewai>=0.1", "pydantic"]\n'
    )
    assert detect_framework(tmp_path) == "crewai"


def test_detect_from_requirements_txt_variant_filename(tmp_path: Path) -> None:
    (tmp_path / "requirements-dev.txt").write_text("anthropic\n")
    assert detect_framework(tmp_path) == "raw_sdk"


def test_detect_from_manifest_in_monorepo_subdirectory(tmp_path: Path) -> None:
    sub = tmp_path / "services" / "agent"
    sub.mkdir(parents=True)
    (sub / "requirements.txt").write_text("langgraph\n")
    (tmp_path / "README.md").write_text("just docs\n")
    assert detect_framework(tmp_path) == "langgraph"


def test_detect_manifest_ignores_venv_subdirectory(tmp_path: Path) -> None:
    venv_site_packages = tmp_path / ".venv" / "lib" / "site-packages" / "langgraph"
    venv_site_packages.mkdir(parents=True)
    (venv_site_packages / "requirements.txt").write_text("langgraph\n")
    (tmp_path / "real_code.py").write_text("def f():\n    pass\n")
    assert detect_framework(tmp_path) == "none"


def test_detect_multiple_frameworks_present_langgraph_wins_over_crewai(tmp_path: Path) -> None:
    """No single 'correct' tie-break exists when a repo genuinely uses
    both — this locks in the current, deterministic priority order so a
    future change to it is a deliberate decision, not an accident."""
    (tmp_path / "agent.py").write_text("import langgraph\nimport crewai\nimport anthropic\n")
    assert detect_framework(tmp_path) == "langgraph"


def test_detect_code_signal_and_manifest_signal_combine_not_override(tmp_path: Path) -> None:
    """crewai in code plus langgraph only in a manifest — the manifest
    signal must still be checked, not skipped because .py files already
    matched something."""
    (tmp_path / "agent.py").write_text("import crewai\n")
    (tmp_path / "requirements.txt").write_text("langgraph\n")
    assert detect_framework(tmp_path) == "langgraph"
