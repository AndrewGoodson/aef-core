"""`--agent-root` and `--agent-path` must describe the same tree (ADR 0167).

`DEFAULT_AGENT_PATH` lives under `DEFAULT_AGENT_ROOT`. `aef migrate` on a
prompt-file repo prints, in its own blast-radius report, "to widen it, re-run
as `aef migrate --dir . --agent-root .claude/agents` and pass `--agent-root
.claude/agents` to every `aef loop` command as well" (ADR 0152) — and says
nothing about `--agent-path`, whose default then names a file that is **Zone
C** under the root now in force.

Reproduced on the pilot clone, migrated with the widened root:

    $ aef loop doctor --repo <pilot> --state <s> --corpus <pilot>/corpus \\
          --agent-root .claude/agents
      [--] reflect node routed to  no reflect node in the graph
      ...
           fix: aef loop bless --repo . --state <s> --agent-path agents/migrated/graph.py
    EXIT=1

Six obligations reported about `agents/migrated/graph.py` — a file the loop
may not propose changes to and `bless` would not archive — and a fix line that
drops `--agent-root` entirely, so following it produces a baseline of the
other tree. And:

    $ aef loop cycle ... --agent-root .claude/agents      # --agent-path default
        the proposer produced nothing from the available evidence
    EXIT=0

ADR 0139's shape again. Neither command said the two flags disagreed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aef.cli.loop import EXIT_USAGE
from aef.cli.main import main
from aef.harness.zones import DEFAULT_AGENT_PATH

WIDENED = ".claude/agents"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo shaped like a migrated prompt-file repo: personas and generated
    graphs under `.claude/agents`, and `aef migrate`'s default-root stub still
    sitting at `agents/migrated/graph.py`."""
    root = tmp_path / "repo"
    (root / ".claude" / "agents" / "migrated" / "marlin_accela").mkdir(parents=True)
    (root / ".claude" / "agents" / "migrated" / "marlin_accela" / "graph.py").write_text(
        "RETRY_BUDGET = 3\n"
    )
    (root / ".claude" / "agents" / "accela-agent.md").write_text("---\nname: a\n---\n\nbody\n")
    (root / "agents" / "migrated").mkdir(parents=True)
    (root / "agents" / "migrated" / "graph.py").write_text("RETRY_BUDGET = 3\n")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@t"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def _argv(command: str, repo: Path, tmp_path: Path) -> list[str]:
    common = [
        "loop",
        command,
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--agent-root",
        WIDENED,
    ]
    if command in ("cycle", "run"):
        common += ["--workdir", str(tmp_path / "work"), "--no-memory"]
    if command == "run":
        common += ["--turns", "1", "--budget-minutes", "1"]
    if command == "doctor":
        common += ["--corpus", str(tmp_path / "corpus")]
    return common


@pytest.mark.parametrize("command", ["bless", "cycle", "run", "doctor"])
def test_a_widened_root_with_the_default_agent_path_is_refused(  # type: ignore[no-untyped-def]
    command: str, repo: Path, tmp_path: Path, capsys
) -> None:
    code = main(_argv(command, repo, tmp_path))
    err = capsys.readouterr().err

    assert code == EXIT_USAGE, f"`loop {command}` proceeded on a Zone C file"
    # Both paths, by name, or the reader has to work out which two flags
    # disagree from a message that names one of them.
    assert WIDENED in err and DEFAULT_AGENT_PATH in err, err
    assert "left at its default" in err, err
    # And the way out: the per-agent path `aef migrate` actually wrote.
    assert ".claude/agents/migrated/marlin_accela/graph.py" in err, err


@pytest.mark.parametrize("command", ["bless", "cycle", "run", "doctor"])
def test_the_same_commands_proceed_when_the_path_is_under_the_widened_root(
    command: str, repo: Path, tmp_path: Path
) -> None:
    """The control is about the two flags disagreeing, not about the widened
    root. Pass a path inside it and every command runs — a guard that refused
    the correct invocation too would just be `--agent-root` removed."""
    argv = _argv(command, repo, tmp_path) + [
        "--agent-path",
        ".claude/agents/migrated/marlin_accela/graph.py",
    ]
    assert main(argv) != EXIT_USAGE


def test_the_default_root_is_left_alone(repo: Path, tmp_path: Path) -> None:
    """Only checked when the root is non-default. Under the default root this
    would be a new refusal on invocations no finding reproduced a problem
    with, and strengthening a control is an owner's decision rather than a fix
    wave's side effect (ADR 0141's rule, applied to itself)."""
    assert (
        main(
            [
                "loop",
                "doctor",
                "--repo",
                str(repo),
                "--state",
                str(tmp_path / "state"),
                "--corpus",
                str(tmp_path / "corpus"),
            ]
        )
        != EXIT_USAGE
    )
