"""`aef loop run --sample-parents` — the flag J0 found missing (ADR 0160).

J0's dimension-6 finding (ADR 0151) was, verbatim: "the lineage archive is
in-memory inside one `run_loop` call, has no CLI flag (`grep sample_parents
aef/cli/` empty), only kept candidates enter it, nothing persists across
invocations". The middle clause is this file. `LoopConfig`/`run_loop` had
carried `sample_parents` since ADR 0121 and no command could set it — the
knob dimension 6 was scored on was unreachable from the CLI, which is the
repo's own *wired but not consumed* shape one layer up.

Two levels are tested on purpose, because either alone is a hole this repo
has already fallen into: the PARSER (the flag exists and defaults right) and
the HANDLER (it actually reaches the driver). A parser test alone passes
against a `cmd_run` that never reads the attribute.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from aef.cli.main import build_parser, main


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
        "run",
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--workdir",
        str(tmp_path / "work"),
        "--turns",
        "1",
        *extra,
    ]


class _Spy:
    """Stands in for `run_loop` and records the keyword arguments it was
    handed. `cmd_run` imports the driver inside the function, so patching the
    module attribute is what the handler will resolve."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def __call__(self, config: Any, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        from aef.harness.loop import LoopRun

        return LoopRun(
            turns=(),
            kept_branch="loop/kept",
            kept_ref="0" * 40,
            stopped_because="spy",
            lines=(),
        )


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    import aef.harness.loop as loop_module

    spied = _Spy()
    monkeypatch.setattr(loop_module, "run_loop", spied)
    return spied


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


def test_the_parser_accepts_the_flags_and_defaults_to_greedy_and_persistent(
    repo: Path, tmp_path: Path
) -> None:
    args = build_parser().parse_args(_argv(repo, tmp_path))
    assert args.sample_parents is False
    assert args.no_lineage is False
    assert args.seed == 0

    on = build_parser().parse_args(
        _argv(repo, tmp_path, "--sample-parents", "--seed", "7", "--no-lineage")
    )
    assert (on.sample_parents, on.seed, on.no_lineage) == (True, 7, True)


# ---------------------------------------------------------------------------
# The handler — the half a parser test cannot reach
# ---------------------------------------------------------------------------


def test_sample_parents_reaches_the_driver(repo: Path, tmp_path: Path, spy: _Spy) -> None:
    assert main(_argv(repo, tmp_path, "--sample-parents", "--seed", "7")) == 0
    assert spy.kwargs["sample_parents"] is True
    assert spy.kwargs["seed"] == 7
    assert spy.kwargs["persist_lineage"] is True


def test_the_default_invocation_is_greedy_and_persistent(
    repo: Path, tmp_path: Path, spy: _Spy
) -> None:
    """The control. `--sample-parents` stays off by default — ADR 0121
    measured it buying nothing on a deterministic proposer and ADR 0160's own
    A/B is what may change that; a flag landing is not a default changing."""
    assert main(_argv(repo, tmp_path)) == 0
    assert spy.kwargs["sample_parents"] is False
    assert spy.kwargs["persist_lineage"] is True


def test_no_lineage_turns_persistence_off_at_the_driver(
    repo: Path, tmp_path: Path, spy: _Spy
) -> None:
    assert main(_argv(repo, tmp_path, "--no-lineage")) == 0
    assert spy.kwargs["persist_lineage"] is False


def test_the_handler_reads_the_flag_rather_than_the_parser_defaulting_it(
    repo: Path, tmp_path: Path, spy: _Spy
) -> None:
    """L6's lesson (see `test_loop_cycle_memory_flag.py`): a control that
    lives only in argparse is invisible to any caller that builds its own
    `Namespace`, and `cmd_run` is importable. The parser is bypassed here."""
    from aef.cli.loop import cmd_run

    args = build_parser().parse_args(_argv(repo, tmp_path))
    args.sample_parents = True
    args.seed = 11
    args.no_lineage = True

    assert cmd_run(args) == 0
    assert spy.kwargs["sample_parents"] is True
    assert spy.kwargs["seed"] == 11
    assert spy.kwargs["persist_lineage"] is False


# ---------------------------------------------------------------------------
# `--build-command`, which `run` did not have
# ---------------------------------------------------------------------------


def test_run_accepts_build_commands_and_they_reach_the_gate_config(
    repo: Path, tmp_path: Path, spy: _Spy
) -> None:
    """`gate` and `cycle` have taken `--build-command` since G1 existed;
    `run` did not, and `_build_commands` reads the attribute with `getattr`,
    so the absence was silent: every `aef loop run` candidate was built with
    G1's default `python -m pytest -q` — the whole suite, per candidate, per
    turn. Found by running J2's first live turn, whose only measurement was
    `G1 rejected it: build command failed (timed out)`.

    The assertion is on the `LoopConfig` the handler builds, because that is
    what `gate` reads; a parser test alone would have passed against the
    broken version had the flag merely existed.
    """
    argv = _argv(
        repo,
        tmp_path,
        "--build-command",
        "python -c pass",
        "--build-command",
        "python -m compileall -q .",
    )
    args = build_parser().parse_args(argv)
    assert args.build_command == ["python -c pass", "python -m compileall -q ."]

    from aef.cli.loop import cmd_run

    captured: dict[str, Any] = {}

    def capture(config: Any, **kwargs: Any) -> Any:
        captured["build_commands"] = config.build_commands
        return _Spy()(config, **kwargs)

    import aef.harness.loop as loop_module

    monkey = pytest.MonkeyPatch()
    monkey.setattr(loop_module, "run_loop", capture)
    try:
        assert cmd_run(args) == 0
    finally:
        monkey.undo()
    assert captured["build_commands"] == (
        ("python", "-c", "pass"),
        ("python", "-m", "compileall", "-q", "."),
    )


def test_without_the_flag_run_still_takes_g1s_default(
    repo: Path, tmp_path: Path, spy: _Spy
) -> None:
    """The control: adding the flag must not change what an invocation
    without it does."""
    from aef.cli.loop import _config

    args = build_parser().parse_args(_argv(repo, tmp_path))
    assert _config(args).build_commands is None


# ---------------------------------------------------------------------------
# End to end, through the real driver and the real gates
# ---------------------------------------------------------------------------


def test_a_real_invocation_writes_the_lineage_file_including_the_rejection(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No spy: the actual command, the actual gates. With no `--entrypoint`
    the behavioural gates refuse the candidate, which is exactly the case
    that used to leave NOTHING behind — and is now a recorded stepping stone
    with its verdict."""
    from aef.harness.archive import read_lineage

    memory = tmp_path / "memory.jsonl"
    memory.write_text(
        '{"kind": "failure", "content": {"verbal_feedback": "gave up at difficulty 4"}, '
        '"run_id": "prod-1", "agent_id": "demo", "tags": [], "id": "mem-1", '
        '"created_at": "2026-09-03T12:00:00+00:00"}\n'
    )
    code = main(
        _argv(
            repo,
            tmp_path,
            "--memory",
            str(memory),
            "--agent-path",
            "agents/demo/graph.py",
            "--sample-parents",
        )
    )
    captured = capsys.readouterr()
    out = captured.out + captured.err

    assert code in (0, 2), out
    records = read_lineage(tmp_path / "state" / "lineage", "default")
    assert records, out
    assert any(r.kept is False for r in records), [
        (r.kept, r.disposition, r.score) for r in records
    ]
    # The summary line reports the archive rather than leaving it in a
    # dataclass nobody reads — J0 scored what the CLI shows, not what the
    # driver holds.
    assert "archive:" in out and "distinct kept tree" in out
    assert "sampling on" in out
