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


def test_loop_doctor_reports_all_five_and_exits_nonzero(pristine: Path) -> None:
    """The adopter's first useful command. It must name every obligation at
    once — discovering them one refusal at a time, in the worst order, is the
    problem it exists to solve (ADR 0073)."""
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
    for obligation in (
        "corpus + tripwire",
        "reflect node routed to",
        "observations",
        "halt channel",
        "blessed baseline",
    ):
        assert obligation in result.stdout, obligation


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
    for name in ("LOOP.md", "corpus/README.md", "AGENT_INTEGRATION.md"):
        for argv in _commands(pristine / name):
            parser.parse_args(argv)  # raises SystemExit if the CLI would refuse
            checked += 1
    # Skipping placeholder-bearing lines instead of substituting into them left
    # 3 commands checked out of 16, and the three that survived were the ones
    # with no arguments worth getting wrong. A coverage floor keeps that from
    # silently happening again.
    assert checked >= 15, f"only {checked} commands checked — the extractor is skipping too much"


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
