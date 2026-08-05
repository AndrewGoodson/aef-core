"""Resume must not invent a state that never existed.

`load_latest` rewinds past a corrupt checkpoint to the highest readable one
(ADR 0031). The cursor was NOT rewound — it still named the node due to run
after the checkpoint that could not be read. `resume()` paired the two and
**silently skipped every node in between**, with no error, then overwrote the
torn file so the evidence disappeared (ADR 0086).

Also here: `run_id` was joined onto the checkpoint root verbatim, so
`../../escaped` wrote outside the backend entirely.
"""

from pathlib import Path

import pydantic
import pytest

from aef.kernel import END, Edge, FileDurabilityBackend, Graph, GraphExecutor, Node, Services
from aef.kernel.durability import CorruptedCheckpointError
from aef.state import AEFState, StateDelta


def _node(name: str, nxt: object):  # type: ignore[no-untyped-def]
    def fn(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(working_memory={f"{name}_done": True}, reflections=[f"{name} ran"]), nxt

    return fn


def _graph() -> Graph:
    return Graph(
        id="g",
        version="1",
        nodes={
            n: Node(id=n, version="1", fn=_node(n, nxt), deterministic=True)
            for n, nxt in (("A", "B"), ("B", "C"), ("C", END))
        },
        edges=[Edge(from_node="A", to_node="B"), Edge(from_node="B", to_node="C")],
        entry_node="A",
    )


@pytest.fixture
def backend(tmp_path: Path) -> FileDurabilityBackend:
    return FileDurabilityBackend(tmp_path / "ck")


def test_a_clean_run_visits_every_node(backend: FileDurabilityBackend) -> None:
    """The control. Without it, the assertion below could pass because the
    graph never ran three nodes in the first place."""
    result = GraphExecutor(_graph().compile(), Services(durability=backend)).run(
        AEFState(run_id="run1", agent_id="a", objective="o")
    )
    assert result.final_state.reflections == ["A ran", "B ran", "C ran"]


def test_a_torn_checkpoint_refuses_resume_rather_than_skipping(
    tmp_path: Path, backend: FileDurabilityBackend
) -> None:
    services = Services(durability=backend)
    GraphExecutor(_graph().compile(), services).run(
        AEFState(run_id="run1", agent_id="a", objective="o")
    )
    checkpoints = backend.list_checkpoints("run1")
    assert len(checkpoints) >= 2, "the fixture needs something to rewind past"

    (tmp_path / "ck" / "run1" / f"{max(checkpoints)}.json").write_text("{not json")
    assert backend.load_latest("run1").checkpoint_seq < max(checkpoints)  # type: ignore[union-attr]

    with pytest.raises(CorruptedCheckpointError, match="would skip every node between them"):
        GraphExecutor(_graph().compile(), services).resume("run1")


def test_an_intact_run_still_resumes(backend: FileDurabilityBackend) -> None:
    """The refusal must not fire on the normal path — a guard that rejects
    healthy runs is worse than the defect."""
    services = Services(durability=backend)
    state = AEFState(run_id="run2", agent_id="a", objective="o")
    GraphExecutor(_graph().compile(), services).run(state)
    resumed = GraphExecutor(_graph().compile(), services).resume("run2")
    assert resumed.final_state.reflections == ["A ran", "B ran", "C ran"]


# --------------------------------------------------------------------------
# run_id is a directory name
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../../escaped", "a/b", "..", "", "."])
def test_a_run_id_that_is_not_a_path_segment_is_rejected(bad: str) -> None:
    with pytest.raises(pydantic.ValidationError, match="single path segment"):
        AEFState(run_id=bad, agent_id="a", objective="o")


def test_the_backend_confines_run_ids_at_its_own_boundary(tmp_path: Path) -> None:
    """The schema check is not the containment. A caller reaching the backend
    directly — it is public API an adopter uses — must not be able to write
    outside the root."""
    backend = FileDurabilityBackend(tmp_path / "ck")
    with pytest.raises(ValueError, match="resolves outside the checkpoint root"):
        backend._run_dir("../../escaped")


def test_an_ordinary_run_id_still_works(tmp_path: Path) -> None:
    backend = FileDurabilityBackend(tmp_path / "ck")
    backend.save_checkpoint(AEFState(run_id="ok-run", agent_id="a", objective="o"))
    assert (tmp_path / "ck" / "ok-run" / "0.json").is_file()
