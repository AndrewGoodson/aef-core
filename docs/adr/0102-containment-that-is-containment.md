# ADR 0102: Containment that is containment

## Status
Accepted. Milestone 4. `network_isolated=True` can now be **true**.

## What was actually there

`sandbox.py` has always been honest about its limits, and the honesty was the
problem: it stated that a process cannot revoke its own network access and
that `cwd` is a default rather than a jail — and everything downstream assumed
containment anyway. G0's import allowlist is a static scan standing in for a
boundary that did not exist.

`SandboxCapabilities.network_isolated` was
`policy.network_isolation_attested`: a **bool a caller passes in**. Honest,
testable, Zone B — and unchecked. The CI job asserts it because the job runs
inside `--network none`. Nothing ever verified that.

## Decision

A container-backed path, as an **option**. `SandboxPolicy.container_image`
names an image; `run_sandboxed` dispatches to `run_containerized` when it is
set. The image is a plain string so `sandbox.py` never imports `container.py`,
which imports it.

**Isolation is measured, not declared.** `detect_container_runtime` runs a
probe before anything else does, and it checks **both directions**: the
isolated run must fail to connect AND the unisolated run must succeed.
Checking only the first would accept an image with no Python, a stopped
daemon, or an offline host — every one of which looks exactly like working
isolation from inside a single assertion. Both directions were run by hand
before the module was written:

```
docker run --rm --network none  ... -> network blocked: OSError
docker run --rm                 ... -> CONTROL: network reachable
```

`network_isolated` is `runtime.verified`, not `True`. An unverified runtime
still runs and still says so.

Five flags, each a control, each pinned by name in a test: `--network none`,
`--rm`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`,
plus a single writable mount of the workspace. `--memory` and `--pids-limit`
come from the same policy fields the in-process path uses for rlimits, so the
two paths bound the same things rather than each bounding whatever its own
mechanism made easy. The host environment is not forwarded at all, which is
stronger than the in-process allowlist.

**Degrading is loud.** No runtime, no image, or a probe that misbehaves raises
`SandboxUnavailableError`. A caller that asked for containment and got a quiet
`None` would run the candidate anyway.

## 4b: the two places now make the same claim

`aef loop gate --sandbox-image <image>` builds the containment locally that
the emitted CI workflow gets from `options: --network none`. `--network-
isolated` remains, and the distinction is now meaningful: that flag is the
caller **asserting**, `--sandbox-image` is the run **building and verifying**.
`LoopConfig.sandbox_policy()` prefers the image.

## What the adversarial round found

**A timed-out container kept running.** `subprocess.run(timeout=...)` kills
the `docker run` **client**; the daemon owns the container, which ran on.
Reproduced: one container still alive two seconds after the gate reported a
timeout. **This is ADR 0093's defect, in a new place** — the direct child dies
and the real work survives it — and it landed in code written specifically to
provide containment. Fixed by naming every run and asking the daemon to
`rm --force` it on timeout. Asserted against `docker ps`, not against the
return value, because the return value was already correct while the container
ran on.

**A missing image was reported as an isolation failure.** A bogus image
produced "docker did not block egress with --network none" — a statement about
something the run never measured. Exit 125 means the runtime never started the
container; it is now distinguished, because a refusal that misnames its own
cause sends the operator to fix the wrong thing (ADR 0074).

Checked and sound: a candidate cannot write to the host outside its workspace
(verified with a real marker file on the host); the container root is
read-only while the workspace is writable and lands on the host; the workspace
is the only mount.

**Checked and benign:** binding port 80 inside the container succeeds despite
`--cap-drop ALL`, because containers commonly set
`net.ipv4.ip_unprivileged_port_start=0`. With `--network none` there is no
network to serve on, so it grants nothing. Recorded rather than quietly
dropped, because the flag test asserts the flag is *present* and not that
every capability is gone — and the difference matters to anyone reading it.

## 4c: nothing was weakened

Stated as a HARD-STOP and tested as one. G0's static scan still rejects a
forbidden import before anything runs. The unattested-policy refusal is
unchanged. A policy naming an image nothing can run still fails rather than
inheriting the exemption. The in-process path still reports
`network_isolated=False`, which is what makes the container path's `True`
worth anything.

Defence in depth is the reason: the zone rule survived three defeats of the
import allowlist (ADR 0085 -> 0088 -> 0093) precisely because the layers are
independent.

## Consequences

Milestone 2 left one thing unmitigated: `evaluator.suites` resolution executes
a module body on import. Inside a container that execution now has no network
and a read-only filesystem. It is contained, not prevented.

The container tests **skip** without a runtime rather than passing. What they
assert cannot be asserted by a mock, since the whole question is whether the
runtime does what its flags say. They ran here against Docker 29.4.0 —
verified as run, not assumed, by checking for `SKIPPED` in the output.

## Confidence
High on what was measured: every containment claim in this ADR was produced by
running a container and observing the result, including two failures found
that way.

Lower on breadth. One image on one host and one runtime — podman is supported
by symmetry of flags and **has not been exercised**. No claim is made about
kernel-level escapes, and `--cap-drop ALL` is asserted as a flag rather than
as an outcome.
