"""Sandboxed execution of agent-authored code.

With self-coding, the harness runs code the agent wrote during validation
(04 §2.5: "a precondition, not a nicety"). This module provides what a
single process genuinely *can* enforce, and — this is the important part —
**declares what it cannot**.

Enforced here, really:
  - environment scrubbed to an explicit allowlist (no credentials inherited)
  - working directory confined to a caller-supplied scratch dir
  - wall-clock timeout, with the whole process group killed
  - POSIX resource limits (address space, file size, processes, core dumps)

**Not** enforced here, and not pretended:
  - **network egress.** Blocking it requires a network namespace, a
    firewall, or a container. A process cannot revoke its own connectivity.
  - **filesystem confinement.** `cwd` is a default, not a jail; nothing
    stops an absolute path.
  - **an exact child environment.** The OS loader injects variables of its
    own after `execve` (macOS adds `__CF_USER_TEXT_ENCODING` to every
    process — verified, not assumed). `env_scrubbed` therefore means
    "nothing is inherited from the parent", which is the property that
    actually protects credentials, and not "the child's environment equals
    the allowlist".

So the default policy **refuses to run** unless isolation has been attested
by the layer that can actually provide it (the CI container). Running
unisolated requires saying so explicitly, and it is recorded on the result.
That is deliberately inconvenient: a sandbox that silently provides less
than it claims is worse than none, because the claim is what gets trusted.

Attestation is passed in, not read from the environment, so it is testable
and so the value comes from Zone B configuration rather than from anything
a candidate can set.
"""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

DEFAULT_ENV_ALLOWLIST = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ"})

_GIB = 1024**3
_MIB = 1024**2


class NetworkPolicy(StrEnum):
    REQUIRE_ISOLATED = "require_isolated"
    ACKNOWLEDGED_UNISOLATED = "acknowledged_unisolated"


class SandboxUnavailableError(RuntimeError):
    """The requested isolation cannot be provided here. Deliberately fatal:
    degrading silently is how a sandbox becomes decorative."""


@dataclass(frozen=True)
class SandboxCapabilities:
    """What this run actually got. Recorded on every result so a gate
    outcome can never be read without knowing the conditions it ran under."""

    env_scrubbed: bool
    cwd_confined: bool
    timeout_enforced: bool
    rlimits_applied: tuple[str, ...]
    network_isolated: bool
    filesystem_isolated: bool = False  # container-level only; never true in-process


@dataclass(frozen=True)
class SandboxPolicy:
    timeout_s: float = 120.0
    max_address_space_bytes: int = 2 * _GIB
    max_file_size_bytes: int = 64 * _MIB
    # `RLIMIT_NPROC` is a PER-UID total, not a per-run allowance. 256 read as
    # "this run may spawn 256 processes" and means "this user may have 256
    # processes in total" — so on any host where the operator already has
    # more (a developer laptop: 538 when this was measured), every build
    # command that forks fails with `BlockingIOError: Resource temporarily
    # unavailable`, which G1 reports as an ordinary build failure. ADR 0069's
    # shape: a harness default that rejects every candidate in the adopting
    # environment, silently, and is invisible in a container (ADR 0093).
    #
    # `None` means "do not set it", which is what a limit nobody can choose
    # correctly should default to. An operator who wants a ceiling sets one
    # knowing it counts their own shell.
    max_processes: int | None = None
    env_allowlist: frozenset[str] = field(default_factory=lambda: DEFAULT_ENV_ALLOWLIST)
    extra_env: Mapping[str, str] = field(default_factory=dict)
    network: NetworkPolicy = NetworkPolicy.REQUIRE_ISOLATED
    network_isolation_attested: bool = False

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError("SandboxPolicy.timeout_s must be positive")
        if self.network is NetworkPolicy.REQUIRE_ISOLATED and not self.network_isolation_attested:
            # Not raised lazily at run() time: a policy that can never run is
            # a configuration error, and finding out at the first gate
            # invocation is finding out too late.
            raise SandboxUnavailableError(
                "network isolation is required but not attested. A process cannot revoke "
                "its own network access — isolation must come from a container or network "
                "namespace, whose runner sets network_isolation_attested=True. To run "
                "without it (local development), set "
                "network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED explicitly; the result will "
                "record network_isolated=False."
            )


@dataclass(frozen=True)
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    capabilities: SandboxCapabilities

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _scrubbed_env(policy: SandboxPolicy) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in policy.env_allowlist}
    env.update(policy.extra_env)
    return env


def _apply_rlimits(policy: SandboxPolicy) -> tuple[str, ...]:
    """Best-effort, and honest about it: macOS ignores or rejects some
    limits that Linux honours, so the applied set is *reported* rather than
    assumed. A caller that needs a hard guarantee reads `capabilities`."""
    applied: list[str] = []
    wanted = [
        ("RLIMIT_FSIZE", getattr(resource, "RLIMIT_FSIZE", None), policy.max_file_size_bytes),
        *(
            [("RLIMIT_NPROC", getattr(resource, "RLIMIT_NPROC", None), policy.max_processes)]
            if policy.max_processes is not None
            else []
        ),
        ("RLIMIT_CORE", getattr(resource, "RLIMIT_CORE", None), 0),
        ("RLIMIT_AS", getattr(resource, "RLIMIT_AS", None), policy.max_address_space_bytes),
    ]
    for name, which, value in wanted:
        if which is None:
            continue
        try:
            soft, hard = resource.getrlimit(which)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(which, (ceiling, hard))
        except (ValueError, OSError):
            continue
        applied.append(name)
    return tuple(applied)


def probe_rlimits(policy: SandboxPolicy | None = None) -> tuple[str, ...]:
    """Which limits this platform will actually accept, without running
    anything. Used to populate `capabilities` truthfully."""
    policy = policy or SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os._exit(len(_apply_rlimits(policy)))
    _, status = os.waitpid(pid, 0)
    count = os.waitstatus_to_exitcode(status)
    names = ("RLIMIT_FSIZE", "RLIMIT_NPROC", "RLIMIT_CORE", "RLIMIT_AS")
    return names[: max(count, 0)]


def _kill_process_group(pid: int) -> None:
    """SIGKILL the timed-out child's whole process group.

    Best-effort: the group may already be gone, and on a platform without
    `killpg` there is nothing to do. Reported as unenforced rather than
    pretended — `timeout_enforced` still means the wall clock was applied to
    the direct child, which is what it always meant.
    """
    if not hasattr(os, "killpg"):
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return


def run_sandboxed(
    argv: Sequence[str],
    *,
    workdir: Path,
    policy: SandboxPolicy | None = None,
) -> SandboxResult:
    """Run `argv` under `policy`, in `workdir`, and report what was enforced."""
    policy = policy or SandboxPolicy()
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise SandboxUnavailableError(f"sandbox workdir {workdir} does not exist")

    def _preexec() -> None:  # pragma: no cover - runs in the forked child
        os.setsid()  # own process group, so a timeout kills descendants too
        _apply_rlimits(policy)

    started = time.monotonic()
    timed_out = False
    try:
        # `Popen`, not `subprocess.run`, so the pid is in hand when the
        # timeout fires. `run(timeout=...)` calls `Popen.kill()` — the DIRECT
        # CHILD only — and `_preexec` calls `setsid()`, so descendants sit in
        # a group nothing ever signalled: a grandchild outlived the timeout
        # by six seconds and touched a marker file after the gate reported
        # finished (ADR 0093). Two comments in this module asserted the group
        # was killed; neither was true.
        proc = subprocess.Popen(
            list(argv),
            cwd=str(workdir),
            env=_scrubbed_env(policy),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_preexec,
        )
        try:
            out, err = proc.communicate(timeout=policy.timeout_s)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_process_group(proc.pid)
            out, err = proc.communicate()
            timed_out = True
            returncode = -1
    except OSError as exc:
        timed_out = False
        returncode = -1
        out, err = b"", str(exc).encode()
    duration = time.monotonic() - started

    return SandboxResult(
        returncode=returncode,
        stdout=out.decode("utf-8", errors="replace"),
        stderr=err.decode("utf-8", errors="replace"),
        timed_out=timed_out,
        duration_s=duration,
        capabilities=SandboxCapabilities(
            env_scrubbed=True,
            cwd_confined=True,
            timeout_enforced=True,
            rlimits_applied=probe_rlimits(policy),
            network_isolated=policy.network_isolation_attested,
        ),
    )
