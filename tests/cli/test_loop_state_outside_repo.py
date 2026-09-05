"""No `aef loop` subcommand may put its state directory inside the repository.

`harness.loop._preflight` has refused this since ADR 0090: with `--state`
inside the working tree an ordinary `git add -A` sweeps the ledger and archive
into the candidate's own commit, so the audit trail becomes part of what it
audits and every candidate looks like it touches Zone C.

Four of the nine subcommands that take both `--repo` and `--state` never
called `_preflight`, so they never asked. Reproduced (ADR 0167), one command
at a time, against a repo with `state/` inside it:

    REFUSED   loop gate     REFUSED   loop monitor  ACCEPTED  loop digest
    REFUSED   loop status   ACCEPTED  loop harvest  REFUSED   loop cycle
    REFUSED   loop run      ACCEPTED  loop bless    ACCEPTED  loop doctor

    $ aef loop bless --repo <r> --state <r>/state --agent-path agents/demo/graph.py
      blessed agents/demo/graph.py as baseline v1 for graph 'default'
    EXIT=0
    contents of <r>/state: ['archive', 'ledger.jsonl']

`bless` is the worst of the four, because the baseline is the one artefact
that must sit outside the candidate's reach: under a widened `--agent-root`
an in-repo archive can end up inside its own next baseline.

The list below is DERIVED from the parser, not remembered — same shape as
`test_loop_turn_commands.py`. `bootstrap` also takes `--state` and is
deliberately absent: it has no `--repo` at all, so there is no repository
root to compare against and nothing this check could say.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from aef.cli.main import build_parser, main

# The minimum extra arguments each subcommand needs to reach its handler.
# Adding a subcommand here is the deliberate act the derived-set assertion
# below forces.
EXTRA: dict[str, list[str]] = {
    "gate": ["--head", "main", "--workdir", "WORK"],
    "monitor": [],
    "digest": [],
    "status": [],
    "harvest": ["agents.demo.graph", "--runs", "RUNS", "--corpus", "CORPUS"],
    "cycle": ["--workdir", "WORK", "--no-memory"],
    "run": ["--workdir", "WORK", "--no-memory", "--turns", "1", "--budget-minutes", "1"],
    "bless": ["--agent-path", "agents/demo/graph.py"],
    "doctor": ["--corpus", "CORPUS"],
}


def _subcommands_taking_repo_and_state() -> set[str]:
    """Every `aef loop` subcommand wired by `_common()` — i.e. every one that
    knows both where the repo is and where the state is, and can therefore be
    asked whether the second is inside the first."""
    (loop_action,) = [
        a
        for a in build_parser()._actions
        if isinstance(a, argparse._SubParsersAction) and "loop" in a.choices
    ]
    sub = loop_action.choices["loop"]
    (inner,) = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
    found = set()
    for name, parser in inner.choices.items():
        options = {opt for action in parser._actions for opt in action.option_strings}
        if "--state" in options and "--repo" in options:
            found.add(name)
    return found


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


def test_the_list_is_derived_from_the_parser_not_remembered() -> None:
    derived = _subcommands_taking_repo_and_state()
    assert derived == set(EXTRA), (
        f"`aef loop` has subcommand(s) {sorted(derived ^ set(EXTRA))} taking --repo and "
        f"--state that this file does not exercise. Four of nine silently accepted a state "
        f"directory inside the repository (ADR 0167)."
    )


@pytest.mark.parametrize("command", sorted(EXTRA))
def test_every_subcommand_refuses_a_state_directory_inside_the_repo(  # type: ignore[no-untyped-def]
    command: str, repo: Path, tmp_path: Path, capsys
) -> None:
    in_repo_state = repo / "state"
    extra = [
        {
            "WORK": str(tmp_path / "w"),
            "RUNS": str(tmp_path / "runs"),
            "CORPUS": str(tmp_path / "c"),
        }.get(a, a)
        for a in EXTRA[command]
    ]
    code = main(["loop", command, "--repo", str(repo), "--state", str(in_repo_state), *extra])
    captured = capsys.readouterr()

    assert code != 0, f"`loop {command}` accepted loop state inside the repository"
    assert "is inside the repository" in (captured.out + captured.err), captured.err
    assert not in_repo_state.exists(), (
        f"`loop {command}` refused and still created {in_repo_state} — a refusal that writes "
        f"the thing it refused is not a refusal"
    )


def test_bless_refuses_it_as_a_library_call_too(repo: Path) -> None:
    """L6's lesson: `bless` is importable, so a control that only binds when
    argparse is involved does not bind on the path a library caller takes."""
    from datetime import UTC, datetime

    from aef.harness.loop import LoopStateInsideRepoError
    from aef.harness.preflight import bless

    with pytest.raises(LoopStateInsideRepoError):
        bless(
            repo_root=repo,
            state_root=repo / "state",
            agent_path="agents/demo/graph.py",
            graph_id="g",
            at=datetime.now(UTC),
        )
    assert not (repo / "state").exists()


def test_a_state_directory_outside_the_repo_is_still_accepted(repo: Path, tmp_path: Path) -> None:
    """The control is about the location, not about `--state`. A guard that
    refused the correct invocation too would just be the loop turned off."""
    assert main(["loop", "status", "--repo", str(repo), "--state", str(tmp_path / "state")]) == 0
