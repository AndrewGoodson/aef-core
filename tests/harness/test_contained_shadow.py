"""Closing the bypass the trust case demonstrated (§2.1).

Suppression by `PolicyEngine` denies tool CALLS. A shadow node that imported
`pathlib` and wrote to disk was never making one, and it wrote — demonstrated,
not argued. Running the candidate inside Milestone 4's container closes it.

**Both directions, in one file.** The in-process path must still show the
bypass and the contained path must not, because "the marker was not written"
is also what a candidate that never ran looks like.

These tests need a container image with `aef` importable, and skip without
one. The skip is the honest outcome: what they assert cannot be asserted by a
mock, since the question is whether the runtime does what its flags say.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from aef.harness.container import ContainerRuntime, available_runtimes
from aef.harness.shadow import ShadowRunner, contained_candidate_graph
from aef.kernel import END, Graph, Node
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta

IMAGE = "aef-worker:test"
_RUNTIMES = available_runtimes()


def _image_present() -> bool:
    if not _RUNTIMES:
        return False
    probe = subprocess.run(
        [_RUNTIMES[0], "image", "inspect", IMAGE], capture_output=True, check=False
    )
    return probe.returncode == 0


needs_worker_image = pytest.mark.skipif(
    not _image_present(),
    reason=f"no {IMAGE} image (build: see docs/trust/promotion-trust-case.md §2.1)",
)

ESCAPING_AGENT = """
from pathlib import Path
from aef.kernel import END, Graph, Node
from aef.state import StateDelta

TARGET = {target!r}


def writes(state, ctx, services):
    Path(TARGET).write_text("the shadow wrote this")
    return StateDelta(working_memory={{"wrote": True}}), END


def build_graph():
    return Graph(
        id="escaping",
        version="1",
        nodes={{"w": Node(id="w", version="1", fn=writes, deterministic=True)}},
        edges=[],
        entry_node="w",
    )
"""


def _incumbent() -> Graph:
    def clean(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(), END

    return Graph(
        id="incumbent",
        version="1",
        nodes={"w": Node(id="w", version="1", fn=clean, deterministic=True)},
        edges=[],
        entry_node="w",
    )


def _uncontained(incumbent, candidate):  # type: ignore[no-untyped-def]
    """A deliberately UNCONTAINED runner.

    Containment is the default (ADR 0105); these tests exercise the
    comparison, divergence and refusal logic, which is identical either way
    and much cheaper without a container. Written once, here, so that every
    call site is not silently opting out of a security control — and so
    `grep uncontained` finds every place that does.
    """
    from aef.harness.shadow import ShadowRunner

    return ShadowRunner(incumbent=incumbent, candidate=candidate, uncontained=True)


def _state() -> AEFState:
    return AEFState(run_id="live", agent_id="a", objective="serve a real request")


def test_the_in_process_shadow_still_escapes(tmp_path: Path) -> None:
    """The control, and the reason the fix is worth anything. If the marker
    were never written even in-process, the contained assertion below would
    pass while proving nothing."""
    marker = tmp_path / "escaped"

    def writes(state, ctx, services):  # type: ignore[no-untyped-def]
        marker.write_text("the shadow wrote this")
        return StateDelta(), END

    candidate = Graph(
        id="c",
        version="1",
        nodes={"w": Node(id="w", version="1", fn=writes, deterministic=True)},
        edges=[],
        entry_node="w",
    )
    _uncontained(_incumbent(), candidate).observe(_state(), agent_services())
    assert marker.exists(), "the in-process bypass is gone — update the trust case §2.1"


@needs_worker_image
def test_the_contained_shadow_cannot_reach_the_host(tmp_path: Path) -> None:
    """The fix. Same candidate, executed inside the container."""
    marker = Path(tempfile.mkdtemp()) / "escaped-to-host"
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "escaping.py").write_text(ESCAPING_AGENT.format(target=str(marker)))

    graph, session = contained_candidate_graph(
        "escaping:build_graph",
        workdir=workdir,
        runtime=ContainerRuntime(binary=_RUNTIMES[0], image=IMAGE),
    )
    try:
        observation = ShadowRunner(
            incumbent=_incumbent(), candidate=graph, session=session
        ).observe(_state(), agent_services())
    finally:
        session.close()

    assert observation.contained, "the runner did not report itself contained"
    assert not marker.exists(), "the contained shadow reached the host"
    assert observation.divergence.diverged, (
        "the candidate failed inside the container and that must be recorded as a divergence, "
        "not swallowed"
    )
    assert observation.state.working_memory == {}, "the incumbent's answer was contaminated"


@needs_worker_image
def test_the_container_root_is_read_only_for_paths_that_exist_in_it() -> None:
    """The control on the CONTROL.

    The test above passes partly because the host path does not exist inside
    the container — which is containment by accident, not by the read-only
    root. This asserts the mechanism actually claimed, on paths the image
    really has.
    """
    result = subprocess.run(
        [
            _RUNTIMES[0],
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            IMAGE,
            "python",
            "-c",
            "from pathlib import Path\n"
            "for t in ('/etc/hosts', '/tmp/x'):\n"
            "    try:\n"
            "        Path(t).write_text('x'); print('WROTE', t)\n"
            "    except OSError: print('blocked', t)\n",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "WROTE" not in result.stdout, f"the read-only root did not bind: {result.stdout}"
    assert result.stdout.count("blocked") == 2, result.stdout


@needs_worker_image
def test_the_workspace_remains_writable_and_that_is_deliberate(tmp_path: Path) -> None:
    """Stated rather than hidden: the candidate CAN write to its own workspace,
    which is a host directory the harness chose. That is what a workspace is.
    Containment means it cannot reach anywhere else."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "escaping.py").write_text(ESCAPING_AGENT.format(target="/aef-workspace/inside.txt"))

    graph, session = contained_candidate_graph(
        "escaping:build_graph",
        workdir=workdir,
        runtime=ContainerRuntime(binary=_RUNTIMES[0], image=IMAGE),
    )
    try:
        ShadowRunner(incumbent=_incumbent(), candidate=graph, session=session).observe(
            _state(), agent_services()
        )
    finally:
        session.close()
    assert (workdir / "inside.txt").exists()


@needs_worker_image
def test_the_parent_keeps_the_state_so_a_contained_candidate_cannot_forge_agreement(
    tmp_path: Path,
) -> None:
    """Why this uses the inverted-control worker rather than just sandboxing
    the whole run (ADR 0094).

    A candidate that reported its own final state could report the
    incumbent's and hide a divergence — making itself look SAFER than it is,
    which matters more here than in the gate. The parent applies every delta,
    so the only thing the worker can lie about is one node's output, and that
    IS its behaviour.
    """
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "diverging.py").write_text(
        "from aef.kernel import END, Graph, Node\n"
        "from aef.state import StateDelta\n\n\n"
        "def w(state, ctx, services):\n"
        "    return StateDelta(working_memory={'answer': 'CANDIDATE'}), END\n\n\n"
        "def build_graph():\n"
        "    return Graph(id='d', version='1',\n"
        "        nodes={'w': Node(id='w', version='1', fn=w, deterministic=True)},\n"
        "        edges=[], entry_node='w')\n"
    )
    graph, session = contained_candidate_graph(
        "diverging:build_graph",
        workdir=workdir,
        runtime=ContainerRuntime(binary=_RUNTIMES[0], image=IMAGE),
    )
    try:
        observation = ShadowRunner(
            incumbent=_incumbent(), candidate=graph, session=session
        ).observe(_state(), agent_services())
    finally:
        session.close()
    assert observation.divergence.fields == ("working_memory",)
    assert observation.state.working_memory == {}, "the incumbent's state was overwritten"


@needs_worker_image
def test_closing_the_session_leaves_no_container_running(tmp_path: Path) -> None:
    """ADR 0093's defect in its third location. `close()` killed the process
    group, and for a containerised worker the process group is the `docker
    run` CLIENT — the daemon owns the container."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "escaping.py").write_text(ESCAPING_AGENT.format(target="/aef-workspace/x"))

    def running() -> set[str]:
        # Filtered to OUR containers by the name prefix `isolated.py` gives
        # them (`aef-worker-<hex>`). The unfiltered `docker ps` diffed the
        # whole daemon, so any container another test — or another worker on
        # this box — started between the two calls failed this one. Three
        # spurious failures were observed that way; a control that cries wolf
        # gets ignored, which is the same end state as not having it.
        out = subprocess.run(
            [_RUNTIMES[0], "ps", "--quiet", "--filter", "name=aef-worker-"],
            capture_output=True,
            text=True,
            check=False,
        )
        return set(out.stdout.split())

    before = running()
    _, session = contained_candidate_graph(
        "escaping:build_graph",
        workdir=workdir,
        runtime=ContainerRuntime(binary=_RUNTIMES[0], image=IMAGE),
    )
    session.close()
    assert not running() - before, "a worker container survived close()"


def test_a_mutating_candidate_is_still_refused_inside_a_container() -> None:
    """Containment stops a node reaching the HOST. It does not stop a MUTATING
    node mutating whatever it was declared to mutate, and shadowing runs it on
    live input. The refusal is not softened because containment now exists —
    the same HARD-STOP Milestone 4 tested."""
    import inspect

    from aef.harness import shadow

    source = inspect.getsource(shadow.contained_candidate_graph)
    assert "assert_shadowable(graph)" in source


# --------------------------------------------------------------------------
# Containment is the DEFAULT (ADR 0105 revision)
# --------------------------------------------------------------------------


def test_an_uncontained_shadow_is_refused_by_default() -> None:
    """The shape `SandboxPolicy` already uses for network isolation: refuse
    unless the containment is really there, and make running without it
    something a caller STATES rather than inherits."""
    from aef.harness.shadow import UncontainedShadowError

    with pytest.raises(UncontainedShadowError, match="TOOL CALLS"):
        ShadowRunner(incumbent=_incumbent(), candidate=_incumbent())


def test_the_refusal_names_the_way_out() -> None:
    """A refusal an operator cannot act on gets routed around, and the route
    around this one is the security control itself."""
    from aef.harness.shadow import UncontainedShadowError

    try:
        ShadowRunner(incumbent=_incumbent(), candidate=_incumbent())
    except UncontainedShadowError as exc:
        message = str(exc)
    assert "contained_candidate_graph" in message
    assert "uncontained=True" in message


def test_opting_out_is_recorded_on_every_observation() -> None:
    """`SandboxCapabilities` exists for the same reason (ADR 0102): a result
    cannot be read without knowing the conditions it ran under. An uncontained
    observation must not be indistinguishable from a contained one."""
    observation = ShadowRunner(
        incumbent=_incumbent(), candidate=_incumbent(), uncontained=True
    ).observe(_state(), agent_services())
    assert observation.contained is False


def test_one_uncontained_observation_downgrades_the_whole_report() -> None:
    """A report is only as strong as its weakest observation. Averaging that
    away is how a mixed run reads as a clean one."""
    from aef.harness.shadow import ShadowReport

    report = ShadowReport()
    assert not report.contained, (
        "an empty report claims containment it never measured — see the adversarial round"
    )

    uncontained = ShadowRunner(
        incumbent=_incumbent(), candidate=_incumbent(), uncontained=True
    ).observe(_state(), agent_services())
    assert not report.with_observation(uncontained).contained


def test_claiming_both_at_once_is_refused(tmp_path: Path) -> None:
    """One of the two is a mistake, and guessing which would mislabel the
    evidence."""
    from aef.harness.shadow import ShadowError

    with pytest.raises(ShadowError, match="one of the two is a mistake"):
        ShadowRunner(
            incumbent=_incumbent(),
            candidate=_incumbent(),
            session=object(),  # type: ignore[arg-type]
            uncontained=True,
        )


@needs_worker_image
def test_a_contained_runner_reports_itself_contained(tmp_path: Path) -> None:
    """The positive control. If `contained` were always False the assertions
    above would pass while proving nothing about the default."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "escaping.py").write_text(ESCAPING_AGENT.format(target="/aef-workspace/x"))

    graph, session = contained_candidate_graph(
        "escaping:build_graph",
        workdir=workdir,
        runtime=ContainerRuntime(binary=_RUNTIMES[0], image=IMAGE),
    )
    try:
        runner = ShadowRunner(incumbent=_incumbent(), candidate=graph, session=session)
        assert runner.contained
        assert runner.observe(_state(), agent_services()).contained
    finally:
        session.close()


# The one production call site allowed to pass `uncontained=True`: the
# fallback branch of `shadow_for`, which `resolve_containment` cannot reach
# under the default mode. Named as a function rather than a line number so
# the allowance survives an edit above it, and pinned to exactly one entry —
# an allowlist that can grow silently is not an allowlist.
ALLOWED_UNCONTAINED_SITE = ("aef/harness/shadow.py", "shadow_for")


def test_every_uncontained_call_site_in_the_repo_is_a_test_or_the_named_fallback() -> None:
    """The default is only a default if nothing in `aef/` quietly opts out.

    A production caller passing `uncontained=True` would restore the bypass
    while every test above still passed. Exactly one is allowed — the branch
    an owner reaches by writing `shadow.containment: fallback` or `off` — and
    `test_the_single_production_opt_out_is_unreachable_under_the_default`
    proves the default cannot get there. Every other one is a defect.

    AST, not grep: the first version of this test matched the error message
    that TELLS a caller how to opt out, and a `.pyc` alongside it. Inferring a
    call from text rather than reading the call is the mistake ADR 0064
    measured.
    """
    import ast

    root = Path(__file__).resolve().parents[2] / "aef"
    sites: list[tuple[str, str, int]] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        enclosing: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Plain assignment, not setdefault: `ast.walk` is
                # breadth-first, so a nested function is visited after the one
                # containing it and overwrites with the INNERMOST name — which
                # is the one that says where the opt-out actually lives.
                for inner in ast.walk(node):
                    enclosing[id(inner)] = node.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "uncontained" and isinstance(kw.value, ast.Constant):
                    if kw.value.value is True:
                        sites.append(
                            (
                                str(path.relative_to(root.parent)),
                                enclosing.get(id(node), "<module>"),
                                node.lineno,
                            )
                        )

    assert [(f, fn) for f, fn, _ in sites] == [ALLOWED_UNCONTAINED_SITE], (
        f"production code opts out of shadow containment somewhere new: {sites}"
    )


# --------------------------------------------------------------------------
# The adversarial round for the default. Three REPRODUCED, one dismissed.
# --------------------------------------------------------------------------


def test_an_object_that_merely_occupies_the_session_slot_is_refused() -> None:
    """REPRODUCED: `session is not None` let ANY truthy object make the runner
    report `contained=True` while the candidate ran in-process. A false
    capability report is the class ADR 0102 exists to prevent."""
    from aef.harness.shadow import ShadowError

    class NotASession:
        pass

    with pytest.raises(ShadowError, match="must be a NodeWorkerSession"):
        ShadowRunner(incumbent=_incumbent(), candidate=_incumbent(), session=NotASession())  # type: ignore[arg-type]


def test_a_session_without_a_container_does_not_count_as_containment(tmp_path: Path) -> None:
    """The subtler half of the same finding. A `NodeWorkerSession` with
    `container=None` is a plain subprocess: real rlimits and a scrubbed
    environment, and NO filesystem or network boundary."""
    from aef.harness.isolated import NodeWorkerSession
    from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
    from aef.harness.shadow import UncontainedShadowError

    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "plain.py").write_text(
        "from aef.kernel import END, Graph, Node\n"
        "from aef.state import StateDelta\n\n\n"
        "def w(state, ctx, services):\n"
        "    return StateDelta(), END\n\n\n"
        "def build_graph():\n"
        "    return Graph(id='p', version='1',\n"
        "        nodes={'w': Node(id='w', version='1', fn=w, deterministic=True)},\n"
        "        edges=[], entry_node='w')\n"
    )
    session = NodeWorkerSession(
        "plain:build_graph",
        workdir=workdir,
        sandbox=SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED),
    )
    try:
        assert not session.is_contained
        with pytest.raises(UncontainedShadowError, match="plain subprocess"):
            ShadowRunner(incumbent=_incumbent(), candidate=_incumbent(), session=session)
    finally:
        session.close()


@needs_worker_image
def test_a_closed_session_is_refused_rather_than_blamed_on_the_candidate(
    tmp_path: Path,
) -> None:
    """REPRODUCED: reusing a closed session recorded `contained=True` and a
    divergence reading `IsolationError: worker died before node` — a HARNESS
    fault reported as candidate behaviour, which is the mistake ADR 0074
    names. Worse than useless: it makes a working candidate look broken."""
    from aef.harness.shadow import ShadowError

    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "escaping.py").write_text(ESCAPING_AGENT.format(target="/aef-workspace/x"))

    graph, session = contained_candidate_graph(
        "escaping:build_graph",
        workdir=workdir,
        runtime=ContainerRuntime(binary=_RUNTIMES[0], image=IMAGE),
    )
    session.close()
    assert session.closed, "`closed` must be set by close(), not inferred from the process"

    with pytest.raises(ShadowError, match="already closed"):
        ShadowRunner(incumbent=_incumbent(), candidate=graph, session=session)


def test_an_empty_report_does_not_claim_containment_it_never_measured() -> None:
    """REPRODUCED: `contained=True` over zero observations asserts a property
    of evidence that does not exist, and makes "never ran" indistinguishable
    from the good case again — the same reasoning as `divergence_rate`."""
    from aef.harness.shadow import ShadowReport

    empty = ShadowReport()
    assert empty.observations == 0
    assert not empty.contained


def test_a_frozen_dataclass_is_not_the_security_boundary() -> None:
    """Dismissed, and recorded so the dismissal is legible rather than an
    omission. `object.__setattr__` bypasses any frozen dataclass in Python;
    anyone who can call it can call the underlying function directly, so it is
    not a boundary and pretending otherwise would be theatre. The boundary is
    the container.
    """
    runner = ShadowRunner(incumbent=_incumbent(), candidate=_incumbent(), uncontained=True)
    object.__setattr__(runner, "session", "not a session")
    assert not runner.contained, (
        "even after tampering, `contained` is derived from the session's own container "
        "rather than from a stored flag"
    )


# --------------------------------------------------------------------------
# The container is the DEFAULT, and the fallback is an owner statement
# (ADR 0161)
# --------------------------------------------------------------------------
#
# ADR 0105 made containment the default by refusing to construct without a
# session. It never PROVIDED one: on this box, with a running daemon and the
# image built, `ShadowRunner(incumbent, candidate)` still refused, and the
# only one-line way past it was `uncontained=True`. These pin the resolver
# that closes that, in both directions.


def _no_runtimes() -> tuple[str, ...]:
    return ()


def _broken_image(image, *, binary=None, verify=True):  # type: ignore[no-untyped-def]
    from aef.harness.sandbox import SandboxUnavailableError

    raise SandboxUnavailableError(f"{binary or 'docker'} could not run image {image!r} (exit 125)")


@needs_worker_image
def test_the_container_is_the_default_when_a_runtime_and_image_are_available(
    tmp_path: Path,
) -> None:
    """The increment, as one assertion. A caller that asks for nothing in
    particular, on a box that HAS a runtime and an image, gets a contained
    candidate — and the write that landed on the host before does not."""
    from aef.harness.shadow import ContainmentMode, shadow_for

    marker = Path(tempfile.mkdtemp()) / "escaped-under-the-default"
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "escaping.py").write_text(ESCAPING_AGENT.format(target=str(marker)))

    with shadow_for(
        _incumbent(),
        entrypoint="escaping:build_graph",
        workdir=workdir,
        image=IMAGE,
    ) as shadow:
        assert shadow.decision.mode is ContainmentMode.AUTO, "the default is not `auto`"
        assert shadow.decision.contained, shadow.decision.reason
        assert shadow.runner.contained
        observation = shadow.runner.observe(_state(), agent_services())

    assert not marker.exists(), "the write reached the host under the DEFAULT configuration"
    assert observation.contained
    assert observation.divergence.diverged, "the container refusal must be recorded"


def test_auto_refuses_rather_than_falling_back_when_there_is_no_runtime() -> None:
    """`auto` does not fall back. An automatic in-process fallback would be
    strictly weaker than the refusal ADR 0105 shipped, and the refusal names
    which half was missing rather than saying 'containment unavailable'."""
    from aef.harness.shadow import (
        NO_RUNTIME_REASON,
        UncontainedShadowError,
        resolve_containment,
    )

    with pytest.raises(UncontainedShadowError) as caught:
        resolve_containment(image=IMAGE, runtimes=_no_runtimes)
    assert NO_RUNTIME_REASON in str(caught.value)
    assert "shadow.containment: fallback" in str(caught.value), (
        "a refusal an operator cannot act on gets routed around"
    )


def test_auto_refuses_when_the_image_is_unavailable_and_says_why() -> None:
    """The other half. `container.py` distinguishes 'the runtime never started
    the container' from 'isolation did not hold'; neither may be laundered
    into a decision to run uncontained."""
    from aef.harness.shadow import (
        IMAGE_UNAVAILABLE_PREFIX,
        UncontainedShadowError,
        resolve_containment,
    )

    with pytest.raises(UncontainedShadowError) as caught:
        resolve_containment(image=IMAGE, detect=_broken_image, runtimes=lambda: ("docker",))
    assert IMAGE_UNAVAILABLE_PREFIX in str(caught.value)
    assert "exit 125" in str(caught.value), "the runtime's own reason was dropped"


def test_auto_refuses_when_no_image_is_configured() -> None:
    """`shadow.image` has no default because this repo has no image to ship.
    An unset one is a refusal that names it, not a silent downgrade."""
    from aef.harness.shadow import NO_IMAGE_REASON, UncontainedShadowError, resolve_containment

    with pytest.raises(UncontainedShadowError, match="shadow.image"):
        resolve_containment(image=None)
    with pytest.raises(UncontainedShadowError) as caught:
        resolve_containment(image="")
    assert NO_IMAGE_REASON in str(caught.value)


def test_the_fallback_names_the_reason_and_is_printed() -> None:
    """`fallback` is reachable only from config, and when taken it says which
    of the two named causes it was — on stderr AND in the decision."""
    from aef.harness.shadow import NO_RUNTIME_REASON, ContainmentMode, resolve_containment

    decision = resolve_containment(
        image=IMAGE, mode=ContainmentMode.FALLBACK, runtimes=_no_runtimes
    )
    assert not decision.contained
    assert decision.reason == NO_RUNTIME_REASON
    assert decision.owner_opted_out, "a fallback taken by owner choice is an owner choice"
    assert NO_RUNTIME_REASON in decision.warning()
    assert "contained=False" in decision.warning()


def test_the_opt_out_is_an_owner_choice_and_says_so() -> None:
    """`containment: off` never looks for a runtime. Its reason names the file
    the owner wrote it in, because 'not contained' with no cause is the thing
    an operator cannot act on."""
    from aef.harness.shadow import OWNER_OPT_OUT_REASON, ContainmentMode, resolve_containment

    decision = resolve_containment(image=IMAGE, mode=ContainmentMode.OFF)
    assert not decision.contained
    assert decision.reason == OWNER_OPT_OUT_REASON
    assert "aef.yaml" in decision.reason
    assert decision.owner_opted_out
    assert "OFF by owner choice" in decision.warning()


def test_the_fallback_is_in_the_ledger_not_only_on_stderr(tmp_path: Path) -> None:
    """A stderr line from last Tuesday is not an audit trail. `security_event`
    is what carries it into the owner's weekly digest — `build_digest` counts
    that key and nothing in this module reads it."""
    from aef.harness.ledger import EventKind, read
    from aef.harness.shadow import (
        NO_RUNTIME_REASON,
        ContainmentMode,
        record_containment_decision,
        resolve_containment,
    )

    decision = resolve_containment(
        image=IMAGE, mode=ContainmentMode.FALLBACK, runtimes=_no_runtimes
    )
    record_containment_decision(tmp_path, decision, proposal_id="p1")

    (entry,) = read(tmp_path)
    assert entry.kind is EventKind.CONTAINMENT
    assert entry.detail["security_event"] is True
    assert entry.detail["containment"]["contained"] is False
    assert entry.detail["containment"]["reason"] == NO_RUNTIME_REASON
    assert entry.detail["containment"]["mode"] == "fallback"
    assert entry.detail["containment"]["owner_opted_out"] is True
    assert "NOT contained" in entry.summary


def test_the_digest_counts_an_uncontained_shadow_as_a_security_event(tmp_path: Path) -> None:
    """The seam. `security_event` is only useful if the thing that reads it
    agrees — a detail key nobody counts is a stderr line with extra steps."""
    from datetime import UTC, datetime, timedelta

    from aef.harness.ledger import read
    from aef.harness.monitoring import build_digest
    from aef.harness.shadow import ContainmentMode, record_containment_decision, resolve_containment

    at = datetime.now(UTC)
    record_containment_decision(
        tmp_path,
        resolve_containment(image=IMAGE, mode=ContainmentMode.OFF),
        proposal_id="p1",
        at=at,
    )
    digest = build_digest(
        read(tmp_path), since=at - timedelta(hours=1), until=at + timedelta(hours=1)
    )
    assert digest.security_events == 1


def test_a_contained_run_is_recorded_too(tmp_path: Path) -> None:
    """Both directions. Recording only the fallbacks would make 'the shadow
    ran contained' and 'no shadow ran at all' the same absence."""
    from aef.harness.container import ContainerRuntime
    from aef.harness.ledger import read
    from aef.harness.shadow import ContainmentDecision, ContainmentMode, record_containment_decision

    decision = ContainmentDecision(
        mode=ContainmentMode.AUTO,
        contained=True,
        reason="contained by docker with image x; isolation verified",
        runtime=ContainerRuntime(binary="docker", image="x", verified=True),
        image="x",
    )
    record_containment_decision(tmp_path, decision, proposal_id="p1")
    (entry,) = read(tmp_path)
    assert "security_event" not in entry.detail
    assert entry.detail["containment"]["contained"] is True
    assert entry.detail["containment"]["isolation_verified"] is True
    assert entry.summary.startswith("shadow containment: contained")


def test_the_bypass_is_still_real_under_the_opt_out_and_is_announced(tmp_path: Path) -> None:
    """The control on the control, run through the RESOLVER rather than a hand
    -built runner. If the marker were never written, every assertion above
    about containment would pass while proving nothing — and if the fallback
    were silent, an owner would have no way to know which mode produced their
    evidence."""
    from aef.harness.ledger import EventKind, read
    from aef.harness.shadow import ContainmentMode, shadow_for

    marker = Path(tempfile.mkdtemp()) / "escaped-under-opt-out"

    def writes(state, ctx, services):  # type: ignore[no-untyped-def]
        marker.write_text("the shadow wrote this")
        return StateDelta(), END

    candidate = Graph(
        id="c",
        version="1",
        nodes={"w": Node(id="w", version="1", fn=writes, deterministic=True)},
        edges=[],
        entry_node="w",
    )
    warnings: list[str] = []
    with shadow_for(
        _incumbent(),
        entrypoint="unused:build_graph",
        workdir=tmp_path,
        image=IMAGE,
        mode=ContainmentMode.OFF,
        in_process_candidate=candidate,
        ledger_root=tmp_path,
        proposal_id="p1",
        warn=warnings.append,
    ) as shadow:
        observation = shadow.runner.observe(_state(), agent_services())

    assert marker.exists(), (
        "the in-process bypass is gone — the trust case section 2.1 is stale and so is this test"
    )
    assert observation.contained is False
    assert warnings and "OFF by owner choice" in warnings[0]
    assert [e.kind for e in read(tmp_path)] == [EventKind.CONTAINMENT]


def test_the_uncontained_path_will_not_import_the_candidate_for_you(tmp_path: Path) -> None:
    """Loading a candidate's module into this interpreter is exactly what
    containment prevents. Doing it silently on the fallback path would make
    the weaker mode the more convenient one again."""
    from aef.harness.shadow import ContainmentMode, ShadowError, shadow_for

    with pytest.raises(ShadowError, match="in_process_candidate"):
        shadow_for(
            _incumbent(),
            entrypoint="escaping:build_graph",
            workdir=tmp_path,
            image=IMAGE,
            mode=ContainmentMode.OFF,
            warn=lambda _m: None,
        )


def test_the_single_production_opt_out_is_unreachable_under_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the AST test below. One production call site passes
    `uncontained=True`; this proves the DEFAULT mode cannot reach it —
    `shadow_for` raises before constructing any runner, even when handed an
    `in_process_candidate` it could have used.

    Runtime detection is patched away rather than the box's docker stopped:
    the branch being pinned is the one an adopter without a daemon takes, and
    it must be exercised on a box that has one.
    """
    from aef.harness import shadow as shadow_module
    from aef.harness.shadow import NO_RUNTIME_REASON, UncontainedShadowError, shadow_for

    monkeypatch.setattr(shadow_module, "available_runtimes", _no_runtimes)

    announced: list[str] = []
    with pytest.raises(UncontainedShadowError) as caught:
        shadow_for(
            _incumbent(),
            entrypoint="escaping:build_graph",
            workdir=tmp_path,
            image=IMAGE,
            in_process_candidate=_incumbent(),
            ledger_root=tmp_path,
            warn=announced.append,
        )
    assert NO_RUNTIME_REASON in str(caught.value)
    assert not announced, "nothing was announced because nothing ran"
    assert not (tmp_path / "ledger.jsonl").exists(), (
        "a refusal is not a run and must not be recorded as one"
    )


def test_the_config_mode_strings_and_the_enum_cannot_drift() -> None:
    """Two spellings of one security decision, with nothing checking that they
    agree, is the drift ADR 0091 records."""
    from aef.config.schema import CONTAINMENT_MODES
    from aef.harness.shadow import ContainmentMode

    assert CONTAINMENT_MODES == {mode.value for mode in ContainmentMode}


def test_the_config_default_is_the_contained_one() -> None:
    """If this ever defaulted to `fallback`, every assertion above would still
    pass and every adopter would be running uncontained."""
    from aef.config.factory import build_containment_mode
    from aef.config.schema import ShadowConfig
    from aef.harness.shadow import ContainmentMode

    assert ShadowConfig().containment == "auto"
    assert build_containment_mode(ShadowConfig()) is ContainmentMode.AUTO


def test_an_unknown_containment_mode_is_refused_at_load_time() -> None:
    """A typo that validates is an owner believing a mode is on."""
    import pydantic

    from aef.config.schema import ShadowConfig

    with pytest.raises(pydantic.ValidationError, match="is not one of"):
        ShadowConfig(containment="contained")
