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
    # Config advisories only. A missing CLAUDE.md is now advisory rather than
    # an error, because an `aef init` project legitimately has none and
    # hard-failing it left a pristine init repo at exit 1 with no fix but to
    # hand-write the file (ADR 0079).
    assert not [
        c for c in checks if c.level == "advisory" and not c.ok and c.name.startswith("advisory:")
    ]


# --------------------------------------------------------------------------
# ADR 0079 — the checks doctor promised and did not perform
# --------------------------------------------------------------------------


def test_a_pristine_init_repo_is_not_a_failure(tmp_path: Path) -> None:
    """`aef init` writes no CLAUDE.md, and doctor hard-failed on that — so a
    freshly initialised project exited 1 while AGENT_INTEGRATION.md said
    "fix any [FAIL]", and the only fix was hand-writing the file the tool
    should have produced."""
    from aef.cli.init import run_init

    run_init("demoagent", tmp_path)
    checks = run_doctor(tmp_path)
    assert not [c for c in checks if c.level == "error" and not c.ok]


def test_an_adopted_repo_still_requires_a_claude_md(tmp_path: Path) -> None:
    """The relaxation must not extend to adopted repos, where the file is
    the point of adopting."""
    _write_config(tmp_path, fallback="[]", objectives="summarize tickets")
    (tmp_path / "aef_adapter.py").write_text("def build_graph():\n    pass\n")
    failed = [c for c in run_doctor(tmp_path) if c.level == "error" and not c.ok]
    assert [c.name for c in failed] == ["claude_md_present"]


def test_an_adapter_that_does_not_parse_is_reported(tmp_path: Path) -> None:
    """`aef adopt` promises doctor "confirms the config and IMPORTS are wired
    correctly" and doctor never looked at the adapter at all — a
    syntactically invalid `aef_adapter.py` passed clean."""
    _write_config(tmp_path, fallback="[]", objectives="summarize tickets")
    (tmp_path / "CLAUDE.md").write_text("# x\n")
    (tmp_path / "aef_adapter.py").write_text("def build_graph(:\n")
    failed = [c for c in run_doctor(tmp_path) if not c.ok and c.name == "adapter_importable"]
    assert failed and "does not parse" in failed[0].detail


def test_the_generated_todo_objective_is_flagged(tmp_path: Path) -> None:
    """`aef adopt` writes `objectives: "TODO: describe..."`, which is
    non-empty — so the advisory built to catch "the agent has no stated
    purpose" could not see the one string that ships by default."""
    _write_config(
        tmp_path,
        fallback="[]",
        objectives="TODO: describe this agent's objective in one or two sentences.",
    )
    advisories = [c for c in run_doctor(tmp_path) if not c.ok and "empty_objectives" in c.name]
    assert advisories, "the placeholder adopt itself writes is not flagged"
