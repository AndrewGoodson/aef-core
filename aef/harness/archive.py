"""The archive — every accepted change, restorable exactly.

Must exist before anything is ever accepted, so that anything accepted can
be undone.

**It stores content, not references.** The three-reviewer audit found this
directly (04 §1.9): a palette ref is a *name*, and the code behind that name
changes under ordinary human PRs. An archive recording "version 7 used
`agents.planner:build`" would restore a version whose *meaning* had silently
changed. So each entry stores the bytes of every Zone A file plus a SHA-256
of each, and a restore verifies the digests before writing anything.

**It does not depend on git.** Git shas are recorded because they are useful
provenance, but the content lives in the archive: an archive that stops
working after `git gc`, a force-push, or a branch deletion is not an archive.

**It is append-only.** Versions are monotonic and an existing version is
never overwritten — `record()` refuses. A rollback does not delete the
version it rolled back from; it appends a new version whose content is the
old one, so the history of what was tried stays legible.

Writes use the kernel's crash-safe helper (`durability._atomic_write_text`:
temp file in the same directory, `fsync`, `os.replace`, directory `fsync`) —
deliberately the same implementation the checkpointer uses rather than a
second one that would need proving separately (ADR 0031).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aef.kernel.durability import _atomic_write_text

ENTRY_FILENAME = "entry.json"
FILES_DIRNAME = "files"


class ArchiveError(RuntimeError):
    pass


class ArchiveIntegrityError(ArchiveError):
    """Stored content does not match its recorded digest. Its own type
    because this is corruption or tampering, not a missing entry."""


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ArchiveEntry:
    version: int
    graph_id: str
    base_sha: str
    head_sha: str
    recorded_at: datetime
    file_digests: dict[str, str] = field(default_factory=dict)
    gate_report: tuple[str, ...] = ()
    rolled_back_from: int | None = None
    notes: str = ""
    # WHICH Zone A tree this entry is the baseline of. A baseline is the whole
    # agent root, so the root is part of what was blessed — and nothing wrote
    # it down until ADR 0167, so a baseline blessed under `--agent-root
    # .claude/agents` and a later cycle at the default `agents` root compared
    # two disjoint trees and charged the first candidate 1.000 drift.
    # Defaults to "" so every entry written before this field existed still
    # loads, and "" means "not recorded" rather than "the repo root".
    agent_root: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "graph_id": self.graph_id,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "recorded_at": self.recorded_at.isoformat(),
            "file_digests": dict(sorted(self.file_digests.items())),
            "gate_report": list(self.gate_report),
            "rolled_back_from": self.rolled_back_from,
            "notes": self.notes,
            "agent_root": self.agent_root,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ArchiveEntry:
        try:
            return cls(
                version=int(payload["version"]),
                graph_id=payload["graph_id"],
                base_sha=payload["base_sha"],
                head_sha=payload["head_sha"],
                recorded_at=datetime.fromisoformat(payload["recorded_at"]),
                file_digests=dict(payload.get("file_digests", {})),
                gate_report=tuple(payload.get("gate_report", ())),
                rolled_back_from=payload.get("rolled_back_from"),
                notes=payload.get("notes", ""),
                agent_root=str(payload.get("agent_root", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ArchiveError(f"malformed archive entry: {exc}") from exc


def _graph_dir(root: Path, graph_id: str) -> Path:
    return root / graph_id


def _version_dir(root: Path, graph_id: str, version: int) -> Path:
    return _graph_dir(root, graph_id) / f"v{version:06d}"


def versions(root: Path, graph_id: str) -> tuple[int, ...]:
    directory = _graph_dir(root, graph_id)
    if not directory.is_dir():
        return ()
    found = sorted(
        int(p.name[1:]) for p in directory.iterdir() if p.is_dir() and p.name.startswith("v")
    )
    return tuple(found)


def next_version(root: Path, graph_id: str) -> int:
    existing = versions(root, graph_id)
    return (existing[-1] + 1) if existing else 1


def record(
    root: Path,
    graph_id: str,
    *,
    files: dict[str, bytes],
    base_sha: str,
    head_sha: str,
    recorded_at: datetime,
    gate_report: tuple[str, ...] = (),
    rolled_back_from: int | None = None,
    notes: str = "",
    agent_root: str = "",
) -> ArchiveEntry:
    """Append a new version. Refuses to overwrite an existing one."""
    version = next_version(root, graph_id)
    directory = _version_dir(root, graph_id, version)
    if directory.exists():  # pragma: no cover - next_version precludes it
        raise ArchiveError(f"archive version {version} for {graph_id!r} already exists")

    entry = ArchiveEntry(
        version=version,
        graph_id=graph_id,
        base_sha=base_sha,
        head_sha=head_sha,
        recorded_at=recorded_at,
        file_digests={path: digest(content) for path, content in files.items()},
        gate_report=gate_report,
        rolled_back_from=rolled_back_from,
        notes=notes,
        agent_root=agent_root,
    )

    files_dir = directory / FILES_DIRNAME
    for path, content in files.items():
        target = (files_dir / path).resolve()
        if not target.is_relative_to(files_dir.resolve()):
            raise ArchiveError(f"refusing to archive {path!r} outside the version directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    directory.mkdir(parents=True, exist_ok=True)
    # Written last, and atomically: the entry file is what makes a version
    # real, so a crash mid-write leaves a directory with no entry rather than
    # an entry describing files that are not all there.
    _atomic_write_text(
        directory / ENTRY_FILENAME, json.dumps(entry.to_payload(), indent=2, sort_keys=True) + "\n"
    )
    return entry


def load_entry(root: Path, graph_id: str, version: int) -> ArchiveEntry:
    path = _version_dir(root, graph_id, version) / ENTRY_FILENAME
    if not path.is_file():
        raise ArchiveError(f"no archived version {version} for graph {graph_id!r}")
    try:
        return ArchiveEntry.from_payload(json.loads(path.read_text()))
    except json.JSONDecodeError as exc:
        raise ArchiveError(f"{path}: not valid JSON: {exc}") from exc


def read_files(root: Path, graph_id: str, version: int) -> dict[str, bytes]:
    """Archived content, **digest-verified**. Raises rather than returning
    content that does not match what was recorded."""
    entry = load_entry(root, graph_id, version)
    files_dir = _version_dir(root, graph_id, version) / FILES_DIRNAME

    contents: dict[str, bytes] = {}
    for path, expected in entry.file_digests.items():
        blob = files_dir / path
        if not blob.is_file():
            raise ArchiveIntegrityError(f"{graph_id} v{version}: archived file {path!r} is missing")
        content = blob.read_bytes()
        actual = digest(content)
        if actual != expected:
            raise ArchiveIntegrityError(
                f"{graph_id} v{version}: {path!r} digest mismatch — recorded {expected}, "
                f"found {actual}. The archive has been altered; a rollback from it would "
                f"restore something other than what was accepted."
            )
        contents[path] = content
    return contents


def verify(root: Path, graph_id: str, version: int) -> None:
    read_files(root, graph_id, version)


def rollback(
    root: Path,
    graph_id: str,
    version: int,
    dest: Path,
    *,
    recorded_at: datetime,
    notes: str = "",
) -> ArchiveEntry:
    """Restore `version`'s content into `dest` and append it as a NEW version.

    A rollback is itself an owner-visible change, so it is archived rather
    than pretended never to have happened. The version rolled back *from* is
    left in place: erasing it would hide the very thing a rollback is
    evidence about.
    """
    contents = read_files(root, graph_id, version)
    previous = next_version(root, graph_id) - 1

    dest = dest.resolve()
    for path, content in contents.items():
        target = (dest / path).resolve()
        if not target.is_relative_to(dest):  # pragma: no cover - record() precludes it
            raise ArchiveError(f"refusing to restore {path!r} outside {dest}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    source = load_entry(root, graph_id, version)
    return record(
        root,
        graph_id,
        files=contents,
        base_sha=source.base_sha,
        head_sha=source.head_sha,
        recorded_at=recorded_at,
        gate_report=(f"rollback to v{version}",),
        rolled_back_from=previous,
        notes=notes or f"rollback to v{version}",
    )


def check_never_shrinks(root: Path, graph_id: str, known: tuple[int, ...]) -> None:
    """Raise unless every previously-recorded version is still present."""
    present = set(versions(root, graph_id))
    missing = sorted(set(known) - present)
    if missing:
        raise ArchiveError(
            f"archive for {graph_id!r} lost version(s) {missing}; history that can be "
            f"deleted is not an audit trail"
        )
