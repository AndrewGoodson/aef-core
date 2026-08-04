from pathlib import Path

import pytest

from aef.kernel import CorruptedCheckpointError, FileDurabilityBackend, InMemoryDurabilityBackend
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


def test_file_backend_list_checkpoints_ignores_stray_non_numeric_json_files(
    tmp_path: Path,
) -> None:
    """Reproduces a real, confirmed bug: a single non-numeric-stem `.json`
    file sharing a run's checkpoint directory (a stray backup, a future
    sidecar file — anything other than `<int>.json` or `cursor.json`) used
    to raise ValueError from `int(p.stem)` inside list_checkpoints, which
    bricked load_latest for that entire run_id, not just the stray file.
    See docs/adr/0026."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_checkpoint(_state(seq=0))
    (root / "r1" / "some_backup.json").write_text("{}")

    assert backend.list_checkpoints("r1") == [0]
    assert backend.load_latest("r1") is not None


def test_file_backend_load_checkpoint_raises_named_error_on_corrupted_json(
    tmp_path: Path,
) -> None:
    """A truncated/corrupted checkpoint file used to raise a bare
    json.JSONDecodeError with no indication of which run_id/checkpoint_seq
    /path was corrupted. See docs/adr/0026."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_checkpoint(_state(seq=0))
    (root / "r1" / "0.json").write_text("{not valid json")

    with pytest.raises(CorruptedCheckpointError, match="r1"):
        backend.load_checkpoint("r1", 0)


def test_file_backend_load_checkpoint_raises_named_error_on_empty_file(tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_checkpoint(_state(seq=0))
    (root / "r1" / "0.json").write_text("")

    with pytest.raises(CorruptedCheckpointError):
        backend.load_checkpoint("r1", 0)


def test_load_latest_recovers_from_a_torn_final_checkpoint(tmp_path: Path) -> None:
    """Reproduces the review's Finding 1 (docs/adr/0031): a crash mid-write
    of the newest checkpoint leaves a truncated max-seq file. Before the
    fix, load_latest picked max(seq) and raised CorruptedCheckpointError,
    bricking resume even though earlier checkpoints were intact on disk.
    After the fix it must fall back to the highest *loadable* checkpoint."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_checkpoint(_state(seq=0))
    backend.save_checkpoint(_state(seq=1))
    # Simulate a crash mid-write of seq 2: a truncated file left behind.
    (root / "r1" / "2.json").write_text('{"run_id": "r1", "agent_id"')

    recovered = backend.load_latest("r1")
    assert recovered is not None
    assert recovered.checkpoint_seq == 1  # fell back past the torn seq-2 file


def test_load_latest_raises_when_every_checkpoint_is_corrupt(tmp_path: Path) -> None:
    """Fallback recovers past *some* torn files, but if none are loadable
    there is genuinely nothing to recover — that must still surface loudly,
    not return None (which would be indistinguishable from 'never ran')."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_checkpoint(_state(seq=0))
    (root / "r1" / "0.json").write_text("{torn")

    with pytest.raises(CorruptedCheckpointError):
        backend.load_latest("r1")


def test_load_cursor_raises_named_error_on_corrupted_cursor_file(tmp_path: Path) -> None:
    """load_cursor lacked the corruption guard load_checkpoint has (ADR 0026):
    an externally-corrupted cursor.json raised a bare json.JSONDecodeError
    naming no run_id. Atomic writes (0031) stop THIS backend producing a torn
    cursor, but external corruption (disk fault, manual edit) is exactly what
    the read-side guard is for. See docs/adr/0031 (follow-up)."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_cursor("r1", "node_b")
    (root / "r1" / "cursor.json").write_text("{not valid json")

    with pytest.raises(CorruptedCheckpointError, match="r1"):
        backend.load_cursor("r1")


def test_save_checkpoint_is_atomic_no_torn_file_visible(tmp_path: Path) -> None:
    """A completed save_checkpoint must leave a fully-valid file — never a
    temp/partial artifact visible in the run dir. Verifies the temp+replace
    write leaves exactly one json per seq and no leftover temp files."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_checkpoint(_state(seq=0))
    files = sorted(p.name for p in (root / "r1").iterdir())
    assert files == ["0.json"]  # no leftover *.tmp / partial file
    assert backend.load_checkpoint("r1", 0) is not None
