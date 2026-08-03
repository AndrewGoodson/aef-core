from pathlib import Path

import pytest

from aef.kernel import FileDurabilityBackend, InMemoryDurabilityBackend
from aef.kernel.durability import DurabilityBackend
from aef.state import AEFState


@pytest.fixture(params=["in_memory", "file"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> DurabilityBackend:
    if request.param == "in_memory":
        return InMemoryDurabilityBackend()
    return FileDurabilityBackend(tmp_path / "checkpoints")


def _state(run_id: str = "r1", seq: int = 0) -> AEFState:
    return AEFState(run_id=run_id, agent_id="a1", objective="test", checkpoint_seq=seq)


def test_load_cursor_for_unknown_run_is_none(backend: DurabilityBackend) -> None:
    assert backend.load_cursor("never-seen") is None


def test_save_and_load_cursor_round_trips(backend: DurabilityBackend) -> None:
    backend.save_cursor("r1", "node_b")
    assert backend.load_cursor("r1") == "node_b"


def test_cursor_can_be_overwritten(backend: DurabilityBackend) -> None:
    backend.save_cursor("r1", "node_a")
    backend.save_cursor("r1", "node_b")
    assert backend.load_cursor("r1") == "node_b"


def test_cursor_set_to_none_represents_completion(backend: DurabilityBackend) -> None:
    backend.save_cursor("r1", "node_b")
    backend.save_cursor("r1", None)
    assert backend.load_cursor("r1") is None


def test_cursors_are_isolated_per_run(backend: DurabilityBackend) -> None:
    backend.save_cursor("r1", "node_a")
    backend.save_cursor("r2", "node_z")
    assert backend.load_cursor("r1") == "node_a"
    assert backend.load_cursor("r2") == "node_z"


def test_checkpoint_and_cursor_are_independent(backend: DurabilityBackend) -> None:
    backend.save_checkpoint(_state(seq=0))
    backend.save_cursor("r1", "node_a")
    backend.save_checkpoint(_state(seq=1))
    assert backend.load_cursor("r1") == "node_a"
    assert backend.list_checkpoints("r1") == [0, 1]


def test_file_backend_cursor_survives_new_instance_same_dir(tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    FileDurabilityBackend(root).save_cursor("r1", "node_b")
    reloaded = FileDurabilityBackend(root)
    assert reloaded.load_cursor("r1") == "node_b"
