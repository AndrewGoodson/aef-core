"""Candidate-diff extraction, against **real** git repositories.

Every repo here is a genuine `git init` with genuine commits. The three
escapes this module exists to close (rename, symlink, submodule) are not
reasoned about from git's documentation — they are built and run.
"""

import subprocess
from pathlib import Path

import pytest

from aef.harness.candidate import (
    MODE_REGULAR,
    check_modes,
    inspect_candidate,
    read_candidate,
)
from aef.harness.git import GitError, GitRepo
from aef.harness.zones import Zone


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    """A repo with a Zone A file, a Zone C file, and a Zone B file on `base`."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "base")
    _git(root, "config", "user.email", "harness@test")
    _git(root, "config", "user.name", "harness")

    (root / "agents").mkdir()
    (root / "aef" / "kernel").mkdir(parents=True)
    (root / "aef" / "harness").mkdir(parents=True)
    (root / "agents" / "planner.py").write_text("ORIGINAL = 1\n")
    (root / "aef" / "kernel" / "executor.py").write_text("CORE = 1\n")
    (root / "aef" / "harness" / "gate.py").write_text("def gate():\n    return False\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def _branch(repo: GitRepo, name: str) -> None:
    _git(repo.root, "checkout", "-qb", name)


def _commit(repo: GitRepo, message: str) -> None:
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", message)


# --------------------------------------------------------------------------
# Reading the candidate
# --------------------------------------------------------------------------


def test_a_zone_a_edit_is_read_and_allowed(repo: GitRepo) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").write_text("ORIGINAL = 2\n")
    _commit(repo, "tweak")

    verdict = inspect_candidate(repo, "base", "cand")
    assert verdict.allowed
    assert verdict.diff.paths == ("agents/planner.py",)
    assert verdict.diff.entries[0].dst_mode == MODE_REGULAR


def test_an_empty_candidate_is_read_as_empty(repo: GitRepo) -> None:
    _branch(repo, "cand")
    verdict = inspect_candidate(repo, "base", "cand")
    assert verdict.diff.is_empty
    assert verdict.allowed  # a no-op is not a zone violation


def test_the_diff_is_since_the_merge_base_not_since_the_branch_point_moved(
    repo: GitRepo,
) -> None:
    # `base...head` must report only what the candidate proposes, never work
    # that landed on base afterwards — otherwise every candidate inherits
    # unrelated violations and the gate becomes noise.
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").write_text("CANDIDATE = 1\n")
    _commit(repo, "candidate work")

    _git(repo.root, "checkout", "-q", "base")
    (repo.root / "aef" / "kernel" / "executor.py").write_text("CORE = 99\n")
    _commit(repo, "unrelated core work on base")

    verdict = inspect_candidate(repo, "base", "cand")
    assert verdict.diff.paths == ("agents/planner.py",)
    assert verdict.allowed


def test_line_counts_are_recorded_for_the_size_budget(repo: GitRepo) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").write_text("a\nb\nc\nd\n")
    _commit(repo, "grow")

    diff = read_candidate(repo, "base", "cand")
    assert diff.changed_files == 1
    assert diff.changed_lines == 5  # 4 added, 1 removed


def test_shas_are_resolved_for_the_record(repo: GitRepo) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").write_text("x\n")
    _commit(repo, "c")

    diff = read_candidate(repo, "base", "cand")
    assert len(diff.base_sha) == 40
    assert diff.base_sha != diff.head_sha


def test_a_moving_head_ref_cannot_mix_two_candidate_snapshots(
    repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").write_text("SMALL = 1\n")
    _commit(repo, "small candidate")
    small_sha = repo.rev_parse("cand")

    (repo.root / "agents" / "planner.py").write_text(
        "".join(f"HUGE_{index} = {index}\n" for index in range(600))
    )
    _commit(repo, "large candidate")
    large_sha = repo.rev_parse("cand")
    _git(repo.root, "update-ref", "refs/heads/cand", small_sha)

    original_numstat = GitRepo.numstat_diff

    def advance_head_after_counting(self: GitRepo, base_ref: str, head_ref: str) -> bytes:
        result = original_numstat(self, base_ref, head_ref)
        _git(self.root, "update-ref", "refs/heads/cand", large_sha)
        return result

    monkeypatch.setattr(GitRepo, "numstat_diff", advance_head_after_counting)

    diff = read_candidate(repo, "base", "cand")

    assert diff.head_sha == small_sha
    assert diff.changed_lines == 2
    assert repo.show(diff.head_sha, "agents/planner.py") == "SMALL = 1\n"


def test_an_unknown_ref_fails_loudly(repo: GitRepo) -> None:
    with pytest.raises(GitError):
        read_candidate(repo, "base", "no-such-branch")


# --------------------------------------------------------------------------
# Escape 1 — rename. THE test for --no-renames.
# --------------------------------------------------------------------------


def test_moving_a_core_file_into_zone_a_is_rejected(repo: GitRepo) -> None:
    # With git's rename detection ON, this diff reports ONLY
    # `agents/executor.py` — a single Zone A path — while deleting a kernel
    # file. Verified against real git before writing this. `--no-renames`
    # reports the deletion too, which is what makes the zone check sound.
    _branch(repo, "cand")
    _git(repo.root, "mv", "aef/kernel/executor.py", "agents/executor.py")
    _commit(repo, "relocate core into my own zone")

    verdict = inspect_candidate(repo, "base", "cand")
    assert not verdict.allowed
    assert "aef/kernel/executor.py" in verdict.diff.paths
    assert [v.path for v in verdict.zones.rejected] == ["aef/kernel/executor.py"]


def test_the_deleted_half_of_a_move_is_classified_zone_c(repo: GitRepo) -> None:
    _branch(repo, "cand")
    _git(repo.root, "mv", "aef/kernel/executor.py", "agents/executor.py")
    _commit(repo, "relocate")

    diff = read_candidate(repo, "base", "cand")
    deleted = next(e for e in diff.entries if e.path == "aef/kernel/executor.py")
    assert deleted.is_deletion
    assert deleted.status == "D"


def test_moving_a_harness_file_into_zone_a_is_a_security_event(repo: GitRepo) -> None:
    # Relocating the gate is the sharpest form of "modify what judges me".
    _branch(repo, "cand")
    _git(repo.root, "mv", "aef/harness/gate.py", "agents/gate.py")
    _commit(repo, "relocate the judge")

    verdict = inspect_candidate(repo, "base", "cand")
    assert not verdict.allowed
    assert "aef/harness/gate.py" in verdict.security_events


# --------------------------------------------------------------------------
# Escape 2 — symlink out of Zone A
# --------------------------------------------------------------------------


def test_a_symlink_out_of_zone_a_is_a_security_event(repo: GitRepo) -> None:
    # `agents/link.py` passes every path test in zones.py. The mode does not.
    _branch(repo, "cand")
    (repo.root / "agents" / "link.py").symlink_to("../aef/kernel/executor.py")
    _commit(repo, "link out")

    verdict = inspect_candidate(repo, "base", "cand")
    assert not verdict.allowed
    assert verdict.zones.allowed  # the PATH was fine — this is why modes matter
    assert "agents/link.py" in verdict.security_events


def test_even_a_symlink_within_zone_a_is_rejected(repo: GitRepo) -> None:
    # Deny-by-default: resolving link targets is a game the harness declines
    # to play, so no symlink lands at all.
    _branch(repo, "cand")
    (repo.root / "agents" / "link.py").symlink_to("planner.py")
    _commit(repo, "inner link")

    assert not inspect_candidate(repo, "base", "cand").allowed


# --------------------------------------------------------------------------
# Escape 3 — modes generally
# --------------------------------------------------------------------------


def test_setting_the_executable_bit_is_rejected_but_is_not_a_security_event(
    repo: GitRepo,
) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").chmod(0o755)
    _commit(repo, "chmod")

    verdict = inspect_candidate(repo, "base", "cand")
    assert not verdict.allowed
    assert verdict.security_events == ()


def test_a_submodule_entry_is_a_security_event() -> None:
    # Built directly rather than via `git submodule add`, which needs a
    # network-reachable remote; the gitlink mode is what matters.
    from aef.harness.candidate import CandidateDiff, DiffEntry

    diff = CandidateDiff(
        base_ref="base",
        head_ref="cand",
        base_sha="0" * 40,
        head_sha="1" * 40,
        entries=(
            DiffEntry(path="agents/vendored", status="A", src_mode="000000", dst_mode="160000"),
        ),
    )
    violations = check_modes(diff)
    assert len(violations) == 1
    assert violations[0].security_event


def test_deleting_a_zone_a_file_is_allowed(repo: GitRepo) -> None:
    # A deletion's destination mode is 000000; that must not be mistaken for
    # an unrecognised mode and rejected.
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").unlink()
    _commit(repo, "remove")

    verdict = inspect_candidate(repo, "base", "cand")
    assert verdict.allowed


def test_every_rejection_names_the_path_and_the_reason(repo: GitRepo) -> None:
    _branch(repo, "cand")
    (repo.root / "aef" / "kernel" / "executor.py").write_text("CORE = 2\n")
    (repo.root / "agents" / "link.py").symlink_to("planner.py")
    _commit(repo, "two problems")

    verdict = inspect_candidate(repo, "base", "cand")
    joined = " ".join(verdict.reasons)
    assert "aef/kernel/executor.py" in joined
    assert "agents/link.py" in joined


def test_zone_classification_survives_a_filename_with_a_space(repo: GitRepo) -> None:
    # Without `-z`, git quotes such paths and naive parsing mis-slices them.
    _branch(repo, "cand")
    (repo.root / "agents" / "my module.py").write_text("x = 1\n")
    _commit(repo, "spacey")

    verdict = inspect_candidate(repo, "base", "cand")
    assert verdict.diff.paths == ("agents/my module.py",)
    assert verdict.allowed


def test_zone_classification_survives_a_filename_with_a_newline(repo: GitRepo) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "we\nird.py").write_text("x = 1\n")
    _commit(repo, "newline")

    verdict = inspect_candidate(repo, "base", "cand")
    assert len(verdict.diff.paths) == 1
    assert verdict.diff.paths[0].startswith("agents/")
    assert verdict.allowed


def test_a_zone_c_path_reported_alongside_zone_a_still_rejects(repo: GitRepo) -> None:
    _branch(repo, "cand")
    (repo.root / "agents" / "planner.py").write_text("ok\n")
    (repo.root / "pyproject.toml").write_text("[project]\n")
    _commit(repo, "mixed")

    verdict = inspect_candidate(repo, "base", "cand")
    assert not verdict.allowed
    assert any(v.zone is Zone.C for v in verdict.zones.rejected)
