from pathlib import Path

from aef.cli.doctor import run_doctor


def test_doctor_flags_missing_claude_md_and_config(tmp_path: Path) -> None:
    checks = run_doctor(tmp_path)
    by_name = {c.name: c for c in checks}
    assert by_name["python_version"].ok
    assert not by_name["claude_md_present"].ok
    assert not by_name["agent_config"].ok


def test_doctor_passes_on_adopted_repo(tmp_path: Path) -> None:
    from aef.cli.adopt import run_adopt

    run_adopt(tmp_path)
    checks = run_doctor(tmp_path)
    by_name = {c.name: c for c in checks}
    assert by_name["claude_md_present"].ok
    assert any(name.startswith("agent_config:") and check.ok for name, check in by_name.items())


def test_doctor_flags_invalid_config(tmp_path: Path) -> None:
    (tmp_path / "aef.yaml").write_text("not_a_real_field: true\n")
    checks = run_doctor(tmp_path)
    config_checks = [c for c in checks if c.name.startswith("agent_config:")]
    assert len(config_checks) == 1
    assert not config_checks[0].ok
