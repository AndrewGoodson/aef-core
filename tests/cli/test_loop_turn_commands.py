"""Every `aef loop` subcommand that RUNS A TURN, held to the same two rules.

ADR 0165 found this repo's nightly `aef loop cycle` exiting 0 having done
nothing, because `--memory` was absent and silence meant "no memory". It fixed
`cycle`. It did not fix `run`, which reads the same flag through the same
`FileMemoryStore(...) if args.memory else None` expression, had no guard at
all, and journalled nothing whatsoever — so five `loop run --turns 2`
invocations without `--memory` each exited 0, left the state directory
non-existent, and left `aef loop monitor` reporting `cycles run: 0 (last
never)` with no warning. That is the "unstarted versus dead" ambiguity ADR
0165 §2 says it removed, one subcommand over (ADR 0167).

So this file does not test `cycle` and `run` by name and stop there. It
**derives** the list of turn-running subcommands from `aef/cli/loop.py`'s own
AST and asserts the derived list is exactly the list it knows how to invoke —
so a third twin cannot be added without failing here first.
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from aef.cli.loop import EXIT_USAGE
from aef.cli.main import main
from aef.harness.monitoring import read_cycle_attempts

LOOP_CLI = Path("aef/cli/loop.py")

# The two names in `aef.harness.loop` that RUN A TURN — propose, gate, decide.
# `gate` judges a branch that already exists and `monitor`/`status`/`digest`
# report on what happened, so none of them is a chance to propose and none
# belongs in the cycle journal.
TURN_DRIVERS = {"cycle", "run_loop"}


def _turn_running_subcommands() -> set[str]:
    """`{subcommand name}` for every handler in the loop CLI that runs a turn.

    Derived, not listed: the point of this file is that the NEXT command to
    call `run_loop` is caught by a test rather than by a reproduction two
    waves later. A handler qualifies when it imports `cycle` or `run_loop`
    from `aef.harness.loop`; the subcommand name is read from the
    `set_defaults(handler=cmd_x)` line that wires it into argparse.
    """
    tree = ast.parse(LOOP_CLI.read_text(encoding="utf-8"))

    drivers: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("cmd_"):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "aef.harness.loop"
                and any(alias.name in TURN_DRIVERS for alias in node.names)
            ):
                drivers.add(fn.name)

    # `loop_subs.add_parser("cycle", ...)` assigned to `p_cycle`, then
    # `p_cycle.set_defaults(handler=cmd_cycle)`. Walk the parser builder to
    # map one to the other rather than assuming `cmd_x` is subcommand `x`.
    parser_names: dict[str, str] = {}
    handlers: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "add_parser"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
        ):
            parser_names[node.targets[0].id] = str(node.value.args[0].value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set_defaults"
            and isinstance(node.func.value, ast.Name)
        ):
            for kw in node.keywords:
                if kw.arg == "handler" and isinstance(kw.value, ast.Name):
                    handlers[node.func.value.id] = kw.value.id

    return {
        parser_names[var] for var, cmd in handlers.items() if cmd in drivers and var in parser_names
    }


# ---------------------------------------------------------------------------
# How to invoke each of them. Adding a subcommand here is the deliberate act
# the derived-set assertion below forces.
# ---------------------------------------------------------------------------


def _cycle_argv(repo: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "loop",
        "cycle",
        "--repo",
        str(repo),
        "--state",
        str(tmp_path / "state"),
        "--workdir",
        str(tmp_path / "work"),
        *extra,
    ]


def _run_argv(repo: Path, tmp_path: Path, *extra: str) -> list[str]:
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
        "2",
        "--budget-minutes",
        "1",
        *extra,
    ]


ARGV: dict[str, Callable[..., list[str]]] = {"cycle": _cycle_argv, "run": _run_argv}


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


# ---------------------------------------------------------------------------
# The enumeration itself
# ---------------------------------------------------------------------------


def test_the_list_of_turn_running_subcommands_is_derived_not_remembered() -> None:
    """THE guard against a third twin. If someone adds a subcommand that calls
    `run_loop` or `cycle` and does not add it to `ARGV`, this fails — and the
    two tests below then hold it to both rules automatically."""
    derived = _turn_running_subcommands()
    assert derived == set(ARGV), (
        f"aef/cli/loop.py has turn-running subcommand(s) {sorted(derived - set(ARGV))} that "
        f"this file does not exercise. Every command that can propose must refuse without a "
        f"memory flag and must journal its attempt — ADR 0165 fixed one of two and the other "
        f"stayed a silent no-op for a whole wave (ADR 0167)."
    )
    assert derived == {"cycle", "run"}, derived


@pytest.mark.parametrize("command", sorted(ARGV))
def test_every_turn_running_subcommand_refuses_without_a_memory_flag(  # type: ignore[no-untyped-def]
    command: str, repo: Path, tmp_path: Path, capsys
) -> None:
    code = main(ARGV[command](repo, tmp_path))
    captured = capsys.readouterr()

    assert code == EXIT_USAGE, f"`loop {command}` reported success having proposed nothing"
    assert "no memory store configured" not in captured.out, (
        "the refusal must come first, before anything looks like work"
    )
    assert "--memory" in captured.err and "--no-memory" in captured.err
    assert "cannot propose" in captured.err


@pytest.mark.parametrize("command", sorted(ARGV))
def test_every_turn_running_subcommand_journals_its_attempt(
    command: str, repo: Path, tmp_path: Path
) -> None:
    """The journal is the only thing that can tell "ran and produced nothing"
    from "never ran": `cycle` writes a ledger entry only when it PROPOSES, so
    a loop that produces nothing leaves a byte-identical ledger either way."""
    assert main(ARGV[command](repo, tmp_path, "--no-memory")) in (0, 1)

    attempts = read_cycle_attempts(tmp_path / "state")
    assert attempts, f"`loop {command}` journalled nothing; the monitor cannot see it ran"
    assert all(a.command == command for a in attempts), [a.command for a in attempts]
    assert not any(a.proposed for a in attempts)


def test_the_refusal_is_in_the_handler_not_only_the_parser(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """L6's lesson, applied to `run` as ADR 0165 applied it to `cycle`: a
    parser-level control is invisible to any caller that builds its own
    `Namespace`, and `cmd_run` is importable."""
    from aef.cli.loop import cmd_run
    from aef.cli.main import build_parser

    args = build_parser().parse_args(_run_argv(repo, tmp_path))
    args.memory = None
    args.no_memory = False

    assert cmd_run(args) == EXIT_USAGE
    assert "--no-memory" in capsys.readouterr().err


def test_the_parser_still_accepts_run_without_a_memory_flag(repo: Path, tmp_path: Path) -> None:
    """Deliberately not enforced in argparse, for the reason ADR 0165 gives
    for `cycle`: several tests parse these flags without running anything, and
    moving the refusal into the parser would make those failures about
    argument shape rather than about the control."""
    from aef.cli.main import build_parser

    args = build_parser().parse_args(_run_argv(repo, tmp_path))
    assert args.memory is None and args.no_memory is False


# ---------------------------------------------------------------------------
# `run` journals per TURN, and the monitor's alarm counts turns
# ---------------------------------------------------------------------------


def test_a_run_journals_one_attempt_per_turn_not_one_per_invocation(
    repo: Path, tmp_path: Path
) -> None:
    """Three `loop run --no-memory` invocations, each stopping after its first
    turn produced nothing, are three quiet attempts — which is what the
    staleness threshold of three consecutive quiet cycles is counting."""
    for i in range(3):
        assert (
            main(_run_argv(repo, tmp_path, "--no-memory", "--workdir", str(tmp_path / f"w{i}")))
            == 0
        )

    attempts = read_cycle_attempts(tmp_path / "state")
    assert len(attempts) == 3, [a.verdict for a in attempts]
    assert all("turn 1" in a.verdict for a in attempts), [a.verdict for a in attempts]
    assert all("--no-memory was passed" in a.verdict for a in attempts)


def test_the_monitor_names_a_run_that_has_been_producing_nothing(  # type: ignore[no-untyped-def]
    repo: Path, tmp_path: Path, capsys
) -> None:
    """End to end at the CLI, the output that would have caught this on the
    third night. Before the fix the same three invocations left the state
    directory non-existent and the monitor said `cycles run: 0`."""
    for i in range(3):
        assert (
            main(_run_argv(repo, tmp_path, "--no-memory", "--workdir", str(tmp_path / f"w{i}")))
            == 0
        )
    capsys.readouterr()

    assert main(["loop", "monitor", "--repo", str(repo), "--state", str(tmp_path / "state")]) == 0
    out = capsys.readouterr().out
    assert "cycles run: 3" in out
    assert "SCHEDULED CYCLE PRODUCING NOTHING" in out


# ---------------------------------------------------------------------------
# F6 — the paths that RAISE are journalled too
# ---------------------------------------------------------------------------


def test_a_halted_cycle_is_journalled(repo: Path, tmp_path: Path) -> None:
    """Reproduced at the CLI before the fix: with the kill switch engaged,
    `loop cycle` printed `HALTED:`, exited 2, and `cycles.jsonl` DID NOT
    EXIST. `record_cycle_attempt` sat after the `try`, so every raising path
    returned before it — and a nightly cycle dying the same way every night
    left a journal as empty as one nobody had ever run."""
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "HALTED").write_text("owner stopped it\n")

    assert main(_cycle_argv(repo, tmp_path, "--no-memory")) == 2

    (attempt,) = read_cycle_attempts(state)
    assert attempt.proposed is False
    assert "HALTED" in attempt.verdict and "LoopHaltedError" in attempt.verdict
    assert "owner stopped it" in attempt.verdict


def test_a_halted_run_is_journalled(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "HALTED").write_text("owner stopped it\n")

    assert main(_run_argv(repo, tmp_path, "--no-memory")) == 2

    (attempt,) = read_cycle_attempts(state)
    assert attempt.proposed is False
    assert "HALTED" in attempt.verdict and attempt.command == "run"


@pytest.mark.parametrize(
    "exception",
    ["PolicyConfigError", "CorpusGraphMismatchError", "LoopHaltedError", "RuntimeError"],
)
def test_every_exception_path_out_of_the_driver_is_journalled(
    exception: str, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three named refusals `cmd_cycle` catches, plus one it does not.

    Injected at the collaborator boundary — `aef.harness.loop.cycle`, which
    `cmd_cycle` calls — rather than mocking `cmd_cycle` itself. Two of these
    are reachable end to end only behind a blessed baseline whose drift is
    inside budget and a corpus recorded from the right graph; the kill-switch
    path above IS the end-to-end reproduction, and this pins the rest of the
    `except` ladder including the one that re-raises.
    """
    import aef.harness.loop as harness_loop
    from aef.harness.loop import CorpusGraphMismatchError, PolicyConfigError
    from aef.harness.monitoring import LoopHaltedError

    kinds = {
        "PolicyConfigError": PolicyConfigError,
        "CorpusGraphMismatchError": CorpusGraphMismatchError,
        "LoopHaltedError": LoopHaltedError,
        "RuntimeError": RuntimeError,
    }

    def boom(*_a: object, **_k: object) -> None:
        raise kinds[exception]("injected")

    monkeypatch.setattr(harness_loop, "cycle", boom)

    # `main()` catches everything and reports exit 1, so the unnamed case is
    # indistinguishable from a rejection at the exit code — which is exactly
    # why the journal has to carry the exception's name.
    assert main(_cycle_argv(repo, tmp_path, "--no-memory")) in (1, 2, 3)

    (attempt,) = read_cycle_attempts(tmp_path / "state")
    assert attempt.proposed is False
    assert exception in attempt.verdict, attempt.verdict
    assert attempt.command == "cycle"


# ---------------------------------------------------------------------------
# R3 — an exception is not a rejection (ADR 0167)
#
# `aef/cli/main.py`'s catch-all returns 1 for ANY exception, and 1 is also
# `EXIT_REJECTED`: "this candidate is no good, the system is working". The
# rendered nightly workflow fails the job on `status >= 2`. So a bad config, a
# missing corpus, an import error, a provider that is down, and the
# `agents.migrated.graph` placeholder whose `build_graph()` raises
# `NotImplementedError` all read as a healthy rejection and the job stays
# green — and, because the exception escaped before the attempt was
# journalled, `cycles.jsonl` gained nothing and the staleness alarm could
# never fire for those nights either.
#
#   $ aef loop cycle ... --module agents.migrated.graph --memory <m>
#   REAL EXIT=1
#   journal exists: False
# ---------------------------------------------------------------------------

PLACEHOLDER = (
    'def build_graph():\n    raise NotImplementedError("convert your call sites into nodes")\n'
)


@pytest.mark.parametrize("command", sorted(ARGV))
def test_an_exception_from_the_graph_is_exit_error_not_a_rejection(
    command: str, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aef.harness.loop import EXIT_ERROR, EXIT_REJECTED

    package = tmp_path / "placeholder_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "graph.py").write_text(PLACEHOLDER)
    monkeypatch.syspath_prepend(str(tmp_path))

    code = main(ARGV[command](repo, tmp_path, "--no-memory", "--module", "placeholder_pkg.graph"))

    assert code == EXIT_ERROR, (
        f"`loop {command}` reported {code}; {EXIT_REJECTED} is 'the candidate was rejected, "
        f"the system is working' and the nightly workflow stays green on it"
    )
    assert code != EXIT_REJECTED
    (attempt,) = read_cycle_attempts(tmp_path / "state")
    assert "NotImplementedError" in attempt.verdict, attempt.verdict
    assert attempt.proposed is False


def test_the_rendered_nightly_workflow_would_fail_the_job_on_that_code() -> None:
    """The rule is in a file this worker does not edit, so it is READ. An exit
    code chosen without checking the rule that consumes it is how exit 1 came
    to mean two things."""
    from aef.harness.loop import EXIT_ERROR, EXIT_HALTED, EXIT_OK, EXIT_REJECTED

    rendered = Path("aef/cli/adopt_loop.py").read_text()
    assert '"$status" -ge 2' in rendered, (
        "the rendered workflow's failure rule changed; the exit codes below were chosen "
        "against `status >= 2`"
    )
    assert EXIT_ERROR >= 2, "an error that cannot fail the job is an error nobody sees"
    assert EXIT_ERROR not in (EXIT_OK, EXIT_REJECTED, EXIT_HALTED), (
        "a crash and a halt call for different actions — fix the invocation versus release "
        "the kill switch — so they must be distinguishable"
    )
