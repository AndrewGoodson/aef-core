"""A11 — write outside the archive with a `../escape` graph id.

Reproduced (ADR 0168). A graph id is not an internal token: `aef migrate`
takes it from a persona's `name:` frontmatter and prints it as the value to
hand `aef loop bless --graph-id`. `archive.record` built `root / graph_id`
with nothing in between, so with `root` at `state/archive`:

    recorded version 1
    archive root contents: []
    WROTE state/escape/v000001/entry.json
    WROTE state/escape/v000001/files/agents/graph.py

One level ABOVE the archive root, with the archive root left empty — and the
absolute form is worse, because `pathlib` makes `root / "/etc/x"` discard
`root` entirely.

The refusal is in the ONE place every read and every write goes through, so
`versions()` cannot report on a directory `record()` would not create. And it
refuses rather than sanitises: silently mapping two ids onto one archive is,
for an append-only store, the failure it exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import archive
from aef.harness.archive import ArchiveError
from aef.harness.zones import segment_refusal

AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
FILES = {"agents/graph.py": b"AGENT = 1\n"}

HOSTILE_IDS = [
    "../escape",
    "../../etc",
    "/etc/aef",
    "a/b",
    "./demo",
    "",
    ".",
    "..",
]


def _record(root: Path, graph_id: str) -> archive.ArchiveEntry:
    return archive.record(
        root,
        graph_id,
        files=FILES,
        base_sha="a" * 40,
        head_sha="b" * 40,
        recorded_at=AT,
        notes="red team",
    )


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


@pytest.mark.parametrize("graph_id", HOSTILE_IDS)
def test_a11_a_hostile_graph_id_is_refused_by_record(tmp_path: Path, graph_id: str) -> None:
    state = tmp_path / "state"
    root = state / "archive"
    root.mkdir(parents=True)

    with pytest.raises(ArchiveError):
        _record(root, graph_id)

    # And nothing landed anywhere under the state directory, which is the
    # assertion that actually matters: an exception raised after the write is
    # not a refusal.
    written = [p for p in state.rglob("*") if p.is_file()]
    assert written == [], f"{graph_id!r} wrote {written} before refusing"


@pytest.mark.parametrize("graph_id", HOSTILE_IDS)
def test_a11_the_same_id_is_refused_by_every_reader(tmp_path: Path, graph_id: str) -> None:
    """`versions()` must not be able to report on a directory `record()` would
    refuse to create — one refusal, in the one place both go through."""
    root = tmp_path / "archive"
    root.mkdir()
    with pytest.raises(ArchiveError):
        archive.versions(root, graph_id)


def test_a11_an_ordinary_id_still_works(tmp_path: Path) -> None:
    """The control for the control. A refusal that also refused the normal
    case would pass every test above while breaking the archive."""
    root = tmp_path / "archive"
    root.mkdir()
    entry = _record(root, "demo_agent")
    assert entry.version == 1
    assert archive.versions(root, "demo_agent") == (1,)
    assert (root / "demo_agent").is_dir()


def test_a11_normalisation_is_refused_rather_than_applied() -> None:
    """`./x` and `x` name the same file, and a checker that silently accepted
    the first would let two spellings of one graph id disagree about which
    directory they mean."""
    assert segment_refusal("demo_agent") == ""
    assert "not a single path segment" in segment_refusal("./demo_agent")
    assert segment_refusal("../escape")


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a11_the_control_is_load_bearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack_log: list[str]
) -> None:
    """Neuter `segment_refusal` — the one predicate `_graph_dir` consults —
    and `../escape` writes above the archive root, exactly as reproduced.

    The assertion is on files ON DISK outside the root, not on the return
    value: `record` reported `recorded version 1` while doing this.
    """
    state = tmp_path / "state"
    root = state / "archive"
    root.mkdir(parents=True)

    import aef.harness.archive as archive_module

    monkeypatch.setattr(archive_module, "segment_refusal", lambda name: "")

    entry = _record(root, "../escape")
    escaped = sorted(
        str(p.relative_to(state)) for p in (state / "escape").rglob("*") if p.is_file()
    )
    attack_log.append(f"recorded version {entry.version}; wrote {escaped}")

    assert escaped, attack_log
    assert list(root.iterdir()) == [], (
        f"the archive root is not empty, so the write did not actually escape: {attack_log}"
    )
