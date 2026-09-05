"""Archive + rollback.

M6's acceptance properties. The one that matters most is digest
verification: an archive that would hand back altered content is worse than
no archive, because a rollback from it restores something other than what
was accepted.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.archive import (
    ArchiveError,
    ArchiveIntegrityError,
    LineageIntegrityError,
    LineageRecord,
    append_lineage,
    check_never_shrinks,
    digest,
    lineage_path,
    load_entry,
    next_version,
    read_files,
    read_lineage,
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


# ---------------------------------------------------------------------------
# The lineage store (ADR 0160) — a second store, deliberately beside the
# version archive rather than inside it
# ---------------------------------------------------------------------------


def _member(**kw: object) -> LineageRecord:
    base: dict[str, object] = {
        "run_id": "20260904T000000",
        "turn": 1,
        "ref": "a" * 40,
        "tree": "b" * 40,
        "parent_ref": "c" * 40,
        "score": 0.7,
        "kept": True,
        "disposition": "escalate",
        "recorded_at": AT,
    }
    base.update(kw)
    return LineageRecord(**base)  # type: ignore[arg-type]


def test_lineage_round_trips_kept_and_rejected_members(tmp_path: Path) -> None:
    append_lineage(tmp_path, "planner", _member())
    append_lineage(
        tmp_path, "planner", _member(turn=2, ref="d" * 40, kept=False, disposition="reject")
    )
    got = read_lineage(tmp_path, "planner")

    assert [r.turn for r in got] == [1, 2]
    assert [r.kept for r in got] == [True, False]
    assert [r.disposition for r in got] == ["escalate", "reject"]
    assert got[0].recorded_at == AT


def test_lineage_is_per_graph_and_empty_before_anything_runs(tmp_path: Path) -> None:
    assert read_lineage(tmp_path, "planner") == ()
    append_lineage(tmp_path, "planner", _member())
    assert read_lineage(tmp_path, "critic") == ()
    assert len(read_lineage(tmp_path, "planner")) == 1


def test_an_altered_lineage_record_is_refused(tmp_path: Path) -> None:
    """The same stance as `read_files`: raise rather than hand back something
    other than what was recorded. A parent sampled from a doctored record is
    not the candidate the gates measured — the score that earned it its
    sampling weight would describe a different tree."""
    append_lineage(tmp_path, "planner", _member(score=0.2))
    path = lineage_path(tmp_path, "planner")
    payload = json.loads(path.read_text())
    payload["record"]["score"] = 0.99  # a better parent, on paper
    path.write_text(json.dumps(payload) + "\n")

    with pytest.raises(LineageIntegrityError, match="digest mismatch"):
        read_lineage(tmp_path, "planner")


def test_a_torn_tail_line_is_a_named_refusal_not_a_silent_member(tmp_path: Path) -> None:
    append_lineage(tmp_path, "planner", _member())
    path = lineage_path(tmp_path, "planner")
    path.write_text(path.read_text() + '{"record": {"ref": "x"}\n')

    with pytest.raises(LineageIntegrityError, match="not a lineage record"):
        read_lineage(tmp_path, "planner")


def test_the_lineage_store_never_enters_the_version_archive(tmp_path: Path) -> None:
    """The separation is the safety property, so it is a test and not only a
    comment. `versions()` is what `_blessed_files` reads as G5's baseline and
    what `monitor` rolls back to; a rejected candidate must never be able to
    reach either by being written down."""
    _record(tmp_path)
    append_lineage(tmp_path, "planner", _member(kept=False, disposition="reject"))

    assert versions(tmp_path, "planner") == (1,)
    assert read_files(tmp_path, "planner", 1).keys() == {"agents/planner.py"}
    known = versions(tmp_path, "planner")
    check_never_shrinks(tmp_path, "planner", known)  # a lineage write is not a version


@pytest.mark.parametrize("graph_id", ["../escape", "a/b", "/etc/x", ".."])
def test_a_traversing_graph_id_is_refused_by_the_lineage_store_too(
    tmp_path: Path, graph_id: str
) -> None:
    """ADR 0168 found this in `_graph_dir` and fixed it there. The lineage
    store is a second place a graph id is joined onto a directory, written
    after that fix, and it inherits the refusal rather than the hole."""
    with pytest.raises(ArchiveError, match="not usable as a lineage filename"):
        lineage_path(tmp_path, graph_id)
    with pytest.raises(ArchiveError):
        read_lineage(tmp_path, graph_id)
    with pytest.raises(ArchiveError):
        append_lineage(tmp_path, graph_id, _member())


# ---------------------------------------------------------------------------
# ADR 0168 / S2 — a graph id is joined onto a directory
#
# REPRODUCED, with `root` at `<tmp>/state/archive`:
#
#     >>> record(root, "../escape", files={"agents/graph.py": b"x = 1\n"}, ...)
#     recorded version 1
#     archive root contents: []
#     WROTE state/escape/v000001/entry.json
#     WROTE state/escape/v000001/files/agents/graph.py
#
# One level ABOVE the archive root, which was left empty. A graph id is not an
# internal token: `aef migrate` reads it from a persona's `name:` frontmatter
# and prints it as the value to hand `aef loop bless --graph-id`.
# ---------------------------------------------------------------------------
ESCAPING_IDS = ("../escape", "../../etc", "a/b", "/absolute", "", ".", "..")


@pytest.mark.parametrize("graph_id", ESCAPING_IDS)
def test_record_refuses_a_graph_id_that_is_not_one_path_segment(
    tmp_path: Path, graph_id: str
) -> None:
    root = tmp_path / "state" / "archive"
    root.mkdir(parents=True)
    with pytest.raises(ArchiveError) as exc:
        record(
            root,
            graph_id,
            files={"agents/graph.py": b"x = 1\n"},
            base_sha="a" * 40,
            head_sha="b" * 40,
            recorded_at=AT,
        )
    assert "not usable as an archive directory" in str(exc.value)
    # Nothing was written anywhere - not in the archive, not beside it.
    assert list(root.iterdir()) == []
    assert sorted(p.name for p in (tmp_path / "state").iterdir()) == ["archive"]


@pytest.mark.parametrize("graph_id", ESCAPING_IDS)
def test_versions_refuses_the_same_ids_reads_and_writes_agree(
    tmp_path: Path, graph_id: str
) -> None:
    """Refused in the ONE place both go through. A `versions()` that quietly
    returned `()` for an id `record()` rejects would report an empty history
    for a graph that cannot have one, which is the shape ADR 0139 calls
    silently inert."""
    root = tmp_path / "archive"
    root.mkdir()
    with pytest.raises(ArchiveError):
        versions(root, graph_id)


def test_a_safe_graph_id_is_untouched(tmp_path: Path) -> None:
    """The control: the refusal must not have narrowed what an ordinary id may
    be. Dots, dashes and underscores inside a segment are all still fine."""
    root = tmp_path / "archive"
    root.mkdir()
    for graph_id in ("planner", "marlin-accela", "agent_2", "v1.2.3", ".hidden"):
        entry = record(
            root,
            graph_id,
            files={"agents/graph.py": b"x = 1\n"},
            base_sha="a" * 40,
            head_sha="b" * 40,
            recorded_at=AT,
        )
        assert entry.version == 1
        assert (root / graph_id / "v000001").is_dir()
        assert versions(root, graph_id) == (1,)
