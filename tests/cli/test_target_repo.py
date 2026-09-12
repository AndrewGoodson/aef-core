"""Target integration must write only in an explicitly selected, separate tree."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    """Include ignored files and new directories; never follow fixture symlinks."""
    result = {}
    for path in sorted(root.rglob("*")):
        stat = path.lstat()
        content = (
            os.readlink(path).encode()
            if path.is_symlink()
            else path.read_bytes()
            if path.is_file()
            else b""
        )
        result[path.relative_to(root).as_posix()] = (
            stat.st_mode,
            stat.st_mtime_ns,
            hashlib.sha256(content).hexdigest(),
        )
    return result


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    shutil.copytree(REPO / "aef", root / "aef", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "scripts").mkdir()
    shutil.copyfile(REPO / "scripts/target_repo.py", root / "scripts/target_repo.py")
    (root / "dirty.txt").write_text("Existing unfinished source work\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def launch(source: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", str(source / "scripts/target_repo.py"), *args],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_real_launcher_integrates_three_harnesses_without_source_writes(
    source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "target with spaces ' and $(literal)"
    target.mkdir()
    owner = b"# Owner rules\r\nPreserve this exact text.\r\n"
    (target / "AGENTS.md").write_bytes(owner)
    for harness in ("claude", "grok"):
        path = target / f".{harness}/agents/reviewer.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: reviewer\ndescription: Review evidence\n---\nUse evidence.\n")
    path = target / ".codex/agents/reviewer.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        'name = "reviewer"\ndescription = "Review evidence"\n'
        'developer_instructions = "Use evidence."\n'
    )
    # Importing target code would execute this: discovery must remain static.
    (target / "aef.py").write_text('raise RuntimeError("TARGET CODE EXECUTED")\n')
    before = snapshot(source)
    first = launch(source, str(target))
    assert first.returncode == 0, first.stderr
    assert "Source verified unchanged:" in first.stdout
    assert "model_provider: null" in (target / "aef.yaml").read_text()
    assert not (target / ".github/workflows").exists()
    assert snapshot(source) == before
    assert (target / "AGENTS.md").read_bytes().startswith(owner)
    assert (target / "AGENT_INTEGRATION.md").is_file()
    assert (target / "AUTONOMY.md").is_file()
    graphs = list((target / "agents/migrated").rglob("*.py"))
    assert len(graphs) == 4  # Three personas plus the call-site graph.
    for graph in graphs:
        compile(graph.read_text(), str(graph), "exec")
    assert "mechanical" in first.stdout.lower()
    assert "not verified" in first.stdout.lower()
    target_before = snapshot(target)
    second = launch(source, str(target))
    assert second.returncode == 0, second.stderr
    assert snapshot(target) == target_before
    assert snapshot(source) == before


@pytest.mark.parametrize("kind", ["missing", "relative", "same", "child", "parent", "alias"])
def test_launcher_rejects_missing_or_overlapping_target(
    source: Path, tmp_path: Path, kind: str
) -> None:
    child = source / "child"
    child.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    choices = {
        "missing": [],
        "relative": ["."],
        "same": [str(source)],
        "child": [str(child)],
        "parent": [str(tmp_path)],
        "alias": [str(alias)],
    }
    before = snapshot(source)
    result = launch(source, *choices[kind])
    assert result.returncode != 0
    assert snapshot(source) == before


@pytest.mark.parametrize(
    "relative_path",
    [
        "CLAUDE.md",
        "AGENTS.md",
        "GROK.md",
        ".github/copilot-instructions.md",
        ".cursor/rules/aef.mdc",
        ".gitignore",
    ],
)
def test_launcher_preserves_hardlinked_owner_instructions(
    source: Path, tmp_path: Path, relative_path: str
) -> None:
    """A skipped owner file is safe even when its inode belongs to the source."""
    target = tmp_path / "target"
    linked = target / relative_path
    linked.parent.mkdir(parents=True)
    original = source / "dirty.txt"
    os.link(original, linked)
    before = snapshot(source)
    first = launch(source, str(target))
    assert first.returncode == 0, first.stderr
    assert f"preserved: {relative_path} (hardlink" in first.stdout
    assert "Source verified unchanged:" in first.stdout
    assert linked.samefile(original)
    assert snapshot(source) == before
    assert (target / "agents/migrated/graph.py").is_file()

    target_before = snapshot(target)
    second = launch(source, str(target))
    assert second.returncode == 0, second.stderr
    assert linked.samefile(original)
    assert snapshot(target) == target_before
    assert snapshot(source) == before


@pytest.mark.parametrize("kind", ["hardlink_graph", "symlink_parent", "dangling_graph"])
def test_escape_paths_cannot_modify_source(source: Path, tmp_path: Path, kind: str) -> None:
    target = tmp_path / "target"
    target.mkdir()
    if kind == "hardlink_graph":
        (target / "agents/migrated").mkdir(parents=True)
        os.link(source / "dirty.txt", target / "agents/migrated/graph.py")
    elif kind == "symlink_parent":
        (target / "agents").symlink_to(source, target_is_directory=True)
    else:
        (target / "agents/migrated").mkdir(parents=True)
        (target / "agents/migrated/graph.py").symlink_to(source / "escaped.py")
    before = snapshot(source)
    target_before = snapshot(target)
    result = launch(source, str(target))
    assert result.returncode != 0
    assert "refus" in result.stderr.lower()
    assert snapshot(source) == before
    assert snapshot(target) == target_before


def test_linked_worktree_is_refused_without_git_changes(source: Path, tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(source), "add", "dirty.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    target = tmp_path / "linked-worktree"
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "core.hooksPath=/dev/null",
            "worktree",
            "add",
            "--detach",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    before = snapshot(source)
    target_before = snapshot(target)
    result = launch(source, str(target))
    assert result.returncode != 0
    assert "shares Git metadata" in result.stderr
    assert snapshot(source) == before
    assert snapshot(target) == target_before


def test_existing_hand_edited_graph_and_config_survive(source: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    (target / "agents/migrated").mkdir(parents=True)
    graph = target / "agents/migrated/graph.py"
    graph.write_bytes(b"# hand-edited graph\r\nOWNER_VALUE = 42\r\n")
    config = target / "aef.yaml"
    config.write_bytes(b"# owner configuration\r\n")
    graph_before = graph.read_bytes()
    config_before = config.read_bytes()
    before = snapshot(source)
    result = launch(source, str(target))
    assert result.returncode == 0, result.stderr
    assert graph.read_bytes() == graph_before
    assert config.read_bytes() == config_before
    assert snapshot(source) == before


def test_skills_agree_on_target_only_contract() -> None:
    paths = [
        REPO / f"{folder}/skills/target-repo/SKILL.md" for folder in (".claude", ".agents", ".grok")
    ]
    texts = [path.read_text() for path in paths]
    assert len(set(texts)) == 1
    assert "name: target-repo" in texts[0]
    assert "scripts/target_repo.py" in texts[0]
    assert "read-only" in texts[0]
    assert "semantic" in texts[0]


@pytest.mark.parametrize("kind", ["content", "mode", "mtime", "added", "deleted", "git", "ignored"])
@pytest.mark.parametrize("child_status", [0, 7])
def test_launcher_detects_source_drift_even_when_child_fails(
    source: Path, tmp_path: Path, kind: str, child_status: int
) -> None:
    """A hostile child modifies ONLY a disposable source copy, never the real repo."""
    target = tmp_path / "target"
    target.mkdir()
    victim = source / (
        ".git/HEAD" if kind == "git" else ".ignored" if kind == "ignored" else "dirty.txt"
    )
    if kind == "ignored":
        victim.write_text("ignored baseline\n")
        (source / ".gitignore").write_text(".ignored\n")
    actions = {
        "content": "victim.write_text('CHANGED')",
        "mode": "victim.chmod(0o700)",
        "mtime": "os.utime(victim, ns=(victim.stat().st_atime_ns, "
        "victim.stat().st_mtime_ns + 12345))",
        "added": "(root / 'new.txt').write_text('ADDED')",
        "deleted": "victim.unlink()",
        "git": "victim.write_text('CHANGED')",
        "ignored": "victim.write_text('CHANGED')",
    }
    # Replace the copied child entrypoint, leaving the actual launcher under test.
    (source / "aef/cli/target_repo.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def main(*args, **kwargs):\n"
        f"    root = Path({str(source)!r})\n"
        f"    victim = Path({str(victim)!r})\n"
        f"    {actions[kind]}\n"
        f"    return {child_status}\n"
    )
    result = launch(source, str(target))
    assert result.returncode != 0
    assert "SOURCE DRIFT" in result.stderr
    assert '"before":' in result.stderr and '"after":' in result.stderr
    assert "Source verified unchanged" not in result.stdout
    if kind in ("content", "git", "ignored"):
        assert victim.read_text() == "CHANGED"  # Never hide drift by restoring files.
    if kind == "deleted":
        assert not victim.exists()


def test_source_manifest_covers_external_git_metadata_but_not_arbitrary_link_targets(
    source: Path, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    external_git = tmp_path / "external-git"
    shutil.move(source / ".git", external_git)
    (source / ".git").write_text(f"gitdir: {external_git}\n")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("owner data")
    (source / "link").symlink_to(unrelated)
    (source / "aef/cli/target_repo.py").write_text(
        "from pathlib import Path\n"
        "def main(*args, **kwargs):\n"
        f"    Path({str(external_git / 'HEAD')!r}).write_text('CHANGED')\n"
        f"    Path({str(unrelated)!r}).write_text('unrelated change')\n"
        "    return 0\n"
    )
    result = launch(source, str(target))
    assert result.returncode != 0
    assert str(external_git / "HEAD") in result.stderr
    assert str(unrelated) not in result.stderr


def test_unverifiable_source_refuses_to_start_integration(source: Path, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    os.mkfifo(source / "unverifiable")
    result = launch(source, str(target))
    assert result.returncode != 0
    assert "source baseline unavailable" in result.stderr
    assert list(target.iterdir()) == []
