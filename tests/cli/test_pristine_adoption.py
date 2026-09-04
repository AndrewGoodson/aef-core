"""What `aef adopt` leaves you with, before anyone touches it.

`test_adoption_sequence.py` hand-writes `agents/mine/graph.py` and
`tests/test_smoke.py` into its fixture — **the two preconditions a real
`aef adopt` output lacks.** That is legitimate for testing the loop, which
needs an agent to run, but it meant the guard for the adoption path was
validating a hand-repaired copy of the thing it guards. Five defects survived
a 984-test suite behind that fixture (ADR 0079).

These tests take the output unmodified. Everything asserted here is something
an adopter hits within their first five minutes.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from aef.cli.main import build_parser
from aef.harness import preflight

_PLACEHOLDER = re.compile(r"<[^>]+>")


def _commands(path: Path) -> list[list[str]]:
    """Every `aef ...` invocation in a generated document, with placeholders
    substituted rather than skipped.

    Skipping any line containing `<...>` skipped every command that takes an
    argument — which is every command whose flags could be wrong.
    """
    joined = path.read_text().replace("\\\n", " ")
    out: list[list[str]] = []
    for raw in joined.splitlines():
        line = raw.strip().lstrip("$ ")
        if not line.startswith("aef ") or line.rstrip().endswith("..."):
            continue
        line = _PLACEHOLDER.sub("PLACEHOLDER", line).replace('"..."', '"placeholder"')
        if "..." in line:
            continue
        try:
            out.append(shlex.split(line)[1:])
        except ValueError:  # unbalanced quotes in prose, not a command
            continue
    return out


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def pristine(tmp_path: Path) -> Path:
    """`aef adopt` output with NOTHING added. No agent, no tests, no
    pyproject — exactly what an adopter has after step one."""
    repo = tmp_path / "adoptee"
    repo.mkdir()
    (repo / "README.md").write_text("# mine\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    from aef.cli.adopt import run_adopt

    run_adopt(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", *args], cwd=repo, capture_output=True, text=True)


def test_doctor_passes_on_untouched_adopt_output(pristine: Path) -> None:
    """It exited 1 on a pristine repo while the kit says "fix any [FAIL]",
    and the only fix was hand-writing a file the tool should have produced."""
    result = _run(pristine, "aef.cli.main", "doctor", "--dir", ".")
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_generated_repo_passes_the_lint_the_kit_prescribes(pristine: Path) -> None:
    """`aef adopt` generated a repo that failed `ruff check .` — the command
    `aef adopt` itself tells you to run. `--isolated` because an adopting repo
    has no ruff config, so ruff's own defaults are what apply."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "."],
        cwd=pristine,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_adapter_shim_is_valid_python(pristine: Path) -> None:
    """`aef doctor` promised to confirm imports were wired and never looked at
    the adapter at all."""
    compile((pristine / "aef_adapter.py").read_text(), "aef_adapter.py", "exec")


def test_loop_doctor_reports_all_six_and_exits_nonzero(pristine: Path) -> None:
    """The adopter's first useful command. It must name every obligation at
    once — discovering them one refusal at a time, in the worst order, is the
    problem it exists to solve (ADR 0073).

    It asserted FIVE while `preflight` declared six (ADR 0137's `model calls
    visible`), so the one obligation an adopter cannot discover by being stuck
    could have vanished silently. The list below is derived from `preflight`
    itself, not typed out again, so the next obligation cannot repeat it."""
    result = _run(
        pristine,
        "aef.cli.main",
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(pristine.parent / "loop-state"),
        "--corpus",
        "corpus",
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert result.returncode != 0, "unmet obligations must not read as ready"
    declared = set(re.findall(r'name="([^"]+)"', Path(preflight.__file__).read_text()))
    assert len(declared) == 6, f"preflight declares {sorted(declared)}; update this test"
    for obligation in declared:
        assert obligation in result.stdout, obligation
    # ...and that they do NOT read as a refusal the loop enforces (ADR 0141).
    assert "ADVISORY" in result.stdout, result.stdout


def test_pytest_exits_five_and_the_docs_say_so(pristine: Path) -> None:
    """A fresh adoptee has no tests, so the FIRST command of the prescribed
    green bar exits 5. That is not a bug — it is the bar telling the truth —
    but the docs prescribed it with no warning, so it read as a broken repo
    (ADR 0079 F13, ADR 0083)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=pristine, capture_output=True, text=True
    )
    assert result.returncode == 5, f"expected 'no tests collected', got {result.returncode}"

    for name in ("AGENT_INTEGRATION.md", "AUTONOMY.md"):
        assert "exit 5 = no tests collected" in (pristine / name).read_text(), name


def test_the_kit_does_not_prescribe_installing_this_repo(pristine: Path) -> None:
    """`pip install -e ".[dev]"` installs the ADOPTER's package, not aef, and
    fails outright when there is no pyproject.toml — which `aef adopt` does
    not write."""
    assert not (pristine / "pyproject.toml").exists(), "the fixture must stay pristine"
    text = (pristine / "AGENT_INTEGRATION.md").read_text()
    assert 'pip install -e ".[dev]"' not in text
    assert "pip install aef-core" in text


def test_every_emitted_aef_command_is_one_the_cli_accepts(pristine: Path) -> None:
    """Three defects have been "a generated document prints a command the CLI
    rejects" (#10, #18, #27). Asserted here against the files as WRITTEN, not
    against the templates that produce them."""
    parser = build_parser()
    checked = 0
    for name in ("FIRST_DAY.md", "LOOP.md", "corpus/README.md", "AGENT_INTEGRATION.md"):
        for argv in _commands(pristine / name):
            parser.parse_args(argv)  # raises SystemExit if the CLI would refuse
            checked += 1
    # Skipping placeholder-bearing lines instead of substituting into them left
    # 3 commands checked out of 16, and the three that survived were the ones
    # with no arguments worth getting wrong. A coverage floor keeps that from
    # silently happening again.
    # 15 -> 30 with FIRST_DAY.md (ADR 0148), whose whole point is that every
    # command in it was executed. A floor, not an equality: documents grow.
    assert checked >= 30, f"only {checked} commands checked — the extractor is skipping too much"


def test_the_command_extractor_detects_a_command_the_cli_rejects(
    pristine: Path, tmp_path: Path
) -> None:
    """The planted fault for the test above. An extractor that quietly matched
    nothing would pass it and prove nothing — this is the third time in this
    program a detector needed its own control (ADR 0063, 0073, 0077)."""
    doc = tmp_path / "planted.md"
    doc.write_text("aef loop bless --nonexistent-flag\n")
    parser = build_parser()
    commands = _commands(doc)
    assert commands, "the extractor did not even find the planted command"
    with pytest.raises(SystemExit):
        for argv in commands:
            parser.parse_args(argv)


def test_the_first_git_add_dash_a_does_not_spend_the_drift_budget_on_bytecode(
    pristine: Path, tmp_path: Path
) -> None:
    """E1 (ADR 0142), end to end on unmodified `aef adopt` output.

    `aef adopt` wrote no `.gitignore`, so an ordinary `git add -A` on day one
    committed `agents/**/__pycache__/*.pyc` into **Zone A**. That bytecode is
    absent from the tree `aef loop bless` archived, so G5's
    `structural_drift(baseline, candidate)` charges every line of it:
    **0.4675 of the 0.500 budget** for a ONE-LINE candidate, measured, against
    **0.0238** for the same candidate with the bytecode excluded — 35 of 36
    differing lines were `.pyc`. Two consecutive drift rejections halt the
    loop, so that is two candidates from a halt caused by nothing the agent
    did.

    Asserted through the harness's own `bless` archive and `structural_drift`,
    on a real git history, rather than against hand-built dicts: the defect
    lived in the join between "what git tracks" and "what the gate compares".
    """
    import subprocess

    from aef.harness import archive
    from aef.harness.gates.g5_rate_drift import DEFAULT_MAX_DRIFT, structural_drift
    from aef.harness.git import GitRepo
    from aef.harness.zones import DEFAULT_AGENT_ROOT

    state = tmp_path / "loop-state"
    agent_dir = pristine / DEFAULT_AGENT_ROOT / "mine"
    agent_dir.mkdir(parents=True)
    (pristine / DEFAULT_AGENT_ROOT / "__init__.py").write_text("")
    (agent_dir / "__init__.py").write_text("")
    (agent_dir / "graph.py").write_text(
        "RETRY_BUDGET = 3\n\n\ndef build_graph() -> int:\n    return RETRY_BUDGET\n"
    )
    _git(pristine, "add", "-A")
    _git(pristine, "commit", "-qm", "my agent")

    blessed = _run(
        pristine,
        "aef.cli.main",
        "loop",
        "bless",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-path",
        f"{DEFAULT_AGENT_ROOT}/mine/graph.py",
    )
    assert blessed.returncode == 0, blessed.stdout + blessed.stderr

    # Day one, verbatim: run something (which compiles the agent), then stage
    # everything. This is the step that used to commit the bytecode.
    compiled = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", DEFAULT_AGENT_ROOT],
        cwd=pristine,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    assert list((agent_dir / "__pycache__").glob("*.pyc")), "compileall wrote no bytecode"
    _git(pristine, "add", "-A")
    # `--allow-empty` because with the fix in place there is nothing to stage:
    # the bytecode is ignored. Without it, `git commit` would fail here for
    # the right reason and the assertions below would never run.
    _git(pristine, "commit", "-qm", "day one", "--allow-empty")

    # ...and a one-line candidate on top, the shape the proposer emits.
    _git(pristine, "checkout", "-q", "-b", "cand")
    source = agent_dir / "graph.py"
    source.write_text(source.read_text().replace("RETRY_BUDGET = 3", "RETRY_BUDGET = 4"))
    _git(pristine, "add", "--", f"{DEFAULT_AGENT_ROOT}/mine/graph.py")
    _git(pristine, "commit", "-qm", "candidate")

    repo = GitRepo(root=pristine)
    graph_id = next(p.name for p in (state / "archive").iterdir() if p.is_dir())
    baseline = archive.read_files(
        state / "archive", graph_id, archive.versions(state / "archive", graph_id)[0]
    )
    paths = sorted(repo.list_tree("cand", DEFAULT_AGENT_ROOT))
    candidate = {p: repo.run_bytes("show", f"cand:{p}") for p in paths}

    assert [p for p in paths if p.endswith(".pyc")] == [], (
        f"bytecode is tracked in Zone A: {paths}. G5 charges it as drift the candidate "
        f"did not cause — 0.4675 of {DEFAULT_MAX_DRIFT} when this was last measured."
    )
    drift = structural_drift(baseline, candidate)
    assert drift < 0.10, (
        f"a one-line candidate drifted {drift:.4f} of {DEFAULT_MAX_DRIFT}; it measured "
        f"0.4675 with committed bytecode and 0.0238 without (ADR 0142)"
    )


def test_the_doctor_help_names_the_number_of_obligations_it_reports() -> None:
    """K1 added a sixth obligation and the `--help` text still said five —
    the same two-numbers-nobody-compares drift ADR 0091 records, in the
    string an adopter reads first. Derived from `preflight`, so the next
    obligation cannot make it wrong again."""
    import re

    from aef.cli import loop as loop_cli
    from aef.harness import preflight

    names = set(re.findall(r'name="([^"]+)"', Path(preflight.__file__).read_text()))
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
    help_text = Path(loop_cli.__file__).read_text()
    assert f"report all {words[len(names)]} loop obligations" in help_text, (
        f"preflight declares {len(names)} obligations {sorted(names)}; "
        f"`loop doctor --help` names a different number"
    )


# ---------------------------------------------------------------------------
# FIRST_DAY.md (ADR 0148) — the sequence, written from a terminal.
# ---------------------------------------------------------------------------


def test_first_day_ships_with_the_scaffold(pristine: Path) -> None:
    """It is the only document that says what to run TODAY and in what order.
    `CLAUDE.md`, `AGENT_INTEGRATION.md`, `LOOP.md` and `AUTONOMY.md` each
    describe a part; none of them was a sequence."""
    text = (pristine / "FIRST_DAY.md").read_text()
    assert text.startswith("# Your first day with AEF"), text[:80]
    # Every command in it, in order, and the CLI accepts each — pinned by
    # `test_every_emitted_aef_command_is_one_the_cli_accepts` above.
    for command in (
        "aef adopt",
        "aef migrate",
        "aef loop bootstrap",
        "aef loop record",
        "aef loop bless",
        "aef loop doctor",
        "aef loop cycle",
    ):
        assert command in text, command
    # The kit points at it, or nobody reads it.
    assert "FIRST_DAY.md" in (pristine / "AGENT_INTEGRATION.md").read_text()
    assert "FIRST_DAY.md" in (pristine / "LOOP.md").read_text()
    assert "FIRST_DAY.md" in (pristine / "AEF_MIGRATION_CHECKLIST.md").read_text()


def test_first_day_names_the_two_bootstrap_flags_nothing_else_did(pristine: Path) -> None:
    """`--memory` and `--config` were reachable only by reading the argument
    parser: `--config` had been there since ADR 0138 while ADR 0139 concluded
    a model-calling graph "cannot get its first corpus", and `--memory` landed
    in ADR 0145 with every generated document still saying bootstrap could not
    supply the failing run's evidence. A flag nobody is pointed at is not a
    feature."""
    text = (pristine / "FIRST_DAY.md").read_text()
    assert "--memory" in text and "--config" in text
    # The flag's PURPOSE, not just its spelling: a mutation that deleted the
    # section explaining `--config` left the string behind elsewhere and this
    # test passed, which is a test pinning a token rather than a claim.
    assert "gets its first corpus" in text
    assert "recording is the one pass that is SUPPOSED to be live" in text
    # ...and the measured consequence of omitting --memory, which is the
    # failure mode that reads like success.
    assert "no admissible failure memory: no candidate this cycle" in text
    # ...and that one of --state/--no-loop-state is not optional (ADR 0141).
    assert "--no-loop-state" in text
    # LOOP.md's own sequence must not print the invocation the CLI refuses.
    loop = (pristine / "LOOP.md").read_text()
    bootstrap_lines = [
        line
        for line in loop.replace("\\\n", " ").splitlines()
        # An INVOCATION, not a mention: prose naming the flag is not a command.
        if line.strip().startswith("aef loop bootstrap ")
    ]
    assert bootstrap_lines, loop
    for line in bootstrap_lines:
        assert "--state" in line or "--no-loop-state" in line, line


def test_first_day_carries_the_sentence_that_bit_every_raw_sdk_adopter(pristine: Path) -> None:
    """A node that keeps its own client runs fine, `aef doctor` is green, and
    the recorder captures no `RecordedCall` — so the gates have nothing to
    replay (ADR 0137). The document has to say what to do about it, including
    the half nobody finds: deleting the import that keeps the module in the
    reachable set (ADR 0141 R4)."""
    text = (pristine / "FIRST_DAY.md").read_text()
    # The heading itself, because the phrase alone survives in prose: a
    # mutation that removed the section left the sentence fragment elsewhere.
    assert "If your function keeps its own client, the gates cannot replay it" in text
    assert "RecordedCall" in text
    assert "--force" in text, "the fix that loops forever must be named as such"
    assert "reachable set" in text


def test_first_day_says_the_obligations_are_advisory(pristine: Path) -> None:
    """ADR 0141 decided against making `cycle`/`gate` refuse on them, and
    required that the surfaces stop implying otherwise. Earlier kit text said
    "with obligations unmet the gates refuse for lack of evidence"."""
    for name in ("FIRST_DAY.md", "LOOP.md", "AGENT_INTEGRATION.md"):
        text = (pristine / name).read_text()
        assert "ADVISORY, not gating" in text, name
    first_day = (pristine / "FIRST_DAY.md").read_text()
    assert "six" in first_day, "the count doctor prints"
    # Nothing may claim the gates refuse because an obligation is unmet.
    assert "the gates refuse for lack of evidence" not in first_day


def test_first_day_states_the_remaining_adopter_requirement_and_its_limits(
    pristine: Path,
) -> None:
    """One item of ADR 0139's measured minimum is still the adopter's: a
    module-level numeric constant. It is a property of `RuleBasedProposer` and
    of the control cohort, and whether `--proposer llm` needs one is UNMEASURED
    and blocked on model quota (INGEST_LOOP L4). A document that quietly
    generalised from the rule-based proposer would be the next false claim."""
    text = (pristine / "FIRST_DAY.md").read_text()
    assert "module-level numeric constant" in text
    assert "RuleBasedProposer" in text
    assert "control cohort" in text
    # The specific claim, not the word: "unmeasured" also appears in the
    # preamble, so asserting it alone passed a mutation that said every
    # proposer needs a constant.
    assert "needs one is unmeasured" in text, "the LLM proposer's need for one is not known"
    assert "blocked on model quota" in text
    assert "--proposer llm" in text


def test_the_kit_agrees_with_what_bootstrap_can_actually_do(pristine: Path) -> None:
    """Item 4 of the generated LOOP.md's measured minimum said `aef loop
    bootstrap` **cannot** leave failure memory — "it gives every input its own
    in-memory store, so nothing it learns survives the process". True when ADR
    0139 measured it; false the day ADR 0145 shipped `--memory`, and it shipped
    false because NO TEST covered that row. L1 and L2 edited rows 1 and 3 of
    the same table this wave and left row 4 standing (ADR 0148).

    The capability is asserted off the real parser, not off a list typed here:
    if `--memory` ever goes away this fails on the first assertion rather than
    passing while the documents describe a flag that does not exist.
    """
    parser = build_parser()
    parser.parse_args(
        shlex.split(
            "loop bootstrap m --corpus c --inputs i --no-loop-state "
            "--memory mem.jsonl --config aef.yaml"
        )
    )

    for name in ("FIRST_DAY.md", "LOOP.md"):
        text = (pristine / name).read_text()
        assert "aef loop bootstrap" in text, name
        for flag in ("--memory", "--config", "--no-loop-state"):
            assert flag in text, f"{name} never names {flag}"
        # The sentence that was false. Any restatement of it fails.
        assert "bootstrap` cannot do this for you" not in text, name
        assert "nothing it learns survives the process" not in text, name

    # ...and the invocation the kit prints is one the command accepts at RUN
    # time, not merely at parse time: `--state`/`--no-loop-state` is enforced
    # in the handler, so the parser-level command check above cannot see it.
    loop_md = (pristine / "LOOP.md").read_text().replace("\\\n", " ")
    printed = [
        line for line in loop_md.splitlines() if line.strip().startswith("aef loop bootstrap ")
    ]
    assert printed, loop_md
    for line in printed:
        assert "--state" in line or "--no-loop-state" in line, line
