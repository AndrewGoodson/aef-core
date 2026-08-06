"""A minimal, explicit git wrapper for the harness.

One place shells out to git, so the flags that carry security weight are
chosen once and reviewed once — notably `--no-renames` (see `candidate.py`)
and `-z` (filename-safe parsing).

No vendor SDK; `git` is invoked as a subprocess. This module is Zone B.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 60


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitRepo:
    root: Path
    timeout_s: int = DEFAULT_TIMEOUT_S

    def run(self, *args: str) -> str:
        return self._run(*args).stdout.decode("utf-8", errors="replace")

    def run_bytes(self, *args: str) -> bytes:
        return self._run(*args).stdout

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:  # pragma: no cover - git is a hard dep
            raise GitError("git executable not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} timed out after {self.timeout_s}s") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"git {' '.join(args)} failed ({completed.returncode}): {stderr}")
        return completed

    def rev_parse(self, ref: str) -> str:
        return self.run("rev-parse", "--verify", f"{ref}^{{commit}}").strip()

    def merge_base(self, base: str, head: str) -> str:
        return self.run("merge-base", base, head).strip()

    def show(self, ref: str, path: str) -> str:
        """Contents of ``path`` as of ``ref``.

        Explicit base-ref reads use this primitive. The provenance of the
        executing harness is established by its launcher, not by this method;
        see ``trust.py`` and ADR 0047.
        """
        return self.run("show", f"{ref}:{path}")

    def path_exists_at(self, ref: str, path: str) -> bool:
        try:
            self.run("cat-file", "-e", f"{ref}:{path}")
        except GitError:
            return False
        return True

    def list_tree(self, ref: str, prefix: str) -> tuple[str, ...]:
        """Every file path under `prefix` as of `ref`.

        Exists because G5's drift metric compares two dicts of path -> bytes
        and is only meaningful when both describe the **same tree**. Feeding
        it a whole-tree baseline and a changed-files-only candidate made every
        untouched file read as deleted (ADR 0074).
        """
        try:
            out = self.run("ls-tree", "-r", "--name-only", "-z", ref, "--", prefix)
        except GitError:
            return ()
        return tuple(p for p in out.split("\0") if p)

    def raw_diff(self, base: str, head: str) -> bytes:
        """`git diff --raw -z --no-renames base...head`.

        `...` is the symmetric form: changes on `head` since its merge-base
        with `base`, which is exactly "what this candidate proposes" and not
        "everything that has happened on base meanwhile".

        `--no-renames` is a **security** flag, not a cosmetic one. With
        rename detection on, moving `aef/kernel/executor.py` to
        `agents/executor.py` reports only the destination path, so a zone
        check would see one Zone A file and wave through the deletion of a
        core one. `--no-renames` reports the delete and the add separately.

        `-z` makes parsing independent of filename contents; without it git
        quotes paths containing spaces, tabs, or newlines.
        """
        return self.run_bytes("diff", "--raw", "-z", "--no-renames", f"{base}...{head}")

    def numstat_diff(self, base: str, head: str) -> bytes:
        """`added\\tremoved\\0path\\0` per entry — the diff-size input the
        G0 budget (Q-A1) applies a threshold to. Same flags, same reasons."""
        return self.run_bytes("diff", "--numstat", "-z", "--no-renames", f"{base}...{head}")
