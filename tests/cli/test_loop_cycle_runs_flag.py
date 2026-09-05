"""`aef loop cycle --runs` may not be a no-op (ADR 0190, closing ADR 0163's
F-M6-3).

`cmd_cycle` builds the graph object the harvest leg needs from `--module`
alone:

    graph = load_graph_reference(args.module) if args.module else None

and `harness/loop.py::cycle` runs that leg only `if runs_dir is not None and
corpus_root is not None and graph is not None`. So `--runs` given with
`--entrypoint` and no `--module` — the spelling a widened-root prompt repo
uses, and the spelling ADR 0163's pilot and ADR 0181 both used — was accepted,
its path validated, and nothing happened.

Reproduced on the pilot on two invocations one flag apart, both `--no-memory`
so neither could reach a model: arm A printed no harvest line and exited 0
with five recorded runs at the path it was handed; arm B, plus `--module`,
printed `promoted 0 run(s) to the train split` and listed all five. That is
ADR 0139's shape — exit 0 having done nothing — and it is why the pilot's
ledger is silent about a step the invocation asked for.
"""

import subprocess
from pathlib import Path

import pytest

from aef.cli.main import build_parser, main
from aef.harness.loop import EXIT_ERROR


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 3\n")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@t"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def _argv(repo: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "loop",
        "cycle",
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--workdir",
        str(tmp_path / "work"),
        "--no-memory",
        *extra,
    ]


def test_runs_without_module_is_refused_and_does_not_exit_zero(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """THE regression test. Before the fix this printed the ordinary cycle
    summary, said nothing about the runs directory, and returned 0."""
    code = main(_argv(repo, tmp_path, "--runs", str(tmp_path / "runs")))

    assert code == EXIT_ERROR, "a cycle that silently skipped a step must not report success"
    captured = capsys.readouterr()
    assert "cycle verdict:" not in captured.out, (
        "the cycle ran; the refusal must come first, before anything looks like work"
    )
    # Both flags named, or the owner is given a puzzle rather than a fix.
    assert "--runs" in captured.err
    assert "--module" in captured.err


def test_the_refusal_is_in_the_handler_not_only_the_parser(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """The same lesson `_require_memory_flag` records: a parser-level control
    is invisible to any caller that builds a `Namespace` itself, and
    `cmd_cycle` is importable."""
    from aef.cli.loop import cmd_cycle

    args = build_parser().parse_args(_argv(repo, tmp_path, "--runs", str(tmp_path / "runs")))
    args.module = None

    assert cmd_cycle(args) == EXIT_ERROR
    assert "--module" in capsys.readouterr().err


def test_no_runs_flag_is_untouched(repo: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The other arm: a cycle that never asked for the harvest leg is exactly
    the cycle it was. Strengthening a control onto invocations no finding
    reproduced a problem with is ADR 0141's rule, applied here."""
    code = main(_argv(repo, tmp_path))

    assert code == 0
    assert "cycle verdict:" in capsys.readouterr().out


def test_runs_with_module_still_reaches_the_harvest_leg(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Arm B, as a test: with both flags and a corpus the leg runs and
    reports, so the refusal above is about the missing flag and not about
    `--runs` itself."""
    module = tmp_path / "cycle_runs_graph_mod.py"
    module.write_text(
        "from aef.kernel import END, Context, Graph, Node, Route, Services\n"
        "from aef.state import AEFState, StateDelta\n"
        "def n(state, ctx, services):\n"
        "    return StateDelta(working_memory={'seen': state.objective}), END\n"
        "def build_graph() -> Graph:\n"
        "    node = Node(id='n', version='0.1.0', fn=n, deterministic=True)\n"
        "    return Graph(id='g', version='0.1.0', nodes={'n': node}, edges=[], "
        "entry_node='n')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "corpus").mkdir()
    (tmp_path / "runs").mkdir()

    code = main(
        _argv(
            repo,
            tmp_path,
            "--runs",
            str(tmp_path / "runs"),
            "--corpus",
            str(tmp_path / "corpus"),
            "--module",
            "cycle_runs_graph_mod",
        )
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "promoted 0 run(s) to the train split" in out, out
