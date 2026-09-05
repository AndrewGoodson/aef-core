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


# ---------------------------------------------------------------------------
# A hand-typed --graph-id is a configuration error, not a rejection (ADR 0167)
#
# `archive.versions` refuses a graph id that is not one safe path segment
# (ADR 0168), and `cmd_doctor`/`cmd_bless` caught neither — so the refusal
# reached `main()`'s catch-all and came back as exit 1, which is also
# `EXIT_REJECTED`: "the candidate was rejected, the system is working".
# Reproduced:
#
#   $ aef loop doctor ... --graph-id ../x
#     error: graph_id '../x' is not usable as an archive directory: ...
#   EXIT=1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["doctor", "bless"])
def test_an_unusable_graph_id_is_a_configuration_error_not_a_rejection(  # type: ignore[no-untyped-def]
    command: str, repo: Path, tmp_path: Path, capsys
) -> None:
    from aef.harness.loop import EXIT_ERROR, EXIT_REJECTED

    argv = [
        "loop",
        command,
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--graph-id",
        "../x",
    ]
    if command == "doctor":
        argv += ["--corpus", str(tmp_path / "corpus")]
    else:
        argv += ["--agent-path", ".claude/agents/migrated/marlin_accela/graph.py"]

    code = main(argv)
    err = capsys.readouterr().err

    assert code == EXIT_ERROR, f"`loop {command}` reported {code}"
    assert code != EXIT_REJECTED
    assert "--graph-id" in err and "../x" in err, err
    assert "one path segment" in err, err


def test_a_loop_command_accepts_the_file_path_module_form_under_a_widened_root(
    repo: Path, tmp_path: Path
) -> None:
    """`aef migrate --agent-root .claude/agents` writes
    `.claude/agents/migrated/<name>/graph.py`, and no dotted spelling of that
    path is importable — a leading dot means relative import (ADR 0168).
    `import_graph_module` takes a file path for exactly that case, and the
    loop's `--module` help now says so; this asserts a loop command actually
    accepts it."""
    graph = repo / ".claude" / "agents" / "migrated" / "marlin_accela" / "graph.py"
    graph.write_text(
        "from aef.kernel import END, Graph, Node\n"
        "from aef.state import StateDelta\n\n\n"
        "def work(state, ctx, services):\n"
        "    return StateDelta(), END\n\n\n"
        "def build_graph():\n"
        '    return Graph(id="g", version="1",\n'
        '                 nodes={"work": Node(id="work", version="1", fn=work,\n'
        "                                     deterministic=True)},\n"
        '                 edges=[], entry_node="work")\n'
    )
    code = main(
        [
            "loop",
            "cycle",
            "--repo",
            str(repo),
            "--state",
            str(tmp_path / "state"),
            "--workdir",
            str(tmp_path / "work"),
            "--agent-root",
            WIDENED,
            "--agent-path",
            ".claude/agents/migrated/marlin_accela/graph.py",
            "--module",
            str(graph),
            "--no-memory",
        ]
    )
    # 0 = it ran and had nothing to propose. Anything else means the module
    # never loaded, which is the defect this pins.
    assert code == 0, "the file-path --module form did not load"


def _graph_reference_arguments() -> list[tuple[str, str, str]]:
    """(subcommand, dest, help) for every `aef loop` argument that names a
    graph, read off the REAL parser rather than a hand-kept list — the G1a
    pattern. A sixth subcommand that grows one is caught by the enumeration
    in `tests/cli/test_loop_graph_reference.py`."""
    import argparse as _argparse

    from aef.cli.loop import GRAPH_REFERENCE_HELP
    from aef.cli.main import build_parser

    found: list[tuple[str, str, str]] = []
    for action in build_parser()._actions:
        if not isinstance(action, _argparse._SubParsersAction):
            continue
        loop = action.choices.get("loop")
        if loop is None:
            continue
        for inner in loop._actions:
            if not isinstance(inner, _argparse._SubParsersAction):
                continue
            for name, sub in inner.choices.items():
                for arg in sub._actions:
                    if arg.help == GRAPH_REFERENCE_HELP:
                        found.append((name, arg.dest, arg.help))
    return found


def test_every_loop_module_argument_says_a_file_path_works() -> None:
    """The help was the whole defect for `aef run` (ADR 0168): a flag whose
    generated command could not be run under it. These are the loop's.

    UPDATED DELIBERATELY (ADR 0176). This counted the substring "OR a path to
    the graph" five times in the source, and five identical help strings had
    been written out five times — which is how `aef loop score` came to
    describe the same argument a sixth way ("'module:factory' returning the
    incumbent Graph") and accept a different language. There is one help
    string now, `GRAPH_REFERENCE_HELP`, so the assertion moved from counting a
    substring to reading the REAL parser: every argument that names a graph
    carries it, and it says all three forms.
    """
    from aef.cli.loop import GRAPH_REFERENCE_HELP

    helps = _graph_reference_arguments()
    assert helps, "no graph-reference argument found in the loop parser"
    for subcommand, dest, help_text in helps:
        assert help_text == GRAPH_REFERENCE_HELP, f"{subcommand} {dest} says something else"
    for form in ("build_graph()", "module:factory", ".py file"):
        assert form in GRAPH_REFERENCE_HELP, form
