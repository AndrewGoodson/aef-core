"""`aef loop cycle` must be told about memory, one way or the other (ADR 0165).

The defect this file pins was in a workflow, not in a function. This repo's
own `.github/workflows/loop-monitor.yml` ran, nightly:

    aef loop cycle --repo . --state ~/.aef-loop-state --workdir ... \\
      --module agents.demo.graph --runs ~/.aef-loop-state/runs --corpus corpus

with no `--memory`. `cmd_cycle` therefore passed `memory=None`, the driver
printed `no memory store configured: nothing to learn from, no candidate`,
and the command **exited 0**. A green tick every morning, for as long as the
workflow had existed, meaning nothing had happened — ADR 0139's failure shape
on a timer.

The fix is ADR 0141's `--state`/`--no-loop-state` shape: one of two flags is
required, and the "do nothing" branch is something the owner SAYS.
"""

import subprocess
from pathlib import Path

import pytest

from aef.cli.main import build_parser, main

MODULE = "agents.demo.graph"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a Zone A agent, which is all `cycle` needs to reach
    the memory branch."""
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
    """The workflow's own invocation, verbatim in shape."""
    return [
        "loop",
        "cycle",
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--workdir",
        str(tmp_path / "work"),
        "--runs",
        str(tmp_path / "state" / "runs"),
        *extra,
    ]


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------


def test_neither_flag_is_refused_and_does_not_exit_zero(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """THE regression test. Before the fix this printed the no-candidate line
    and returned 0."""
    code = main(_argv(repo, tmp_path))

    assert code == 2, "a cycle that cannot propose must not report success"
    captured = capsys.readouterr()
    assert "no memory store configured" not in captured.out, (
        "the cycle ran; the refusal must come first, before anything looks like work"
    )
    # The message names BOTH flags and says why, or it is a puzzle.
    assert "--memory" in captured.err
    assert "--no-memory" in captured.err
    assert "cannot propose" in captured.err


def test_the_refusal_is_in_the_handler_not_only_the_parser(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """L6's lesson, made a test: a parser-level control is invisible to any
    caller that builds a `Namespace` itself, and `cmd_cycle` is importable.
    So the guard is asserted through the handler, with the parser bypassed
    entirely."""
    from aef.cli.loop import cmd_cycle

    args = build_parser().parse_args(_argv(repo, tmp_path))
    # Exactly what a caller constructing its own Namespace would leave: the
    # attribute present and falsy, which is what the old `if args.memory`
    # read as "the owner does not want memory".
    args.memory = None
    args.no_memory = False

    assert cmd_cycle(args) == 2
    assert "--no-memory" in capsys.readouterr().err


def test_the_parser_still_accepts_the_bare_form(repo: Path, tmp_path: Path) -> None:
    """Enforcement is deliberately NOT at the parser: `loop cycle`'s flags are
    parsed in several tests that never run the command, and moving the refusal
    into argparse would make those failures about argument shape rather than
    about the control. Pinning this keeps the two levels honest about which
    one is load-bearing."""
    args = build_parser().parse_args(_argv(repo, tmp_path))
    assert args.memory is None and args.no_memory is False


# ---------------------------------------------------------------------------
# What each flag then does
# ---------------------------------------------------------------------------


def test_no_memory_keeps_todays_behaviour_and_says_it_was_asked_for(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    code = main(_argv(repo, tmp_path, "--no-memory"))
    out = capsys.readouterr().out

    assert code == 0
    assert "no memory store configured" in out
    # The difference from before: the summary line says the silence was chosen.
    assert "cycle verdict:" in out
    assert "--no-memory was passed" in out


def test_memory_reaches_the_proposer(repo: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The other half of the reproduction: the same invocation, plus a file
    with one admissible failure record, proposes a candidate."""
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
            "--build-command",
            "python -c pass",
        )
    )
    out = capsys.readouterr().out

    assert "proposed " in out, out
    assert "cycle verdict: proposed " in out
    assert "--no-memory was passed" not in out
    assert code in (0, 1), out  # escalated or rejected; 2 would mean halted


# ---------------------------------------------------------------------------
# The journal — every turn, including the ones that did nothing
# ---------------------------------------------------------------------------


def test_every_cycle_is_journalled_even_when_it_produced_nothing(
    repo: Path, tmp_path: Path
) -> None:
    """`cycle` writes a ledger entry only when it proposes, so a loop that
    produces nothing leaves an audit trail indistinguishable from one nobody
    has ever run. That is exactly how a nightly no-op stayed invisible."""
    from aef.harness import ledger
    from aef.harness.monitoring import read_cycle_attempts

    assert main(_argv(repo, tmp_path, "--no-memory")) == 0

    state = tmp_path / "state"
    assert ledger.read(state) == (), "nothing was proposed, so the ledger is silent"

    (attempt,) = read_cycle_attempts(state)
    assert attempt.proposed is False
    assert "no memory store configured" in attempt.verdict


def test_the_monitor_names_the_loop_that_has_been_producing_nothing(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """End to end at the CLI: three no-op cycles, then `aef loop monitor`
    says so in words. This is the output that would have caught ADR 0165 on
    night three instead of never."""
    for _ in range(3):
        assert main(_argv(repo, tmp_path, "--no-memory")) == 0
    capsys.readouterr()

    code = main(["loop", "monitor", "--repo", str(repo), "--state", str(tmp_path / "state")])
    out = capsys.readouterr().out

    assert code == 0
    assert "cycles run: 3" in out
    assert "last PROPOSED: never" in out
    assert "last KEPT/MERGED: never" in out
    assert "SCHEDULED CYCLE PRODUCING NOTHING" in out


def test_the_monitor_is_quiet_about_a_loop_nobody_has_run(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    code = main(["loop", "monitor", "--repo", str(repo), "--state", str(tmp_path / "state")])
    out = capsys.readouterr().out

    assert code == 0
    assert "cycles run: 0" in out
    assert "SCHEDULED CYCLE PRODUCING NOTHING" not in out, (
        "an unstarted loop is not stale, and warning about it trains the reader to ignore the line"
    )


# ---------------------------------------------------------------------------
# The workflow that had the defect
# ---------------------------------------------------------------------------


def test_this_repos_own_nightly_cycle_passes_a_memory_flag() -> None:
    """The finding was in a YAML file, so the assertion is too. A test that
    only covered the CLI would have left the workflow free to keep doing what
    it was doing, because it never ran in CI's own test job."""
    text = Path(".github/workflows/loop-monitor.yml").read_text()
    cycle_step = text[text.index("aef loop cycle") :]
    step_body = cycle_step[: cycle_step.index("\n      - name:")]

    assert "--memory" in step_body, (
        "the nightly cycle passes no memory flag; it will refuse (and before ADR 0165 it "
        "silently did nothing and exited 0)"
    )
    assert "GITHUB_STEP_SUMMARY" in step_body, (
        "the verdict must be visible in words, not only in a collapsed log"
    )


def test_the_nightly_cycle_does_not_report_an_ordinary_rejection_as_a_halt() -> None:
    """Exit 1 means the candidate was rejected, which is the normal outcome.
    Letting it fail the job would route every ordinary rejection into the
    `Surface a halt` step, and an alarm that fires on the normal case is an
    alarm nobody reads."""
    text = Path(".github/workflows/loop-monitor.yml").read_text()
    assert '"$status" -ge 2' in text
