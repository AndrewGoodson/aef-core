"""The lineage fold, and the closing record that erased what it folded onto.

ADR 0198's defect, found by RUNNING the J2b greedy arm rather than by reading
the code. `run_loop` writes each member twice: once when the gates judge it,
and once at the end of the run that proposed from it, carrying the `children`
count the novelty term needs. The fold in `_resume_lineage` took the LAST
record for a ref, wholesale — and the closing record for a **resumed root** is
built from `ArchiveMember(ref=kept_ref, score=None, parent_ref=None, ...)`, so
it carried no parent and no verdict and overwrote both with nulls.

One invocation later, the candidate that had been KEPT read back as a
parentless, verdictless root. On the live arm: turn 1 kept `a4d0bfe4` from
`c01e9b06` at score 0.818, and after the resumed invocation the same ref said
`parent_ref None, disposition None` — so any count of kept-members-with-a-
parent, the stepping-stone statistic included, was 0 for a run that had kept
one.

`archive.fold_lineage` is now THE fold, shared by the driver and by `aef loop
lineage list`: first record per ref, largest children count. Everything about
a member except that count is a fact about the moment it was gated.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aef.harness import archive
from aef.harness.git import GitRepo
from aef.harness.loop import (
    EXIT_OK,
    EXIT_REJECTED,
    CycleRun,
    LoopConfig,
    LoopPaths,
    _materialise_candidate_branch,
    read_lineage_entries,
    run_loop,
)
from aef.harness.review import Decision, Disposition

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
AGENT = "agents/demo/graph.py"


def _record(ref: str, **kw: Any) -> archive.LineageRecord:
    payload: dict[str, Any] = {
        "run_id": "r1",
        "turn": 1,
        "ref": ref,
        "tree": f"tree-{ref}",
        "parent_ref": None,
        "score": None,
        "kept": True,
        "disposition": None,
        "recorded_at": NOW,
        "children": 0,
    }
    payload.update(kw)
    return archive.LineageRecord(**payload)


# ---------------------------------------------------------------------------
# The fold itself
# ---------------------------------------------------------------------------
def test_a_closing_record_does_not_erase_the_members_parent_or_verdict() -> None:
    """THE defect. The second record for a ref carries only the children
    count; taking it wholesale threw away the parent and the gate verdict."""
    gated = _record("cand", parent_ref="root", score=0.8, kept=True, disposition="escalate")
    closing = _record("cand", turn=0, children=7)  # what a resumed root writes
    folded = archive.fold_lineage((gated, closing))
    assert folded["cand"].parent_ref == "root"
    assert folded["cand"].disposition == "escalate"
    assert folded["cand"].score == 0.8
    # ...and the one thing the closing record exists to update is updated.
    assert folded["cand"].children == 7


def test_the_fold_keeps_the_largest_children_count_whatever_the_order() -> None:
    """The count is monotonic — a member never un-spawns a child — so a
    closing record from an earlier invocation appearing after a later one
    must not walk it backwards."""
    folded = archive.fold_lineage(
        (_record("a", children=0), _record("a", children=5), _record("a", children=2))
    )
    assert folded["a"].children == 5


def test_the_fold_keeps_one_entry_per_ref_in_first_appearance_order() -> None:
    folded = archive.fold_lineage(
        (_record("root"), _record("a", parent_ref="root"), _record("root", children=3))
    )
    assert list(folded) == ["root", "a"]


# ---------------------------------------------------------------------------
# The same thing through the driver, which is where it was found
# ---------------------------------------------------------------------------
def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 3\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


class _FakeCycle:
    def __init__(self, dispositions: list[Disposition], *, tag: str) -> None:
        self.dispositions = dispositions
        self.tag = tag
        self.calls = 0

    def __call__(self, config: LoopConfig, *, now: datetime, workdir: Path, **_: Any) -> CycleRun:
        self.calls += 1
        source = config.repo.show(config.base_ref, AGENT)
        current = int(source.split("=")[1])
        proposal_id = f"{self.tag}{self.calls}"
        _materialise_candidate_branch(
            config, f"loop/{proposal_id}", AGENT, f"RETRY_BUDGET = {current + 1}\n"
        )
        disposition = self.dispositions[self.calls - 1]
        return CycleRun(
            proposed=proposal_id,
            decision=Decision(disposition=disposition, reason="fake"),
            lines=(f"gated: {disposition.value}",),
            score=0.8,
            exit_code=EXIT_REJECTED if disposition is Disposition.REJECT else EXIT_OK,
        )


def test_a_second_invocation_does_not_forget_the_parent_of_the_branch_it_resumed(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The live reproduction, in a test. Invocation 1 keeps a candidate;
    invocation 2 resumes from it and proposes from it, which writes the
    closing record. The kept candidate must still name its parent afterwards —
    without that, an owner reading the archive cannot tell the branch the loop
    advanced from the baseline it started at."""
    config = LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"), base_ref="main")
    first = run_loop(
        config,
        now=NOW,
        workdir=tmp_path / "w1",
        turns=1,
        budget_seconds=3600.0,
        cycle_fn=_FakeCycle([Disposition.ESCALATE], tag="a"),
    )
    assert first.kept_count == 1
    kept_ref = first.kept_ref

    run_loop(
        config,
        now=NOW + timedelta(hours=1),
        workdir=tmp_path / "w2",
        turns=1,
        budget_seconds=3600.0,
        cycle_fn=_FakeCycle([Disposition.REJECT], tag="b"),
    )
    folded = archive.fold_lineage(archive.read_lineage(config.paths.lineage_dir, config.graph_id))
    assert folded[kept_ref].parent_ref is not None, (
        "the resumed root's closing record erased the parent of the kept candidate"
    )
    assert folded[kept_ref].disposition == "escalate"
    assert folded[kept_ref].children >= 1


def test_the_reader_reports_the_samplers_own_eligibility(repo: GitRepo, tmp_path: Path) -> None:
    """`read_lineage_entries` calls `_parent_weight`, so a reject that never
    reached a score is listed and marked unsampleable — the exact rule the
    sampler applies, not a second opinion about it."""
    lineage = tmp_path / "state" / "lineage"
    archive.append_lineage(
        lineage, "default", _record("kept1", parent_ref="root", score=0.7, kept=True)
    )
    archive.append_lineage(
        lineage,
        "default",
        _record("scored", parent_ref="kept1", score=0.6, kept=False, disposition="reject"),
    )
    archive.append_lineage(
        lineage,
        "default",
        _record("cheap", parent_ref="kept1", score=None, kept=False, disposition="reject"),
    )
    entries = {e.record.ref: e for e in read_lineage_entries(lineage, "default")}
    assert entries["scored"].sampleable is True
    assert entries["cheap"].sampleable is False
    assert "never a parent" in entries["cheap"].why_not


def test_a_member_whose_ref_is_gone_is_history_only(repo: GitRepo, tmp_path: Path) -> None:
    """A candidate branch deleted between invocations cannot be a parent, and
    the listing says which reason applies — the same distinction
    `_resume_lineage` draws when it skips the member."""
    lineage = tmp_path / "state" / "lineage"
    head = repo.rev_parse("main")
    archive.append_lineage(lineage, "default", _record(head, score=0.7, kept=True))
    archive.append_lineage(
        lineage,
        "default",
        _record("0" * 40, parent_ref=head, score=0.6, kept=False, disposition="reject"),
    )
    entries = {e.record.ref: e for e in read_lineage_entries(lineage, "default", repo=repo)}
    assert entries[head].sampleable is True
    assert entries["0" * 40].sampleable is False
    assert "no longer resolves" in entries["0" * 40].why_not
