"""One spelling of "which graph", shared by every `aef loop` subcommand that
takes one (ADR 0176, F3).

THE DEFECT, reproduced at the CLI before anything changed. The same graph was
named two ways by two subcommands of one command, and each spelling failed on
the other:

    $ aef loop score agents.demo.graph --corpus corpus
    error: entrypoint must be 'module:factory', got 'agents.demo.graph'
    exit=1
    $ aef loop bootstrap agents.demo.graph:build_graph --corpus corpus2 ...
    error: No module named 'agents.demo.graph:build_graph'
    exit=1

and ADR 0168's file-path form, which `record`/`bootstrap`/`harvest`/`cycle`
had accepted since G1b, was refused by `score` outright:

    $ aef loop score /…/agents/demo/graph.py --corpus corpus
    error: entrypoint must be 'module:factory', got '/…/agents/demo/graph.py'

Nothing was narrowed to fix it. Every subcommand accepts the union: a dotted
module, `module:factory`, and a file path (optionally with `:factory`).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aef.cli.loop import (
    DEFAULT_GRAPH_FACTORY,
    GRAPH_REFERENCE_HELP,
    load_graph_reference,
    split_graph_reference,
)
from aef.cli.main import build_parser, main

MODULE = "agents.demo.graph"
GRAPH_FILE = str(Path(__file__).resolve().parents[2] / "agents" / "demo" / "graph.py")

# The subcommands that take a graph reference in-process.
#
# `run` was PENDING here through ADR 0176's wave — `cmd_run` was another
# worker's file, so `run --module` still went through
# `cli.run.load_graph_module`, which took a dotted module and a file path and
# refused `module:factory`, and which lacks ADR 0085's `BaseException` guard.
# ADR 0182 converted it. That is the deliberate edit the PENDING pin existed
# to force, and `test_the_pending_subcommand_is_still_the_only_one_left` is
# the test that failed on the day it happened — exactly as its docstring said
# it would. PENDING is empty now, and the test stays: it is the shape that
# catches the NEXT dialect.
COVERED = {"record", "bootstrap", "harvest", "cycle", "score", "run"}
PENDING: set[str] = set()

# The subcommands whose `--entrypoint` names a graph for the OUT-OF-PROCESS
# gates. It was the FOURTH spelling: `scenario_runner.load_graph` demanded
# `module:factory` and refused both other forms, so
# `aef loop cycle --module agents/x/graph.py --entrypoint agents/x/graph.py`
# accepted the first and refused the second inside one invocation (reproduced,
# ADR 0182). Derived from the parser below, never trusted from this list.
ENTRYPOINT_SUBCOMMANDS = {"gate", "cycle", "run"}


def _loop_subparsers() -> dict[str, argparse.ArgumentParser]:
    for action in build_parser()._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        loop = action.choices.get("loop")
        if loop is None:
            continue
        for inner in loop._actions:
            if isinstance(inner, argparse._SubParsersAction):
                return dict(inner.choices)
    raise AssertionError("no `aef loop` subparsers found")


def _graph_argument(sub: argparse.ArgumentParser) -> argparse.Action | None:
    for arg in sub._actions:
        if arg.help == GRAPH_REFERENCE_HELP:
            return arg
    return None


# ---------------------------------------------------------------------------
# The enumeration — derived from the real parser, never a hand-kept list
# ---------------------------------------------------------------------------


def test_every_subcommand_that_names_a_graph_uses_the_one_help_string() -> None:
    """The G1a pattern. A seventh subcommand that grows a graph argument with
    its own wording fails here rather than shipping a sixth dialect."""
    subs = _loop_subparsers()
    with_help = {name for name, sub in subs.items() if _graph_argument(sub) is not None}

    assert with_help == COVERED, (
        f"the set of subcommands sharing GRAPH_REFERENCE_HELP moved: {sorted(with_help)}. "
        f"If you converted one of {sorted(PENDING)}, update COVERED and PENDING together."
    )


def test_the_one_help_string_names_all_three_forms() -> None:
    for form in ("build_graph()", "module:factory", ".py file", "ADR 0168"):
        assert form in GRAPH_REFERENCE_HELP, form


def test_the_pending_subcommand_is_still_the_only_one_left() -> None:
    """A pin on a KNOWN gap, kept deliberately (see COVERED's comment). It
    fired the day `run` was converted (ADR 0182), which is when it was read.
    PENDING is empty now; the loop is kept so a gap re-declared here is
    checked rather than remembered."""
    subs = _loop_subparsers()
    for name in PENDING:
        assert name in subs, name
        assert _graph_argument(subs[name]) is None, (
            f"`aef loop {name}` now shares the graph-reference help — move it from "
            f"PENDING into COVERED and make sure its handler calls load_graph_reference"
        )


def test_run_no_longer_uses_the_old_loader() -> None:
    """`cmd_run` was the sixth in-process caller and the last on
    `cli.run.load_graph_module`, which refused `module:factory` and carried no
    `BaseException` guard. An AST scan rather than a behaviour test, because
    the property is "there is no second loader left", and a behaviour test
    passes the day someone adds a fallback."""
    import ast

    tree = ast.parse(Path("aef/cli/loop.py").read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "load_graph_module" not in called, (
        "aef/cli/loop.py calls the OLD loader again; every subcommand that names a "
        "graph must go through load_graph_reference (ADR 0176/0182)"
    )
    assert "load_graph_reference" in called


# ---------------------------------------------------------------------------
# `--entrypoint`, the fourth spelling
# ---------------------------------------------------------------------------


def _entrypoint_argument(sub: argparse.ArgumentParser) -> argparse.Action | None:
    for arg in sub._actions:
        if "--entrypoint" in arg.option_strings:
            return arg
    return None


def test_every_entrypoint_flag_shares_one_help_string() -> None:
    """It had three, all three wrong about what it accepted:
    "module:factory that builds your graph, e.g. …" (gate),
    "module:factory that builds your graph; G2/G3 refuse without it" (cycle),
    "module:factory; G2/G3 refuse without it" (run). Derived from the real
    parser, so a fourth `--entrypoint` with its own wording fails here."""
    from aef.cli.loop import ENTRYPOINT_HELP

    subs = _loop_subparsers()
    with_flag = {name for name, sub in subs.items() if _entrypoint_argument(sub) is not None}

    assert with_flag == ENTRYPOINT_SUBCOMMANDS, sorted(with_flag)
    for name in with_flag:
        arg = _entrypoint_argument(subs[name])
        assert arg is not None
        assert arg.help == ENTRYPOINT_HELP, name
    # And it says the SAME three forms `--module` says — one sentence, one
    # splitter, one loader.
    assert GRAPH_REFERENCE_HELP in ENTRYPOINT_HELP


@pytest.mark.parametrize("subcommand", sorted(ENTRYPOINT_SUBCOMMANDS))
@pytest.mark.parametrize("reference", [MODULE, f"{MODULE}:build_graph", GRAPH_FILE])
def test_entrypoint_accepts_each_of_the_three_forms(
    subcommand: str, reference: str, tmp_path: Path
) -> None:
    """Parser -> the loader the OUT-OF-PROCESS gates actually use.

    `scenario_runner.load_graph` is the one the in-process gate path calls and
    `node_worker.load_graph` the one the subprocess calls; both split through
    `graph_loading.split_entrypoint`, so both are covered by asserting the
    split and running one of them.
    """
    from aef.harness.scenario_runner import load_graph

    args = build_parser().parse_args(_entrypoint_argv_for(subcommand, reference, tmp_path))
    assert args.entrypoint == reference

    graph = load_graph(args.entrypoint)
    assert graph.id == "demo_agent"


def test_the_two_flags_of_one_invocation_agree_on_one_spelling(tmp_path: Path) -> None:
    """THE reproduction, as a test. `--module agents/demo/graph.py --entrypoint
    agents/demo/graph.py` used to accept the first and refuse the second."""
    from aef.harness.scenario_runner import load_graph

    args = build_parser().parse_args(
        [
            "loop",
            "cycle",
            "--repo",
            str(tmp_path),
            "--state",
            str(tmp_path / "state"),
            "--workdir",
            str(tmp_path / "w"),
            "--module",
            GRAPH_FILE,
            "--entrypoint",
            GRAPH_FILE,
            "--no-memory",
        ]
    )

    assert load_graph_reference(args.module).id == "demo_agent"
    assert load_graph(args.entrypoint).id == "demo_agent"


def test_node_worker_and_the_runner_split_an_entrypoint_identically() -> None:
    """Both sides of G2. ADR 0177 gave them one IMPORTER and left them two
    splitters' worth of tolerance apart; they share the splitter now, so a
    spelling one side accepts cannot be a G2 regression on the other."""
    import ast

    for path in (Path("aef/harness/scenario_runner.py"), Path("aef/harness/node_worker.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "aef.harness.graph_loading"
            for alias in node.names
        }
        assert "split_entrypoint" in imported, path


# ---------------------------------------------------------------------------
# The three forms, through the real parser into the real loader
# ---------------------------------------------------------------------------


def _argv_for(name: str, reference: str, tmp_path: Path) -> list[str]:
    """A minimal accepted invocation of each subcommand, so the reference is
    parsed by the argument that actually carries it."""
    state = str(tmp_path / "state")
    common = ["--repo", str(tmp_path), "--state", state]
    if name == "record":
        return [
            "loop",
            "record",
            reference,
            "--corpus",
            str(tmp_path / "c"),
            "--scenario-id",
            "s",
            "--objective",
            "o",
        ]
    if name == "bootstrap":
        return [
            "loop",
            "bootstrap",
            reference,
            "--corpus",
            str(tmp_path / "c"),
            "--inputs",
            str(tmp_path / "in.json"),
            "--no-loop-state",
        ]
    if name == "harvest":
        return [
            "loop",
            "harvest",
            reference,
            *common,
            "--runs",
            str(tmp_path / "runs"),
            "--corpus",
            str(tmp_path / "c"),
        ]
    if name == "cycle":
        return [
            "loop",
            "cycle",
            *common,
            "--workdir",
            str(tmp_path / "w"),
            "--module",
            reference,
            "--no-memory",
        ]
    if name == "run":
        return [
            "loop",
            "run",
            *common,
            "--workdir",
            str(tmp_path / "w"),
            "--module",
            reference,
            "--no-memory",
        ]
    if name == "score":
        return ["loop", "score", reference, "--corpus", str(tmp_path / "c")]
    raise AssertionError(name)


def _entrypoint_argv_for(name: str, reference: str, tmp_path: Path) -> list[str]:
    """A minimal accepted invocation carrying `--entrypoint`."""
    common = ["--repo", str(tmp_path), "--state", str(tmp_path / "state")]
    workdir = ["--workdir", str(tmp_path / "w")]
    if name == "gate":
        return ["loop", "gate", *common, *workdir, "--head", "HEAD", "--entrypoint", reference]
    if name == "cycle":
        return ["loop", "cycle", *common, *workdir, "--entrypoint", reference, "--no-memory"]
    if name == "run":
        return ["loop", "run", *common, *workdir, "--entrypoint", reference, "--no-memory"]
    raise AssertionError(name)


@pytest.mark.parametrize("subcommand", sorted(COVERED))
@pytest.mark.parametrize("reference", [MODULE, f"{MODULE}:build_graph", GRAPH_FILE])
def test_each_subcommand_accepts_each_of_the_three_forms(
    subcommand: str, reference: str, tmp_path: Path
) -> None:
    """Producer -> parser -> loader, for all fifteen combinations.

    The parser is the real one and the loader is the real one; what is not run
    is the rest of each handler, because what the defect was about is whether
    the reference survives the trip, and `score` used to reject two of these
    three before it ran anything at all.
    """
    args = build_parser().parse_args(_argv_for(subcommand, reference, tmp_path))
    sub = _loop_subparsers()[subcommand]
    dest = _graph_argument(sub)
    assert dest is not None
    value = getattr(args, dest.dest)
    assert value == reference

    graph = load_graph_reference(value)
    assert graph.id == "demo_agent"


def test_bootstrap_and_score_agree_end_to_end_on_every_form(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """THE reproduction, as a test: the two subcommands the defect was
    reported between, run for real, on all three spellings."""
    inputs = tmp_path / "in.json"
    inputs.write_text(
        json.dumps(
            [{"id": "s-1", "objective": "an easy task", "working_memory": {"difficulty": 1}}]
        )
    )
    for index, reference in enumerate((MODULE, f"{MODULE}:build_graph", GRAPH_FILE)):
        corpus = tmp_path / f"corpus{index}"
        assert (
            main(
                [
                    "loop",
                    "bootstrap",
                    reference,
                    "--corpus",
                    str(corpus),
                    "--inputs",
                    str(inputs),
                    "--no-loop-state",
                ]
            )
            == 0
        ), f"bootstrap refused {reference!r}"
        assert main(["loop", "score", reference, "--corpus", str(corpus)]) == 0, (
            f"score refused {reference!r}"
        )
        assert "mean=1.0000" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The split itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("agents.mine.graph", ("agents.mine.graph", DEFAULT_GRAPH_FACTORY)),
        ("agents.mine.graph:build_graph", ("agents.mine.graph", "build_graph")),
        ("agents.mine.graph:make", ("agents.mine.graph", "make")),
        ("a/b/graph.py", ("a/b/graph.py", DEFAULT_GRAPH_FACTORY)),
        ("a/b/graph.py:make", ("a/b/graph.py", "make")),
        # A colon that is not a factory name stays part of the path, so the
        # importer's error is about the thing the user typed.
        (r"C:\a\graph.py", (r"C:\a\graph.py", DEFAULT_GRAPH_FACTORY)),
    ],
)
def test_the_split_reads_the_way_the_reference_reads(
    reference: str, expected: tuple[str, str]
) -> None:
    assert split_graph_reference(reference) == expected


@pytest.mark.parametrize("reference", ["agents.mine.graph:", ":build_graph"])
def test_a_half_written_reference_is_refused_by_name(reference: str) -> None:
    with pytest.raises(ValueError, match="three forms"):
        split_graph_reference(reference)


def test_a_missing_factory_names_the_three_forms() -> None:
    from aef.harness.scenario_runner import EntrypointError

    with pytest.raises(EntrypointError, match="three forms"):
        load_graph_reference(f"{MODULE}:no_such_factory")


def test_a_factory_that_calls_sys_exit_does_not_exit_this_process(tmp_path: Path) -> None:
    """ADR 0085's control, which `scenario_runner.load_graph` had and
    `cli.run.load_graph_module` did not — so folding the two together had to
    keep the stronger one. `SystemExit` is a BaseException: an `except
    Exception` here lets a candidate that printed forged output own the
    runner's exit code.
    """
    from aef.harness.scenario_runner import EntrypointError

    module = tmp_path / "exiting_graph.py"
    module.write_text("import sys\n\n\ndef build_graph():\n    raise SystemExit(0)\n")

    with pytest.raises(EntrypointError, match="SystemExit"):
        load_graph_reference(str(module))


def test_a_factory_returning_something_else_is_refused(tmp_path: Path) -> None:
    from aef.harness.scenario_runner import EntrypointError

    module = tmp_path / "not_a_graph.py"
    module.write_text("def build_graph():\n    return 42\n")

    with pytest.raises(EntrypointError, match="expected a Graph"):
        load_graph_reference(str(module))
