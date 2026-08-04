from pathlib import Path

from aef.cli.doctor import run_doctor


def test_doctor_flags_missing_claude_md_and_config(tmp_path: Path) -> None:
    checks = run_doctor(tmp_path)
    by_name = {c.name: c for c in checks}
    assert by_name["python_version"].ok
    assert not by_name["claude_md_present"].ok
    assert not by_name["agent_config"].ok


def test_doctor_missing_claude_md_gives_an_actionable_message(tmp_path: Path) -> None:
    checks = run_doctor(tmp_path)
    by_name = {c.name: c for c in checks}
    assert "aef adopt" in by_name["claude_md_present"].detail


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


def _write_config(
    tmp_path: Path, *, fallback: str = "[]", objectives: str = "do the thing"
) -> None:
    (tmp_path / "aef.yaml").write_text(
        "model_provider:\n"
        "  impl: anthropic\n"
        "  model: claude-x\n"
        f"  fallback: {fallback}\n"
        "memory:\n"
        "  impl: in_memory\n"
        f'objectives: "{objectives}"\n'
    )


def test_doctor_advises_on_fallback_duplicating_the_primary_impl(tmp_path: Path) -> None:
    """Review Finding 4: a fallback naming the SAME impl as primary is a
    pointless same-vendor fallback (fails identically on a vendor outage).
    Advisory only — not a hard failure, since pydantic can't judge intent."""
    _write_config(tmp_path, fallback="[anthropic]")
    checks = run_doctor(tmp_path)
    advisories = [c for c in checks if c.level == "advisory" and not c.ok]
    assert any("fallback" in c.detail for c in advisories)
    # Advisory must NOT flip the overall doctor result to failure.
    assert all(c.ok for c in checks if c.level == "error" and c.name.startswith("agent_config:"))


def test_doctor_advises_on_empty_objectives(tmp_path: Path) -> None:
    _write_config(tmp_path, objectives="   ")
    checks = run_doctor(tmp_path)
    advisories = [c for c in checks if c.level == "advisory" and not c.ok]
    assert any("objectives" in c.detail for c in advisories)


def test_doctor_no_advisories_on_a_clean_config(tmp_path: Path) -> None:
    _write_config(tmp_path, fallback="[]", objectives="summarize incident tickets")
    checks = run_doctor(tmp_path)
    assert not [c for c in checks if c.level == "advisory" and not c.ok]
