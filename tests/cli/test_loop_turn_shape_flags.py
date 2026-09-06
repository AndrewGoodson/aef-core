"""`--candidates` and `--audit-slice` on `aef loop run|cycle` (ADR 0200).

Two levels on purpose, the same two `test_loop_run_archive_flags.py` names
and for the same reason: a PARSER test alone passes against a handler that
never reads the attribute — which is precisely how `sample_parents` sat in
`LoopConfig` for two ADRs with no command able to set it.

Here the handler half is a config-level assertion rather than a driver-level
one, because both flags are consumed by `_config` into `LoopConfig` and the
drivers read them off that.
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


def _argv(command: str, repo: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "loop",
        command,
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--workdir",
        str(tmp_path / "work"),
        *(("--turns", "1") if command == "run" else ()),
        *extra,
        "--no-memory",
    ]


class _ConfigSpy:
    """Records the `LoopConfig` the handler built, then stops the turn."""

    def __init__(self) -> None:
        self.config: Any = None

    def __call__(self, config: Any, **kwargs: Any) -> Any:
        self.config = config
        raise RuntimeError("stop here — the config is what this test is about")


@pytest.fixture
def cycle_spy(monkeypatch: pytest.MonkeyPatch) -> _ConfigSpy:
    import aef.harness.loop as loop_module

    spy = _ConfigSpy()
    monkeypatch.setattr(loop_module, "cycle", spy)
    return spy


@pytest.fixture
def run_spy(monkeypatch: pytest.MonkeyPatch) -> _ConfigSpy:
    import aef.harness.loop as loop_module

    spy = _ConfigSpy()
    monkeypatch.setattr(loop_module, "run_loop", spy)
    return spy


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["run", "cycle"])
def test_the_defaults_are_one_candidate_and_no_slice(
    command: str, repo: Path, tmp_path: Path
) -> None:
    """The defaults are the behaviour that existed before ADR 0200."""
    args = build_parser().parse_args(_argv(command, repo, tmp_path))

    assert args.candidates == 1
    assert args.audit_slice == 0


@pytest.mark.parametrize("command", ["run", "cycle"])
def test_the_parser_accepts_both(command: str, repo: Path, tmp_path: Path) -> None:
    args = build_parser().parse_args(
        _argv(command, repo, tmp_path, "--candidates", "3", "--audit-slice", "2")
    )

    assert (args.candidates, args.audit_slice) == (3, 2)


# ---------------------------------------------------------------------------
# The handler — the half a parser test cannot reach
# ---------------------------------------------------------------------------


def test_they_reach_the_cycle_config(repo: Path, tmp_path: Path, cycle_spy: _ConfigSpy) -> None:
    assert main(_argv("cycle", repo, tmp_path, "--candidates", "3", "--audit-slice", "2")) == 3

    assert cycle_spy.config.candidates_per_turn == 3
    assert cycle_spy.config.audit_slice_size == 2


def test_they_reach_the_run_config(repo: Path, tmp_path: Path, run_spy: _ConfigSpy) -> None:
    assert main(_argv("run", repo, tmp_path, "--candidates", "2", "--audit-slice", "1")) == 3

    assert run_spy.config.candidates_per_turn == 2
    assert run_spy.config.audit_slice_size == 1


def test_the_default_invocation_builds_the_configuration_it_always_built(
    repo: Path, tmp_path: Path, cycle_spy: _ConfigSpy
) -> None:
    """The control: a flag landing is not a default changing."""
    assert main(_argv("cycle", repo, tmp_path)) == 3

    assert cycle_spy.config.candidates_per_turn == 1
    assert cycle_spy.config.audit_slice_size == 0


def test_a_command_that_defines_neither_flag_is_unchanged(repo: Path, tmp_path: Path) -> None:
    """`_config` reads both through `getattr` with the dataclass's default, so
    the subcommands that define no such flag build what they built before."""
    import argparse

    from aef.cli.loop import _config

    args = argparse.Namespace(
        repo=str(repo),
        state=str(tmp_path / "state"),
        corpus=None,
        base=None,
        graph_id="default",
    )
    config = _config(args)

    assert config.candidates_per_turn == 1
    assert config.audit_slice_size == 0


# ---------------------------------------------------------------------------
# The rendered adopter nightly
# ---------------------------------------------------------------------------


def test_the_adopter_nightly_reads_a_held_back_slice(tmp_path: Path) -> None:
    """An adopting repo gets the automated comparison too, or the capability
    exists only where its author happened to wire it (ADR 0200)."""
    from aef.cli.adopt_loop import render_loop_monitor_workflow

    text = render_loop_monitor_workflow("acme", "agents.migrated.x.graph")

    cycle = text[text.index("aef loop cycle \\") :]
    assert "--audit-slice 1" in cycle
    assert "--i-am-spending-the-holdout" not in text
