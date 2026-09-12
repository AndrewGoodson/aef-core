"""Adoption labels and writes must stay within the repository's own files."""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

from aef.cli.adopt import detect_framework, run_adopt


def test_offline_readoption_keeps_detection_and_owner_bytes_stable(tmp_path: Path) -> None:
    first = run_adopt(tmp_path, profile="offline")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    second = run_adopt(tmp_path, profile="offline")
    assert first.detection() == second.detection() == "none"
    assert before == {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }


def test_offline_readoption_still_counts_existing_owner_instructions(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"# Owner rules\r\nKeep my workflow.\r\n")
    first = run_adopt(tmp_path, profile="offline")
    second = run_adopt(tmp_path, profile="offline")
    assert first.detection() == second.detection() == "prompt_files (AGENTS.md)"
    assert (tmp_path / "AGENTS.md").read_bytes().startswith(b"# Owner rules\r\n")


def test_adopt_refuses_hardlinked_instruction_file(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "owner.md"
    owner = b"# Original owner instructions\r\n"
    outside.write_bytes(owner)
    os.link(outside, target / "AGENTS.md")
    result = run_adopt(target, profile="offline")
    assert outside.read_bytes() == owner
    assert (target / "AGENTS.md").read_bytes() == owner
    assert "hardlink" in result.skip_reason(target / "AGENTS.md")


def test_framework_scan_does_not_follow_external_file_links(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "external.py"
    outside.write_text("import langgraph\n")
    (target / "agent.py").symlink_to(outside)
    (target / "requirements.txt").symlink_to(outside)
    assert detect_framework(target) == "none"


def test_framework_scan_prunes_dependency_trees_before_visiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency = tmp_path / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "agent.py").write_text("import langgraph\n")
    source = tmp_path / "packages" / "agent"
    source.mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\ndependencies = ["crewai"]\n')
    real_scandir = os.scandir
    visited: list[Path] = []

    def observe(path: str | os.PathLike[str]) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        visited.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", observe)
    # Python 3.13's glob captures scandir in a staticmethod at import time.
    if hasattr(glob, "_StringGlobber"):
        monkeypatch.setattr(glob._StringGlobber, "scandir", staticmethod(observe))
    assert detect_framework(tmp_path) == "crewai"
    assert tmp_path in visited
    assert not any(path.is_relative_to(tmp_path / "node_modules") for path in visited)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs require POSIX")
def test_adoption_skips_special_files_without_waiting_for_a_writer(tmp_path: Path) -> None:
    for name in ("AGENTS.md", ".gitignore", "agent.py", "requirements.txt"):
        os.mkfifo(tmp_path / name)
    probe = """import sys
from pathlib import Path
from aef.cli.adopt import run_adopt
target = Path(sys.argv[1])
result = run_adopt(target, profile="offline")
assert result.detection() == "none"
for name in ("AGENTS.md", ".gitignore"):
    assert result.skip_reason(target / name) == "exists but is not a regular file"
"""
    # A regression must fail within seconds instead of hanging the CI worker.
    outcome = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr


def test_framework_file_budget_samples_deterministically(tmp_path: Path) -> None:
    # Creation order must not decide which source the bounded scan sees.
    (tmp_path / "z.py").write_text("import langgraph\n")
    (tmp_path / "a.py").write_text("import crewai\n")
    assert detect_framework(tmp_path, max_files=1) == "crewai"
    assert detect_framework(tmp_path, max_files=2) == "langgraph"
