import hashlib
import re
from pathlib import Path

import pytest

from aef.cli.adopt import (
    GITIGNORE_MARKERS,
    MD_MARKERS,
    AdoptResult,
    detect_framework,
    render_migration_checklist,
    run_adopt,
    signed_begin,
)

# `<!-- aef:begin sha256=... -->`, the only begin marker `aef adopt` writes
# and the only one it will ever replace between (ADR 0172). Spelled out here
# rather than imported from the private helper so the TEST pins the format an
# adopter sees, and a change to it has to be made twice, on purpose.
_SIGNED_BEGIN_RE = re.compile(r"<!-- aef:begin sha256=[0-9a-f]{16} -->")
_SIGNED_GITIGNORE_BEGIN_RE = re.compile(r"# aef:begin sha256=[0-9a-f]{16}")


def signed_begins(text: str, gitignore: bool = False) -> int:
    pattern = _SIGNED_GITIGNORE_BEGIN_RE if gitignore else _SIGNED_BEGIN_RE
    return len(pattern.findall(text))


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
        # The SIGNED begin marker (ADR 0172) — a bare `<!-- aef:begin -->` is
        # something an adopter's own prose may contain, so it can no longer be
        # what identifies adopt's block.
        assert signed_begins(text) == 1, text
        assert "<!-- aef:end -->" in text
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
    assert signed_begins(text) == 1, text
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
    body = "__pycache__/\n*.py[cod]"
    assert f"{signed_begin(GITIGNORE_MARKERS[0], body)}\n{body}\n{GITIGNORE_MARKERS[1]}" in text, (
        text
    )
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
    ADR 0153 is allowed to extend ADR 0034/0040's rule rather than break it.

    The planted stale block is SIGNED (ADR 0172): a signed pair is the only
    thing adopt replaces between, and its signature is over the stale body —
    so this also pins that a *changed* block is still found and replaced."""
    end = MD_MARKERS[1]
    stale = "an ANCIENT aef block"
    begin = signed_begin(MD_MARKERS[0], stale)
    original = f"# My rules\n\nLine one.\n\n{begin}\n{stale}\n{end}\n\nLine two.\n"
    (tmp_path / "AGENTS.md").write_text(original)

    result = run_adopt(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()

    def outside(body: str) -> str:
        start = _SIGNED_BEGIN_RE.search(body).start()  # type: ignore[union-attr]
        stop = body.index(end, start) + len(end)
        return body[:start] + body[stop:]

    assert hashlib.sha256(outside(text).encode()).hexdigest() == (
        hashlib.sha256(outside(original).encode()).hexdigest()
    ), "bytes outside the markers changed"
    assert "an ANCIENT aef block" not in text, "the stale block survived"
    assert "AGENT_INTEGRATION.md" in text
    assert "Line two." in text, "content AFTER the block must survive"
    assert tmp_path / "AGENTS.md" in result.appended_files


_SIGNED_A = signed_begin(MD_MARKERS[0], "a")
_SIGNED_B = signed_begin(MD_MARKERS[0], "b")
_LEGACY_ONE = "<!-- aef:begin -->\n## AEF scaffold (one) — generated section\nx\n<!-- aef:end -->"
_LEGACY_TWO = "<!-- aef:begin -->\n## AEF scaffold (two) — generated section\ny\n<!-- aef:end -->"


@pytest.mark.parametrize(
    "content,why",
    [
        (f"# mine\n{_SIGNED_A}\nhalf a block\n", "a signed begin with no end"),
        (
            f"{_SIGNED_A}\na\n<!-- aef:end -->\n{_SIGNED_B}\nb\n<!-- aef:end -->\n",
            "two signed blocks",
        ),
        (f"# mine\n{_LEGACY_ONE}\n\n{_LEGACY_TWO}\n", "two pre-signature blocks"),
    ],
)
def test_a_file_with_markers_adopt_cannot_resolve_is_skipped_with_the_reason(
    tmp_path: Path, content: str, why: str
) -> None:
    """Guessing where someone else's block ends is how a never-destroy tool
    destroys. Each of these is left exactly as it was, and the skip says why
    rather than reading as "already exists".

    UPDATED DELIBERATELY (ADR 0172): the three shapes are now stated on the
    marker adopt actually WRITES. The unbalanced *bare* shapes that used to be
    here are covered by the fourth case below — they are the adopter's prose,
    and prose is left alone and appended after, not refused."""
    (tmp_path / "AGENTS.md").write_text(content)

    result = run_adopt(tmp_path)

    assert (tmp_path / "AGENTS.md").read_text() == content, why
    assert tmp_path / "AGENTS.md" in result.skipped_files
    assert "refusing to guess" in result.skip_reason(tmp_path / "AGENTS.md"), why


@pytest.mark.parametrize(
    "content,why",
    [
        ("# mine\n<!-- aef:begin -->\nhalf a quotation\n", "a bare begin with no end"),
        ("# mine\nstray\n<!-- aef:end -->\n", "a bare end with no begin"),
        (
            "<!-- aef:begin -->\na\n<!-- aef:end -->\n<!-- aef:begin -->\nb\n<!-- aef:end -->\n",
            "two bare pairs",
        ),
        (
            "# mine\n\nadopt writes a block between <!-- aef:begin --> and\n"
            "**RULE 7: no agent may push to main.**\n"
            "...and closes it with <!-- aef:end --> at the end.\n",
            "a BALANCED bare pair around the adopter's own rule",
        ),
    ],
)
def test_bare_markers_in_the_adopters_prose_are_inert_and_nothing_between_them_is_lost(
    tmp_path: Path, content: str, why: str
) -> None:
    """R2, as a test. `apply_block` used to take the FIRST `<!-- aef:begin -->`
    and the next `<!-- aef:end -->` anywhere in the file and replace everything
    between them. This kit's own documentation teaches those two strings, so an
    adopter's `CLAUDE.md` quoting them — with a house rule in between — had the
    rule deleted, while `aef adopt` printed "your bytes outside it are
    unchanged".

    Reproduced before the fix on a scratch repo: `RULE 7` and `RULE 8` were in
    the file before, `grep -c "RULE 7" CLAUDE.md` returned 0 after.

    A signature makes the difference legible: only `<!-- aef:begin sha256=... -->`
    is adopt's. Everything here is prose, so every byte of it survives and the
    block is appended after it."""
    (tmp_path / "AGENTS.md").write_text(content)

    result = run_adopt(tmp_path)

    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith(content), f"{why}: the adopter's bytes must be a prefix"
    assert signed_begins(text) == 1, f"{why}: exactly one block, appended after the prose"
    assert "AGENT_INTEGRATION.md" in text, why
    assert tmp_path / "AGENTS.md" in result.appended_files, why
    assert tmp_path / "AGENTS.md" not in result.skipped_files, why


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
    from aef.cli.adopt import render_aef_block

    run_adopt(tmp_path)
    block = render_aef_block(tmp_path.name, "none")
    for name in ("CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"):
        text = (tmp_path / name).read_text()
        assert block in text, name
        assert signed_begins(text) == 1, f"{name} has more than one block"


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


# ---------------------------------------------------------------------------
# ADR 0172 — the bytes, the signature, one discovery, and the nightly cycle.
# ---------------------------------------------------------------------------


_CRLF_AGENTS = (
    b"# House rules\r\n"
    b"\r\n"
    b"Our agents read this file.\r\n"
    b"Rule one: be careful.\r\n"
    b"Rule two: never guess.\r\n"
)


def test_a_crlf_entry_file_is_not_rewritten_line_by_line(tmp_path: Path) -> None:
    """R1, as a test, and it is the whole of ADR 0153's argument.

    `Path.read_text()` translates `\\r\\n` to `\\n`; the marker logic was
    byte-exact on the TRANSLATED text; `Path.write_text()` wrote it back with
    `os.linesep`. So on a CRLF `AGENTS.md` every line of the adopter's file
    was rewritten while the CLI printed "your bytes outside it are unchanged".

    Reproduced on a scratch repo before the fix — `git diff --stat` said
    `41 insertions(+), 5 deletions(-)` and every original line was a `-` — and
    after it says `36 insertions(+)` with the original bytes at offset 0.
    """
    (tmp_path / "AGENTS.md").write_bytes(_CRLF_AGENTS)

    result = run_adopt(tmp_path)

    after = (tmp_path / "AGENTS.md").read_bytes()
    assert after.startswith(_CRLF_AGENTS), "the adopter's CRLF lines were rewritten"
    assert after.find(_CRLF_AGENTS) == 0
    assert tmp_path / "AGENTS.md" in result.appended_files
    # ...and the block adopt added is CRLF too, or the file is now mixed.
    added = after[len(_CRLF_AGENTS) :]
    assert added.count(b"\n") == added.count(b"\r\n"), "the added block is not in the file's ending"
    assert signed_begins(after.decode()) == 1


@pytest.mark.parametrize(
    "original,newline,why",
    [
        (b"# mine\nrule one\n", b"\n", "LF"),
        (b"# mine\r\nrule one\r\n", b"\r\n", "CRLF"),
        (b"# mine\r\nrule one\r\nrule two\r\nodd one out\n", b"\r\n", "mixed, CRLF dominant"),
        (b"# mine\nrule one\nrule two\r\n", b"\n", "mixed, LF dominant"),
        (b"# mine\nno trailing newline", b"\n", "no trailing newline, LF"),
        (b"# mine\r\nno trailing newline", b"\r\n", "no trailing newline, CRLF"),
    ],
)
def test_the_block_takes_the_files_own_line_ending_and_every_byte_before_it_survives(
    tmp_path: Path, original: bytes, newline: bytes, why: str
) -> None:
    """The CRLF twin of every byte-preservation assertion, plus the two shapes
    the LF-only fixtures never covered: a mixed file (the majority ending
    wins, and the minority lines are pasted back verbatim rather than
    normalised) and a file with no trailing newline."""
    (tmp_path / "AGENTS.md").write_bytes(original)

    run_adopt(tmp_path)

    after = (tmp_path / "AGENTS.md").read_bytes()
    assert after.startswith(original), f"{why}: the adopter's bytes are not a prefix"
    assert after.find(original) == 0, why
    added = after[len(original) :]
    if newline == b"\r\n":
        assert added.count(b"\n") == added.count(b"\r\n"), why
    else:
        assert b"\r\n" not in added, why


def test_appending_to_a_crlf_file_is_insertions_only_and_git_agrees(tmp_path: Path) -> None:
    """The reproduction's own instrument. A string comparison can be argued
    with; `git diff --numstat` is what an adopter will actually look at, and
    before the fix it read `41  5` on this file."""
    import subprocess

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, text=True, check=False
        )

    (tmp_path / "AGENTS.md").write_bytes(_CRLF_AGENTS)
    (tmp_path / ".gitignore").write_bytes(b"node_modules/\r\n")
    run("init", "-q")
    run("config", "core.autocrlf", "false")
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

    run_adopt(tmp_path)

    numstat = run("diff", "--numstat", "--", "AGENTS.md", ".gitignore").stdout
    assert numstat.strip(), numstat
    for line in numstat.strip().splitlines():
        added, removed, name = line.split("\t")
        assert removed == "0", f"{name}: {removed} line(s) of the adopter's file were removed"
        assert int(added) > 0, name


def test_the_never_destroy_rule_is_checked_in_code_before_anything_is_written() -> None:
    """ADR 0153 argued that appending is not overwriting because "every
    pre-existing byte survives verbatim". On a CRLF file that was false, and
    nothing in the code would have noticed. This is the same claim as an
    executable check: the prefix and the suffix of the original must both
    still be there, at the same ends, or the write is refused."""
    from aef.cli.adopt import _verify_preserved

    prefix, suffix = b"# mine\r\n", b"\r\ntail\r\n"
    assert _verify_preserved(prefix, suffix, prefix + b"BLOCK" + suffix)
    assert not _verify_preserved(prefix, suffix, b"# mine\nBLOCK" + suffix), "LF-ised prefix"
    assert not _verify_preserved(prefix, suffix, prefix + b"BLOCK"), "the suffix was dropped"
    assert not _verify_preserved(prefix, suffix, b"BLOCK" + suffix), "the prefix was dropped"
    # and a result too short to contain both, even though it starts and ends right
    assert not _verify_preserved(b"aa", b"aa", b"aaa")


def test_adopt_never_reads_or_writes_a_file_through_a_newline_translating_api() -> None:
    """`Path.read_text()` translates line endings on the way in and
    `Path.write_text()` writes `os.linesep` on the way out. Both are wrong for
    a tool whose contract is that the adopter's bytes are untouched, and the
    second is the mirror of R1 on Windows: every file this scaffold generates
    would be CRLF there while its own tests compare against LF.

    An AST scan rather than a review note, for the same reason
    `tests/test_vendor_isolation.py` is one."""
    import ast

    import aef.cli.adopt as module

    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    offenders = [
        f"line {node.lineno}: .{node.func.attr}()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_text", "write_text"}
    ]
    assert offenders == [], f"aef/cli/adopt.py translates newlines: {offenders}"


def test_a_pre_signature_block_is_upgraded_once_in_place_and_the_adopter_is_told(
    tmp_path: Path,
) -> None:
    """The decision ADR 0172 had to make: a block written before the marker
    carried a signature is adopt's, and it is MIGRATED once rather than
    refused — because treating it as prose would leave the stale block in
    place and append a second one, and two contradicting copies of the
    contract in the file the repo's agents read is the worse failure.

    It is recognised only by its first line, which is a line
    `render_aef_block_body` emits — so a quotation is never mistaken for one
    — and the upgrade is announced in the checklist."""
    legacy = (
        "# My rules\n\n"
        "<!-- aef:begin -->\n"
        "## AEF scaffold (old) — generated section\n"
        "an ANCIENT aef block\n"
        "<!-- aef:end -->\n\n"
        "Line after.\n"
    )
    (tmp_path / "AGENTS.md").write_text(legacy)

    result = run_adopt(tmp_path)

    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# My rules\n\n"), "the adopter's bytes moved"
    assert text.endswith("\n\nLine after.\n"), "content after the block must survive"
    assert "an ANCIENT aef block" not in text, "the stale block survived"
    assert signed_begins(text) == 1, text
    assert tmp_path / "AGENTS.md" in result.upgraded_blocks
    told = [item for item in result.checklist if "pre-signature" in item]
    assert told, result.checklist
    assert "AGENTS.md" in told[0], told[0]
    assert "pre-signature" in (tmp_path / "AEF_MIGRATION_CHECKLIST.md").read_text()

    # ...and ONCE: the second run finds a signed block and replaces between it.
    again = run_adopt(tmp_path)
    assert again.upgraded_blocks == []
    assert [item for item in again.checklist if "pre-signature" in item] == []


def test_an_m2_format_entry_file_is_still_recognised_as_adopts_own_output(tmp_path: Path) -> None:
    """The transition property, and it is about a COUNT rather than a block.

    `_is_adopt_generated` is what stops adopt counting the `AGENTS.md` it
    wrote as the adopter's prompt surface. Keyed on the signed marker alone it
    would answer "not ours" for one run on every repo already adopted under
    the ADR 0153 format, and the detection line — which ADR 0153 asserts is
    identical on both runs — would gain a signal and then lose it."""
    from aef.cli.adopt import _is_adopt_generated

    m2 = (
        "# somerepo — agent instructions (aef-core)\n\n"
        "<!-- aef:begin -->\n"
        "## AEF scaffold (somerepo) — generated section\n\nbody\n"
        "<!-- aef:end -->\n"
    )
    (tmp_path / "AGENTS.md").write_text(m2)
    assert _is_adopt_generated(tmp_path / "AGENTS.md"), "an M2-format block stopped being ours"

    # ...and the adopter's own file that merely QUOTES the markers is still theirs.
    (tmp_path / "other.md").write_text(
        "# somerepo — agent instructions (aef-core)\n\n"
        "adopt writes <!-- aef:begin --> ... <!-- aef:end --> around its section.\n"
    )
    assert not _is_adopt_generated(tmp_path / "other.md")


def test_the_signature_is_over_the_block_body_so_a_rerun_reproduces_it() -> None:
    """What makes a signed marker idempotent rather than a nonce: it is a
    function of the block it opens, so rendering the same block twice writes
    the same marker byte for byte, and `aef adopt` reports
    `already carries the current aef block` rather than rewriting."""
    body = "## AEF scaffold (x) — generated section\n\nbody text"
    marker = signed_begin(MD_MARKERS[0], body)
    assert marker == signed_begin(MD_MARKERS[0], body)
    assert marker != signed_begin(MD_MARKERS[0], body + "!")
    assert marker == f"<!-- aef:begin sha256={hashlib.sha256(body.encode()).hexdigest()[:16]} -->"
    assert signed_begin(GITIGNORE_MARKERS[0], body).startswith("# aef:begin sha256=")


def _nested_prompt_repo(root: Path) -> None:
    agents = root / ".claude" / "agents"
    (agents / "sub").mkdir(parents=True)
    for name in ("alpha", "beta"):
        (agents / f"{name}.md").write_text(f"---\nname: {name}\n---\n{name}.\n")
    (agents / "sub" / "gamma.md").write_text("---\nname: gamma\n---\ngamma.\n")


def test_adopt_and_migrate_agree_on_the_number_of_prompt_agents(tmp_path: Path) -> None:
    """R4. `aef migrate`'s discovery is RECURSIVE, and that was measured
    against the Claude Code CLI (ADR 0152) — a flat glob migrates some of an
    adopter's agents and silently leaves the organised ones behind. Adopt
    globbed one level, so on a repo with one nested persona adopt said `2` in
    the detection line, the checklist AND the appended block while migrate
    wrote 3 graphs.

    Fixed by importing migrate's discovery rather than reimplementing it:
    one discovery, one number."""
    from aef.cli.adopt import detect_prompt_surface
    from aef.cli.migrate import discover_prompt_agents

    _nested_prompt_repo(tmp_path)

    assert detect_prompt_surface(tmp_path).agents == len(discover_prompt_agents(tmp_path)) == 3

    result = run_adopt(tmp_path)
    assert "3 agents" in result.detection(), result.detection()
    assert [i for i in result.checklist if "3 prompt agents" in i], result.checklist
    assert "3 under `.claude/agents/`" in (tmp_path / "AGENTS.md").read_text()


def test_adopt_still_does_not_count_its_own_skill_after_reusing_migrates_discovery(
    tmp_path: Path,
) -> None:
    """The exclusion that has to survive the shared discovery: `aef adopt`
    writes `.claude/skills/new-model-check/SKILL.md` itself, and counting it
    would make the numbers differ between run 1 and run 2.

    `aef migrate`'s own skills count does NOT apply this exclusion — measured
    5 from adopt against 6 from migrate on the same tree after adoption. That
    is migrate's to mirror; it is reported in ADR 0172 rather than fixed here,
    because this worker does not own `aef/cli/migrate.py`."""
    from aef.cli.adopt import _ADOPT_SKILL_PATH, detect_prompt_surface
    from aef.cli.migrate import discover_skills

    _nested_prompt_repo(tmp_path)
    for name in ("one", "two"):
        (tmp_path / ".claude" / "skills" / name).mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / name / "SKILL.md").write_text(f"# {name}\n")

    run_adopt(tmp_path)

    assert detect_prompt_surface(tmp_path).skills == 2, "adopt counted its own skill"
    assert _ADOPT_SKILL_PATH in discover_skills(tmp_path), "the skill adopt writes"
    assert len(discover_skills(tmp_path)) == 3, "migrate counts adopt's own — reported, not fixed"


def test_the_generated_config_names_the_shadow_containment_default(tmp_path: Path) -> None:
    """`shadow.containment` exists, defaults to `auto`, and `auto` REFUSES
    rather than downgrading when there is no runtime or no image — a default
    an adopter cannot discover from the config they were handed is a default
    they meet as a refusal instead."""
    from aef.config.loader import load_agent_config
    from aef.config.schema import CONTAINMENT_MODES

    run_adopt(tmp_path)
    text = (tmp_path / "aef.yaml").read_text()

    assert "# shadow:" in text, text
    assert "#   containment: auto" in text, text
    for mode in CONTAINMENT_MODES:
        assert mode in text, mode
    assert "ADR 0161" in text
    # commented out, so the template still loads and still means `auto`
    assert load_agent_config(tmp_path / "aef.yaml").shadow.containment == "auto"


# --- R3/S1: the nightly workflow ------------------------------------------


def _monitor_workflow(root: Path) -> dict[str, object]:
    import yaml

    parsed = yaml.safe_load((root / ".github/workflows/loop-monitor.yml").read_text())
    assert isinstance(parsed, dict)
    return parsed


def _steps(document: dict[str, object]) -> list[dict[str, object]]:
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    return list(jobs["monitor"]["steps"])


@pytest.mark.parametrize("workflow", ["loop-monitor.yml", "loop-gate.yml"])
def test_the_emitted_workflows_scope_the_loop_state_cache_to_the_run(
    tmp_path: Path, workflow: str
) -> None:
    """S1. `actions/cache` skips its post-job SAVE on an exact key hit, so a
    constant `key: loop-state-${{ github.repository }}` means run 1 populates
    the cache and no run after it ever writes one: the ledger, `cycles.jsonl`
    and the archive reset to run 1's contents every night, and ADR 0165's
    `SCHEDULED CYCLE PRODUCING NOTHING` warning — which needs three
    consecutive journalled cycles — could never see two.

    Not executed: this is YAML for a scheduler this suite cannot run, so what
    is asserted is that the key varies per run and that a prefix restore-key
    loads the previous run's state."""
    import yaml

    _adopt(tmp_path)
    document = yaml.safe_load((tmp_path / ".github/workflows" / workflow).read_text())
    job = next(iter(document["jobs"].values()))
    caches = [step for step in job["steps"] if "actions/cache" in str(step.get("uses", ""))]
    assert caches, workflow
    for step in caches:
        key = step["with"]["key"]
        assert "${{ github.run_id }}" in key, f"{workflow}: constant cache key {key!r} never saves"
        restore = step["with"]["restore-keys"]
        assert "loop-state-${{ github.repository }}-" in restore, workflow
        assert "${{ github.run_id }}" not in restore, "a run-scoped restore key restores nothing"


def test_the_nightly_cycle_never_defaults_to_the_placeholder_that_raises(tmp_path: Path) -> None:
    """R3(a). `aef migrate` writes `agents/migrated/graph.py` — whose
    `build_graph()` raises `NotImplementedError` — in every repo with no
    wrappable call site, which is every prompt-file repo. A workflow whose
    `AEF_MODULE` defaults to it names a module that EXISTS and cannot build.

    Where adopt can know the answer it names it: the first prompt agent's
    module, derived from migrate's own discovery and sanitiser."""
    from aef.cli.adopt_loop import PLACEHOLDER_MODULE

    _nested_prompt_repo(tmp_path)
    _adopt(tmp_path)

    cycle = [s for s in _steps(_monitor_workflow(tmp_path)) if s.get("name") == "Daily cycle"][0]
    module = cycle["env"]["AEF_MODULE"]
    assert module != PLACEHOLDER_MODULE, "the nightly cycle names the placeholder that raises"
    assert module == "agents.migrated.alpha.graph", module
    assert cycle["env"]["AEF_ENTRYPOINT"] == f"{module}:build_graph"


def test_a_repo_with_no_prompt_agents_still_gets_the_guard_rather_than_a_silent_placeholder(
    tmp_path: Path,
) -> None:
    """Adopt cannot invent a module for a repo whose agents it cannot see. It
    keeps the placeholder as the *editable* value and relies on the guard step
    to fail the job by name until the owner replaces it — which is the
    difference between a cron job that says what is wrong and one that is
    green having done nothing."""
    from aef.cli.adopt_loop import PLACEHOLDER_MODULE

    _adopt(tmp_path)
    steps = _steps(_monitor_workflow(tmp_path))
    cycle = [s for s in steps if s.get("name") == "Daily cycle"][0]
    assert cycle["env"]["AEF_MODULE"] == PLACEHOLDER_MODULE
    guard = [s for s in steps if str(s.get("name", "")).startswith("The graph")]
    assert guard, [s.get("name") for s in steps]
    assert steps.index(guard[0]) < steps.index(cycle), "the guard must run BEFORE the cycle"
    assert PLACEHOLDER_MODULE in guard[0]["run"], "the guard does not know the placeholder"


def _guard_script(root: Path) -> tuple[str, str]:
    """The rendered guard step's python body and its `AEF_MODULE`, extracted
    from the YAML the adopter would commit — not from a Python string this
    test happens to have."""
    import re as _re

    guard = [
        s for s in _steps(_monitor_workflow(root)) if str(s.get("name", "")).startswith("The graph")
    ][0]
    body = _re.search(r"python - <<'PY'\n(.*?)\n\s*PY", str(guard["run"]), _re.S)
    assert body is not None, guard["run"]
    import textwrap

    return textwrap.dedent(body.group(1)), str(guard["env"]["AEF_MODULE"])


def test_the_rendered_cycle_reads_as_a_healthy_rejection_and_the_guard_is_what_stops_it(  # type: ignore[no-untyped-def]
    tmp_path: Path, capsys
) -> None:
    """R3(b), executed rather than argued.

    The rendered workflow fails the job only on `status >= 2`. A module whose
    `build_graph()` raises reaches `main()`'s catch-all, which returns 1 —
    `EXIT_REJECTED`, an ordinary candidate rejection — so the nightly job is
    GREEN on a repo whose graph cannot be built, every night, with no journal
    entry. Reproduced: `aef loop cycle ... --module agents.migrated.graph`
    exited 1 with `error: aef migrate found no wrappable call site in this
    repo`.

    The exit constants are read from `aef.harness.loop` AT TEST TIME, so this
    stays correct whether or not a distinct `EXIT_ERROR` has landed: if one
    exists and the CLI returns it, the workflow's own rule already fails; if
    not, the guard step is what fails the job, and it is asserted either way.
    """
    import importlib
    import os
    import subprocess
    import sys

    from aef.cli.main import main
    from aef.harness import loop as loop_module

    _nested_prompt_repo(tmp_path)
    _adopt(tmp_path)
    graph = tmp_path / "agents" / "migrated" / "alpha" / "graph.py"
    graph.parent.mkdir(parents=True)
    for package in (tmp_path / "agents", tmp_path / "agents/migrated", graph.parent):
        (package / "__init__.py").write_text("")
    graph.write_text(
        "def build_graph():\n"
        "    raise NotImplementedError('aef migrate found no wrappable call site in this repo')\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True, capture_output=True)
    memory = tmp_path / "memory.jsonl"
    memory.write_text(
        '{"kind": "failure", "run_id": "r1", "verbal_feedback": "it ignored the deadline"}\n'
    )

    argv = [
        "loop",
        "cycle",
        "--repo",
        str(tmp_path),
        "--state",
        # Outside the repo: G1a made every --state subcommand refuse an in-repo
        # state dir (ADR 0167), and this test met that refusal before its own.
        str(tmp_path.parent / f"{tmp_path.name}-state"),
        "--workdir",
        str(tmp_path / "work"),
        "--module",
        "agents.migrated.alpha.graph",
        "--entrypoint",
        "agents.migrated.alpha.graph:build_graph",
        "--corpus",
        str(tmp_path / "corpus"),
        "--config",
        str(tmp_path / "aef.yaml"),
        "--memory",
        str(memory),
        "--cassette-miss",
        "fail",
        "--build-command",
        "true",
    ]

    def _forget_agents_package() -> None:
        # This repo has an `agents/` package of its own and other tests import
        # it, so a cached module would win over the adopted repo's. Purge
        # before AND after, or this test passes or fails on run order.
        for name in [m for m in list(sys.modules) if m.split(".")[0] == "agents"]:
            del sys.modules[name]

    here = os.getcwd()
    _forget_agents_package()
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    try:
        os.chdir(tmp_path)
        code = main(argv)
    finally:
        os.chdir(here)
        sys.path.remove(str(tmp_path))
        _forget_agents_package()
        importlib.invalidate_caches()

    # The exit code must be the one the RAISING MODULE produced, not some
    # other refusal that happens to share it — a test that cannot tell those
    # apart pins nothing.
    stderr = capsys.readouterr().err
    assert "no wrappable call site" in stderr, stderr

    error_code = getattr(loop_module, "EXIT_ERROR", None)
    fails_the_job = code >= loop_module.EXIT_HALTED
    if error_code is not None and code == error_code:
        assert fails_the_job, "EXIT_ERROR must be a code the workflow's `status >= 2` rule fails on"
    else:
        assert code == loop_module.EXIT_REJECTED, code
        assert not fails_the_job, "this test's premise — 1 reads as a healthy rejection — is gone"

    # ...and the guard, run exactly as the runner would, refuses first.
    script, module = _guard_script(tmp_path)
    guarded = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "AEF_MODULE": module, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert guarded.returncode != 0, "the guard let a graph that cannot build through"
    assert "does not build" in guarded.stderr, guarded.stderr
    # R3(c): the CAUSE, not migrate's call-site sentence.
    assert "NotImplementedError" in guarded.stderr, guarded.stderr
    assert "AEF_MODULE" in guarded.stderr, guarded.stderr


def test_the_guard_passes_once_the_named_module_actually_builds(tmp_path: Path) -> None:
    """A guard that cannot pass is a guard nobody keeps. Same repo, a
    `build_graph()` that returns instead of raising."""
    import os
    import subprocess
    import sys

    _nested_prompt_repo(tmp_path)
    _adopt(tmp_path)
    graph = tmp_path / "agents" / "migrated" / "alpha" / "graph.py"
    graph.parent.mkdir(parents=True)
    for package in (tmp_path / "agents", tmp_path / "agents/migrated", graph.parent):
        (package / "__init__.py").write_text("")
    graph.write_text("def build_graph():\n    return object()\n")

    script, module = _guard_script(tmp_path)
    guarded = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "AEF_MODULE": module, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert guarded.returncode == 0, guarded.stderr


def test_the_cycle_summary_says_what_the_exit_code_MEANS(tmp_path: Path) -> None:
    """R3(c). A nightly job whose summary is `(exit 1)` has told the reader a
    number. `escalated`, `nothing to propose`, `rejected` and `the cycle
    raised` are four different nights.

    Every branch is asserted, not just the interesting ones: a mutation that
    emptied the exit-0 arm survived the first version of this test, because
    the arm nobody asserts is the arm the workflow is green on."""
    import re as _re

    _adopt(tmp_path)
    cycle = [s for s in _steps(_monitor_workflow(tmp_path)) if s.get("name") == "Daily cycle"][0]
    run = str(cycle["run"])
    arms = dict(_re.findall(r'\n\s+(\d|\*)\)\s+meaning="([^"]*)"', run))
    assert set(arms) == {"0", "1", "2", "3", "*"}, arms
    assert all(text.strip() for text in arms.values()), arms
    assert "escalated" in arms["0"] and "nothing to propose" in arms["0"], arms["0"]
    assert "REJECTED" in arms["1"], arms["1"]
    assert "HALTED" in arms["2"], arms["2"]
    # 3 is EXIT_ERROR (ADR 0167 §6), chosen over reusing 2 precisely because a
    # crash's remedy — fix the invocation — is not a halt's — clear the kill
    # switch. It was reaching the reader as "HALTED" anyway (ADR 0178).
    assert "HALTED" not in arms["3"], arms["3"]
    assert "ERROR" in arms["3"] and "crashed" in arms["3"], arms["3"]
    assert "kill switch" in arms["2"] and "kill switch" in arms["3"], arms
    assert arms["2"] != arms["3"], "a halt and a crash must not read the same"
    assert "raised" in arms["*"], "an exception must not read as a verdict"
    assert "GITHUB_STEP_SUMMARY" in run


def test_the_exit_code_case_is_shell_that_maps_every_code(tmp_path: Path) -> None:
    """The arms are ASSERTED as text above and EXECUTED here, because a `case`
    that does not parse maps nothing at all and a text assertion cannot tell."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash exists on every runner here
        pytest.skip("no bash")

    _adopt(tmp_path)
    cycle = [s for s in _steps(_monitor_workflow(tmp_path)) if s.get("name") == "Daily cycle"][0]
    run = str(cycle["run"])
    case = run[run.index('case "$status"') : run.index("esac") + 4]
    seen = {}
    for status in (0, 1, 2, 3, 9):
        done = subprocess.run(
            [bash, "-c", f'status={status}\n{case}\nprintf "%s" "$meaning"'],
            capture_output=True,
            text=True,
            check=True,
        )
        seen[status] = done.stdout
    assert "HALTED" in seen[2] and "HALTED" not in seen[3], seen
    assert "ERROR" in seen[3], seen
    assert len({seen[0], seen[1], seen[2], seen[3]}) == 4, seen
    assert seen[9] == seen[9].replace("$status", ""), "the fallback must interpolate the code"
    assert "9" in seen[9], seen[9]


def test_the_failure_step_does_not_call_a_crash_a_halt(tmp_path: Path) -> None:
    """`Surface a halt` fired on `if: failure()` and printed
    `## Self-rewiring loop HALTED` for exit 3 — a crash, for which there is no
    kill switch to clear. It is the summary an owner reads first, so it named
    the wrong remedy for the failure most likely to repeat (ADR 0178)."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash exists on every runner here
        pytest.skip("no bash")

    _adopt(tmp_path)
    steps = _steps(_monitor_workflow(tmp_path))
    cycle = [s for s in steps if s.get("name") == "Daily cycle"][0]
    assert 'echo "$status" > "$RUNNER_TEMP/cycle.status"' in str(cycle["run"]), (
        "the failure step cannot tell a halt from a crash unless the code is recorded"
    )

    failing = [s for s in steps if s.get("if") == "failure()"]
    assert len(failing) == 1, [s.get("name") for s in failing]
    (surface,) = failing
    body = str(surface["run"])
    body = body[: body.index("aef loop status")]

    printed = {}
    for status in ("2", "3", ""):
        script = body.replace(
            'status=$(cat "$RUNNER_TEMP/cycle.status" 2>/dev/null || echo "")',
            f'status="{status}"',
        )
        done = subprocess.run(
            [bash, "-c", f"GITHUB_STEP_SUMMARY=/dev/stdout\n{script}"],
            capture_output=True,
            text=True,
            check=True,
        )
        printed[status] = done.stdout

    assert "HALTED" in printed["2"], printed["2"]
    assert "HALTED" not in printed["3"], printed["3"]
    assert "ERROR" in printed["3"] and "crashed" in printed["3"], printed["3"]
    assert "NOT a halt" in printed["3"], printed["3"]
    # The two remedies, and they are different sentences.
    assert "HALTED to resume" in printed["2"], printed["2"]
    assert "fix" in printed["3"] and "invocation" in printed["3"], printed["3"]
    # A failure with no cycle code is neither — some other step broke.
    assert "HALTED" not in printed[""] and "FAILED" in printed[""], printed[""]
