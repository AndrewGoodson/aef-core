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
        # the adopter's sequence, in the order they meet it (ADR 0148).
        # Separate from LOOP.md: that file says what the loop NEEDS, this one
        # says what to run today and what each step costs.
        "FIRST_DAY.md",
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


def test_run_adopt_appends_to_existing_harness_files_without_touching_a_byte(
    tmp_path: Path,
) -> None:
    """UPDATED DELIBERATELY (ADR 0153), and this is the note saying so.

    It asserted that an existing `AGENTS.md` came back byte-identical and was
    reported `skipped`. That was ADR 0034/0040's never-overwrite rule read as
    "never write" — and measured on a real repo with eight `.claude/agents`
    agents, it meant `aef adopt` wrote a `CLAUDE.md` the repo does not use and
    skipped the `AGENTS.md` it does: `grep -c AEF AGENTS.md` returned 0.

    The rule the scaffold actually needs is "never destroy": the adopter's
    bytes survive verbatim, and adopt maintains one block between markers.
    So the assertion moves from "the file is unchanged" to "the file's own
    bytes are unchanged and the block is now there", which is the property
    that was worth defending all along."""
    (tmp_path / "AGENTS.md").write_text("# my own agents file\n")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").write_text("# mine\n")

    result = run_adopt(tmp_path)

    for path, original in (
        (tmp_path / "AGENTS.md", "# my own agents file\n"),
        (tmp_path / ".github" / "copilot-instructions.md", "# mine\n"),
    ):
        text = path.read_text()
        assert text.startswith(original), f"{path} lost the adopter's own bytes"
        assert "<!-- aef:begin -->" in text and "<!-- aef:end -->" in text
        assert "AGENT_INTEGRATION.md" in text, "the block must point at the canonical guide"
        assert path in result.appended_files
        assert path not in result.skipped_files


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


def test_run_adopt_never_overwrites_an_existing_first_day(tmp_path: Path) -> None:
    """FIRST_DAY.md (ADR 0148) is under the same never-overwrite rule as every
    other scaffold file: an adopter who has written their own is not silently
    handed ours."""
    (tmp_path / "FIRST_DAY.md").write_text("# our own runbook\n")
    result = run_adopt(tmp_path)
    assert (tmp_path / "FIRST_DAY.md").read_text() == "# our own runbook\n"
    assert tmp_path / "FIRST_DAY.md" in result.skipped_files
    # ...and the rest of the kit still lands.
    assert (tmp_path / "LOOP.md").exists()


def test_run_adopt_appends_to_an_existing_claude_md_and_destroys_nothing(tmp_path: Path) -> None:
    """UPDATED DELIBERATELY (ADR 0153) — see the harness-file test above for
    the reason. The adopter's own text is still there, verbatim and first; the
    only addition is the block, and its markers say where it ends."""
    (tmp_path / "CLAUDE.md").write_text("# my own notes, do not touch\n")

    result = run_adopt(tmp_path)

    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.startswith("# my own notes, do not touch\n")
    assert "<!-- aef:begin -->" in text
    assert tmp_path / "CLAUDE.md" in result.appended_files
    assert "CLAUDE.md" not in {p.name for p in result.skipped_files}


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
    # 15 -> 16 with the `.gitignore` of ADR 0142, 16 -> 17 with `FIRST_DAY.md`
    # of ADR 0148. Updated deliberately each time: this count is the pin that
    # makes "adopt quietly started writing something" a test failure rather
    # than a discovery.
    assert len(first.written_files) == 17
    assert len(second.written_files) == 0
    assert len(second.skipped_files) == 17


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


def test_the_emitted_monitor_workflow_actually_runs_a_cycle(tmp_path: Path) -> None:
    """The rendered workflow had `loop monitor` (hourly) and `loop digest`
    (weekly) and **no `loop cycle` step at all** — so an adopted repo's loop
    never proposed anything unattended, however many obligations were green.
    Found by the independent re-score; this repo's own workflow has had a
    daily cycle since ADR 0057.

    Asserted through the parsed YAML and the real CLI parser, not a string
    match: a step whose flags the CLI rejects is a cron job that fails every
    night, and a cycle with no `--memory` reports `no memory store configured`
    and exits 0, which reads exactly like a healthy run."""
    import shlex

    import yaml

    from aef.cli.main import build_parser

    _adopt(tmp_path)
    document = yaml.safe_load((tmp_path / ".github/workflows/loop-monitor.yml").read_text())
    triggers = document.get(True, document.get("on"))
    assert "0 3 * * *" in [entry["cron"] for entry in triggers["schedule"]], triggers
    assert "workflow_dispatch" in triggers, "an owner must be able to run one on demand"

    steps = document["jobs"]["monitor"]["steps"]
    cycle = [s for s in steps if s.get("name") == "Daily cycle"]
    assert cycle, [s.get("name") for s in steps]
    step = cycle[0]
    assert "workflow_dispatch" in step["if"] and "0 3 * * *" in step["if"]

    joined = step["run"].replace("\\\n", " ")
    invocation = [line for line in joined.splitlines() if line.strip().startswith("aef loop cycle")]
    assert invocation, step["run"]
    argv = shlex.split(invocation[0].split("2>&1")[0])[1:]
    build_parser().parse_args(argv)  # SystemExit if the CLI would refuse it
    for flag, value in (
        ("--state", "~/.aef-loop-state"),
        ("--memory", "~/.aef-loop-state/memory.jsonl"),
        ("--config", "aef.yaml"),
        ("--corpus", "corpus"),
        ("--module", "$AEF_MODULE"),
        # Never `live` by default: CI has no coding-agent harness login, so a
        # live miss either fails for want of a credential or spends one the
        # owner did not choose to spend.
        ("--cassette-miss", "fail"),
    ):
        assert argv[argv.index(flag) + 1] == value, flag

    # The verdict in words. `no admissible failure memory` and `escalated`
    # both exit 0, so a green nightly job says nothing on its own.
    assert "GITHUB_STEP_SUMMARY" in step["run"]
    assert "cycle.log" in step["run"]


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


def test_run_adopt_appends_the_bytecode_patterns_to_an_existing_gitignore(tmp_path: Path) -> None:
    """UPDATED DELIBERATELY (ADR 0153). ADR 0142 reported the gap in the
    checklist and left the file alone, on the reading that appending was
    overwriting by another route. It is not: the two patterns go inside
    `# aef:begin` / `# aef:end`, every pre-existing byte stays outside them,
    and deleting the block undoes it exactly. A checklist line was the weakest
    control available against a cost measured at 93.5% of a drift budget.

    The checklist still carries the measurement — in the past tense, because
    it now reports what the tool did rather than asking for what it could have
    done itself."""
    (tmp_path / ".gitignore").write_text("# mine\nnode_modules/\n")

    result = run_adopt(tmp_path)

    text = (tmp_path / ".gitignore").read_text()
    assert text.startswith("# mine\nnode_modules/\n"), "the adopter's own bytes must survive"
    assert "# aef:begin\n__pycache__/\n*.py[cod]\n# aef:end" in text
    assert tmp_path / ".gitignore" in result.appended_files

    told = [item for item in result.checklist if "__pycache__/" in item]
    assert told, result.checklist
    assert "appended" in told[0], told[0]
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


def test_the_bytecode_advisory_covers_a_widened_agent_root(tmp_path: Path) -> None:
    """ADR 0168 / F8. The message named `agents/` — interpolated from
    `DEFAULT_AGENT_ROOT` — as the directory at risk, so an operator who ran
    `aef migrate --agent-root .claude/agents` was told about the wrong one.

    REPRODUCED on the pilot clone, whose `.gitignore` covers no bytecode:
    compiling one generated module and running `git add -A` staged

        A  .claude/agents/migrated/marlin_accela/__pycache__/graph.cpython-313.pyc

    which is Zone A content under a root this sentence did not mention.

    `aef adopt` runs BEFORE `aef migrate` and cannot know which root will be
    chosen, so the rule is stated instead of a path guessed — asserted here,
    because "name the other directory too" would have been the wrong fix.
    """
    from aef.cli.adopt import gitignore_appended_note, gitignore_gaps
    from aef.harness.zones import DEFAULT_AGENT_ROOT

    (gap,) = gitignore_gaps("node_modules/\n*.pem\n")
    for text in (gap, gitignore_appended_note()):
        assert "AGENT ROOT" in text, text
        assert "--agent-root" in text, text
        assert ".claude/agents/" in text, text
        assert "runs before" in text and "cannot know" in text, text
        assert f"`{DEFAULT_AGENT_ROOT}/` by default" in text, text


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


# --------------------------------------------------------------------------
# Prompt-file agents, and append-within-markers (ADR 0153)
# --------------------------------------------------------------------------


def _prompt_repo(root: Path, *, agents: int = 8, skills: int = 5) -> Path:
    """A repo shaped like the ones the survey found: agents that are `.md`
    prompt files, skills, an `AGENTS.md`, a `.codex/` — and NO model-SDK call
    site anywhere. Every eligible repo surveyed for UPGRADE_LOOP.md had zero."""
    (root / ".claude" / "agents").mkdir(parents=True)
    for i in range(agents):
        (root / ".claude" / "agents" / f"agent-{i}.md").write_text(
            f"---\nname: agent-{i}\n---\n\nYou are agent {i}.\n"
        )
    for i in range(skills):
        skill = root / ".claude" / "skills" / f"skill-{i}"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: skill-{i}\n---\n\nDo a thing.\n")
    (root / "AGENTS.md").write_text("# House rules\n\nRun the tests.\n")
    (root / ".codex").mkdir()
    (root / ".codex" / "README.md").write_text("codex config\n")
    return root


def test_a_repo_whose_agents_are_prompt_files_is_not_reported_as_none(tmp_path: Path) -> None:
    """The reproduction, as a test. On the surveyed repos `aef adopt` printed
    `detected framework: none` — the label meaning "no orchestration code to
    migrate away from", handed to a repo with eight agents. `none` is now
    reserved for a repo that really has neither."""
    from aef.cli.adopt import detect_prompt_surface

    _prompt_repo(tmp_path)
    assert detect_framework(tmp_path) == "prompt_files"

    surface = detect_prompt_surface(tmp_path)
    assert surface.agents == 8
    assert surface.skills == 5
    assert surface.has_agents_md and surface.has_codex_dir
    assert surface.describe() == "8 agents, 5 skills, AGENTS.md, .codex"

    result = run_adopt(tmp_path)
    assert result.detection() == "prompt_files (8 agents, 5 skills, AGENTS.md, .codex)"


def test_prompt_file_detection_does_not_count_what_adopt_itself_wrote(tmp_path: Path) -> None:
    """The seam, planted: `aef adopt` writes `AGENTS.md`, a Cursor rule and a
    skill. Counting its own output would make a PRISTINE repo detect as `none`
    on the first run and `prompt_files` on the second, and would change the
    counts a marker block quotes — so re-running adopt would rewrite files it
    had just written. Asserted by running adopt twice."""
    from aef.cli.adopt import detect_prompt_surface

    (tmp_path / "utils.py").write_text("def f():\n    return 1\n")
    assert detect_framework(tmp_path) == "none"

    run_adopt(tmp_path)

    assert detect_prompt_surface(tmp_path).total == 0, detect_prompt_surface(tmp_path)
    assert detect_framework(tmp_path) == "none", "adopt counted its own output as agents"


def test_a_second_adopt_on_a_prompt_repo_changes_no_byte_of_any_file(tmp_path: Path) -> None:
    """Idempotency across the WHOLE tree, not just the counts — the property
    the marker block exists to make possible. Hashes every file after run 1
    and after run 2 and demands they match, because a block interpolating
    something adopt itself changes would rewrite four entry files forever."""
    import hashlib

    _prompt_repo(tmp_path)

    def snapshot() -> dict[str, str]:
        return {
            str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(tmp_path.rglob("*"))
            if p.is_file()
        }

    first_result = run_adopt(tmp_path)
    after_first = snapshot()
    second_result = run_adopt(tmp_path)
    after_second = snapshot()

    assert after_first == after_second, "a second `aef adopt` is not a no-op"
    assert second_result.written_files == []
    assert second_result.appended_files == []
    assert first_result.detection() == second_result.detection()


def test_the_block_is_replaced_in_place_and_the_bytes_outside_it_are_untouched(
    tmp_path: Path,
) -> None:
    """The load-bearing property, asserted with a hash of the text outside the
    markers: an OLDER block version is replaced, and nothing else moves. This
    is what makes appending different from overwriting — and the only reason
    ADR 0153 is allowed to extend ADR 0034/0040's rule rather than break it."""
    import hashlib

    from aef.cli.adopt import MD_MARKERS

    begin, end = MD_MARKERS
    original = f"# My rules\n\nLine one.\n\n{begin}\nan ANCIENT aef block\n{end}\n\nLine two.\n"
    (tmp_path / "AGENTS.md").write_text(original)

    result = run_adopt(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()

    def outside(body: str) -> str:
        start, stop = body.index(begin), body.index(end) + len(end)
        return body[:start] + body[stop:]

    assert hashlib.sha256(outside(text).encode()).hexdigest() == (
        hashlib.sha256(outside(original).encode()).hexdigest()
    ), "bytes outside the markers changed"
    assert "an ANCIENT aef block" not in text, "the stale block survived"
    assert "AGENT_INTEGRATION.md" in text
    assert "Line two." in text, "content AFTER the block must survive"
    assert tmp_path / "AGENTS.md" in result.appended_files


@pytest.mark.parametrize(
    "content,why",
    [
        ("# mine\n<!-- aef:begin -->\nhalf a block\n", "a begin with no end"),
        ("# mine\nstray\n<!-- aef:end -->\n", "an end with no begin"),
        (
            "<!-- aef:begin -->\na\n<!-- aef:end -->\n<!-- aef:begin -->\nb\n<!-- aef:end -->\n",
            "two blocks",
        ),
    ],
)
def test_a_file_with_markers_adopt_cannot_resolve_is_skipped_with_the_reason(
    tmp_path: Path, content: str, why: str
) -> None:
    """Guessing where someone else's block ends is how a never-destroy tool
    destroys. Each of these is left exactly as it was, and the skip says why
    rather than reading as "already exists"."""
    (tmp_path / "AGENTS.md").write_text(content)

    result = run_adopt(tmp_path)

    assert (tmp_path / "AGENTS.md").read_text() == content, why
    assert tmp_path / "AGENTS.md" in result.skipped_files
    assert "refusing to guess" in result.skip_reason(tmp_path / "AGENTS.md"), why


def test_a_binary_entry_file_is_skipped_with_the_reason_not_appended_to(tmp_path: Path) -> None:
    """`read_text()` raises on it and `write_text()` would replace it. The
    skip names the cause; nothing is appended to bytes nobody could read."""
    (tmp_path / "AGENTS.md").write_bytes(b"\xff\xfe\x00\x01binary\x00")

    result = run_adopt(tmp_path)

    assert (tmp_path / "AGENTS.md").read_bytes() == b"\xff\xfe\x00\x01binary\x00"
    assert tmp_path / "AGENTS.md" in result.skipped_files
    assert "not readable as text" in result.skip_reason(tmp_path / "AGENTS.md")


def test_the_checklist_tells_a_prompt_repo_to_run_migrate_not_to_convert_call_sites(
    tmp_path: Path,
) -> None:
    """There is no call site to convert. The step that replaces it names the
    count, the command, and the one-graph-per-agent output path — derived from
    migrate's own default so a doc cannot name a directory nothing writes."""
    from aef.cli.adopt import DEFAULT_MIGRATED_OUT

    _prompt_repo(tmp_path, agents=3, skills=1)
    result = run_adopt(tmp_path)

    named = [item for item in result.checklist if "aef migrate" in item and "prompt agent" in item]
    assert named, result.checklist
    item = named[0]
    assert "3 prompt agents" in item, item
    assert f"{DEFAULT_MIGRATED_OUT.rsplit('/', 1)[0]}/<agent>/graph.py" in item, item
    assert "Zone A" in item, item
    # The half an adopter would otherwise discover from a G0 rejection: the
    # generated graph is Zone A, the persona `.md` it reads is not, and
    # widening the agent root is an opt-in scope decision.
    assert "Zone C" in item and "--agent-root" in item, item
    # ...and no step tells them to convert a call site they do not have.
    assert not [i for i in result.checklist if "Convert each call site" in i], result.checklist


def test_a_repo_with_call_sites_and_prompt_agents_keeps_the_sdk_notes_and_gains_the_step(
    tmp_path: Path,
) -> None:
    """The precedence decision, pinned: a code/manifest signal wins the LABEL,
    because the label selects the per-framework migration notes and a repo
    with real call sites still needs them. Nothing is lost the other way — the
    counts are reported under every label and the prompt-agent step is emitted
    whenever there is a prompt agent."""
    _prompt_repo(tmp_path, agents=2, skills=0)
    (tmp_path / "app.py").write_text("import anthropic\nclient = anthropic.Anthropic()\n")

    result = run_adopt(tmp_path)

    assert result.framework == "raw_sdk"
    assert "prompt files: 2 agents" in result.detection(), result.detection()
    assert [i for i in result.checklist if "Convert each call site" in i], "SDK step lost"
    assert [i for i in result.checklist if "2 prompt agents" in i], "prompt step missing"


def test_the_block_text_depends_only_on_signals_adopt_does_not_write() -> None:
    """The mutation that survived the first pass, turned into a control.

    The block is interpolated into files adopt must be able to REWRITE
    byte-identically. So it may quote the `.claude/agents/*.md` count — a
    directory adopt never writes into — and nothing else: `AGENTS.md`, the
    Cursor rule, the Copilot file and the `new-model-check` skill are all
    things adopt itself creates, so a block quoting them says something
    different on the second run and the "re-running replaces the block with
    the same bytes" promise is gone.
    """
    from aef.cli.adopt import PromptSurface, render_aef_block

    base = PromptSurface(agents=8)
    for changed in (
        PromptSurface(agents=8, skills=5),
        PromptSurface(agents=8, has_agents_md=True),
        PromptSurface(agents=8, has_copilot_instructions=True),
        PromptSurface(agents=8, cursor_rules=3),
        PromptSurface(agents=8, has_codex_dir=True),
    ):
        assert render_aef_block("repo", "prompt_files", changed) == render_aef_block(
            "repo", "prompt_files", base
        ), f"the block text varies with {changed}"
    # ...and it DOES follow the one signal adopt cannot influence, or it is
    # not saying anything about the repo at all.
    assert render_aef_block("repo", "prompt_files", PromptSurface(agents=3)) != render_aef_block(
        "repo", "prompt_files", base
    )


def test_the_cli_reports_appended_as_a_third_verb(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """`wrote` and `skipped` were the only two words adopt had, and a file
    that gained the block is neither: its own bytes are still there, and the
    adopter's agent now reads the contract. Asserted through the real command
    handler, because that is where the report is produced."""
    from aef.cli.main import build_parser

    (tmp_path / "AGENTS.md").write_text("# mine\n")
    (tmp_path / "AUTONOMY.md").write_text("# my own rules\n")  # skipped, not appended
    args = build_parser().parse_args(["adopt", "--dir", str(tmp_path)])
    assert args.handler(args) == 0
    out = capsys.readouterr().out

    assert f"appended aef block to {tmp_path / 'AGENTS.md'}" in out, out
    assert f"skipped {tmp_path / 'AGENTS.md'}" not in out, "an append reported as a skip"
    assert "wrote " in out and "skipped " in out, "the other two verbs must survive"


def test_the_kit_names_every_wired_harness_and_guesses_at_none(tmp_path: Path) -> None:
    """Four harnesses reach a node's model call (ADR 0112/0154), and an
    adopter picks one in `aef.yaml`. The generated config listed two.

    The Grok number is asserted because it is the honest one: `--cwd <empty
    dir>` is its isolation flag and ~17.9k tokens of the operator's session
    still reach the model with nothing to stop it. A document that named the
    flag and not the leak would be selling isolation it does not have. And
    Copilot is named as `command`, configured by the owner — this repo ships
    no guess about a CLI it has not run (ADR 0150)."""
    run_adopt(tmp_path)
    config = (tmp_path / "aef.yaml").read_text()
    for impl in ("claude_code", "codex", "grok", "anthropic", "command"):
        assert impl in config, impl
    assert "Copilot" in config and "no guess" in config

    sequence = (tmp_path / "FIRST_DAY.md").read_text()
    assert "17.9k tokens" in sequence, "the leak Grok's isolation flag does not close"
    assert "--cwd" in sequence
    assert "not** reproduced" in sequence, "codex's status must not be overstated"


def test_the_generated_entry_files_carry_the_block_they_would_append(tmp_path: Path) -> None:
    """One contract, not four. The block adopt appends to someone else's
    `AGENTS.md` is the same text its own generated `CLAUDE.md` carries — which
    is also what makes a re-run a byte-for-byte replace rather than a second
    append."""
    from aef.cli.adopt import MD_MARKERS, render_aef_block

    run_adopt(tmp_path)
    block = render_aef_block(tmp_path.name, "none")
    for name in ("CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"):
        text = (tmp_path / name).read_text()
        assert block in text, name
        assert text.count(MD_MARKERS[0]) == 1, f"{name} has more than one block"


def test_the_generated_shim_runs_the_graph_aef_migrate_generates(tmp_path: Path) -> None:
    """The shim built a bare `Services()`, and the documented next step is to
    point it at your migrated graph — which since ADR 0143 is wired
    `<call site> -> reflect -> consolidate -> END`. Reflect requires
    critic/judge/memory and consolidate requires knowledge, so the documented
    path raised `ServiceNotConfiguredError: service 'critic'`. Reproduced
    against the shim as GENERATED before the fix (ADR 0148).

    Executed rather than grepped: an assertion that the source names
    `agent_services` would pass on a shim that imported it and never called it.
    """
    from aef.kernel import END, Context, Edge, Graph, Node, Route, Services
    from aef.reasoning.nodes import make_consolidate_node, make_reflect_node
    from aef.state import AEFState, Plan, StateDelta

    run_adopt(tmp_path)
    namespace: dict[str, object] = {}
    exec(compile((tmp_path / "aef_adapter.py").read_text(), "aef_adapter.py", "exec"), namespace)

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        return StateDelta(plan=Plan(goal=state.objective, status="done")), "reflect"

    def build_graph() -> Graph:
        return Graph(
            id="mine",
            version="0.1.0",
            nodes={
                "work": Node(id="work", version="0.1.0", fn=work, deterministic=True),
                "reflect": make_reflect_node(route="consolidate"),
                "consolidate": make_consolidate_node(route=END),
            },
            edges=[
                Edge(from_node="work", to_node="reflect"),
                Edge(from_node="reflect", to_node="consolidate"),
            ],
            entry_node="work",
        )

    namespace["build_graph"] = build_graph
    run_via_aef = namespace["run_via_aef"]
    final = run_via_aef("an ordinary task")  # type: ignore[operator]
    assert final.plan is not None and final.plan.status == "done"
