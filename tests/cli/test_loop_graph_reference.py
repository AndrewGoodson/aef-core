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

# The subcommands that take a graph reference in-process. `run` is the sixth
# and is DELIBERATELY absent: `cmd_run` is another worker's file this wave
# (S4's `--sample-parents`/archive region), so `run --module` still goes
# through `cli.run.load_graph_module`. If you have just converted it, add
# "run" here and delete it from PENDING below — the pin exists so that day is
# a deliberate edit and not a silent drift.
COVERED = {"record", "bootstrap", "harvest", "cycle", "score"}
PENDING = {"run"}


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
    fails the day `run` is converted, which is when someone should read it."""
    subs = _loop_subparsers()
    for name in PENDING:
        assert name in subs, name
        assert _graph_argument(subs[name]) is None, (
            f"`aef loop {name}` now shares the graph-reference help — move it from "
            f"PENDING into COVERED and make sure its handler calls load_graph_reference"
        )


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
    if name == "score":
        return ["loop", "score", reference, "--corpus", str(tmp_path / "c")]
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
