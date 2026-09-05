"""The halt channel (ADR 0195).

Reproduced first, by running. Before this existed, `aef loop digest` printed

    - Halt channel configured: NO

on every run of every repo, and the line was accurate: `_halt` engaged the
kill switch, wrote a ledger entry, and told nobody. A halt at 3am was
discovered by someone noticing the loop had stopped.

`HaltNotifier` had a webhook field, and it had no production caller — nothing
in `aef/` ever called `notify`, and the URL came from an environment variable
no workflow set. So the honest reading of the old line is not "the owner did
not configure it" but "there was nothing an owner could configure and have run".

What is asserted here is the whole path and its boundaries: the channel is
read from the BASE REF, it is invoked with the reason and the ledger's last
entry, a failure is recorded beside the halt and never replaces it, and the
digest reports the channel AND the last notifications — because a configured
channel that fails looks identical, from the config alone, to a working one.

No test here reaches a network. The channel is `/bin/sh -c 'cat >> file'`,
which is a real subprocess doing a real thing.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.config.factory import build_halt_channel
from aef.config.loader import load_agent_config_text
from aef.config.schema import HaltChannelConfig
from aef.harness import ledger
from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, _halt, _halt_channel, digest
from aef.harness.monitoring import HaltChannel, HaltNotifier, build_digest

NOW = datetime(2026, 9, 5, 3, 0, tzinfo=UTC)
WINDOW = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 8, tzinfo=UTC))
REASON = "a gated change regressed live; the gates have a blind spot"

BASE_YAML = """extends: _base
model_provider: {impl: claude_code, model: claude-opus-5, fallback: []}
memory: {impl: in_memory}
evaluator: {suites: []}
tools: {allow: []}
policies: {require_hitl_above_risk: 0.0, forbid: []}
objectives: "answer the question"
evolution: {enabled: false}
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _sh_append(target: Path) -> str:
    """The test channel: a real subprocess, no network. Written as YAML so the
    whole path from `aef.yaml` to the process is exercised."""
    return (
        "halt_channel:\n"
        f"  argv: ['/bin/sh', '-c', 'cat >> {target}', '--', '{{reason}}']\n"
        "  timeout_s: 20.0\n"
    )


def _repo(tmp_path: Path, yaml_text: str, *, branch_yaml: str | None = None) -> LoopConfig:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "aef.yaml").write_text(yaml_text, encoding="utf-8")
    (repo / "agents").mkdir()
    (repo / "agents" / "graph.py").write_text("AGENT = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    if branch_yaml is not None:
        _git(repo, "checkout", "-qb", "cand")
        (repo / "aef.yaml").write_text(branch_yaml, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "candidate")
    return LoopConfig(
        repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"), base_ref="main"
    )


def _digest_lines(config: LoopConfig) -> list[str]:
    return digest(config, since=WINDOW[0], until=WINDOW[1]).render().splitlines()


# --------------------------------------------------------------------------
# The state this replaces
# --------------------------------------------------------------------------


def test_with_no_channel_the_halt_still_happens_and_nothing_external_runs(
    tmp_path: Path,
) -> None:
    """The reproduction. The loop halts correctly and tells nobody, and the
    digest says so in both places an owner might look."""
    config = _repo(tmp_path, BASE_YAML)
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))

    assert config.paths.kill_switch.engaged
    (entry,) = ledger.read(config.paths.ledger_dir)
    assert entry.kind is ledger.EventKind.HALTED
    assert "halt_notification" not in entry.detail

    lines = _digest_lines(config)
    assert "- Halt channel configured: NO" in lines
    assert any("No halt channel is configured" in line for line in lines)
    assert any("NOT SENT" in line for line in lines), (
        "the digest counts the halt and does not say the halt reached nobody"
    )


# --------------------------------------------------------------------------
# The channel, end to end
# --------------------------------------------------------------------------


def test_a_configured_channel_is_invoked_with_the_reason_and_the_last_entry(
    tmp_path: Path,
) -> None:
    """The whole path: `aef.yaml` -> `_halt_channel` -> a real subprocess."""
    paged = tmp_path / "paged.txt"
    config = _repo(tmp_path, BASE_YAML + _sh_append(paged))

    # A prior entry, so the notification has a last-entry to carry. This is
    # the field that answers "which candidate, and when" without the reader
    # opening the ledger.
    ledger.append(
        config.paths.ledger_dir,
        kind=ledger.EventKind.MERGED,
        at=NOW,
        proposal_id="p-42",
        summary="merged the candidate that later regressed",
        detail={"archive_version": 3},
    )
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))

    assert paged.is_file(), "the configured command was never run"
    payload = paged.read_text(encoding="utf-8")
    assert REASON in payload
    assert '"event": "halt"' in payload
    assert '"proposal_id": "p-42"' in payload, (
        "the ledger's last entry did not reach the channel, so the page says the loop "
        "stopped and not what it stopped on"
    )


def test_the_reason_slot_is_substituted_in_argv(tmp_path: Path) -> None:
    """`{reason}` is a slot, like `impl: command`'s `{prompt}`. A channel that
    wants a subject line rather than a JSON body uses it."""
    seen: list[tuple[str, ...]] = []
    channel = HaltChannel(
        argv=("/usr/bin/true", "--subject", "{reason}"),
        runner=lambda argv, payload, timeout: seen.append(argv) or (0, "ok"),  # type: ignore[func-returns-value]
    )
    channel.notify("the gates have a blind spot", at=NOW, last_entry=None)
    assert seen == [("/usr/bin/true", "--subject", "the gates have a blind spot")]


def test_the_notification_is_recorded_in_the_ledger(tmp_path: Path) -> None:
    """Durable, because the process that halted is gone by the time anyone
    reads the digest."""
    paged = tmp_path / "paged.txt"
    config = _repo(tmp_path, BASE_YAML + _sh_append(paged))
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))

    (entry,) = ledger.read(config.paths.ledger_dir)
    notification = entry.detail["halt_notification"]
    assert notification["delivered"] is True
    assert notification["command"] == "/bin/sh"


def test_only_argv0_is_recorded_not_the_arguments(tmp_path: Path) -> None:
    """The ledger is committed evidence and an owner's command line is where a
    token ends up when somebody writes one there."""
    secret = "hunter2-do-not-commit"
    channel = HaltChannel(
        argv=("/usr/bin/true", "--token", secret), runner=lambda argv, payload, timeout: (0, "ok")
    )
    payload = channel.notify(REASON, at=NOW, last_entry=None).to_payload()
    assert secret not in repr(payload)
    assert secret not in channel.description


# --------------------------------------------------------------------------
# Failure never masks the halt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ("/nonexistent/pager",),  # the program is not there
        (sys.executable, "-c", "raise SystemExit(7)"),  # it runs and fails
    ],
)
def test_a_failing_channel_is_recorded_and_the_halt_stands(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    config = _repo(tmp_path, BASE_YAML)
    config = LoopConfig(
        repo=config.repo,
        paths=config.paths,
        base_ref="main",
        halt_channel=HaltChannel(argv=argv, timeout_s=20.0),
    )
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))

    assert config.paths.kill_switch.engaged, "a failing channel unhalted the loop"
    (entry,) = ledger.read(config.paths.ledger_dir)
    assert entry.summary == REASON
    assert entry.detail["halt_notification"]["delivered"] is False

    lines = _digest_lines(config)
    assert any("FAILED" in line for line in lines)
    assert any("Fix the command, not the loop" in line for line in lines)


def test_a_channel_that_hangs_does_not_hang_the_halt(tmp_path: Path) -> None:
    """Bounded by `timeout_s`, and the timeout is a recorded failure rather
    than an exception that would replace the halt."""
    config = _repo(tmp_path, BASE_YAML)
    config = LoopConfig(
        repo=config.repo,
        paths=config.paths,
        base_ref="main",
        halt_channel=HaltChannel(
            argv=(sys.executable, "-c", "import time; time.sleep(30)"), timeout_s=0.5
        ),
    )
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))

    (entry,) = ledger.read(config.paths.ledger_dir)
    assert entry.detail["halt_notification"]["delivered"] is False
    assert "Timeout" in entry.detail["halt_notification"]["detail"]


def test_the_kill_switch_is_engaged_before_the_channel_runs(tmp_path: Path) -> None:
    """Order matters: a channel that takes its whole timeout must not leave a
    window in which the loop is still runnable."""
    engaged: list[bool] = []
    config = _repo(tmp_path, BASE_YAML)
    switch = config.paths.kill_switch
    config = LoopConfig(
        repo=config.repo,
        paths=config.paths,
        base_ref="main",
        halt_channel=HaltChannel(
            argv=("/usr/bin/true",),
            runner=lambda argv, payload, timeout: engaged.append(switch.engaged) or (0, "ok"),  # type: ignore[func-returns-value]
        ),
    )
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))
    assert engaged == [True]


# --------------------------------------------------------------------------
# Where it is read from
# --------------------------------------------------------------------------


def test_a_candidate_cannot_silence_its_own_halt(tmp_path: Path) -> None:
    """Read from the BASE REF, like every other rule a candidate is judged by.
    A channel a candidate could delete on its own branch is one it would."""
    paged = tmp_path / "paged.txt"
    config = _repo(tmp_path, BASE_YAML + _sh_append(paged), branch_yaml=BASE_YAML)

    channel = _halt_channel(config)
    assert channel is not None, "the base ref's channel was lost"
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))
    assert paged.is_file()


def test_the_digest_and_the_halt_resolve_the_same_channel(tmp_path: Path) -> None:
    """The failure this feature closes, one level up: a digest saying `yes`
    while a halt finds nothing to run would be a worse lie than `NO`."""
    paged = tmp_path / "paged.txt"
    config = _repo(tmp_path, BASE_YAML + _sh_append(paged))

    lines = _digest_lines(config)
    described = next(line for line in lines if line.startswith("- Halt channel configured:"))
    assert "yes — /bin/sh" in described

    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))
    assert paged.is_file(), "the digest described a channel the halt did not run"


def test_an_unreadable_config_reports_no_channel_rather_than_raising(tmp_path: Path) -> None:
    """The halt matters more than the notification. A malformed `aef.yaml`
    must not stop a halt from being recorded."""
    config = _repo(tmp_path, "not: valid: yaml: at: all:\n")
    assert _halt_channel(config) is None
    _halt(config, at=NOW, proposal_id="(monitor)", reasons=(REASON,))
    assert config.paths.kill_switch.engaged
    assert len(ledger.read(config.paths.ledger_dir)) == 1


def test_no_config_file_at_all_is_no_channel(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("no aef.yaml here\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    config = LoopConfig(
        repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"), base_ref="main"
    )
    assert _halt_channel(config) is None


# --------------------------------------------------------------------------
# The config block
# --------------------------------------------------------------------------


def test_the_block_loads_from_a_real_aef_yaml() -> None:
    config = load_agent_config_text(
        BASE_YAML + "halt_channel: {argv: ['/usr/bin/logger', '-t', 'aef', '{reason}']}\n",
        source="test",
    )
    assert config.halt_channel is not None
    channel = build_halt_channel(config.halt_channel)
    assert channel is not None
    assert channel.argv == ("/usr/bin/logger", "-t", "aef", "{reason}")
    assert channel.timeout_s == 30.0


def test_an_absent_block_builds_nothing_rather_than_a_default() -> None:
    """A channel this repo invented would be an alarm the owner never chose
    and cannot be reached by — worse than the honest `NO` it replaces."""
    assert load_agent_config_text(BASE_YAML, source="test").halt_channel is None
    assert build_halt_channel(None) is None


@pytest.mark.parametrize(
    "block",
    [
        "halt_channel: {argv: []}\n",
        "halt_channel: {argv: ['  ']}\n",
        "halt_channel: {argv: ['/usr/bin/true'], timeout_s: 0}\n",
        "halt_channel: {argv: ['/usr/bin/true'], timeout_s: -1}\n",
    ],
)
def test_a_channel_that_could_never_run_is_refused_at_load_time(block: str) -> None:
    """An unconfigured alarm that stays quiet is worse than none, because it
    looks like a working one. A block that validates and cannot run is exactly
    that shape."""
    from aef.config.loader import AgentConfigError

    with pytest.raises((AgentConfigError, ValueError)):
        load_agent_config_text(BASE_YAML + block, source="test")


def test_an_unknown_key_in_the_block_is_refused() -> None:
    from aef.config.loader import AgentConfigError

    with pytest.raises(AgentConfigError):
        load_agent_config_text(
            BASE_YAML + "halt_channel: {argv: ['/usr/bin/true'], retries: 3}\n", source="test"
        )


def test_the_channel_object_refuses_the_same_things_the_schema_does() -> None:
    """One rule, two doors (ADR 0091). A hand-built channel must fail the same
    way a bad `aef.yaml` does."""
    with pytest.raises(ValueError, match="tell nobody"):
        HaltChannel(argv=())
    with pytest.raises(ValueError, match="timeout"):
        HaltChannel(argv=("/usr/bin/true",), timeout_s=0)
    with pytest.raises(ValueError):
        HaltChannelConfig(argv=[])


# --------------------------------------------------------------------------
# The notifier and the digest
# --------------------------------------------------------------------------


def test_the_notifier_counts_a_command_channel_as_configured() -> None:
    """`aef loop digest` reads `notifier.configured`; a notifier that only knew
    about the webhook would report `NO` for a repo with a working channel."""
    assert not HaltNotifier().configured
    assert HaltNotifier(channel=HaltChannel(argv=("/usr/bin/true",))).configured
    assert HaltNotifier(webhook_url="https://example.invalid/hook").configured


def test_the_notifier_runs_both_channels_and_writes_halt_md(tmp_path: Path) -> None:
    posted: list[str] = []
    ran: list[tuple[str, ...]] = []
    notifier = HaltNotifier(
        webhook_url="https://example.invalid/hook",
        poster=lambda url, body: posted.append(body),
        channel=HaltChannel(
            argv=("/usr/bin/true",),
            runner=lambda argv, payload, timeout: ran.append(argv) or (0, "ok"),  # type: ignore[func-returns-value]
        ),
    )
    done = notifier.notify(REASON, repo_root=tmp_path, at=NOW, last_entry=None)

    assert (tmp_path / "HALT.md").is_file()
    assert ran and posted
    assert any("delivered" in line for line in done)


def test_a_webhook_that_throws_does_not_stop_the_command_channel(tmp_path: Path) -> None:
    ran: list[tuple[str, ...]] = []

    def explode(url: str, body: str) -> None:
        raise RuntimeError("no network")

    notifier = HaltNotifier(
        webhook_url="https://example.invalid/hook",
        poster=explode,
        channel=HaltChannel(
            argv=("/usr/bin/true",),
            runner=lambda argv, payload, timeout: ran.append(argv) or (0, "ok"),  # type: ignore[func-returns-value]
        ),
    )
    done = notifier.notify(REASON, repo_root=tmp_path, at=NOW, last_entry=None)
    assert ran, "the command channel was skipped because the webhook failed"
    assert any("POST FAILED" in line for line in done)


def test_the_digest_reports_at_most_the_last_n_notifications() -> None:
    entries = tuple(
        ledger.LedgerEntry(
            sequence=i + 1,
            kind=ledger.EventKind.HALTED,
            at=NOW,
            proposal_id=f"p-{i}",
            summary="halted",
            detail={
                "halt_notification": {
                    "at": NOW.isoformat(),
                    "command": "/usr/bin/logger",
                    "delivered": True,
                    "detail": f"exit 0 ({i})",
                }
            },
        )
        for i in range(9)
    )
    report = build_digest(
        entries,
        since=WINDOW[0],
        until=WINDOW[1],
        halt_channel="/usr/bin/logger (2 argument(s))",
        max_halt_notifications=3,
    )
    assert len(report.halt_notifications) == 3
    assert "(8)" in report.halt_notifications[-1], "the OLDEST three were kept, not the newest"
    assert report.halt_channel_configured is True, (
        "a described channel must imply a configured one, or the digest contradicts itself"
    )


def test_the_json_digest_carries_the_channel_too() -> None:
    import json

    report = build_digest(
        (), since=WINDOW[0], until=WINDOW[1], halt_channel="/usr/bin/logger (2 argument(s))"
    )
    payload = json.loads(report.to_json())
    assert payload["halt_channel_configured"] is True
    assert payload["halt_channel"].startswith("/usr/bin/logger")
