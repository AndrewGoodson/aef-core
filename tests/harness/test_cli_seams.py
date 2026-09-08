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


# --------------------------------------------------------------------------
# ADR 0141 — nothing consumed `Preflight.ready`
# --------------------------------------------------------------------------


def test_cycle_and_gate_report_unmet_obligations() -> None:
    """`Preflight.ready` had exactly one reader in `aef/`: `cmd_doctor`.
    ADR 0137 §2 said "`Preflight.ready` is false while it stands, so the gates
    refuse". Reproduced otherwise — `loop doctor` exit 1 with obligation 6
    red, then `loop cycle` proposes and gates the same repo.

    The decision (ADR 0141) was NOT to make them blocking: obligation 4 is
    only knowable at this boundary, `harness.loop.cycle()` is importable and
    would stay unguarded, three of the six enforce themselves later anyway,
    and turning five long-advisory obligations into blockers is an owner's
    call. So the surface must at least SAY it."""
    for command in ("cmd_cycle", "cmd_gate"):
        assert "_warn_unmet_obligations" in _source_of(command), command


def test_the_warning_is_advisory_and_says_so() -> None:
    source = _source_of("_warn_unmet_obligations")
    assert "ADVISORY" in source
    assert "return EXIT" not in source, (
        "this is a warning by decision; making it a refusal is an owner's call, "
        "not a side effect (ADR 0141)"
    )


def test_preflight_ready_has_a_reader_that_is_not_only_doctor() -> None:
    """The property is the wiring: `result.unmet` must be read somewhere other
    than `cmd_doctor`, or the obligations are computed for nobody."""
    readers = [
        name
        for name in ("cmd_cycle", "cmd_gate", "cmd_doctor", "_warn_unmet_obligations")
        if "unmet" in _source_of(name) or "result.ready" in _source_of(name)
    ]
    assert set(readers) >= {"cmd_doctor", "_warn_unmet_obligations"}


# --------------------------------------------------------------------------
# ADR 0141 — `corpus.check_never_shrinks` had no production caller
# --------------------------------------------------------------------------


def test_the_loop_preflight_checks_the_corpus_never_shrank() -> None:
    """Reproduced: delete the two scenarios the agent fails, `aef loop score`
    rises 0.6667 to 1.0000, exit 0, nothing complains — while
    `recorder.refuse_existing_ids` justified its own rule by citing this
    guard. It had test callers and no production one."""
    import aef.harness.loop as loop_harness

    source = inspect.getsource(loop_harness._preflight)
    # Was `"check_never_shrinks(config.corpus" in source` — a pin on ONE LINE's
    # spelling, which a reformat broke while the call it guards was untouched
    # (the call gained a `baseline_ref=` argument in ADR 0204 and wrapped).
    # Normalise the whitespace so the assertion is about the call, not the
    # line breaks.
    flat = " ".join(source.split())
    called = flat.replace("( ", "(")
    assert "check_never_shrinks(config.corpus" in called
    assert "baseline_ref=config.base_ref" in flat, (
        "the refusal's remedy depends on where the baseline came from (ADR 0204)"
    )
    assert "archive.check_never_shrinks" in source, "the archive check must still be there"


def test_a_shrunken_corpus_stops_a_cycle(tmp_path: Path) -> None:
    """End to end through the real driver, not a source assertion."""
    from datetime import UTC, datetime

    from aef.harness.corpus import CorpusShrankError, Scenario, Split, load_corpus, save_scenario
    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths, _preflight
    from aef.state import AEFState

    corpus_root = tmp_path / "corpus"
    for sid in ("keep-me", "delete-me"):
        save_scenario(
            corpus_root,
            Scenario(
                id=sid,
                split=Split.TRAIN,
                graph_id="g",
                graph_version="1",
                initial_state=AEFState(run_id=sid, agent_id="a", objective="o"),
                trace=(),
                recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
        )

    def config() -> LoopConfig:
        return LoopConfig(
            repo=GitRepo(root=tmp_path / "repo"),
            paths=LoopPaths(root=tmp_path / "state"),
            corpus=load_corpus(corpus_root),
        )

    (tmp_path / "repo").mkdir()
    _preflight(config())  # the unshrunken corpus passes

    (corpus_root / "train" / "delete-me.json").unlink()
    with pytest.raises(CorpusShrankError, match="delete-me"):
        _preflight(config())
