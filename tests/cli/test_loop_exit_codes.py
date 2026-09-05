"""A crash is EXIT_ERROR on EVERY `aef loop` subcommand (ADR 0182, K3-1).

THE DEFECT, reproduced at the CLI before anything changed. Eleven of the
thirteen `aef loop` subcommands let an exception reach `aef/cli/main.py`'s
catch-all, which prints `error: <exc>` and returns **1** — and 1 is also
`EXIT_REJECTED`, "the candidate was rejected, the system is working":

    EXIT_REJECTED=1  EXIT_ERROR=3

    $ aef loop score agents.demo.graph --corpus <a plain file> --splits bogus
    error: 'bogus' is not a valid Split
    exit=1   <- EXIT_REJECTED (a verdict on a candidate)

    $ aef loop record agents.demo.graph --corpus <a path under a plain file> \\
        --scenario-id s-1 --objective 'do a thing'
    error: [Errno 20] Not a directory: '.../afile.txt/under-a-file/train'
    exit=1   <- EXIT_REJECTED (a verdict on a candidate)

    $ aef loop harvest agents.demo.no_such_module --repo … --state … \\
        --runs … --corpus …
    error: cannot import 'agents.demo.no_such_module': No module named …
    exit=1   <- EXIT_REJECTED (a verdict on a candidate)

That is ADR 0167's R3 — a crash's remedy is not a rejection's — still standing
for the majority of the surface after G1a fixed `cycle`/`run` and ADR 0167
fixed `doctor`/`bless`. ADR 0178 wrote the words for exit 3 into the rendered
nightly workflow ("the cycle crashed; no kill switch is set, fix the
invocation") and recorded this as its "Still open" item.

The fix is a wrapper applied to every handler `add_loop_parser` registers, so
a fourteenth subcommand cannot forget. Everything below derives its list from
the REAL parser.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from aef.cli.loop import EXIT_USAGE, LOOP_TURN_COMMANDS
from aef.cli.main import build_parser, main
from aef.harness.loop import EXIT_ERROR, EXIT_REJECTED
from aef.harness.monitoring import read_cycle_attempts

MODULE = "agents.demo.graph"


def _crashing_args(**overrides: object) -> argparse.Namespace:
    """A Namespace that satisfies every FLAG guard and supplies nothing else.

    `--memory`/`--no-memory` (ADR 0165/0167) and `--state`/`--no-loop-state`
    (ADR 0141) are refusals a handler makes BEFORE it does any work, and each
    returns a code of its own that this fix must not disturb — so they are
    answered here, and the first argument any handler actually reads then
    raises `AttributeError`. One instrument for all thirteen: a hand-built
    failure per subcommand would be thirteen different tests wearing one name.
    """
    return argparse.Namespace(no_memory=True, no_loop_state=True, **overrides)


def _loop_handlers() -> dict[str, object]:
    """Every `aef loop` handler, keyed by the name a user types. Derived from
    the built parser and recursing into `corpus`, which is a group."""
    found: dict[str, object] = {}

    def walk(subs: argparse._SubParsersAction[argparse.ArgumentParser], prefix: str) -> None:
        for name, sub in subs.choices.items():
            handler = sub.get_default("handler")
            if handler is None:
                for action in sub._actions:
                    if isinstance(action, argparse._SubParsersAction):
                        walk(action, f"{prefix}{name} ")
                continue
            found[f"{prefix}{name}"] = handler

    for action in build_parser()._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        loop = action.choices.get("loop")
        if loop is None:
            continue
        for inner in loop._actions:
            if isinstance(inner, argparse._SubParsersAction):
                walk(inner, "")
    assert found, "no `aef loop` handlers found"
    return found


def test_the_enumeration_finds_every_documented_subcommand() -> None:
    """The list is derived, so this asserts the DERIVATION rather than the
    list: `loop --help` names thirteen, `corpus` is a group whose one leaf is
    `reconcile`, and the walk must reach it."""
    names = set(_loop_handlers())

    assert {"gate", "monitor", "digest", "status", "record", "bootstrap"} <= names
    assert {"score", "skills", "harvest", "cycle", "run", "bless", "doctor"} <= names
    assert "corpus reconcile" in names, "the nested `loop corpus` handler was not reached"


@pytest.mark.parametrize("name", sorted(_loop_handlers()))
def test_every_loop_subcommand_reports_a_crash_as_an_error(  # type: ignore[no-untyped-def]
    name: str, capsys
) -> None:
    """One raising invocation per subcommand, and the same one for all of them.

    `_crashing_args()` makes every handler raise `AttributeError` on the first
    argument it reads — a genuine unexpected exception, of exactly the kind
    that used to reach `main()`'s catch-all. The property under test is the
    CODE, so an artificial fault is the right instrument: a per-subcommand
    hand-built failure would test thirteen different things.
    """
    handler = _loop_handlers()[name]
    assert callable(handler)

    code = handler(_crashing_args())

    assert code == EXIT_ERROR, (
        f"`aef loop {name}` reported a crash as {code}; {EXIT_REJECTED} means 'the "
        f"candidate was rejected, the system is working' and the nightly rule is >= 2"
    )
    assert "AttributeError" in capsys.readouterr().err, "the exception must be NAMED"


def test_the_wrapper_names_the_exception_type_not_just_its_message(  # type: ignore[no-untyped-def]
    capsys,
) -> None:
    """`error: 'bogus' is not a valid Split` does not say what kind of failure
    it was. `error (ValueError): …` does, and the type is what tells a reader
    whether to fix the invocation or the repo."""
    handler = _loop_handlers()["status"]
    assert callable(handler)
    handler(_crashing_args())

    assert capsys.readouterr().err.startswith("error (AttributeError): ")


# ---------------------------------------------------------------------------
# The three reproductions, end to end through `main`
# ---------------------------------------------------------------------------


def test_score_reports_a_crash_as_an_error(tmp_path: Path) -> None:
    plain = tmp_path / "afile.txt"
    plain.write_text("not a directory\n")

    code = main(["loop", "score", MODULE, "--corpus", str(plain), "--splits", "bogus"])

    assert code == EXIT_ERROR


def test_record_reports_a_crash_as_an_error(tmp_path: Path) -> None:
    plain = tmp_path / "afile.txt"
    plain.write_text("not a directory\n")

    code = main(
        [
            "loop",
            "record",
            MODULE,
            "--corpus",
            str(plain / "under-a-file"),
            "--scenario-id",
            "s-1",
            "--objective",
            "do a thing",
        ]
    )

    assert code == EXIT_ERROR


def test_harvest_reports_a_crash_as_an_error(tmp_path: Path) -> None:
    code = main(
        [
            "loop",
            "harvest",
            "agents.demo.no_such_module",
            "--repo",
            str(tmp_path / "repo"),
            "--state",
            str(tmp_path / "state"),
            "--runs",
            str(tmp_path / "runs"),
            "--corpus",
            str(tmp_path / "corpus"),
        ]
    )

    assert code == EXIT_ERROR


# ---------------------------------------------------------------------------
# What did NOT change
# ---------------------------------------------------------------------------


def test_a_named_refusal_is_still_a_rejection(tmp_path: Path) -> None:
    """The wrapper catches what nothing else caught; it does not swallow the
    refusals each handler names. `loop corpus reconcile` on a directory that
    is not there is an operator error about the argument they typed, and 1 —
    "no" — is the right answer to it."""
    code = main(["loop", "corpus", "reconcile", "--corpus", str(tmp_path / "nope")])

    assert code == EXIT_REJECTED


def test_a_usage_refusal_is_still_exit_two(tmp_path: Path) -> None:
    """`_require_memory_flag` returns EXIT_USAGE before anything can raise, and
    the wrapper never sees it (ADR 0165/0167)."""
    code = main(
        [
            "loop",
            "cycle",
            "--repo",
            str(tmp_path),
            "--state",
            str(tmp_path / "state"),
            "--workdir",
            str(tmp_path / "w"),
        ]
    )

    assert code == EXIT_USAGE


def test_a_top_level_command_still_returns_one(tmp_path: Path) -> None:
    """WHY THE FIX IS NOT IN `main()`'s CATCH-ALL, asserted rather than argued
    in a comment. `aef adopt`/`migrate`/`init`/`run`/`eval`/`trace`/`doctor`
    issue no verdicts, so 1 is the ordinary "this command failed" of any CLI
    and nothing distinguishes a rejection from a crash for them. Changing the
    catch-all would have moved all seven onto a vocabulary they do not use.
    """
    code = main(["eval", "--checkpoints-dir", str(tmp_path / "nope"), "--run-id", "r1"])

    assert code == 1, "the global catch-all's code is unchanged"


# ---------------------------------------------------------------------------
# The turn-running ones are journalled, whatever killed them
# ---------------------------------------------------------------------------


def test_the_turn_running_commands_are_the_two_that_run_turns() -> None:
    assert LOOP_TURN_COMMANDS == {"cycle", "run"}
    assert LOOP_TURN_COMMANDS <= set(_loop_handlers())


@pytest.mark.parametrize("name", sorted(LOOP_TURN_COMMANDS))
def test_a_crash_in_a_turn_running_command_is_journalled(name: str, tmp_path: Path) -> None:
    """G1a journalled `cycle`/`run` from inside their own `try`. The wrapper
    covers what happens BEFORE it — a `--state` that cannot be parsed, an
    argument read outside the block — because a nightly turn that died is
    still a slot that produced nothing, and a `cycles.jsonl` byte-identical to
    one nobody ever ran is the ambiguity the journal exists to remove."""
    handler = _loop_handlers()[name]
    assert callable(handler)
    state = tmp_path / "state"

    code = handler(_crashing_args(state=str(state)))

    assert code == EXIT_ERROR
    attempts = read_cycle_attempts(state)
    assert len(attempts) == 1, attempts
    assert attempts[0].command == name
    assert not attempts[0].proposed
    assert "AttributeError" in attempts[0].verdict


def test_a_crash_in_a_reporting_command_is_not_journalled(tmp_path: Path) -> None:
    """`gate` judges a branch that already exists and `status`/`digest`/
    `monitor` report on what happened; none is a chance to propose, so none
    belongs in the cycle journal (the rule `test_loop_turn_commands.py`
    derives from this module's AST)."""
    handler = _loop_handlers()["gate"]
    assert callable(handler)
    state = tmp_path / "state"

    assert handler(_crashing_args(state=str(state))) == EXIT_ERROR
    assert read_cycle_attempts(state) == ()
