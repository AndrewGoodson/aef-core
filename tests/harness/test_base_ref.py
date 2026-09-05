"""The default base ref is derived from the repository, not spelled `main`.

ADR 0189, closing ADR 0187's F-M8-1. The failure it fixes is ADR 0139's
signature shape reached from the documented defaults: on a repo whose default
branch is `azure-agent/uptime-monitoring` — a real one, with no `main` in it at
all — `aef loop cycle` printed `no agent source at .claude/agents/dev-agent.md
in main: no candidate` and exited **0**, blaming a persona that was present,
in the same sentence and with the same exit code a legitimate empty proposal
prints.

`aef/harness/zones.py` names this shape for the agent PATH and ADR 0149 closed
it there. The base REF was the same shape and was left behind.

Every case below builds a real repository and asks the real function; nothing
here is mocked, because the whole defect was in what git actually answers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aef.harness.git import GitRepo
from aef.harness.loop import (
    FALLBACK_BASE_REF,
    BaseRefError,
    require_base_ref,
    resolve_default_base_ref,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _repo(root: Path, *, branch: str) -> GitRepo:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", branch)
    (root / "README.md").write_text("# x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    return GitRepo(root=root)


# --------------------------------------------------------------------------
# The derivation, in order
# --------------------------------------------------------------------------
def test_a_repo_with_no_remote_resolves_to_the_branch_head_is_on(tmp_path: Path) -> None:
    """Step 2. `git init -b trunk` is the whole of F-M8-1's isolated
    reproduction: no remote exists, so nothing can be asked of `origin/HEAD`,
    and the branch the operator is on is the only statement the repository
    makes about which line of development is current."""
    repo = _repo(tmp_path / "trunk", branch="trunk")
    assert resolve_default_base_ref(repo) == "trunk"
    assert not repo.ref_exists("main"), "the fixture is wrong if `main` exists"


def test_the_ordinary_repo_still_resolves_to_main(tmp_path: Path) -> None:
    """Nothing that works today changes: a `main` checkout resolves to `main`
    at step 2, exactly as the literal default used to."""
    repo = _repo(tmp_path / "ordinary", branch="main")
    assert resolve_default_base_ref(repo) == "main"


def test_origin_head_wins_over_the_branch_checked_out(tmp_path: Path) -> None:
    """Step 1 beats step 2, and that is the point of the order: `origin/HEAD`
    is the repository's own published answer and does not move when the
    operator checks something else out, so a nightly cycle and an interactive
    one resolve the same base."""
    upstream = _repo(tmp_path / "upstream", branch="release")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(upstream.root), str(clone)], check=True, capture_output=True
    )
    repo = GitRepo(root=clone)
    _git(clone, "checkout", "-q", "-b", "feature-of-the-day")

    assert repo.symbolic_ref("refs/remotes/origin/HEAD") == "origin/release"
    assert resolve_default_base_ref(repo) == "release"


def test_a_loop_branch_is_never_inherited_as_the_base(tmp_path: Path) -> None:
    """The exclusion that keeps step 2 from being circular. A cycle run while
    an un-gated candidate is checked out must not base the next candidate on
    it: the diff, the G0 budget and G5's drift would all be measured against
    a baseline nothing blessed."""
    repo = _repo(tmp_path / "onloop", branch="trunk")
    _git(repo.root, "checkout", "-q", "-b", "loop/cycle-20260905T000000")

    assert repo.symbolic_ref("HEAD") == "loop/cycle-20260905T000000"
    assert resolve_default_base_ref(repo) == FALLBACK_BASE_REF


def test_a_detached_head_with_no_remote_falls_back(tmp_path: Path) -> None:
    """Step 3. The repository has no answer, so the one constant is used —
    and `require_base_ref` is then what refuses, by name."""
    repo = _repo(tmp_path / "detached", branch="trunk")
    _git(repo.root, "checkout", "-q", "--detach")

    assert repo.symbolic_ref("HEAD") is None
    assert resolve_default_base_ref(repo) == FALLBACK_BASE_REF


# --------------------------------------------------------------------------
# The refusal
# --------------------------------------------------------------------------
def test_a_missing_ref_is_refused_by_name_and_lists_what_exists(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "trunk", branch="trunk")
    with pytest.raises(BaseRefError) as exc:
        require_base_ref(repo, "main")

    message = str(exc.value)
    assert "'main' does not exist" in message
    assert "trunk" in message, "a refusal naming only what is absent is not actionable"
    assert str(repo.root.resolve()) in message


def test_a_ref_that_exists_is_not_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "trunk", branch="trunk")
    require_base_ref(repo, "trunk")  # must not raise


def test_a_plain_directory_is_not_a_base_ref_mistake(tmp_path: Path) -> None:
    """A directory that is not a repository has no refs to be right or wrong
    about. `aef loop doctor` is a diagnostic and must still run and say what
    IS missing rather than refuse to look, and every command that genuinely
    needs a repository fails on its own first call out to git."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    repo = GitRepo(root=plain)

    assert not repo.is_repo()
    require_base_ref(repo, "main")  # must not raise


def test_the_two_questions_path_exists_at_could_not_tell_apart(tmp_path: Path) -> None:
    """The primitive at the bottom of F-M8-1. `git cat-file -e <ref>:<path>`
    fails identically for a missing file and a missing ref, so one bool
    carried two answers and the message picked the wrong one."""
    repo = _repo(tmp_path / "trunk", branch="trunk")

    # Missing FILE at a ref that exists.
    assert repo.ref_exists("trunk")
    assert not repo.path_exists_at("trunk", "nope.md")
    # Missing REF. `path_exists_at` says exactly the same thing; `ref_exists`
    # is what tells them apart.
    assert not repo.ref_exists("main")
    assert not repo.path_exists_at("main", "README.md")
    assert repo.path_exists_at("trunk", "README.md")
