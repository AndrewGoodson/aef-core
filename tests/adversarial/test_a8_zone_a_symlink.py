"""A8 — escape Zone A with a symlink.

Not one of the trust case's original seven. It is here because it is better
evidence than they are: it was found and REPRODUCED on this system (ADR 0147
named it untested, ADR 0149's F5 ran it), so the exploit is known-good rather
than imagined.

Two directions, and the asymmetry between them was the seam:

  * **Landing one.** A candidate that ADDS `agents/graph.py -> ../real/graph.py`
    has a Zone A path pointing outside Zone A. `candidate.check_modes` refuses
    it as a SECURITY EVENT, not an ordinary rejection.
  * **Blessing one.** `aef loop bless` accepted exactly that as the baseline.
    Git's blob for mode 120000 is the LINK TARGET STRING, so the archive held
    16 bytes reading `../real/graph.py`: the baseline contained the agent by
    name and none of it by content, and G5 then measured every candidate's
    drift against a tree that never held the code. Any edit to the real file
    was drift of zero.

Both use one `ESCAPE_MODES`, imported rather than re-listed, and this module
asserts that too — two lists of what counts as an escape drifting apart is
what let the asymmetry exist.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from aef.harness import archive
from aef.harness.candidate import ESCAPE_MODES, check_modes, inspect_candidate
from aef.harness.git import GitRepo
from aef.harness.preflight import BlessError, bless
from aef.harness.zones import ZonePolicy

AT = __import__("datetime").datetime(2026, 3, 1, 12, 0, tzinfo=__import__("datetime").UTC)
REAL = "the real agent's source, which the baseline must contain\n" * 4


def _repo_with_a_symlinked_agent(
    root: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> GitRepo:
    """`agents/graph.py` is a link to `real/graph.py`, one directory OUT of
    Zone A. Committed, so git records mode 120000 and the blob is the target
    string."""
    new_repo(root)
    (root / "real").mkdir()
    (root / "real" / "graph.py").write_text(REAL, encoding="utf-8")
    (root / "agents").mkdir()
    os.symlink("../real/graph.py", root / "agents" / "graph.py")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "a symlinked agent")
    return GitRepo(root=root)


# --------------------------------------------------------------------------
# The attack — landing a symlink
# --------------------------------------------------------------------------


def test_a8_a_candidate_that_adds_a_zone_a_symlink_is_a_security_event(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    root = tmp_path / "repo"
    new_repo(root)
    (root / "real").mkdir()
    (root / "real" / "graph.py").write_text(REAL, encoding="utf-8")
    (root / "agents").mkdir()
    (root / "agents" / "graph.py").write_text("# the honest incumbent\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")

    git(root, "checkout", "-qb", "cand")
    (root / "agents" / "graph.py").unlink()
    os.symlink("../real/graph.py", root / "agents" / "graph.py")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "escape by link")

    repo = GitRepo(root=root)
    verdict = inspect_candidate(repo, "main", "cand", ZonePolicy())
    assert not verdict.allowed
    assert verdict.security_events, "a Zone A path pointing outside Zone A was not a security event"

    violations = check_modes(verdict.diff)
    assert [v.path for v in violations] == ["agents/graph.py"]
    assert violations[0].security_event
    assert violations[0].mode in ESCAPE_MODES


# --------------------------------------------------------------------------
# The attack — blessing a symlink as the baseline
# --------------------------------------------------------------------------


def test_a8_bless_refuses_a_zone_a_tree_holding_a_symlink(
    tmp_path: Path, git: Callable[..., None], new_repo: Callable[[Path], None]
) -> None:
    repo = _repo_with_a_symlinked_agent(tmp_path / "repo", git, new_repo)
    state = tmp_path / "state"

    with pytest.raises(BlessError, match="symlink or submodule|symlink"):
        bless(
            repo_root=repo.root,
            state_root=state,
            agent_path="agents/graph.py",
            graph_id="demo_agent",
            at=AT,
            ref="main",
        )
    assert archive.versions(state / "archive", "demo_agent") == (), (
        "the refusal archived something anyway"
    )


def test_a8_one_escape_list_serves_both_directions() -> None:
    """`preflight._zone_a_escapes` imports `candidate.ESCAPE_MODES`. If it
    ever grew its own list, the two halves above could disagree about what an
    escape is — which is precisely how blessing accepted what gating refused."""
    import aef.harness.preflight as preflight

    assert preflight.ESCAPE_MODES is ESCAPE_MODES


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a8_the_control_is_load_bearing(
    tmp_path: Path,
    git: Callable[..., None],
    new_repo: Callable[[Path], None],
    monkeypatch: pytest.MonkeyPatch,
    attack_log: list[str],
) -> None:
    """Remove the escape scan from `bless` and the baseline becomes 16 bytes
    of link target — ADR 0149's reproduction, re-run here.

    The assertion is on the ARCHIVED BYTES, not on the printed line: what made
    this defect survivable for a release is that `bless` said
    `blessed agents/graph.py as baseline v1` and exited 0 while archiving the
    string `../real/graph.py`.
    """
    repo = _repo_with_a_symlinked_agent(tmp_path / "repo", git, new_repo)
    state = tmp_path / "state"

    import aef.harness.preflight as preflight

    monkeypatch.setattr(preflight, "_zone_a_escapes", lambda repo, ref, agent_root: {})

    entry = bless(
        repo_root=repo.root,
        state_root=state,
        agent_path="agents/graph.py",
        graph_id="demo_agent",
        at=AT,
        ref="main",
    )
    archived = archive.read_files(state / "archive", "demo_agent", entry.version)
    blob = archived["agents/graph.py"]
    attack_log.append(f"archived {len(blob)} bytes: {blob!r}")

    assert blob == b"../real/graph.py", attack_log
    assert len(blob) < len(REAL.encode()), (
        "the baseline holds the real source, so the symlink was resolved somewhere and this "
        "attack is no longer the one ADR 0149 reproduced"
    )
