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


def test_an_adapter_that_is_not_utf8_is_reported(tmp_path: Path) -> None:
    _write_config(tmp_path, fallback="[]", objectives="summarize tickets")
    (tmp_path / "CLAUDE.md").write_text("# x\n")
    (tmp_path / "aef_adapter.py").write_bytes(b"\xff\xfe")

    failed = [c for c in run_doctor(tmp_path) if not c.ok and c.name == "adapter_importable"]
    assert failed and "is not UTF-8" in failed[0].detail


def test_an_adopted_repo_with_a_missing_adapter_fails_doctor(tmp_path: Path) -> None:
    from aef.cli.adopt import run_adopt

    run_adopt(tmp_path)
    (tmp_path / "aef_adapter.py").unlink()

    failed = [c for c in run_doctor(tmp_path) if c.level == "error" and not c.ok]
    assert any(c.name == "adapter_present" for c in failed)


def test_nested_build_graph_does_not_count_as_an_exposed_adapter(tmp_path: Path) -> None:
    _write_config(tmp_path)
    (tmp_path / "aef_adapter.py").write_text(
        "def wrapper():\n    def build_graph():\n        pass\n    return build_graph\n"
    )

    failed = [c for c in run_doctor(tmp_path) if c.name == "adapter_importable" and not c.ok]
    assert failed and "top-level build_graph" in failed[0].detail


def test_generated_adapter_stub_is_a_warning_not_an_ok(tmp_path: Path) -> None:
    from aef.cli.adopt import run_adopt

    run_adopt(tmp_path)

    adapter = next(c for c in run_doctor(tmp_path) if c.name == "adapter_importable")
    assert not adapter.ok
    assert adapter.level == "advisory"
    assert "still the generated stub" in adapter.detail


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


# --------------------------------------------------------------------------
# ADR 0137 — `aef doctor` reported the bypass green
#
# Reproduced on the adopted+migrated repo the ready loop built: exit 0, two
# advisories, and neither about the fact that the migrated node's model call
# reached no `Services.model_provider` at all. Advisory here, because whether
# a repo is READY TO BE GATED is `aef loop doctor`'s question and that one
# refuses; this surface only has to stop saying nothing.
# --------------------------------------------------------------------------


def _migrated(tmp_path: Path, node_body: str) -> None:
    (tmp_path / "aef_migrated.py").write_text(
        "from aef.kernel import END, Graph, Node\n"
        "from aef.state import StateDelta\n\n\n"
        "def work(state, ctx, services):\n"
        f"{node_body}"
        "    return StateDelta(), END\n\n\n"
        "def build_graph():\n"
        "    return Graph(id='g', version='1',\n"
        "                 nodes={'work': Node(id='work', version='1', fn=work,\n"
        "                                     deterministic=False)},\n"
        "                 edges=[], entry_node='work')\n"
    )


def test_a_migrated_node_whose_call_bypasses_the_provider_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "legacy.py").write_text("import anthropic\n\n\ndef ask(p):\n    return anthropic\n")
    _migrated(tmp_path, "    from legacy import ask\n\n    ask(state.objective)\n")

    check = next(c for c in run_doctor(tmp_path) if c.name.startswith("model_calls_visible"))
    assert not check.ok
    assert check.level == "advisory"
    assert "legacy.py" in check.detail
    assert "cannot replay" in check.detail


def test_a_routed_migrated_node_is_not_flagged(tmp_path: Path) -> None:
    _migrated(tmp_path, "    services.require_model_provider()\n")
    check = next(c for c in run_doctor(tmp_path) if c.name.startswith("model_calls_visible"))
    assert check.ok


def test_the_check_is_absent_when_the_repo_has_not_been_migrated(tmp_path: Path) -> None:
    """`aef init`-shaped repos have no `aef_migrated.py`, and a check that
    cannot look at anything must not report on it either way."""
    assert not any(c.name.startswith("model_calls_visible") for c in run_doctor(tmp_path))


# --------------------------------------------------------------------------
# ADR 0141 — the advisory is keyed on the graph, not on migrate's artefact
# --------------------------------------------------------------------------


_ADAPTER = (
    "from aef.kernel import END, Graph, Node\n"
    "from aef.state import StateDelta\n\n\n"
    "def work(state, ctx, services):\n"
    "{body}"
    "    return StateDelta(), END\n\n\n"
    "def build_graph():\n"
    "    return Graph(id='g', version='1',\n"
    "                 nodes={{'work': Node(id='work', version='1', fn=work,\n"
    "                                     deterministic=False)}},\n"
    "                 edges=[], entry_node='work')\n"
)


def test_the_documented_adoption_path_triggers_the_advisory(tmp_path: Path) -> None:
    """`aef adopt`, wire `aef_adapter.py`, write nodes under `agents/**` — the
    only path the docs describe, and it never produced `aef_migrated.py`, so
    the advisory could not fire for it (reproduced, ADR 0141). The check was
    keyed on the artefact of a different command."""
    (tmp_path / "agents" / "mine").mkdir(parents=True)
    (tmp_path / "agents" / "mine" / "vendor_helper.py").write_text(
        "import anthropic\n\n\ndef ask(p):\n    return anthropic\n"
    )
    (tmp_path / "agents" / "mine" / "graph.py").write_text(
        _ADAPTER.format(body="    from agents.mine.vendor_helper import ask\n\n    ask(1)\n")
    )
    assert not (tmp_path / "aef_migrated.py").exists()

    checks = [c for c in run_doctor(tmp_path) if c.name.startswith("model_calls_visible")]
    assert checks, "the documented path produced no finding at all"
    flagged = [c for c in checks if not c.ok]
    assert flagged and "vendor_helper.py" in flagged[0].detail


def test_the_adapter_shim_is_scanned_too(tmp_path: Path) -> None:
    (tmp_path / "legacy.py").write_text("import openai\n\n\ndef ask(p):\n    return openai\n")
    (tmp_path / "aef_adapter.py").write_text(
        _ADAPTER.format(body="    from legacy import ask\n\n    ask(1)\n")
    )
    flagged = [
        c for c in run_doctor(tmp_path) if c.name.startswith("model_calls_visible") and not c.ok
    ]
    assert flagged and "legacy.py" in flagged[0].detail
    assert flagged[0].level == "advisory", "aef doctor never fails on this; loop doctor asks"


def test_an_explicit_agent_path_wins_over_discovery(tmp_path: Path) -> None:
    """The same flag `aef loop doctor` takes. When the owner says which file
    it is, doctor does not go looking for others."""
    (tmp_path / "legacy.py").write_text("import openai\n\n\ndef ask(p):\n    return openai\n")
    (tmp_path / "aef_adapter.py").write_text(
        _ADAPTER.format(body="    from legacy import ask\n\n    ask(1)\n")
    )
    (tmp_path / "clean.py").write_text(_ADAPTER.format(body=""))

    names = [
        c.name
        for c in run_doctor(tmp_path, agent_path="clean.py")
        if c.name.startswith("model_calls_visible")
    ]
    assert names == ["model_calls_visible:clean.py"]
    assert all(c.ok for c in run_doctor(tmp_path, agent_path="clean.py") if c.name in names)


# --------------------------------------------------------------------------
# The entry file the agent actually reads (ADR 0153)
# --------------------------------------------------------------------------


def test_an_entry_file_that_never_reaches_the_guide_is_reported(tmp_path: Path) -> None:
    """Reproduced on a real repo: `aef adopt` skipped the `AGENTS.md` that
    repo's agents read, so `grep -c AEF AGENTS.md` returned 0 and the scaffold
    contract sat in files nobody opens. Adopt appends a block now — but a repo
    adopted before that, or one whose block was deleted, still has the gap and
    nothing said so.

    Advisory, not an error: an adopter may point their agents elsewhere on
    purpose. What they may not do is fail to notice.
    """
    from aef.cli.adopt import run_adopt

    run_adopt(tmp_path)
    (tmp_path / "AGENTS.md").write_text("# my own rules\n\nnothing about the scaffold here\n")

    by_name = {c.name: c for c in run_doctor(tmp_path)}
    check = by_name["entry_file_points_at_the_guide:AGENTS.md"]
    assert not check.ok
    assert check.level == "advisory", "this must not fail an otherwise-healthy repo"
    assert "AGENT_INTEGRATION.md" in check.detail
    assert "aef adopt" in check.detail
    # ...and the file adopt did write is fine, so the check is not simply
    # "every AGENTS.md is bad".
    assert by_name["entry_file_points_at_the_guide:CLAUDE.md"].ok


def test_the_entry_file_check_is_silent_in_a_repo_that_was_never_adopted(tmp_path: Path) -> None:
    """An `aef init` project has no adoption markers and rightly has no
    `CLAUDE.md`. Reporting a missing scaffold block there is noise about a
    scaffold nobody installed."""
    (tmp_path / "AGENTS.md").write_text("# mine\n")
    names = {c.name for c in run_doctor(tmp_path)}
    assert not any(n.startswith("entry_file_points_at_the_guide") for n in names), names
