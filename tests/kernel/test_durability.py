from pathlib import Path

import pytest

from aef.kernel import (
    CorruptedCheckpointError,
    FileDurabilityBackend,
    InMemoryDurabilityBackend,
    PostgresDurabilityBackend,
    TemporalDurabilityBackend,
)
from aef.kernel.durability import DurabilityBackend
from aef.state import AEFState


def test_phase2_durability_stubs_fail_loudly_on_construction() -> None:
    """Postgres/Temporal backends are exported public symbols, so a user can
    import and instantiate them. Their one promised Phase-0/1 behavior — fail
    loudly with a Phase-2 pointer, never silently half-work — must be pinned,
    or a deleted `raise` / half-built backend would ship uncaught."""
    with pytest.raises(NotImplementedError, match="Phase 2"):
        PostgresDurabilityBackend(dsn="postgres://ignored")
    with pytest.raises(NotImplementedError, match="Phase 2"):
        TemporalDurabilityBackend(task_queue="ignored")


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


def test_cursor_cannot_be_paired_with_a_later_checkpoint(backend: DurabilityBackend) -> None:
    backend.save_checkpoint(_state(seq=0))
    backend.save_cursor("r1", "node_a")
    backend.save_checkpoint(_state(seq=1))
    with pytest.raises(CorruptedCheckpointError, match="cursor.*checkpoint"):
        backend.load_cursor("r1")
    assert backend.list_checkpoints("r1") == [0, 1]
    assert backend.load_latest("r1") == _state(seq=1)


def test_checkpoint_without_cursor_is_not_completion(backend: DurabilityBackend) -> None:
    backend.save_checkpoint(_state())
    with pytest.raises(CorruptedCheckpointError, match="cursor.*checkpoint"):
        backend.load_cursor("r1")


def test_checkpoint_identity_cannot_be_replaced_under_existing_cursor(
    backend: DurabilityBackend,
) -> None:
    original = _state(seq=1).model_copy(update={"reflections": ["A ran"]})
    backend.save_checkpoint(original)
    backend.save_cursor("r1", "node_b")
    changed = original.model_copy(update={"reflections": ["A ran", "B ran"]})
    with pytest.raises(CorruptedCheckpointError, match="immutable"):
        backend.save_checkpoint(changed)
    assert backend.load_checkpoint("r1", 1) == original
    assert backend.load_cursor("r1") == "node_b"


def test_identical_checkpoint_retry_preserves_cursor(backend: DurabilityBackend) -> None:
    backend.save_checkpoint(_state(seq=1))
    backend.save_cursor("r1", "node_b")
    backend.save_checkpoint(_state(seq=1))
    assert backend.load_cursor("r1") == "node_b"


def test_file_checkpoint_retry_after_restart_does_not_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aef.kernel.durability as durability

    FileDurabilityBackend(tmp_path).save_checkpoint(_state(seq=1))

    def unexpected_write(path: Path, text: str) -> None:
        pytest.fail("an identical checkpoint retry must not rewrite the checkpoint")

    monkeypatch.setattr(durability, "_atomic_write_text", unexpected_write)
    FileDurabilityBackend(tmp_path).save_checkpoint(_state(seq=1))


def test_saving_over_corrupt_checkpoint_preserves_evidence(tmp_path: Path) -> None:
    backend = FileDurabilityBackend(tmp_path)
    backend.save_checkpoint(_state(seq=1))
    backend.save_cursor("r1", "node_b")
    path = tmp_path / "r1" / "1.json"
    path.write_text("{torn checkpoint")
    with pytest.raises(CorruptedCheckpointError):
        backend.save_checkpoint(_state(seq=1))
    assert path.read_text() == "{torn checkpoint"


@pytest.mark.parametrize("field,value", [("run_id", "other"), ("checkpoint_seq", 5)])
def test_file_checkpoint_payload_must_match_requested_identity(
    tmp_path: Path, field: str, value: str | int
) -> None:
    backend = FileDurabilityBackend(tmp_path)
    backend.save_checkpoint(_state(seq=1))
    changed = _state(seq=1).model_copy(update={field: value})
    path = tmp_path / "r1" / "1.json"
    path.write_text(changed.model_dump_json())
    with pytest.raises(CorruptedCheckpointError, match="identity"):
        backend.load_checkpoint("r1", 1)
    assert path.read_text() == changed.model_dump_json()


def test_cursor_for_an_older_write_cannot_claim_a_newer_checkpoint(
    backend: DurabilityBackend,
) -> None:
    backend.save_checkpoint(_state(seq=1))
    backend.save_cursor("r1", "node_b")
    backend.save_checkpoint(_state(seq=0))
    backend.save_cursor("r1", "node_a")
    with pytest.raises(CorruptedCheckpointError, match="cursor.*checkpoint"):
        backend.load_cursor("r1")


@pytest.mark.parametrize("next_node", ["node_b", None])
def test_legacy_cursor_remains_inspectable_but_cannot_resume_unbound_checkpoint(
    tmp_path: Path, next_node: str | None
) -> None:
    import json

    backend = FileDurabilityBackend(tmp_path)
    backend.save_checkpoint(_state())
    (tmp_path / "r1" / "cursor.json").write_text(json.dumps({"next_node": next_node}))
    assert backend.load_checkpoint("r1", 0) == _state()
    with pytest.raises(CorruptedCheckpointError, match="legacy checkpoint/cursor pair"):
        backend.load_cursor("r1")


@pytest.mark.parametrize("checkpoint_seq", [True, False, "0", -1, 0.0, [], {}])
def test_cursor_rejects_malformed_checkpoint_binding(
    tmp_path: Path, checkpoint_seq: object
) -> None:
    import json

    backend = FileDurabilityBackend(tmp_path)
    backend.save_checkpoint(_state())
    (tmp_path / "r1" / "cursor.json").write_text(
        json.dumps({"next_node": None, "checkpoint_seq": checkpoint_seq})
    )
    with pytest.raises(CorruptedCheckpointError, match="invalid checkpoint_seq"):
        backend.load_cursor("r1")


def test_file_backend_records_steps_without_rescanning_checkpoint_history(tmp_path: Path) -> None:
    class CountScans(FileDurabilityBackend):
        scans = 0

        def list_checkpoints(self, run_id: str) -> list[int]:
            self.scans += 1
            return super().list_checkpoints(run_id)

    backend = CountScans(tmp_path)
    for seq in range(20):
        backend.save_checkpoint(_state(seq=seq))
        backend.save_cursor("r1", "node_b")
    assert backend.scans == 0
    assert FileDurabilityBackend(tmp_path).load_cursor("r1") == "node_b"


def test_file_backend_cursor_survives_new_instance_same_dir(tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    FileDurabilityBackend(root).save_cursor("r1", "node_b")
    reloaded = FileDurabilityBackend(root)
    assert reloaded.load_cursor("r1") == "node_b"


@pytest.mark.parametrize("operation", ["load_checkpoint", "list_checkpoints", "load_cursor"])
def test_file_backend_reads_reject_run_ids_that_escape_the_root(
    tmp_path: Path, operation: str
) -> None:
    """Read paths must enforce the same containment boundary as writes."""
    outside = FileDurabilityBackend(tmp_path / "outside")
    outside.save_checkpoint(_state(run_id="victim", seq=0))
    outside.save_cursor("victim", "node_b")
    backend = FileDurabilityBackend(tmp_path / "checkpoints")
    escaped_run_id = "../outside/victim"

    with pytest.raises(ValueError, match="directory name, not a path"):
        if operation == "load_checkpoint":
            backend.load_checkpoint(escaped_run_id, 0)
        elif operation == "list_checkpoints":
            backend.list_checkpoints(escaped_run_id)
        else:
            backend.load_cursor(escaped_run_id)


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


@pytest.mark.parametrize(
    "payload",
    ['{"next_node": 7}', "{}", "[]", '"node_b"'],
)
def test_load_cursor_rejects_valid_json_with_invalid_schema(tmp_path: Path, payload: str) -> None:
    """A schema-invalid cursor must not be treated as a completed run."""
    root = tmp_path / "checkpoints"
    backend = FileDurabilityBackend(root)
    backend.save_cursor("r1", "node_b")
    (root / "r1" / "cursor.json").write_text(payload)

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


def test_atomic_write_completes_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    real_write = os.write

    def short_write(fd: int, data: bytes | memoryview) -> int:
        return real_write(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(os, "write", short_write)
    backend = FileDurabilityBackend(tmp_path)
    backend.save_checkpoint(_state())
    backend.save_cursor("r1", "node_b")
    assert backend.load_checkpoint("r1", 0) == _state()
    assert backend.load_cursor("r1") == "node_b"


def test_zero_byte_write_preserves_previous_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    backend = FileDurabilityBackend(tmp_path)
    backend.save_checkpoint(_state())
    real_write = os.write
    calls = 0

    def stopped_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        return 0 if calls == 1 else real_write(fd, data)

    monkeypatch.setattr(os, "write", stopped_write)
    with pytest.raises(OSError, match="made no progress"):
        backend.save_checkpoint(_state(seq=1))
    assert backend.load_checkpoint("r1", 0) == _state()
    assert backend.load_checkpoint("r1", 1) is None
