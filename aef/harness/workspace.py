"""Building the tree a gate actually runs against.

A candidate cannot simply be checked out and tested: that would run the
branch's harness, which is the thing ADR 0047 exists to prevent. Nor can the
base ref be tested alone — it does not contain the change.

The workspace is the **post-merge state**: every file as of the base ref,
with the candidate's **Zone A files only** overlaid. That is exactly what the
repository would look like after this candidate merged, because a candidate
that could alter anything outside Zone A would have been rejected before
reaching here.

Constructing it this way rather than by `git checkout <branch>` means the
trust boundary holds even if a zone check upstream has a bug: the overlay
loop refuses any path it cannot classify Zone A, so a Zone B or C file has no
route into the tree gates run against.
"""

from __future__ import annotations

from pathlib import Path

from aef.harness.candidate import CandidateDiff
from aef.harness.git import GitRepo
from aef.harness.trust import TrustBoundaryError
from aef.harness.zones import Zone, ZonePolicy, classify_path


def build_candidate_workspace(
    repo: GitRepo,
    diff: CandidateDiff,
    dest: Path,
    policy: ZonePolicy | None = None,
) -> Path:
    """Materialise base-ref tree + the candidate's Zone A overlay into `dest`."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    repo.run("archive", "--format=tar", "-o", str(dest / "_base.tar"), diff.base_sha)
    _extract_tar(dest / "_base.tar", dest)
    (dest / "_base.tar").unlink()

    for entry in diff.entries:
        zone = classify_path(entry.path, policy)
        if zone is not Zone.A:
            # Defence in depth: G0 should already have rejected this
            # candidate. If it did not, the file still never lands.
            raise TrustBoundaryError(
                f"refusing to overlay {entry.path!r} into the candidate workspace: it is "
                f"Zone {zone.value}, and only Zone A may differ from the base ref"
            )
        target = (dest / entry.path).resolve()
        if not target.is_relative_to(dest):  # pragma: no cover - zones reject traversal first
            raise TrustBoundaryError(f"refusing to write {entry.path!r} outside {dest}")

        if entry.is_deletion:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(repo.run_bytes("show", f"{diff.head_sha}:{entry.path}"))

    return dest


def _extract_tar(archive: Path, dest: Path) -> None:
    import tarfile

    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            # `git archive` cannot emit these, but the check costs nothing
            # and this function writes to disk.
            if member.islnk() or member.issym() or Path(member.name).is_absolute():
                continue
            target = (dest / member.name).resolve()
            if not target.is_relative_to(dest):
                continue
            tar.extract(member, dest, filter="data")
