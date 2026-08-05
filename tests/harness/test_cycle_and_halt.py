"""The autonomous cycle, and getting a halt in front of the owner.

The cycle's tests are all refusals: what it declines to do matters more than
what it does, because the thing it does is change code.
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import ledger
from aef.harness.git import GitRepo
from aef.harness.loop import CycleRun, LoopConfig, LoopPaths, cycle
from aef.harness.monitoring import Digest, HaltNotifier, LoopHaltedError
from aef.services.memory.in_memory import InMemoryMemoryStore

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 3\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def _config(repo: GitRepo, tmp_path: Path) -> LoopConfig:
    return LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"), base_ref="main")


def _cycle(config: LoopConfig, tmp_path: Path, **kw: object) -> CycleRun:
    return cycle(config, now=NOW, workdir=tmp_path / "work", **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# What the cycle refuses to do
# --------------------------------------------------------------------------


def test_a_halted_loop_does_nothing(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    config.paths.kill_switch.engage("gates have a blind spot")

    with pytest.raises(LoopHaltedError):
        _cycle(config, tmp_path)

    assert ledger.read(config.paths.ledger_dir) == ()


def test_a_broken_ledger_chain_stops_the_cycle(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.PROPOSED,
        at=NOW,
        proposal_id="p1",
        summary="seed",
    )
    path = config.paths.ledger_dir / "ledger.jsonl"
    path.write_text(path.read_text().replace("seed", "tampered"))

    with pytest.raises(ledger.LedgerTamperedError):
        _cycle(config, tmp_path)


def test_no_memory_store_produces_no_candidate(repo: GitRepo, tmp_path: Path) -> None:
    run = _cycle(_config(repo, tmp_path), tmp_path)
    assert run.proposed is None
    assert any("nothing to learn from" in line for line in run.lines)


def test_no_admissible_failure_memory_produces_no_candidate(repo: GitRepo, tmp_path: Path) -> None:
    """The proposer does not speculate. No recorded failures means no
    hypothesis, which is a legitimate outcome and not an error."""
    run = _cycle(_config(repo, tmp_path), tmp_path, memory=InMemoryMemoryStore())

    assert run.proposed is None
    assert run.exit_code == 0
    assert any("no admissible failure memory" in line for line in run.lines)


def test_the_cycle_reports_what_it_verified(repo: GitRepo, tmp_path: Path) -> None:
    run = _cycle(_config(repo, tmp_path), tmp_path, memory=InMemoryMemoryStore())
    assert any("ledger verified" in line for line in run.lines)


def test_the_cycle_never_pushes(repo: GitRepo, tmp_path: Path) -> None:
    # Creating a local branch needs no repository permission; pushing does,
    # and the gate job must never have it (ADR 0057).
    import inspect

    import aef.harness.loop as loop_module

    source = inspect.getsource(loop_module._materialise_candidate_branch)
    assert '"push"' not in source and "'push'" not in source


def test_the_cycle_proposes_at_most_one_candidate(repo: GitRepo, tmp_path: Path) -> None:
    import inspect

    import aef.harness.loop as loop_module

    source = inspect.getsource(loop_module.cycle)
    assert "proposals[0]" in source, "the cycle must take one proposal, not iterate"


# --------------------------------------------------------------------------
# Q-A5 — getting a halt in front of the owner
# --------------------------------------------------------------------------


def test_a_halt_writes_a_file_at_the_repo_root(tmp_path: Path) -> None:
    actions = HaltNotifier().notify("blind spot", repo_root=tmp_path, at=NOW)

    halt = tmp_path / "HALT.md"
    assert halt.is_file()
    assert "blind spot" in halt.read_text()
    assert any("HALT.md" in a for a in actions)


def test_an_unconfigured_channel_says_so_loudly(tmp_path: Path) -> None:
    """An unconfigured alarm that stays quiet is worse than none, because it
    looks like a working one."""
    actions = HaltNotifier().notify("reason", repo_root=tmp_path, at=NOW)
    assert any("NO HALT CHANNEL CONFIGURED" in a for a in actions)


def test_a_configured_channel_is_posted_to(tmp_path: Path) -> None:
    sent: list[tuple[str, str]] = []
    notifier = HaltNotifier(
        webhook_url="https://example.invalid/hook",
        poster=lambda url, body: sent.append((url, body)),
    )

    actions = notifier.notify("gates have a blind spot", repo_root=tmp_path, at=NOW)

    assert sent and "blind spot" in sent[0][1]
    assert any("posted" in a for a in actions)


def test_a_failing_webhook_does_not_hide_the_halt(tmp_path: Path) -> None:
    def explode(url: str, body: str) -> None:
        raise RuntimeError("network down")

    notifier = HaltNotifier(webhook_url="https://example.invalid/hook", poster=explode)
    actions = notifier.notify("reason", repo_root=tmp_path, at=NOW)

    assert (tmp_path / "HALT.md").is_file(), "the file must be written regardless"
    assert any("FAILED" in a and "still stands" in a for a in actions)


def test_no_webhook_url_ships_in_this_repo() -> None:
    # The URL is owner configuration living outside the repository.
    assert HaltNotifier().webhook_url is None


# --------------------------------------------------------------------------
# The digest names the two ways this loop can be quietly inert
# --------------------------------------------------------------------------


def test_the_digest_warns_when_no_halt_channel_is_configured() -> None:
    rendered = Digest(since=NOW, until=NOW, halt_channel_configured=False).render()
    assert "No halt channel is configured" in rendered
    assert "you will find out by noticing it stopped" in rendered


def test_the_digest_is_quiet_when_a_channel_exists() -> None:
    rendered = Digest(since=NOW, until=NOW, halt_channel_configured=True, runs_recorded=5).render()
    assert "No halt channel is configured" not in rendered


def test_the_digest_warns_when_no_production_runs_were_recorded() -> None:
    # A repo that never passes --record-runs gets a corpus that never grows,
    # silently (owed by ADR 0066).
    rendered = Digest(since=NOW, until=NOW, runs_recorded=0).render()
    assert "No production runs were recorded" in rendered


def test_the_digest_reports_both_counts() -> None:
    rendered = Digest(since=NOW, until=NOW, runs_recorded=12, halt_channel_configured=True).render()
    assert "Production runs recorded: 12" in rendered
    assert "Halt channel configured: yes" in rendered
