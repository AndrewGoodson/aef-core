"""Sandbox — what it enforces, and what it refuses to pretend it enforces.

The honesty tests matter as much as the enforcement ones. A sandbox that
claims network isolation it does not have is worse than no sandbox, because
the claim is what downstream decisions trust.
"""

import os
import sys
from pathlib import Path

import pytest

from aef.harness.sandbox import (
    NetworkPolicy,
    SandboxPolicy,
    SandboxUnavailableError,
    _scrubbed_env,
    run_sandboxed,
)

UNISOLATED = NetworkPolicy.ACKNOWLEDGED_UNISOLATED


def _policy(**overrides: object) -> SandboxPolicy:
    defaults: dict[str, object] = {"network": UNISOLATED, "timeout_s": 30.0}
    defaults.update(overrides)
    return SandboxPolicy(**defaults)  # type: ignore[arg-type]


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


# --------------------------------------------------------------------------
# Refusing to run without the isolation it was asked to provide
# --------------------------------------------------------------------------


def test_the_default_policy_refuses_to_exist_without_attested_isolation() -> None:
    # Fails at construction, not at first use: a policy that can never run
    # is a configuration error, and discovering it at the first gate
    # invocation is discovering it too late.
    with pytest.raises(SandboxUnavailableError, match="network isolation"):
        SandboxPolicy()


def test_attested_isolation_permits_the_strict_policy() -> None:
    policy = SandboxPolicy(network_isolation_attested=True)
    assert policy.network is NetworkPolicy.REQUIRE_ISOLATED


def test_running_unisolated_requires_saying_so(tmp_path: Path) -> None:
    result = run_sandboxed(_py("print(1)"), workdir=tmp_path, policy=_policy())
    assert result.ok
    assert result.capabilities.network_isolated is False


def test_capabilities_never_claim_filesystem_isolation(tmp_path: Path) -> None:
    # `cwd` is a default, not a jail — nothing stops an absolute path. Real
    # confinement is container-level, so this stays False in-process.
    result = run_sandboxed(_py("print(1)"), workdir=tmp_path, policy=_policy())
    assert result.capabilities.filesystem_isolated is False


def test_a_nonpositive_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        _policy(timeout_s=0)


def test_a_missing_workdir_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(SandboxUnavailableError, match="workdir"):
        run_sandboxed(_py("print(1)"), workdir=tmp_path / "nope", policy=_policy())


# --------------------------------------------------------------------------
# Environment scrubbing — the credential control that genuinely works
# --------------------------------------------------------------------------


def test_a_credential_in_the_parent_environment_does_not_reach_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-inherited")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "also-secret")

    result = run_sandboxed(
        _py(
            "import os;print(os.environ.get('ANTHROPIC_API_KEY'));"
            "print(os.environ.get('AWS_SECRET_ACCESS_KEY'))"
        ),
        workdir=tmp_path,
        policy=_policy(),
    )
    assert result.ok
    assert result.stdout.split() == ["None", "None"]
    assert result.capabilities.env_scrubbed


def test_the_allowlisted_variables_do_reach_the_child(tmp_path: Path) -> None:
    result = run_sandboxed(
        _py("import os;print(bool(os.environ.get('PATH')))"), workdir=tmp_path, policy=_policy()
    )
    assert result.stdout.strip() == "True"


def test_the_environment_we_hand_over_contains_only_allowlisted_keys() -> None:
    # This is the contract the sandbox can actually keep: the mapping passed
    # to execve. See the test below for why that is not the same as the
    # child's final environment.
    policy = _policy()
    assert set(_scrubbed_env(policy)) <= set(policy.env_allowlist) | set(policy.extra_env)


def test_the_os_may_inject_variables_we_did_not_pass(tmp_path: Path) -> None:
    # Documented limit, verified rather than assumed: macOS's loader adds
    # __CF_USER_TEXT_ENCODING to every process after execve. `env_scrubbed`
    # therefore means "nothing is INHERITED from the parent", not "the
    # child's environment equals the allowlist" — a distinction that matters
    # only because claiming the stronger version would be false.
    result = run_sandboxed(
        _py("import os;print(sorted(os.environ))"), workdir=tmp_path, policy=_policy()
    )
    seen = set(eval(result.stdout.strip()))  # noqa: S307 - our own literal output
    injected = seen - set(SandboxPolicy(network=UNISOLATED).env_allowlist)
    assert all(name.startswith("__") for name in injected), f"unexpected leak: {injected}"


def test_no_secret_bearing_parent_variable_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The property that actually matters, stated directly.
    for name in ("OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SESSION_TOKEN", "NEO4J_PASSWORD"):
        monkeypatch.setenv(name, "leaked")
    result = run_sandboxed(
        _py("import os;print([k for k,v in os.environ.items() if v == 'leaked'])"),
        workdir=tmp_path,
        policy=_policy(),
    )
    assert result.stdout.strip() == "[]"


def test_extra_env_can_be_injected_deliberately(tmp_path: Path) -> None:
    result = run_sandboxed(
        _py("import os;print(os.environ['CANDIDATE_ID'])"),
        workdir=tmp_path,
        policy=_policy(extra_env={"CANDIDATE_ID": "cand-42"}),
    )
    assert result.stdout.strip() == "cand-42"


# --------------------------------------------------------------------------
# Confinement, timeout, failure reporting
# --------------------------------------------------------------------------


def test_the_child_starts_in_the_scratch_directory(tmp_path: Path) -> None:
    result = run_sandboxed(_py("import os;print(os.getcwd())"), workdir=tmp_path, policy=_policy())
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


def test_a_hanging_process_is_killed_and_reported(tmp_path: Path) -> None:
    result = run_sandboxed(
        _py("import time;time.sleep(30)"), workdir=tmp_path, policy=_policy(timeout_s=1.0)
    )
    assert result.timed_out
    assert not result.ok
    assert result.duration_s < 15


def test_a_nonzero_exit_is_reported_not_raised(tmp_path: Path) -> None:
    result = run_sandboxed(_py("raise SystemExit(3)"), workdir=tmp_path, policy=_policy())
    assert result.returncode == 3
    assert not result.ok


def test_stderr_is_captured(tmp_path: Path) -> None:
    result = run_sandboxed(
        _py("import sys;sys.stderr.write('boom')"), workdir=tmp_path, policy=_policy()
    )
    assert "boom" in result.stderr


def test_the_child_runs_in_its_own_process_group(tmp_path: Path) -> None:
    # setsid() is what lets a timeout kill grandchildren too, rather than
    # orphaning them to keep running after the gate has "finished".
    result = run_sandboxed(
        _py("import os;print(os.getpgid(0) == os.getpid())"), workdir=tmp_path, policy=_policy()
    )
    assert result.stdout.strip() == "True"


def test_rlimits_applied_are_reported_rather_than_assumed(tmp_path: Path) -> None:
    # macOS honours a different subset than Linux. The result reports what
    # was actually accepted so a caller can tell what it got.
    result = run_sandboxed(_py("print(1)"), workdir=tmp_path, policy=_policy())
    assert isinstance(result.capabilities.rlimits_applied, tuple)
    assert set(result.capabilities.rlimits_applied) <= {
        "RLIMIT_FSIZE",
        "RLIMIT_NPROC",
        "RLIMIT_CORE",
        "RLIMIT_AS",
    }


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX only")
def test_a_runaway_write_hits_the_file_size_limit(tmp_path: Path) -> None:
    result = run_sandboxed(
        _py("open('big','wb').write(b'x' * (200 * 1024 * 1024))"),
        workdir=tmp_path,
        policy=_policy(max_file_size_bytes=1024 * 1024),
    )
    if "RLIMIT_FSIZE" not in result.capabilities.rlimits_applied:
        pytest.skip("platform did not accept RLIMIT_FSIZE")
    assert not result.ok
