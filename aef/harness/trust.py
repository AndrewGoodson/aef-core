"""The trust boundary: **gates execute from the base ref, never the branch.**

This is the single mechanism that makes self-coding survivable (ADR 0044).
Everything else in the harness is enforcement detail; this is the property
being enforced.

The candidate is **input** to the harness, never part of it. Concretely:
every byte of gate code, corpus, eval suite, and CI configuration is read
through `BaseRefHarness`, which resolves it at the base ref via
`git show <base>:<path>`. A branch may rewrite `aef/harness/gate.py` to
`return True` and it changes nothing — that file is never the one that runs.

Why this and not a review rule: a rule saying "don't let candidates edit
gates" fails open the first time someone forgets to check. Reading from the
base ref fails *closed* by construction — there is no code path that reaches
the branch's copy, so there is nothing to forget.

The zone check (`zones.py`) still rejects Zone B diffs, but as a *signal*
(a security event worth halting on), not as the load-bearing control. If the
zone check were the only defence, a bug in it would be a full escape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aef.harness.git import GitError, GitRepo
from aef.harness.zones import Zone, classify_path


class TrustBoundaryError(RuntimeError):
    """Raised when something tries to read non-harness code through the
    harness API, or to materialise outside the scratch directory."""


@dataclass(frozen=True)
class BaseRefHarness:
    """Reads harness content as of `base_ref`, and refuses anything else."""

    repo: GitRepo
    base_ref: str

    @property
    def base_sha(self) -> str:
        """Pinned once so a concurrent push to the base branch cannot swap
        the harness mid-run."""
        return self.repo.rev_parse(self.base_ref)

    def read(self, path: str) -> str:
        """Contents of a **Zone B** file as of the base ref.

        Refuses any other zone: this API exists to load the judge, and
        loading candidate code through it would defeat the entire boundary.
        Read the candidate with `candidate.py` instead — deliberately a
        different module with a different name.
        """
        zone = classify_path(path)
        if zone is not Zone.B:
            raise TrustBoundaryError(
                f"refusing to read {path!r} through the trust boundary: it is Zone "
                f"{zone.value}, and this API loads harness code (Zone B) only. Candidate "
                f"content is read via aef.harness.candidate, never executed as a gate."
            )
        return self.repo.show(self.base_sha, path)

    def harness_paths(self) -> tuple[str, ...]:
        """Every Zone B path present at the base ref."""
        listing = self.repo.run_bytes("ls-tree", "-r", "--name-only", "-z", self.base_sha)
        names = listing.decode("utf-8", errors="replace").split("\0")
        return tuple(sorted(n for n in names if n and classify_path(n) is Zone.B))

    def materialize(self, dest: Path) -> Path:
        """Write the base ref's harness tree into `dest` and return it.

        Gates run against this directory. Only Zone B lands here — verified
        per path rather than assumed from the export command, so a
        mis-specified path filter cannot quietly widen what gets trusted.
        """
        dest = dest.resolve()
        dest.mkdir(parents=True, exist_ok=True)
        for path in self.harness_paths():
            target = (dest / path).resolve()
            if not target.is_relative_to(dest):  # pragma: no cover - git cannot emit this
                raise TrustBoundaryError(f"refusing to materialise {path!r} outside {dest}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.repo.show(self.base_sha, path))
        return dest

    def verify_base_is_ancestor(self, head_ref: str) -> None:
        """Assert the candidate actually descends from the base ref.

        A branch with no merge-base is not a candidate against this
        incumbent, and diffing it would report the whole tree as changed —
        every path a violation, or worse, a coincidental pass.
        """
        try:
            merge_base = self.repo.merge_base(self.base_ref, head_ref)
        except GitError as exc:
            raise TrustBoundaryError(
                f"{head_ref!r} shares no history with base ref {self.base_ref!r}; it is not "
                f"a candidate against this incumbent"
            ) from exc
        if not merge_base:  # pragma: no cover - git errors instead
            raise TrustBoundaryError(f"no merge base between {self.base_ref!r} and {head_ref!r}")
