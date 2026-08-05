"""The seams between CLI commands.

Every component here is individually tested and green. These tests exist
because the last three defects all lived in the joins: the cohort floor was
dead because of how the driver wired a correct gate, the reflection wire was
missing because two correct components were never connected, and both of the
defects below survived every component-level test in the suite.
"""

import inspect
from pathlib import Path

import pytest


def _source_of(name: str) -> str:
    import aef.cli.loop as loop_cli

    fn = getattr(loop_cli, name)
    return inspect.getsource(fn)


# --------------------------------------------------------------------------
# ADR 0069 defect 1 — the cycle's memory store was constructed empty
# --------------------------------------------------------------------------


def test_the_cycle_does_not_construct_its_own_empty_memory_store() -> None:
    """`cmd_cycle` built `InMemoryMemoryStore()` inline, so the evidence the
    proposer reads was empty on every invocation and the reflection wire
    (ADR 0065) could never fire from the CLI. Running the real command
    printed 'no admissible failure memory' and always would have."""
    source = _source_of("cmd_cycle")
    assert "InMemoryMemoryStore()" not in source, (
        "a memory store constructed inside the command is empty by definition; "
        "the proposer would never see a recorded failure"
    )


def test_the_cycle_accepts_a_memory_path() -> None:
    import aef.cli.loop as loop_cli

    parser_source = inspect.getsource(loop_cli.add_loop_parser)
    assert "--memory" in parser_source, "the cycle needs somewhere durable to read memory from"


# --------------------------------------------------------------------------
# ADR 0069 defect 2 — harvest bypassed the kill switch
# --------------------------------------------------------------------------


def test_harvest_checks_the_kill_switch() -> None:
    """Harvest writes to `corpus/`, which IS the evidence every behavioural
    gate is measured against. It took no `--state`, so a halted loop could
    still have its gate evidence modified."""
    source = _source_of("cmd_harvest")
    assert "kill_switch" in source or "_preflight" in source, (
        "harvest modifies gate evidence and must not run while the loop is halted"
    )


def test_harvest_accepts_the_state_directory() -> None:
    import aef.cli.loop as loop_cli

    parser_source = inspect.getsource(loop_cli.add_loop_parser)
    harvest_block = parser_source[parser_source.index('"harvest"') :]
    harvest_block = harvest_block[: harvest_block.index("set_defaults")]
    assert "_common(p_harvest)" in parser_source or "--state" in harvest_block


# --------------------------------------------------------------------------
# Every loop subcommand that mutates state must be behind the kill switch
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["cmd_gate", "cmd_monitor", "cmd_cycle", "cmd_harvest"])
def test_every_mutating_command_is_behind_the_kill_switch(command: str) -> None:
    """`status` and `digest` are deliberately readable while halted — reading
    why the loop stopped is what you do when it stops. Everything that WRITES
    must refuse."""
    source = _source_of(command)
    reaches_preflight = any(
        marker in source
        for marker in ("kill_switch", "_preflight", "loop_gate", "loop_monitor", "loop_cycle")
    )
    assert reaches_preflight, f"{command} mutates state without a kill-switch check"


def test_status_and_digest_remain_readable_while_halted() -> None:
    for command in ("cmd_status", "cmd_digest"):
        source = _source_of(command)
        assert "LoopHaltedError" not in source, (
            f"{command} must work while halted; it is what you run to find out why"
        )


# --------------------------------------------------------------------------
# ADR 0069 defect 3 — G1's defaults assumed aef-core's own tree
# --------------------------------------------------------------------------


def test_g1_defaults_do_not_assume_this_repos_layout() -> None:
    """`mypy --strict aef` ran against the ADOPTING repo, which has no `aef/`
    directory — so G1 rejected every candidate in every adopting repo,
    forever, and silently, because the failure looks like an ordinary gate
    rejection."""
    from aef.harness.gates.g1_builds import DEFAULT_BUILD_COMMANDS

    flat = " ".join(" ".join(c) for c in DEFAULT_BUILD_COMMANDS)
    assert "aef" not in flat, f"G1's default build commands are repo-specific: {flat}"


def test_build_commands_are_configurable_from_the_cli() -> None:
    import aef.cli.loop as loop_cli

    parser_source = inspect.getsource(loop_cli.add_loop_parser)
    assert parser_source.count("--build-command") >= 2, "gate and cycle both need it"


def test_configured_build_commands_reach_g1() -> None:
    from aef.harness.gates.g1_builds import G1Builds
    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths

    config = LoopConfig(
        repo=GitRepo(root=Path("/nowhere")),
        paths=LoopPaths(root=Path("/tmp/state-not-in-repo")),
        build_commands=(("python", "-m", "pytest", "-q", "tests/"),),
    )
    g1 = next(g for g in config.default_gates() if g.id == "G1")
    assert isinstance(g1, G1Builds)
    assert g1.commands == (("python", "-m", "pytest", "-q", "tests/"),)


def test_no_build_commands_falls_back_to_the_default() -> None:
    from aef.harness.gates.g1_builds import DEFAULT_BUILD_COMMANDS, G1Builds
    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths

    config = LoopConfig(
        repo=GitRepo(root=Path("/nowhere")),
        paths=LoopPaths(root=Path("/tmp/state-not-in-repo")),
    )
    g1 = next(g for g in config.default_gates() if g.id == "G1")
    assert isinstance(g1, G1Builds)
    assert g1.commands == DEFAULT_BUILD_COMMANDS
