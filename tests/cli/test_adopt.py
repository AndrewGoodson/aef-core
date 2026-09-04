from pathlib import Path

import pytest

from aef.cli.adopt import (
    AdoptResult,
    detect_framework,
    render_migration_checklist,
    run_adopt,
)


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


def test_run_adopt_writes_all_artifacts(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("import openai\n")
    result = run_adopt(tmp_path)

    assert result.framework == "raw_sdk"
    # Relative paths, not bare names: the loop kit adds two files both called
    # README.md, and a name-set would silently collapse them into one.
    written = {str(p.relative_to(tmp_path)) for p in result.written_files}
    assert written == {
        # onboarding kit
        "CLAUDE.md",
        "aef.yaml",
        "aef_adapter.py",
        "AEF_MIGRATION_CHECKLIST.md",
        "AGENT_INTEGRATION.md",
        "AUTONOMY.md",
        # cross-harness entry files (ADR 0040)
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".cursor/rules/aef.mdc",
        # self-rewiring loop kit (ADR 0057/0058)
        "LOOP.md",
        "agents/README.md",
        "corpus/README.md",
        ".github/workflows/loop-gate.yml",
        ".github/workflows/loop-monitor.yml",
        # per-model-release re-audit (docs/adr/0111)
        ".claude/skills/new-model-check/SKILL.md",
        # Zone A hygiene (docs/adr/0142): without it the adopter's first
        # `git add -A` commits bytecode into Zone A and G5 charges it as
        # drift — 0.4675 of a 0.500 budget for a one-line candidate.
        ".gitignore",
    }
    for path in result.written_files:
        assert path.exists()
    assert (tmp_path / "CLAUDE.md").read_text().startswith("#")


def test_run_adopt_emits_native_entry_file_for_each_harness(tmp_path: Path) -> None:
    """Every major coding-agent harness reads a different instructions file.
    adopt emits a native entry file for each so the scaffold is usable from
    Claude, Codex, Copilot, or Cursor — not Claude-only (docs/adr/0040).
    AGENTS.md carries the full contract (identical to CLAUDE.md); the Copilot
    and Cursor files are thin pointers that still inline the safety contract
    and point at the canonical guide."""
    run_adopt(tmp_path)
    # Codex (and the cross-tool AGENTS.md convention): full contract.
    assert (tmp_path / "AGENTS.md").read_text() == (tmp_path / "CLAUDE.md").read_text()
    # GitHub Copilot.
    copilot = (tmp_path / ".github" / "copilot-instructions.md").read_text()
    assert "AGENT_INTEGRATION.md" in copilot
    assert "HARD-STOP" in copilot
    # Cursor (modern .cursor/rules/*.mdc format).
    cursor = (tmp_path / ".cursor" / "rules" / "aef.mdc").read_text()
    assert "AGENT_INTEGRATION.md" in cursor
    assert "HARD-STOP" in cursor


def test_run_adopt_autonomy_contract_carries_unattended_run_blocks(tmp_path: Path) -> None:
    """Model-check 2026-09-03: the vendor guide's autonomy + scope blocks for
    unattended runs ship in AUTONOMY.md, and the verification rules the guide
    says to keep are still there beside them."""
    run_adopt(tmp_path)
    autonomy = (tmp_path / "AUTONOMY.md").read_text()
    # The blocks are wrapped at 90 columns for ruff; markdown joins `>`
    # continuation lines, so compare the joined quote, not raw lines.
    quoted = " ".join(line[2:] for line in autonomy.splitlines() if line.startswith("> "))
    assert "You are operating autonomously." in quoted
    assert "the scope is the deliverable" in quoted
    assert "surgically edit a file rather than rewrite the entire thing." in quoted
    assert "Reproduce-first" in autonomy  # kept, not traded for the new blocks
    assert "\\\\#" not in autonomy  # a doubled backslash would mean the f-string escape leaked


def test_run_adopt_never_overwrites_harness_files(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# my own agents file\n")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").write_text("# mine\n")
    result = run_adopt(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text() == "# my own agents file\n"
    assert (tmp_path / ".github" / "copilot-instructions.md").read_text() == "# mine\n"
    skipped = {p.name for p in result.skipped_files}
    assert {"AGENTS.md", "copilot-instructions.md"} <= skipped


def test_run_adopt_emits_onboarding_kit_content(tmp_path: Path) -> None:
    """Review/Phase-C: adopt emits the ingest-and-start guide and the
    inlined safety contract so a new repo agent inherits both. AUTONOMY.md
    must carry the HARD-STOP gates and point at the canonical spec; the
    integration guide must be self-contained enough to start from."""
    run_adopt(tmp_path)
    autonomy = (tmp_path / "AUTONOMY.md").read_text()
    assert "HARD-STOP" in autonomy
    assert "evolution" in autonomy  # the gated boundary must be named
    assert "self-improving-loop.md" in autonomy  # points at the canonical aef-core spec
    integration = (tmp_path / "AGENT_INTEGRATION.md").read_text()
    assert "aef doctor" in integration
    assert "(AEFState, Context, Services)" in integration


def test_run_adopt_never_overwrites_the_onboarding_kit(tmp_path: Path) -> None:
    (tmp_path / "AGENT_INTEGRATION.md").write_text("# my own guide\n")
    (tmp_path / "AUTONOMY.md").write_text("# my own rules\n")
    result = run_adopt(tmp_path)
    assert (tmp_path / "AGENT_INTEGRATION.md").read_text() == "# my own guide\n"
    assert (tmp_path / "AUTONOMY.md").read_text() == "# my own rules\n"
    skipped_names = {p.name for p in result.skipped_files}
    assert {"AGENT_INTEGRATION.md", "AUTONOMY.md"} <= skipped_names


def test_run_adopt_never_overwrites_existing_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# my own notes, do not touch\n")
    result = run_adopt(tmp_path)

    assert (tmp_path / "CLAUDE.md").read_text() == "# my own notes, do not touch\n"
    skipped_names = {p.name for p in result.skipped_files}
    assert "CLAUDE.md" in skipped_names


def test_run_adopt_does_not_follow_a_dangling_output_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-claude.md"
    (tmp_path / "CLAUDE.md").symlink_to(outside)

    result = run_adopt(tmp_path)

    assert not outside.exists()
    assert tmp_path / "CLAUDE.md" in result.skipped_files


def test_run_adopt_does_not_write_through_a_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-github"
    outside.mkdir()
    (tmp_path / ".github").symlink_to(outside, target_is_directory=True)

    result = run_adopt(tmp_path)

    assert list(outside.iterdir()) == []
    skipped = {str(path.relative_to(tmp_path)) for path in result.skipped_files}
    assert {
        ".github/copilot-instructions.md",
        ".github/workflows/loop-gate.yml",
        ".github/workflows/loop-monitor.yml",
    } <= skipped


def test_run_adopt_never_overwrites_existing_aef_yaml(tmp_path: Path) -> None:
    (tmp_path / "aef.yaml").write_text("custom: true\n")
    run_adopt(tmp_path)
    assert (tmp_path / "aef.yaml").read_text() == "custom: true\n"


def test_run_adopt_is_idempotent_on_second_run(tmp_path: Path) -> None:
    first = run_adopt(tmp_path)
    second = run_adopt(tmp_path)
    # 15 -> 16 with the `.gitignore` of ADR 0142. Updated deliberately: this
    # count is the pin that makes "adopt quietly started writing something"
    # a test failure rather than a discovery.
    assert len(first.written_files) == 16
    assert len(second.written_files) == 0
    assert len(second.skipped_files) == 16


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


# --------------------------------------------------------------------------
# The self-rewiring loop kit (ADR 0057/0058)
# --------------------------------------------------------------------------


def _adopt(tmp_path: Path) -> AdoptResult:
    (tmp_path / "README.md").write_text("# target\n")
    return run_adopt(tmp_path)


LOOP_KIT = (
    "LOOP.md",
    "agents/README.md",
    "corpus/README.md",
    ".github/workflows/loop-gate.yml",
    ".github/workflows/loop-monitor.yml",
)


@pytest.mark.parametrize("name", LOOP_KIT)
def test_adopt_emits_the_loop_kit(tmp_path: Path, name: str) -> None:
    _adopt(tmp_path)
    assert (tmp_path / name).is_file()


@pytest.mark.parametrize("name", LOOP_KIT)
def test_the_loop_kit_never_overwrites(tmp_path: Path, name: str) -> None:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("MINE\n")

    result = _adopt(tmp_path)

    assert target.read_text() == "MINE\n"
    assert target in result.skipped_files


@pytest.mark.parametrize(
    "name", [".github/workflows/loop-gate.yml", ".github/workflows/loop-monitor.yml"]
)
def test_the_emitted_workflows_carry_no_pull_request_trigger(tmp_path: Path, name: str) -> None:
    """The same trap the aef-core workflows avoid, carried into every repo
    that adopts: `pull_request` would let a candidate editing
    .github/workflows/ supply the workflow that judges it."""
    import yaml

    _adopt(tmp_path)
    document = yaml.safe_load((tmp_path / name).read_text())
    triggers = document.get(True, document.get("on"))
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert set(triggers) <= {"workflow_dispatch", "schedule"}


@pytest.mark.parametrize(
    "name", [".github/workflows/loop-gate.yml", ".github/workflows/loop-monitor.yml"]
)
def test_the_emitted_workflows_are_read_only(tmp_path: Path, name: str) -> None:
    import yaml

    _adopt(tmp_path)
    document = yaml.safe_load((tmp_path / name).read_text())
    assert document["permissions"] == {"contents": "read"}


def test_the_emitted_gate_workflow_checks_out_main(tmp_path: Path) -> None:
    import yaml

    _adopt(tmp_path)
    document = yaml.safe_load((tmp_path / ".github/workflows/loop-gate.yml").read_text())
    checkouts = [
        s
        for s in document["jobs"]["gate"]["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkouts
    assert all(s["with"]["ref"] == "main" for s in checkouts)


def test_the_emitted_workflows_keep_state_outside_the_checkout(tmp_path: Path) -> None:
    _adopt(tmp_path)
    for name in (".github/workflows/loop-gate.yml", ".github/workflows/loop-monitor.yml"):
        text = (tmp_path / name).read_text()
        assert "--state ~/" in text
        assert "--state ." not in text


def test_loop_md_leads_with_what_does_not_work_yet(tmp_path: Path) -> None:
    # An adopting repo whose agents produce candidates against an empty corpus
    # sees every one rejected, and that reads as "the loop is broken" unless
    # the doc says otherwise first.
    _adopt(tmp_path)
    text = (tmp_path / "LOOP.md").read_text()
    assert text.index("Nothing merges automatically") < text.index("Running it")
    assert "must supply before the loop can approve anything" in text


def test_loop_md_states_tier1_is_off(tmp_path: Path) -> None:
    _adopt(tmp_path)
    assert "Tier-1 auto-merge is OFF" in (tmp_path / "LOOP.md").read_text()


def test_loop_md_names_all_three_owner_obligations(tmp_path: Path) -> None:
    _adopt(tmp_path)
    text = (tmp_path / "LOOP.md").read_text()
    assert "A corpus" in text
    assert "Observations" in text
    assert "Halt notification" in text


def test_the_corpus_readme_says_empty_is_deliberate(tmp_path: Path) -> None:
    _adopt(tmp_path)
    assert "Empty on purpose" in (tmp_path / "corpus/README.md").read_text()


def test_the_agents_readme_marks_the_zone(tmp_path: Path) -> None:
    _adopt(tmp_path)
    text = (tmp_path / "agents/README.md").read_text()
    assert "Zone A" in text
    assert "Nothing here is auto-merged" in text


def test_run_adopt_ships_new_model_check_skill(tmp_path: Path) -> None:
    """`/new-model-check` ships with the scaffold so an adopted repo can
    re-audit its prompt and API surfaces at each model release instead of
    rotting silently. Never-overwrite like every other scaffold file."""
    result = run_adopt(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "new-model-check" / "SKILL.md"
    assert skill in result.written_files
    text = skill.read_text()
    assert text.startswith("---\nname: new-model-check\n")
    # The skill must carry no per-model facts: it reads them each run.
    assert "claude-api" in text
    assert "migration-guide" in text
    assert "planted" in text  # the detector is proved before "nothing found"


def test_run_adopt_never_overwrites_existing_new_model_check_skill(tmp_path: Path) -> None:
    skill = tmp_path / ".claude" / "skills" / "new-model-check" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# mine\n")
    result = run_adopt(tmp_path)
    assert skill.read_text() == "# mine\n"
    assert skill in result.skipped_files


def test_new_model_check_skill_template_matches_repo_copy() -> None:
    """The template is the source of truth; this repo's own copy under
    `.claude/skills/` must be byte-identical, the same way AGENTS.md is
    pinned to CLAUDE.md. Two drifting copies is how a shipped skill and the
    one that was actually tested stop being the same document."""
    from aef.cli.adopt import render_new_model_check_skill

    repo_root = Path(__file__).resolve().parents[2]
    repo_copy = repo_root / ".claude" / "skills" / "new-model-check" / "SKILL.md"
    assert repo_copy.read_text() == render_new_model_check_skill()


# --------------------------------------------------------------------------
# Zone A hygiene (ADR 0142)
# --------------------------------------------------------------------------


def test_run_adopt_writes_a_gitignore_that_keeps_bytecode_out_of_zone_a(tmp_path: Path) -> None:
    """`aef adopt` wrote no `.gitignore`, so the adopter's first `git add -A`
    committed `agents/**/__pycache__/*.pyc` into ZONE A. Those files are not
    in the baseline `aef loop bless` archived, so G5 charges every line of
    them: **0.4675 of a 0.500 drift budget for a ONE-LINE candidate**, against
    0.0238 with the bytecode excluded — 35 of the 36 differing lines were
    bytecode. Two consecutive drift rejections halt the loop (ADR 0142)."""
    result = run_adopt(tmp_path)
    path = tmp_path / ".gitignore"
    assert path in result.written_files
    body = path.read_text()
    patterns = {line.strip() for line in body.splitlines() if line.strip()}
    assert "__pycache__/" in patterns
    assert "*.py[cod]" in patterns
    # Zone B is EVIDENCE, read from git. An ignored corpus is an empty one,
    # and the gates would then judge against nothing.
    assert "corpus" not in patterns
    assert ".github" not in patterns


def test_the_generated_gitignore_actually_makes_git_ignore_zone_a_bytecode(tmp_path: Path) -> None:
    """The patterns are asserted above; this asserts GIT agrees, because the
    thing that matters is what `git check-ignore` answers, not a string
    match against a file nobody consulted."""
    import subprocess

    run_adopt(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True, capture_output=True)
    bytecode = tmp_path / "agents" / "mine" / "__pycache__" / "graph.cpython-313.pyc"
    bytecode.parent.mkdir(parents=True)
    bytecode.write_bytes(b"\x00\x01")
    checked = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", "-v", str(bytecode)],
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, f"git does not ignore it: {checked.stdout}{checked.stderr}"
    # ...and the agent source itself is NOT ignored, or the loop has no agent.
    source = tmp_path / "agents" / "mine" / "graph.py"
    source.write_text("x = 1\n")
    not_ignored = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", str(source)], capture_output=True, text=True
    )
    assert not_ignored.returncode == 1, not_ignored.stdout


def test_run_adopt_never_overwrites_a_gitignore_and_says_what_is_missing(tmp_path: Path) -> None:
    """Never-overwrite is the scaffold's rule, and appending is the same
    trespass wearing a politer hat. So the gap is REPORTED instead — in the
    checklist, which `aef adopt` prints and also writes to disk."""
    (tmp_path / ".gitignore").write_text("# mine\nnode_modules/\n")
    result = run_adopt(tmp_path)

    assert (tmp_path / ".gitignore").read_text() == "# mine\nnode_modules/\n"
    assert tmp_path / ".gitignore" in result.skipped_files

    told = [item for item in result.checklist if "__pycache__/" in item]
    assert told, result.checklist
    assert "0.4675" in told[0] and "0.500" in told[0], told[0]
    # and it reaches disk, not just the return value
    assert "__pycache__/" in (tmp_path / "AEF_MIGRATION_CHECKLIST.md").read_text()


def test_a_gitignore_that_already_covers_bytecode_is_not_nagged(tmp_path: Path) -> None:
    """`*.pyc` alone keeps every CPython 3 bytecode file out of the tree, and
    so does `__pycache__/` alone. Telling an adopter to add a pattern
    equivalent to one they already have is how generated advice stops being
    read."""
    (tmp_path / ".gitignore").write_text("*.pyc\n.venv/\n")
    result = run_adopt(tmp_path)
    assert [item for item in result.checklist if "__pycache__/" in item] == []


def test_gitignore_gaps_ignores_commented_out_patterns() -> None:
    """A commented pattern ignores nothing. Reading one as coverage is the
    detector failing in the direction that costs the adopter a drift budget."""
    from aef.cli.adopt import gitignore_gaps

    assert gitignore_gaps("# __pycache__/\n# *.pyc\n"), "a comment is not a rule"
    assert gitignore_gaps("__pycache__/\n") == ()
    assert gitignore_gaps("*.py[cod]\n") == ()


def test_the_checklist_names_the_zone_a_root_the_harness_actually_uses(tmp_path: Path) -> None:
    """E2 (ADR 0142): `aef migrate` wrote `aef_migrated.py` to the repo ROOT,
    which is Zone C — the one place the loop is structurally forbidden to
    propose changes to (`G0 rejected it: candidate touches paths outside Zone
    A`, measured). Nothing `aef adopt` generated said so: neither the string
    "Zone A" nor "agents/" appeared anywhere in CLAUDE.md or the checklist.

    UPDATED DELIBERATELY for ADR 0143, which fixed the command rather than
    only the documentation: migrate's default `--out` is now
    `DEFAULT_MIGRATED_OUT`, inside Zone A. The pin moves from the old
    root-level filename to that path, because a checklist still naming the
    root would now be telling an adopter to fix something the tool already
    did.

    Derived from `DEFAULT_AGENT_ROOT`, not hardcoded, and cross-checked
    against the directory `adopt` really creates — a doc naming a directory
    the harness does not use is the same defect one level up.
    """
    from aef.cli.migrate import DEFAULT_MIGRATED_OUT
    from aef.harness.zones import DEFAULT_AGENT_ROOT

    result = run_adopt(tmp_path)

    named = [item for item in result.checklist if f"{DEFAULT_AGENT_ROOT}/" in item]
    assert named, result.checklist
    assert DEFAULT_MIGRATED_OUT in named[0], named[0]
    assert "Zone A" in named[0], named[0]

    # The same directory adopt actually writes its Zone A README into.
    zone_a = {
        p.relative_to(tmp_path).parts[0]
        for p in result.written_files
        if p.name == "README.md" and p.parent != tmp_path
    }
    assert DEFAULT_AGENT_ROOT in zone_a, zone_a


def test_claude_md_states_where_converted_nodes_must_live(tmp_path: Path) -> None:
    """The checklist is step-by-step; CLAUDE.md is what a fresh session with
    no other context reads first. Both have to carry it (ADR 0142)."""
    from aef.cli.migrate import DEFAULT_MIGRATED_OUT
    from aef.harness.zones import DEFAULT_AGENT_ROOT

    run_adopt(tmp_path)
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (tmp_path / name).read_text()
        assert "Zone A" in text, name
        assert f"{DEFAULT_AGENT_ROOT}/" in text, name
        # ADR 0143: the path migrate writes to now, not the root-level name
        # it used to. The old name survives one sentence back, as the reason
        # a graph left over from an older run still has to be moved.
        assert DEFAULT_MIGRATED_OUT in text, name
        assert "outside Zone A" in text, name
