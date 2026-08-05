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
    ShadowRunner(incumbent=_incumbent(), candidate=candidate).observe(_state(), agent_services())
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
        observation = ShadowRunner(incumbent=_incumbent(), candidate=graph).observe(
            _state(), agent_services()
        )
    finally:
        session.close()

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
        ShadowRunner(incumbent=_incumbent(), candidate=graph).observe(_state(), agent_services())
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
        observation = ShadowRunner(incumbent=_incumbent(), candidate=graph).observe(
            _state(), agent_services()
        )
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
        out = subprocess.run(
            [_RUNTIMES[0], "ps", "--quiet"], capture_output=True, text=True, check=False
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
