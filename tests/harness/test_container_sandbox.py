"""Milestone 4: containment that is containment.

Split deliberately in two.

The **flag tests** run everywhere and pin the command line, because every flag
in it is a control and a silently dropped one leaves a boundary that reads as
present. The **container tests** need a real runtime and are skipped without
one — and the skip is the honest outcome, not a hidden pass: what they assert
cannot be asserted by a mock, since the whole question is whether the runtime
does what its flags say.

Both directions of the network probe are exercised. "The connection failed" is
also what a broken image, a stopped daemon and an offline host look like, so an
isolation test that only checks the isolated case proves nothing. That negative
control was run by hand before `container.py` was written:

    docker run --rm --network none  ... -> network blocked: OSError
    docker run --rm                 ... -> network reachable
"""

from pathlib import Path

import pytest

from aef.harness.container import (
    NETWORK_PROBE,
    PROBE_BLOCKED_CODE,
    WORKDIR_MOUNT,
    ContainerRuntime,
    available_runtimes,
    container_argv,
    detect_container_runtime,
    run_containerized,
    verify_network_isolation,
)
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy, SandboxUnavailableError

IMAGE = "python:3.13-slim"

_RUNTIMES = available_runtimes()
needs_container = pytest.mark.skipif(
    not _RUNTIMES, reason="no container runtime with a responsive daemon"
)


def _policy(**kw: object) -> SandboxPolicy:
    kw.setdefault("network", NetworkPolicy.ACKNOWLEDGED_UNISOLATED)
    return SandboxPolicy(**kw)  # type: ignore[arg-type]


def _argv(policy: SandboxPolicy | None = None, workdir: Path | None = None) -> list[str]:
    return container_argv(
        ["python", "-c", "print(1)"],
        runtime=ContainerRuntime(binary="docker", image=IMAGE),
        policy=policy or _policy(),
        workdir=workdir or Path("/tmp"),
    )


# --------------------------------------------------------------------------
# The command line. Every flag is a control.
# --------------------------------------------------------------------------


def test_every_containment_flag_is_present() -> None:
    """Named one by one. A test asserting only `--network none` would let the
    other four be dropped by a refactor without anything failing."""
    line = " ".join(_argv())
    for flag in (
        "--network none",  # the whole point
        "--rm",  # no state left for the next candidate
        "--read-only",  # the filesystem confinement `cwd` never gave
        "--cap-drop ALL",  # a candidate that can raise privileges undid the boundary
        "--security-opt no-new-privileges",
    ):
        assert flag in line, f"missing containment flag: {flag}"


def test_the_workspace_is_the_only_writable_mount() -> None:
    argv = _argv(workdir=Path("/tmp"))
    mounts = [argv[i + 1] for i, token in enumerate(argv) if token == "--volume"]
    assert len(mounts) == 1, f"expected exactly one mount, got {mounts}"
    assert mounts[0].endswith(f":{WORKDIR_MOUNT}")
    assert argv[argv.index("--workdir") + 1] == WORKDIR_MOUNT


def test_the_host_environment_is_not_forwarded() -> None:
    """Stronger than the in-process allowlist: the container starts from the
    image's environment, so nothing of the host's is inherited at all."""
    argv = _argv()
    forwarded = [argv[i + 1] for i, token in enumerate(argv) if token == "--env"]
    assert forwarded == []


def test_explicit_extra_env_is_forwarded_and_nothing_else() -> None:
    argv = _argv(_policy(extra_env={"AEF_RUN": "1"}))
    forwarded = [argv[i + 1] for i, token in enumerate(argv) if token == "--env"]
    assert forwarded == ["AEF_RUN=1"]


def test_the_same_policy_fields_bound_both_paths() -> None:
    """`--memory` and `--pids-limit` come from the fields the in-process path
    uses for rlimits, so the two paths bound the same things rather than
    each bounding whatever its own mechanism made easy."""
    argv = _argv(_policy(max_address_space_bytes=512 * 1024 * 1024, max_processes=64))
    assert argv[argv.index("--memory") + 1] == str(512 * 1024 * 1024)
    assert argv[argv.index("--pids-limit") + 1] == "64"


def test_no_pids_limit_when_the_policy_sets_none() -> None:
    """ADR 0093: `max_processes` defaults to None because `RLIMIT_NPROC` is
    per-UID. The container flag must not resurrect a limit the policy
    deliberately declines to set."""
    assert "--pids-limit" not in _argv(_policy(max_processes=None))


def test_the_command_runs_after_the_image() -> None:
    """A flag emitted after the image name is passed to the CONTAINER's
    command, not to the runtime — it would be silently inert."""
    argv = _argv()
    assert argv[argv.index(IMAGE) + 1 :] == ["python", "-c", "print(1)"]


# --------------------------------------------------------------------------
# Degrading loudly
# --------------------------------------------------------------------------


def test_a_runtime_needs_both_a_binary_and_an_image() -> None:
    for binary, image in (("", IMAGE), ("docker", "")):
        with pytest.raises(SandboxUnavailableError):
            ContainerRuntime(binary=binary, image=image)


def test_an_unverified_runtime_does_not_claim_isolation() -> None:
    """The capability report is what a gate outcome is read against. A report
    that overstates is the failure this module exists to end."""
    assert ContainerRuntime(binary="docker", image=IMAGE).verified is False


def test_a_missing_runtime_raises_rather_than_returning_none() -> None:
    """A caller that asked for containment and got a quiet `None` would run
    the candidate anyway (4a: degrade loudly)."""
    with pytest.raises(SandboxUnavailableError, match="not on PATH"):
        detect_container_runtime(IMAGE, binary="definitely-not-a-container-runtime")


def test_the_probe_is_the_real_one_and_reports_a_distinct_code() -> None:
    """Pinned verbatim. A paraphrased probe is how a detector passes its own
    check and is still wrong — three times in this program."""
    assert "socket.create_connection(('1.1.1.1', 53), timeout=5)" in NETWORK_PROBE
    assert f"sys.exit({PROBE_BLOCKED_CODE})" in NETWORK_PROBE
    assert PROBE_BLOCKED_CODE != 0, "a blocked probe must not share an exit code with success"
    assert PROBE_BLOCKED_CODE != 1, "1 is what a crashed interpreter exits with"


# --------------------------------------------------------------------------
# The real thing. Skipped without a runtime, never faked.
# --------------------------------------------------------------------------


@needs_container
def test_network_isolation_verifies_in_both_directions() -> None:
    """The isolated run must fail to connect AND the unisolated one succeed."""
    verify_network_isolation(_RUNTIMES[0], IMAGE)


@needs_container
def test_a_candidate_inside_the_container_cannot_reach_the_network(tmp_path: Path) -> None:
    """Not the probe helper — a run through the actual entry point, with the
    candidate's own code doing the reaching."""
    runtime = detect_container_runtime(IMAGE, verify=False)
    result = run_containerized(
        ["python", "-c", NETWORK_PROBE], workdir=tmp_path, runtime=runtime, policy=_policy()
    )
    assert result.returncode == PROBE_BLOCKED_CODE, (
        f"the candidate reached the network: exit={result.returncode} stderr={result.stderr[:300]}"
    )


@needs_container
def test_the_capability_report_says_isolated_only_when_it_was_measured(tmp_path: Path) -> None:
    """The whole milestone in one assertion: `network_isolated=True`, true."""
    unverified = run_containerized(
        ["python", "-c", "print('ok')"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=False),
        policy=_policy(),
    )
    assert unverified.ok
    assert unverified.capabilities.network_isolated is False, (
        "an unverified runtime claimed isolation it never measured"
    )

    verified = run_containerized(
        ["python", "-c", "print('ok')"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=True),
        policy=_policy(),
    )
    assert verified.ok
    assert verified.capabilities.network_isolated is True
    assert verified.capabilities.filesystem_isolated is True


@needs_container
def test_the_root_filesystem_is_read_only(tmp_path: Path) -> None:
    """`cwd` was never a jail. This is the first run where an absolute path
    outside the workspace actually fails."""
    result = run_containerized(
        ["python", "-c", "open('/escaped', 'w').write('x')"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=False),
        policy=_policy(),
    )
    assert result.returncode != 0
    assert "Read-only file system" in result.stderr or "OSError" in result.stderr


@needs_container
def test_the_workspace_is_writable_and_lands_on_the_host(tmp_path: Path) -> None:
    """The control for the test above: if nothing were writable, the
    read-only assertion would pass for the wrong reason."""
    result = run_containerized(
        ["python", "-c", "open('wrote.txt', 'w').write('hello')"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=False),
        policy=_policy(),
    )
    assert result.ok, result.stderr
    assert (tmp_path / "wrote.txt").read_text() == "hello"


@needs_container
def test_a_timeout_is_reported_as_a_timeout_not_a_broken_harness(tmp_path: Path) -> None:
    result = run_containerized(
        ["python", "-c", "import time; time.sleep(30)"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=False),
        policy=_policy(timeout_s=3.0),
    )
    assert result.timed_out
    assert not result.ok


# --------------------------------------------------------------------------
# The adversarial round for this milestone. Both REPRODUCED first.
# --------------------------------------------------------------------------


@needs_container
def test_a_timed_out_container_is_actually_dead(tmp_path: Path) -> None:
    """REPRODUCED: the timeout killed the `docker run` CLIENT and left the
    container RUNNING — one still alive two seconds after the gate reported a
    timeout. Word for word the defect ADR 0093 found in the in-process path:
    the direct child dies and the real work survives it.

    The daemon owns the container's lifetime, so the only thing that ends it
    is asking the daemon. Asserted against `docker ps`, not against the
    return value, because the return value was already correct while the
    container ran on.
    """
    import subprocess
    import uuid

    # THIS run's container, by a name nobody else can be using. Filtering
    # `docker ps` by the `aef-gate-` prefix (the previous fix) still raced
    # with a concurrent full-suite run of this very test on the same
    # daemon; the fourth flake in one night. The assertion is about the one
    # container this test started, so ask the daemon about exactly that.
    mine = f"aef-gate-test-{uuid.uuid4().hex[:12]}"

    def still_running() -> set[str]:
        out = subprocess.run(
            [_RUNTIMES[0], "ps", "--quiet", "--filter", f"name=^{mine}$"],
            capture_output=True,
            text=True,
            check=False,
        )
        return set(out.stdout.split())

    result = run_containerized(
        ["python", "-c", "import time; time.sleep(60)"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=False),
        policy=_policy(timeout_s=3.0),
        name=mine,
    )
    assert result.timed_out, "the fixture did not time out; this test proves nothing"

    leaked = still_running()
    assert not leaked, f"container {mine} still running after the timeout: {leaked}"


def test_the_run_is_named_so_there_is_something_to_kill() -> None:
    """Without a `--name` there is no handle for the timeout path, and the
    only thing killable is the client."""
    argv = container_argv(
        ["python", "-c", "1"],
        runtime=ContainerRuntime(binary="docker", image=IMAGE),
        policy=_policy(),
        workdir=Path("/tmp"),
        name="aef-gate-abc",
    )
    assert argv[argv.index("--name") + 1] == "aef-gate-abc"


@needs_container
def test_a_missing_image_is_not_reported_as_an_isolation_failure() -> None:
    """REPRODUCED: a bogus image produced "docker did not block egress with
    --network none", which is a statement about isolation the run never
    measured. A refusal that misnames its own cause sends the operator to fix
    the wrong thing (ADR 0074)."""
    with pytest.raises(SandboxUnavailableError, match="could not run image"):
        verify_network_isolation(_RUNTIMES[0], "aef-nonexistent-image:never-built")


@needs_container
def test_a_candidate_cannot_write_to_the_host_outside_the_workspace(tmp_path: Path) -> None:
    """The workspace mount is the only way out, and it goes where it should."""
    escape = Path("/tmp/aef-container-escape-marker")
    if escape.exists():
        escape.unlink()
    result = run_containerized(
        ["python", "-c", f"open({str(escape)!r}, 'w').write('x')"],
        workdir=tmp_path,
        runtime=detect_container_runtime(IMAGE, verify=False),
        policy=_policy(),
    )
    assert result.returncode != 0
    assert not escape.exists(), "a candidate wrote to the host outside its workspace"


# --------------------------------------------------------------------------
# 4c: nothing is weakened because containment now exists
# --------------------------------------------------------------------------


def test_the_static_scan_still_rejects_before_anything_runs() -> None:
    """HARD-STOP 4c. Containment is defence in depth, not a replacement for
    G0 — the zone rule survived three defeats of the import allowlist
    (ADR 0085 -> 0088 -> 0093) precisely because the layers are independent.
    A container that contains a forbidden import is still a rejection.
    """
    from aef.harness.gates.g0_static_safety import FORBIDDEN_AEF_SUBPACKAGES, scan_source

    assert FORBIDDEN_AEF_SUBPACKAGES, "the control is empty"
    findings = scan_source("agents/a.py", b"from aef.harness.loop import gate\n")
    assert findings, "G0 stopped rejecting a forbidden import"


def test_an_image_does_not_let_an_unattested_policy_skip_the_refusal() -> None:
    """`container_image` satisfies REQUIRE_ISOLATED because a container
    PROVIDES isolation — but only by actually building one. A policy naming
    an image nothing can run must still fail, at run time, rather than
    inheriting the exemption and running unisolated."""
    from aef.harness.sandbox import run_sandboxed

    policy = SandboxPolicy(
        network=NetworkPolicy.REQUIRE_ISOLATED, container_image="aef-nonexistent:never-built"
    )
    with pytest.raises(SandboxUnavailableError):
        run_sandboxed(["python", "-c", "print(1)"], workdir=Path("/tmp"), policy=policy)


def test_an_unattested_policy_with_no_image_is_still_refused() -> None:
    """The original guard, unchanged. A process cannot revoke its own network
    access, and adding a container path must not have softened that."""
    with pytest.raises(SandboxUnavailableError, match="not attested"):
        SandboxPolicy(network=NetworkPolicy.REQUIRE_ISOLATED)


def test_the_in_process_path_still_reports_isolation_it_did_not_get() -> None:
    """The honest `False`. A local run without a container still says so,
    which is what makes the container path's `True` worth anything."""
    from aef.harness.sandbox import run_sandboxed

    result = run_sandboxed(["python", "-c", "print(1)"], workdir=Path("/tmp"), policy=_policy())
    assert result.ok
    assert result.capabilities.network_isolated is False
    assert result.capabilities.filesystem_isolated is False
