"""The trust boundary — gates execute from the base ref, never the branch.

This file contains M1's acceptance test. The scenario is the whole point of
the design: a candidate branch rewrites the gate that judges it, and the
rewritten gate never runs. It is built with a real git repo and a real
Python execution of the loaded gate, not asserted from source.
"""

import subprocess
from pathlib import Path

import pytest

from aef.harness.git import GitRepo
from aef.harness.trust import BaseRefHarness, TrustBoundaryError

REJECTING_GATE = "def gate(candidate):\n    return False\n"
SUBVERTED_GATE = "def gate(candidate):\n    return True\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "base")
    _git(root, "config", "user.email", "harness@test")
    _git(root, "config", "user.name", "harness")

    (root / "aef" / "harness").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "corpus").mkdir()
    (root / "aef" / "harness" / "gate.py").write_text(REJECTING_GATE)
    (root / "corpus" / "s1.json").write_text('{"scenario": 1}\n')
    (root / "agents" / "planner.py").write_text("VALUE = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


# --------------------------------------------------------------------------
# M1 ACCEPTANCE TEST
# --------------------------------------------------------------------------


def test_a_candidate_that_rewrites_its_gate_still_faces_the_original_gate(
    repo: GitRepo, tmp_path: Path
) -> None:
    """THE property. A branch subverts the gate; the base ref's gate runs."""
    _git(repo.root, "checkout", "-qb", "cand")
    (repo.root / "aef" / "harness" / "gate.py").write_text(SUBVERTED_GATE)
    (repo.root / "agents" / "planner.py").write_text("VALUE = 2\n")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "improve the gate :)")

    # The branch's working tree really does contain the subverted gate...
    assert (repo.root / "aef" / "harness" / "gate.py").read_text() == SUBVERTED_GATE

    # ...and the harness loads the base ref's gate regardless.
    harness = BaseRefHarness(repo=repo, base_ref="base")
    source = harness.read("aef/harness/gate.py")
    assert source == REJECTING_GATE

    # Execute it for real — the property is about behaviour, not text.
    namespace: dict[str, object] = {}
    exec(compile(source, "gate.py", "exec"), namespace)  # noqa: S102 - loading the base-ref gate is the test
    gate = namespace["gate"]
    assert callable(gate)
    assert gate({"paths": ["agents/planner.py"]}) is False


def test_materialized_harness_is_the_base_version_not_the_branch(
    repo: GitRepo, tmp_path: Path
) -> None:
    _git(repo.root, "checkout", "-qb", "cand")
    (repo.root / "aef" / "harness" / "gate.py").write_text(SUBVERTED_GATE)
    (repo.root / "corpus" / "s1.json").write_text('{"scenario": "trivially passing"}\n')
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "subvert gate and corpus")

    dest = BaseRefHarness(repo=repo, base_ref="base").materialize(tmp_path / "harness")

    assert (dest / "aef" / "harness" / "gate.py").read_text() == REJECTING_GATE
    assert (dest / "corpus" / "s1.json").read_text() == '{"scenario": 1}\n'


def test_materialize_writes_only_zone_b(repo: GitRepo, tmp_path: Path) -> None:
    # Candidate code must never be present in the directory gates run from —
    # otherwise an import could reach it.
    dest = BaseRefHarness(repo=repo, base_ref="base").materialize(tmp_path / "harness")
    written = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
    assert written == {"aef/harness/gate.py", "corpus/s1.json"}
    assert not (dest / "agents").exists()


def test_harness_paths_lists_only_zone_b(repo: GitRepo) -> None:
    paths = BaseRefHarness(repo=repo, base_ref="base").harness_paths()
    assert paths == ("aef/harness/gate.py", "corpus/s1.json")


# --------------------------------------------------------------------------
# The API refuses to be used as a candidate loader
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["agents/planner.py", "aef/kernel/executor.py", "pyproject.toml"])
def test_reading_a_non_harness_path_through_the_boundary_is_refused(
    repo: GitRepo, path: str
) -> None:
    # If this API would load Zone A, "gates run from the base ref" degrades
    # into "gates run from wherever the caller asked", which is no boundary.
    with pytest.raises(TrustBoundaryError, match="Zone"):
        BaseRefHarness(repo=repo, base_ref="base").read(path)


def test_a_traversal_path_is_refused(repo: GitRepo) -> None:
    with pytest.raises(TrustBoundaryError):
        BaseRefHarness(repo=repo, base_ref="base").read("aef/harness/../../etc/passwd")


# --------------------------------------------------------------------------
# Pinning and ancestry
# --------------------------------------------------------------------------


def test_the_base_sha_is_pinned_to_a_commit(repo: GitRepo) -> None:
    sha = BaseRefHarness(repo=repo, base_ref="base").base_sha
    assert len(sha) == 40


def test_a_branch_with_no_shared_history_is_not_a_candidate(repo: GitRepo) -> None:
    # An orphan branch has no merge-base, so `base...orphan` would report the
    # entire tree. Refuse rather than produce a meaningless diff.
    _git(repo.root, "checkout", "-q", "--orphan", "orphan")
    _git(repo.root, "rm", "-rqf", ".")
    (repo.root / "unrelated.py").write_text("x = 1\n")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "orphan root")

    with pytest.raises(TrustBoundaryError, match="no history|not a candidate"):
        BaseRefHarness(repo=repo, base_ref="base").verify_base_is_ancestor("orphan")


def test_a_normal_candidate_passes_the_ancestry_check(repo: GitRepo) -> None:
    _git(repo.root, "checkout", "-qb", "cand")
    (repo.root / "agents" / "planner.py").write_text("VALUE = 2\n")
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", "work")

    BaseRefHarness(repo=repo, base_ref="base").verify_base_is_ancestor("cand")
