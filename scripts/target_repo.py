#!/usr/bin/env python3
"""Launch target-only integration with isolated imports and bytecode disabled."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

# The child receives paths as argv, never as interpolated Python or shell code.
_BOOTSTRAP = """
import sys
sys.path.insert(0, sys.argv[1])
from aef.cli.target_repo import main
raise SystemExit(main(sys.argv[2], profile=sys.argv[3], with_workflows=sys.argv[4] == "true"))
"""


def source_roots(source: Path) -> list[Path]:
    """Include external worktree/common metadata without running Git."""
    roots = [source]
    git_dir = source / ".git"
    if git_dir.is_file():
        marker = git_dir.read_text(encoding="utf-8").strip()
        if not marker.startswith("gitdir: "):
            raise ValueError(f"malformed Git metadata: {git_dir}")
        git_dir = (source / marker.removeprefix("gitdir: ")).resolve(strict=True)
    elif git_dir.is_symlink():
        git_dir = git_dir.resolve(strict=True)
    if git_dir.is_dir():
        candidates = [git_dir]
        common = git_dir / "commondir"
        if common.is_file():
            candidates.append((git_dir / common.read_text().strip()).resolve(strict=True))
        for candidate in candidates:
            if not any(candidate.is_relative_to(root) for root in roots):
                roots.append(candidate)
    return roots


def manifest(roots: list[Path]) -> dict[str, dict[str, object]]:
    """Hash every entry, including ignored files and roots; do not follow links.

    atime is intentionally excluded: reading a file can change it. This is a
    before/after integrity check, not a sandbox or attribution mechanism.
    """
    result: dict[str, dict[str, object]] = {}

    def visit(path: Path) -> None:
        if str(path) in result:
            return
        before = path.lstat()
        entry: dict[str, object] = {
            "mode": before.st_mode,
            "mtime_ns": before.st_mtime_ns,
        }
        if stat.S_ISLNK(before.st_mode):
            entry["link"] = os.readlink(path)
        elif stat.S_ISREG(before.st_mode):
            digest = hashlib.sha256()
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            entry["sha256"] = digest.hexdigest()
            entry["size"] = before.st_size
        elif not stat.S_ISDIR(before.st_mode):
            raise ValueError(f"cannot verify nonregular source entry: {path}")
        result[str(path)] = entry
        if stat.S_ISDIR(before.st_mode):
            with os.scandir(path) as children:
                for child in sorted(children, key=lambda item: item.name):
                    visit(Path(child.path))
        after = path.lstat()
        if (before.st_mode, before.st_mtime_ns, before.st_ino, before.st_size) != (
            after.st_mode,
            after.st_mtime_ns,
            after.st_ino,
            after.st_size,
        ):
            raise ValueError(f"source changed while taking manifest: {path}")

    for root in roots:
        visit(root)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="absolute path to an existing, separate target repository")
    parser.add_argument("--profile", choices=("offline", "model"), default="offline")
    parser.add_argument("--with-workflows", action="store_true")
    args = parser.parse_args()
    if args.with_workflows and args.profile != "model":
        parser.error("--with-workflows requires --profile model")
    target = Path(args.target).expanduser()
    if not target.is_absolute():
        parser.error("provide an explicit absolute target directory")
    if not target.is_dir():
        parser.error("target must be an existing directory")
    source = Path(__file__).resolve().parents[1]
    interpreter = source / ".venv/bin/python"
    if not interpreter.is_file():
        interpreter = Path(sys.executable)
    # -I excludes cwd/PYTHONPATH/user site; -B prevents even ignored .pyc writes
    # in the source. No installs, logs, reports, or Git operations run there.
    try:
        roots = source_roots(source)
        before = manifest(roots)
    except (OSError, ValueError) as exc:
        print(f"target-repo: source baseline unavailable: {exc}", file=sys.stderr)
        return 1
    result = 1
    try:
        result = subprocess.run(
            [
                str(interpreter),
                "-I",
                "-B",
                "-c",
                _BOOTSTRAP,
                str(source),
                str(target),
                args.profile,
                str(args.with_workflows).lower(),
            ],
            cwd=target.resolve(),
            check=False,
        ).returncode
    except OSError as exc:
        print(f"target-repo: integration could not start: {exc}", file=sys.stderr)
    finally:
        try:
            # Keep old metadata roots even if the source's .git pointer changed.
            after = manifest(list(dict.fromkeys([*roots, *source_roots(source)])))
            changed = [
                {"path": path, "before": before.get(path), "after": after.get(path)}
                for path in sorted(before.keys() | after.keys())
                if before.get(path) != after.get(path)
            ]
            if changed:
                print("target-repo: SOURCE DRIFT; no source files restored", file=sys.stderr)
                print(json.dumps(changed, sort_keys=True), file=sys.stderr)
                result = 1
            else:
                digest = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
                print(f"Source verified unchanged: {len(before)} entries; manifest sha256={digest}")
        except (OSError, ValueError) as exc:
            print(f"target-repo: source preservation NOT verified: {exc}", file=sys.stderr)
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
