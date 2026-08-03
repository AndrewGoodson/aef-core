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
