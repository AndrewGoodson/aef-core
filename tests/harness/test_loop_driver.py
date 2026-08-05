"""The loop driver.

M11's acceptance properties. Each is a refusal — a driver that cannot refuse
is not a gate:

  - the kill switch stops it BEFORE anything else happens
  - a broken ledger chain stops it rather than being appended to
  - a Zone B candidate is a security event AND halts the loop
  - a fully passing candidate ESCALATES and does not merge (Tier-1 off)
"""

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aef.harness import ledger
from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult
from aef.harness.git import GitRepo
from aef.harness.loop import (
    EXIT_HALTED,
    EXIT_OK,
    EXIT_REJECTED,
    LoopConfig,
    LoopPaths,
    LoopStateInsideRepoError,
    gate,
    load_observations,
    monitor,
    status,
)
from aef.harness.monitoring import LoopHaltedError
from aef.harness.review import Disposition

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class _Stub(Gate):
    def __init__(self, gate_id: str, outcome: GateOutcome, *, security: bool = False) -> None:
        self.id = gate_id
        self._outcome = outcome
        self._security = security

    def run(self, ctx: GateContext) -> GateResult:
        return GateResult(
            gate=self.id, outcome=self._outcome, reason="stub", security_event=self._security
        )


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "loop@test")
    _git(root, "config", "user.name", "loop")
    (root / "agents").mkdir()
    (root / "aef" / "harness").mkdir(parents=True)
    (root / "agents" / "planner.py").write_text("RETRY_LIMIT = 3\n")
    (root / "aef" / "harness" / "gate.py").write_text("MARKER = 'base'\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def _candidate(repo: GitRepo, files: dict[str, str]) -> None:
    _git(repo.root, "checkout", "-qb", "cand")
    for path, content in files.items():
        target = repo.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "candidate")


def _config(repo: GitRepo, tmp_path: Path, gates: tuple[Gate, ...] | None = None) -> LoopConfig:
    return LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        base_ref="main",
        gates=gates if gates is not None else (_Stub("G0", GateOutcome.PASS),),
    )


def _gate(config: LoopConfig, tmp_path: Path, head: str = "cand"):
    return gate(config, head, now=NOW, workdir=tmp_path / "work")


# --------------------------------------------------------------------------
# Loop state must live outside the repository it judges
# --------------------------------------------------------------------------


def test_loop_state_inside_the_repo_is_refused(repo: GitRepo, tmp_path: Path) -> None:
    """Found by running the driver, not by reading it: with state inside the
    working tree, `git add -A` sweeps the ledger and archive into the
    candidate's own commit, so the audit trail becomes part of what it
    audits and every candidate looks like it touches Zone C."""
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=repo.root / ".loop"),
        gates=(_Stub("G0", GateOutcome.PASS),),
    )
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})

    with pytest.raises(LoopStateInsideRepoError, match="inside the repository"):
        gate(config, "cand", now=NOW, workdir=tmp_path / "work")


def test_the_repo_root_itself_is_refused_as_state(repo: GitRepo, tmp_path: Path) -> None:
    config = LoopConfig(repo=repo, paths=LoopPaths(root=repo.root))
    with pytest.raises(LoopStateInsideRepoError):
        status(config)


def test_status_also_refuses_state_inside_the_repo(repo: GitRepo, tmp_path: Path) -> None:
    # status() is the diagnostic; it must not paper over a misconfiguration
    # that makes every other answer untrustworthy.
    config = LoopConfig(repo=repo, paths=LoopPaths(root=repo.root / "nested" / "state"))
    with pytest.raises(LoopStateInsideRepoError):
        status(config)


def test_state_outside_the_repo_is_accepted(repo: GitRepo, tmp_path: Path) -> None:
    config = LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "elsewhere"))
    assert status(config).ledger_entries == 0


# --------------------------------------------------------------------------
# ACCEPTANCE — the kill switch stops everything, first
# --------------------------------------------------------------------------


def test_an_engaged_kill_switch_stops_the_gate(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    config.paths.kill_switch.engage("gates have a blind spot")
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})

    with pytest.raises(LoopHaltedError, match="blind spot"):
        _gate(config, tmp_path)


def test_the_kill_switch_is_checked_before_anything_is_written(
    repo: GitRepo, tmp_path: Path
) -> None:
    """A halt evaluated after the work is a report, not a stop."""
    config = _config(repo, tmp_path)
    config.paths.kill_switch.engage("halted")
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})

    with pytest.raises(LoopHaltedError):
        _gate(config, tmp_path)

    # Nothing was appended — not even a PROPOSED entry.
    assert ledger.read(config.paths.ledger_dir) == ()


def test_an_engaged_kill_switch_stops_the_monitor(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    config.paths.kill_switch.engage("halted")
    with pytest.raises(LoopHaltedError):
        monitor(config, now=NOW)


# --------------------------------------------------------------------------
# ACCEPTANCE — a broken ledger chain refuses
# --------------------------------------------------------------------------


def test_a_broken_ledger_chain_stops_the_gate(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})
    _gate(config, tmp_path)  # writes some entries

    path = config.paths.ledger_dir / "ledger.jsonl"
    path.write_text(path.read_text().replace("file(s)", "tampered"))

    with pytest.raises(ledger.LedgerTamperedError):
        _gate(config, tmp_path)


def test_a_broken_chain_is_not_appended_to(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})
    _gate(config, tmp_path)

    path = config.paths.ledger_dir / "ledger.jsonl"
    before = path.read_text().replace("file(s)", "tampered")
    path.write_text(before)

    with pytest.raises(ledger.LedgerTamperedError):
        _gate(config, tmp_path)
    assert path.read_text() == before  # unchanged


# --------------------------------------------------------------------------
# ACCEPTANCE — a Zone B candidate is a security event and halts
# --------------------------------------------------------------------------


def test_a_zone_b_candidate_halts_the_loop(repo: GitRepo, tmp_path: Path) -> None:
    """Halt criterion 2: a proposal reaching for the judge is a category
    signal about the proposer, not a fact about this one candidate."""
    from aef.harness.gates.g0_static_safety import G0StaticSafety

    config = _config(repo, tmp_path, gates=(G0StaticSafety(),))
    _candidate(repo, {"aef/harness/gate.py": "MARKER = 'subverted'\n"})

    run = _gate(config, tmp_path)

    assert run.halted
    assert run.exit_code == EXIT_HALTED
    assert config.paths.kill_switch.engaged
    kinds = [e.kind for e in ledger.read(config.paths.ledger_dir)]
    assert ledger.EventKind.REJECTED in kinds
    assert ledger.EventKind.HALTED in kinds


def test_the_halt_reason_names_the_category(repo: GitRepo, tmp_path: Path) -> None:
    from aef.harness.gates.g0_static_safety import G0StaticSafety

    config = _config(repo, tmp_path, gates=(G0StaticSafety(),))
    _candidate(repo, {"aef/harness/gate.py": "MARKER = 'subverted'\n"})
    _gate(config, tmp_path)

    assert "harness" in config.paths.kill_switch.reason


# --------------------------------------------------------------------------
# ACCEPTANCE — a passing candidate escalates, it does not merge
# --------------------------------------------------------------------------


def test_a_fully_passing_candidate_escalates_and_does_not_merge(
    repo: GitRepo, tmp_path: Path
) -> None:
    config = _config(repo, tmp_path, gates=(_Stub("G0", GateOutcome.PASS),))
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})

    run = _gate(config, tmp_path)

    assert run.decision.disposition is Disposition.ESCALATE
    assert run.exit_code == EXIT_OK  # a question is not a failure
    kinds = [e.kind for e in ledger.read(config.paths.ledger_dir)]
    assert ledger.EventKind.ESCALATED in kinds
    assert ledger.EventKind.MERGED not in kinds


def test_tier1_is_off_in_the_default_config(repo: GitRepo, tmp_path: Path) -> None:
    assert _config(repo, tmp_path).tier1_enabled is False


def test_a_rejected_candidate_exits_nonzero(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path, gates=(_Stub("G0", GateOutcome.FAIL),))
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})

    run = _gate(config, tmp_path)

    assert run.decision.disposition is Disposition.REJECT
    assert run.exit_code == EXIT_REJECTED
    assert ledger.EventKind.REJECTED in [e.kind for e in ledger.read(config.paths.ledger_dir)]


def test_a_rejection_does_not_halt_the_loop(repo: GitRepo, tmp_path: Path) -> None:
    # An ordinary rejection is the system working, not a reason to stop.
    config = _config(repo, tmp_path, gates=(_Stub("G0", GateOutcome.FAIL),))
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})
    _gate(config, tmp_path)

    assert not config.paths.kill_switch.engaged


# --------------------------------------------------------------------------
# The ledger records every transition
# --------------------------------------------------------------------------


def test_every_transition_is_recorded(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path, gates=(_Stub("G0", GateOutcome.PASS),))
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})
    _gate(config, tmp_path)

    kinds = [e.kind for e in ledger.read(config.paths.ledger_dir)]
    assert kinds == [
        ledger.EventKind.PROPOSED,
        ledger.EventKind.GATED,
        ledger.EventKind.ESCALATED,
    ]


def test_the_proposal_id_pins_the_candidate_commit(repo: GitRepo, tmp_path: Path) -> None:
    # "branch X was gated" is not enough — branches move.
    config = _config(repo, tmp_path)
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})
    _gate(config, tmp_path)

    proposal_id = ledger.read(config.paths.ledger_dir)[0].proposal_id
    assert proposal_id.startswith("cand@")
    assert repo.rev_parse("cand").startswith(proposal_id.split("@")[1])


def test_all_six_gates_are_registered_by_default(repo: GitRepo, tmp_path: Path) -> None:
    # A gate with no evidence configured must FAIL, not be omitted — omitting
    # would make a candidate look gated when it was not.
    config = LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"))
    assert {g.id for g in config.default_gates()} == {"G0", "G1", "G2", "G3", "G4", "G5"}


# --------------------------------------------------------------------------
# Sandbox attestation
# --------------------------------------------------------------------------


def test_the_sandbox_is_unisolated_unless_attested(repo: GitRepo, tmp_path: Path) -> None:
    policy = _config(repo, tmp_path).sandbox_policy()
    assert policy.network_isolation_attested is False


def test_attesting_isolation_produces_the_strict_policy(repo: GitRepo, tmp_path: Path) -> None:
    from aef.harness.sandbox import NetworkPolicy

    config = LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"), network_isolated=True)
    policy = config.sandbox_policy()
    assert policy.network is NetworkPolicy.REQUIRE_ISOLATED
    assert policy.network_isolation_attested is True


# --------------------------------------------------------------------------
# monitor / status / observations
# --------------------------------------------------------------------------


def test_a_missing_observations_file_reads_as_empty(tmp_path: Path) -> None:
    assert load_observations(tmp_path / "nope.jsonl") == ()


def test_a_malformed_observation_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "obs.jsonl"
    path.write_text('{"at": "not-a-date", "passed": true}\n')
    with pytest.raises(ValueError, match="malformed observation"):
        load_observations(path)


def test_observations_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "obs.jsonl"
    path.write_text('{"at": "2026-03-01T13:00:00+00:00", "passed": true, "cost_tokens": 5}\n')
    obs = load_observations(path)
    assert len(obs) == 1
    assert obs[0].passed and obs[0].cost_tokens == 5


def test_monitor_with_no_merges_does_nothing(repo: GitRepo, tmp_path: Path) -> None:
    run = monitor(_config(repo, tmp_path), now=NOW)
    assert run.checked == 0
    assert run.exit_code == EXIT_OK


def test_status_reports_a_broken_ledger_without_raising(repo: GitRepo, tmp_path: Path) -> None:
    # `status` is what you run when something is wrong, so it must work when
    # the ledger is broken and the loop is halted.
    config = _config(repo, tmp_path)
    _candidate(repo, {"agents/planner.py": "RETRY_LIMIT = 4\n"})
    _gate(config, tmp_path)
    path = config.paths.ledger_dir / "ledger.jsonl"
    path.write_text(path.read_text().replace("file(s)", "tampered"))

    result = status(config)
    assert not result.ledger_ok
    assert "BROKEN" in result.render()


def test_status_reports_an_engaged_kill_switch(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    config.paths.kill_switch.engage("stopped")
    result = status(config)
    assert result.halted
    assert "ENGAGED" in result.render()


def test_status_on_a_clean_empty_state(repo: GitRepo, tmp_path: Path) -> None:
    result = status(_config(repo, tmp_path))
    assert not result.halted
    assert result.ledger_ok
    assert result.ledger_entries == 0


def test_the_digest_is_readable_while_the_loop_is_halted(repo: GitRepo, tmp_path: Path) -> None:
    # Reading the record of why the loop halted is exactly what you want to
    # do while it is halted.
    from aef.harness.loop import digest as loop_digest

    config = _config(repo, tmp_path)
    config.paths.kill_switch.engage("halted")
    result = loop_digest(config, since=NOW - timedelta(days=7), until=NOW)
    assert result.proposed == 0


# --------------------------------------------------------------------------
# ADR 0063 — G3's cohort floor must not move with the cohort
# --------------------------------------------------------------------------


def test_the_driver_does_not_pass_the_cohort_size_as_the_minimum(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The builder generates exactly cohort_size members, so wiring
    min_cohort_size=cohort_size made `len(cohort) < min_cohort_size`
    unsatisfiable: a cohort of 2 passed, with p95 over two samples. A floor
    that moves with the thing it floors is not a floor."""
    import inspect

    import aef.harness.loop as loop_module

    source = inspect.getsource(loop_module._gates_with_evidence)
    assert "min_cohort_size=config.cohort_size" not in source


def test_an_undersized_cohort_config_is_refused_at_construction(
    repo: GitRepo, tmp_path: Path
) -> None:
    # Every candidate would be rejected for an undersized cohort; better to
    # say so once than to discover it at the first gate run.
    with pytest.raises(ValueError, match="below G3's minimum"):
        LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"), cohort_size=2)


def test_the_default_cohort_size_meets_the_floor(repo: GitRepo, tmp_path: Path) -> None:
    from aef.harness.gates.g3_improvement import DEFAULT_MIN_COHORT_SIZE

    config = LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"))
    assert config.cohort_size >= DEFAULT_MIN_COHORT_SIZE
