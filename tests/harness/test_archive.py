"""Archive + rollback.

M6's acceptance properties. The one that matters most is digest
verification: an archive that would hand back altered content is worse than
no archive, because a rollback from it restores something other than what
was accepted.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.archive import (
    ArchiveError,
    ArchiveIntegrityError,
    check_never_shrinks,
    digest,
    load_entry,
    next_version,
    read_files,
    record,
    rollback,
    verify,
    versions,
)

AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _record(root: Path, content: bytes = b"VALUE = 1\n", **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "files": {"agents/planner.py": content},
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "recorded_at": AT,
    }
    kwargs.update(overrides)
    return record(root, "planner", **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def test_the_first_version_is_one(tmp_path: Path) -> None:
    assert next_version(tmp_path, "planner") == 1
    entry = _record(tmp_path)
    assert entry.version == 1  # type: ignore[attr-defined]


def test_versions_are_monotonic(tmp_path: Path) -> None:
    for _ in range(3):
        _record(tmp_path)
    assert versions(tmp_path, "planner") == (1, 2, 3)


def test_an_entry_records_the_digest_of_every_file(tmp_path: Path) -> None:
    entry = _record(tmp_path, b"CONTENT\n")
    assert entry.file_digests["agents/planner.py"] == digest(b"CONTENT\n")  # type: ignore[attr-defined]


def test_an_entry_round_trips_from_disk(tmp_path: Path) -> None:
    original = _record(tmp_path, gate_report=("G0: pass", "G1: pass"))
    restored = load_entry(tmp_path, "planner", 1)
    assert restored == original


def test_recording_never_overwrites_an_existing_version(tmp_path: Path) -> None:
    _record(tmp_path, b"first\n")
    _record(tmp_path, b"second\n")
    # v1 is untouched by the later write.
    assert read_files(tmp_path, "planner", 1)["agents/planner.py"] == b"first\n"


def test_an_unknown_version_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match="no archived version"):
        load_entry(tmp_path, "planner", 99)


def test_an_unknown_graph_has_no_versions(tmp_path: Path) -> None:
    assert versions(tmp_path, "never-seen") == ()


# --------------------------------------------------------------------------
# M6 ACCEPTANCE — content, not references
# --------------------------------------------------------------------------


def test_the_archive_stores_content_not_a_reference(tmp_path: Path) -> None:
    """A palette ref is a NAME, and the code behind it changes under ordinary
    human PRs. Storing the ref would restore a version whose meaning had
    silently changed (04 §1.9)."""
    _record(tmp_path, b"ORIGINAL = 1\n")
    files_dir = tmp_path / "planner" / "v000001" / "files"
    assert (files_dir / "agents" / "planner.py").read_bytes() == b"ORIGINAL = 1\n"


def test_the_archive_does_not_depend_on_git(tmp_path: Path) -> None:
    # There is no repository here at all. An archive that stops working after
    # `git gc` or a force-push is not an archive.
    entry = _record(tmp_path, b"STANDALONE = 1\n")
    assert read_files(tmp_path, "planner", entry.version)  # type: ignore[attr-defined]


def test_a_tampered_archive_file_is_detected(tmp_path: Path) -> None:
    """THE integrity test. Handing back altered content would mean a rollback
    restores something other than what was accepted."""
    _record(tmp_path, b"ACCEPTED = 1\n")
    blob = tmp_path / "planner" / "v000001" / "files" / "agents" / "planner.py"
    blob.write_bytes(b"ALTERED = 1\n")

    with pytest.raises(ArchiveIntegrityError, match="digest mismatch"):
        read_files(tmp_path, "planner", 1)


def test_a_deleted_archive_file_is_detected(tmp_path: Path) -> None:
    _record(tmp_path)
    (tmp_path / "planner" / "v000001" / "files" / "agents" / "planner.py").unlink()
    with pytest.raises(ArchiveIntegrityError, match="missing"):
        verify(tmp_path, "planner", 1)


def test_an_intact_archive_verifies(tmp_path: Path) -> None:
    _record(tmp_path)
    verify(tmp_path, "planner", 1)


# --------------------------------------------------------------------------
# M6 ACCEPTANCE — rollback restores exactly
# --------------------------------------------------------------------------


def test_rollback_restores_the_exact_prior_content(tmp_path: Path) -> None:
    _record(tmp_path, b"GOOD = 1\n")
    _record(tmp_path, b"REGRESSION = 1\n")

    dest = tmp_path / "worktree"
    rollback(tmp_path, "planner", 1, dest, recorded_at=AT)

    assert (dest / "agents" / "planner.py").read_bytes() == b"GOOD = 1\n"


def test_rollback_is_itself_recorded_as_a_new_version(tmp_path: Path) -> None:
    # A rollback is an owner-visible change, not something that pretends
    # never to have happened.
    _record(tmp_path, b"GOOD = 1\n")
    _record(tmp_path, b"BAD = 1\n")

    entry = rollback(tmp_path, "planner", 1, tmp_path / "wt", recorded_at=AT)

    assert entry.version == 3
    assert entry.rolled_back_from == 2
    assert versions(tmp_path, "planner") == (1, 2, 3)


def test_rollback_does_not_delete_the_version_it_rolled_back_from(tmp_path: Path) -> None:
    # Erasing it would hide the very thing the rollback is evidence about.
    _record(tmp_path, b"GOOD = 1\n")
    _record(tmp_path, b"BAD = 1\n")
    rollback(tmp_path, "planner", 1, tmp_path / "wt", recorded_at=AT)

    assert read_files(tmp_path, "planner", 2)["agents/planner.py"] == b"BAD = 1\n"


def test_the_rolled_back_version_is_byte_identical_to_its_source(tmp_path: Path) -> None:
    _record(tmp_path, b"GOOD = 1\n")
    _record(tmp_path, b"BAD = 1\n")
    entry = rollback(tmp_path, "planner", 1, tmp_path / "wt", recorded_at=AT)

    assert read_files(tmp_path, "planner", entry.version) == read_files(tmp_path, "planner", 1)


def test_rollback_from_a_tampered_version_refuses(tmp_path: Path) -> None:
    _record(tmp_path, b"GOOD = 1\n")
    blob = tmp_path / "planner" / "v000001" / "files" / "agents" / "planner.py"
    blob.write_bytes(b"TAMPERED\n")

    with pytest.raises(ArchiveIntegrityError):
        rollback(tmp_path, "planner", 1, tmp_path / "wt", recorded_at=AT)


def test_rollback_restores_multiple_files(tmp_path: Path) -> None:
    _record(tmp_path, files={"agents/a.py": b"A\n", "agents/sub/b.py": b"B\n"})
    dest = tmp_path / "wt"
    rollback(tmp_path, "planner", 1, dest, recorded_at=AT)

    assert (dest / "agents" / "a.py").read_bytes() == b"A\n"
    assert (dest / "agents" / "sub" / "b.py").read_bytes() == b"B\n"


# --------------------------------------------------------------------------
# Never shrinks
# --------------------------------------------------------------------------


def test_a_growing_archive_passes_the_never_shrinks_check(tmp_path: Path) -> None:
    _record(tmp_path)
    known = versions(tmp_path, "planner")
    _record(tmp_path)
    check_never_shrinks(tmp_path, "planner", known)


def test_deleting_a_version_is_caught(tmp_path: Path) -> None:
    import shutil

    _record(tmp_path)
    _record(tmp_path)
    known = versions(tmp_path, "planner")

    shutil.rmtree(tmp_path / "planner" / "v000001")

    with pytest.raises(ArchiveError, match="lost version"):
        check_never_shrinks(tmp_path, "planner", known)


def test_a_path_escaping_the_version_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match="outside"):
        _record(tmp_path, files={"../../escape.py": b"x\n"})
