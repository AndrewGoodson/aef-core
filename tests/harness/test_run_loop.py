"""`run_loop` — keep/revert on the metric, inside the gates (ADR 0114).

The driver is tested against a fake `cycle` that materialises a candidate
branch and returns the disposition the test chooses. What is under test is
the driver's own promises: keep advances a LOCAL branch and never main,
revert leaves it alone, improvements stack (the next turn proposes from the
kept state), and it stops on budget / halt / no-candidate / a repeated
rejected tree. The gates themselves have their own tests."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aef.harness import ledger
from aef.harness.git import GitRepo
from aef.harness.loop import (
    EXIT_HALTED,
    EXIT_OK,
    EXIT_REJECTED,
    CycleRun,
    LoopConfig,
    LoopPaths,
    _materialise_candidate_branch,
    run_loop,
)
from aef.harness.review import Decision, Disposition

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
AGENT = "agents/demo/graph.py"


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


def _config(repo: GitRepo, tmp_path: Path) -> LoopConfig:
    return LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "state"), base_ref="main")


class _FakeCycle:
    """Proposes RETRY_BUDGET+1 from whatever the turn's base_ref holds, so a
    kept candidate changes what the next proposal starts from — the property
    that makes improvements stack."""

    def __init__(self, dispositions: list[Disposition | None], *, halt_at: int | None = None):
        self.dispositions = dispositions
        self.halt_at = halt_at
        self.bases_seen: list[str] = []
        self.calls = 0

    def __call__(self, config: LoopConfig, *, now: datetime, workdir: Path, **_: Any) -> CycleRun:
        self.calls += 1
        source = config.repo.show(config.base_ref, AGENT)
        self.bases_seen.append(source.strip())
        disposition = self.dispositions[self.calls - 1]
        if disposition is None:
            return CycleRun(lines=("no candidate",))
        current = int(source.split("=")[1])
        proposal_id = f"t{self.calls}"
        _materialise_candidate_branch(
            config, f"loop/{proposal_id}", AGENT, f"RETRY_BUDGET = {current + 1}\n"
        )
        halted = self.halt_at == self.calls
        exit_code = (
            EXIT_HALTED
            if halted
            else (EXIT_REJECTED if disposition is Disposition.REJECT else EXIT_OK)
        )
        return CycleRun(
            proposed=proposal_id,
            decision=Decision(disposition=disposition, reason="fake"),
            lines=(f"gated: {disposition.value}",),
            exit_code=exit_code,
        )


def _run(config: LoopConfig, tmp_path: Path, fake: _FakeCycle, **kw: Any):  # type: ignore[no-untyped-def]
    kw.setdefault("turns", len(fake.dispositions))
    kw.setdefault("budget_seconds", 3600.0)
    return run_loop(config, now=NOW, workdir=tmp_path / "work", cycle_fn=fake, **kw)


# ---------------------------------------------------------------------------
# Keep and revert
# ---------------------------------------------------------------------------
def test_keep_advances_the_kept_branch_and_never_main(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    main_before = repo.rev_parse("main")
    run = _run(config, tmp_path, _FakeCycle([Disposition.ESCALATE]))
    assert run.kept_count == 1
    assert repo.rev_parse("loop/kept") == run.kept_ref == repo.rev_parse("loop/t1")
    assert repo.rev_parse("main") == main_before
    assert repo.show("loop/kept", AGENT) == "RETRY_BUDGET = 4\n"
    kinds = [e.kind for e in ledger.read(config.paths.ledger_dir)]
    assert kinds == [ledger.EventKind.KEPT]


def test_revert_leaves_the_kept_branch_where_it_was(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    run = _run(config, tmp_path, _FakeCycle([Disposition.REJECT]))
    assert (run.kept_count, run.reverted_count) == (0, 1)
    assert repo.rev_parse("loop/kept") == repo.rev_parse("main")
    # The fake gate wrote nothing; neither did the driver.
    assert ledger.read(config.paths.ledger_dir) == ()


def test_improvements_stack_because_the_next_turn_proposes_from_kept(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The point of the driver. `cycle` alone re-proposes from main every
    time (test_successive_cycles_do_not_compound pins that); the loop
    proposes from what it kept."""
    fake = _FakeCycle([Disposition.ESCALATE, Disposition.ESCALATE, Disposition.REJECT])
    run = _run(_config(repo, tmp_path), tmp_path, fake)
    assert fake.bases_seen == ["RETRY_BUDGET = 3", "RETRY_BUDGET = 4", "RETRY_BUDGET = 5"]
    assert repo.show("loop/kept", AGENT) == "RETRY_BUDGET = 5\n"
    assert (run.kept_count, run.reverted_count) == (2, 1)
    assert repo.show("main", AGENT) == "RETRY_BUDGET = 3\n"


def test_auto_merge_disposition_is_also_kept_but_still_not_merged(
    repo: GitRepo, tmp_path: Path
) -> None:
    """If an owner ever enables Tier-1, `gate` merges. The driver itself
    must still never touch main — it only knows about the kept branch."""
    run = _run(_config(repo, tmp_path), tmp_path, _FakeCycle([Disposition.AUTO_MERGE]))
    assert run.kept_count == 1
    assert repo.show("main", AGENT) == "RETRY_BUDGET = 3\n"


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------
def test_stops_when_the_wall_clock_budget_is_spent(repo: GitRepo, tmp_path: Path) -> None:
    ticks = iter([0.0, 1.0, 100.0, 200.0])
    fake = _FakeCycle([Disposition.ESCALATE] * 3)
    run = _run(
        _config(repo, tmp_path), tmp_path, fake, budget_seconds=50.0, clock=lambda: next(ticks)
    )
    assert fake.calls == 1
    assert "wall-clock budget" in run.stopped_because
    assert run.kept_count == 1


def test_stops_when_a_turn_produces_no_candidate(repo: GitRepo, tmp_path: Path) -> None:
    fake = _FakeCycle([Disposition.ESCALATE, None, Disposition.ESCALATE])
    run = _run(_config(repo, tmp_path), tmp_path, fake)
    assert fake.calls == 2
    assert "no candidate" in run.stopped_because
    assert run.kept_count == 1


def test_stops_on_a_halt(repo: GitRepo, tmp_path: Path) -> None:
    fake = _FakeCycle([Disposition.REJECT, Disposition.ESCALATE], halt_at=1)
    run = _run(_config(repo, tmp_path), tmp_path, fake)
    assert fake.calls == 1
    assert "halted" in run.stopped_because
    assert repo.rev_parse("loop/kept") == repo.rev_parse("main")


def test_stops_when_the_proposer_repeats_a_rejected_tree(repo: GitRepo, tmp_path: Path) -> None:
    """After a rejection the base is unchanged, so a deterministic proposer
    proposes the identical diff again. Re-gating it costs N+2 corpus passes
    to learn nothing; the driver notices the identical tree and stops."""
    fake = _FakeCycle([Disposition.REJECT] * 5)
    run = _run(_config(repo, tmp_path), tmp_path, fake)
    assert fake.calls == 2
    assert "already rejected" in run.stopped_because


def test_every_turn_gets_its_own_scratch_dir(repo: GitRepo, tmp_path: Path) -> None:
    """G1 refuses a non-empty `workdir/workspace`, so a workdir shared across
    turns rejected every turn after the first with a TrustBoundaryError
    (ADR 0122). The driver hands each turn a distinct dir under the one it
    was given."""
    seen: list[Path] = []

    class _Recording(_FakeCycle):
        def __call__(
            self, config: LoopConfig, *, now: datetime, workdir: Path, **kw: Any
        ) -> CycleRun:
            seen.append(workdir)
            return super().__call__(config, now=now, workdir=workdir, **kw)

    _run(_config(repo, tmp_path), tmp_path, _Recording([Disposition.ESCALATE] * 3))
    assert len(seen) == 3 and len(set(seen)) == 3, seen
    assert all(p.parent == tmp_path / "work" for p in seen), seen


def test_a_second_run_resumes_from_the_existing_kept_branch(repo: GitRepo, tmp_path: Path) -> None:
    config = _config(repo, tmp_path)
    _run(config, tmp_path, _FakeCycle([Disposition.ESCALATE]))
    fake = _FakeCycle([Disposition.ESCALATE])
    run = _run(config, tmp_path, fake)
    assert fake.bases_seen == ["RETRY_BUDGET = 4"]
    assert repo.show("loop/kept", AGENT) == "RETRY_BUDGET = 5\n"
    assert "at " in run.lines[0] and "loop/kept" in run.lines[0]


# ---------------------------------------------------------------------------
# Archive sampling (ADR 0121) — DGM's parent selection, off by default
# ---------------------------------------------------------------------------
class _ScoredCycle(_FakeCycle):
    """Like _FakeCycle, but each turn also reports a G3 score, and the
    proposed value depends on the PARENT so different parents yield
    different trees."""

    def __init__(self, dispositions: list[Disposition | None], scores: list[float]):
        super().__init__(dispositions)
        self.scores = scores

    def __call__(self, config: LoopConfig, *, now: datetime, workdir: Path, **_: Any) -> CycleRun:
        run = super().__call__(config, now=now, workdir=workdir)
        if run.proposed is None:
            return run
        return CycleRun(
            proposed=run.proposed,
            decision=run.decision,
            lines=run.lines,
            exit_code=run.exit_code,
            score=self.scores[self.calls - 1],
            incumbent_score=0.5,
        )


def test_greedy_mode_is_unchanged_by_the_archive(repo: GitRepo, tmp_path: Path) -> None:
    fake = _ScoredCycle([Disposition.ESCALATE] * 2, [0.6, 0.7])
    run = _run(_config(repo, tmp_path), tmp_path, fake)
    assert fake.bases_seen == ["RETRY_BUDGET = 3", "RETRY_BUDGET = 4"]
    assert len(run.archive) == 3  # root + two kept
    assert run.archive[1].parent_ref == run.archive[0].ref
    assert run.archive[2].parent_ref == run.archive[1].ref
    assert run.distinct_kept_trees == 2


def test_sampling_records_lineage_and_points_kept_at_the_best_score(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Three kept candidates with scores 0.9, 0.6, 0.7: whatever parents the
    seed picks, the kept branch must end on the 0.9 member and every member
    must name a parent that is in the archive."""
    fake = _ScoredCycle([Disposition.ESCALATE] * 3, [0.9, 0.6, 0.7])
    run = _run(_config(repo, tmp_path), tmp_path, fake, sample_parents=True, seed=1)
    kept = [m for m in run.archive if m.parent_ref is not None]
    assert [m.score for m in kept] == [0.9, 0.6, 0.7]
    best = max(kept, key=lambda m: m.score or 0)
    assert repo.rev_parse("loop/kept") == best.ref == run.kept_ref
    refs = {m.ref for m in run.archive}
    assert all(m.parent_ref in refs for m in kept)
    entries = ledger.read(_config(repo, tmp_path).paths.ledger_dir)
    assert all(e.detail["parent_ref"] in refs for e in entries if e.kind == ledger.EventKind.KEPT)


def test_sampling_can_revisit_an_earlier_parent(repo: GitRepo, tmp_path: Path) -> None:
    """The property greedy cannot have: a later turn proposes from a member
    that is not the latest kept. With the root scored low and a strong kept
    member with no children yet, the sampler prefers it over the root."""
    fake = _ScoredCycle([Disposition.ESCALATE] * 4, [0.95, 0.2, 0.95, 0.2])
    run = _run(_config(repo, tmp_path), tmp_path, fake, sample_parents=True, seed=3)
    kept = [m for m in run.archive if m.parent_ref is not None]
    # Greedy gives parent(k) == kept[k-1] for every k and never a duplicate.
    # Sampling breaks that in one of two visible ways: a kept member whose
    # parent is not the previous kept, or a re-drawn parent whose proposal
    # duplicates a kept tree (the deterministic fake proposes the same thing
    # from the same parent). Observed with seed=3: a duplicate.
    chain_broken = any(kept[k].parent_ref != kept[k - 1].ref for k in range(1, len(kept)))
    duplicated = any(t.duplicate for t in run.turns)
    assert chain_broken or duplicated, [(t.parent_ref[:6], t.kept, t.duplicate) for t in run.turns]


def test_a_candidate_matching_a_kept_tree_is_a_duplicate_not_a_revert(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Sampling the root twice makes the deterministic fake propose
    RETRY_BUDGET = 4 twice; the second is a duplicate of a kept tree and
    must be neither kept nor counted as reverted, and the loop continues."""

    class _RootOnly(_ScoredCycle):
        def __call__(self, config: LoopConfig, **kw: Any) -> CycleRun:  # type: ignore[override]
            return super().__call__(replace_base(config), **kw)

    def replace_base(config: LoopConfig) -> LoopConfig:
        from dataclasses import replace as _r

        return _r(config, base_ref="main")

    fake = _RootOnly([Disposition.ESCALATE] * 3, [0.6, 0.6, 0.6])
    run = _run(_config(repo, tmp_path), tmp_path, fake, sample_parents=True)
    assert run.kept_count == 1
    assert run.reverted_count == 0
    assert sum(t.duplicate for t in run.turns) == 2
    assert "turn budget" in run.stopped_because


def test_parent_weight_prefers_score_and_penalises_children() -> None:
    """The two terms of DGM's rule, each pinned on its own. Mutation M38
    (dropping the novelty term) passed every test above — this is the test
    that exists because of it."""
    from aef.harness.loop import ArchiveMember, _parent_weight

    fresh = ArchiveMember(ref="a", score=0.8, parent_ref=None)
    tired = ArchiveMember(ref="b", score=0.8, parent_ref=None, children=3)
    weak = ArchiveMember(ref="c", score=0.2, parent_ref=None)
    unknown = ArchiveMember(ref="d", score=None, parent_ref=None)
    assert _parent_weight(tired) == pytest.approx(_parent_weight(fresh) / 4)
    assert _parent_weight(weak) < _parent_weight(fresh)
    assert _parent_weight(unknown) == pytest.approx(0.5)  # a 0.5 score, no children


# ---------------------------------------------------------------------------
# The kept branch is for reviewing, not for standing on (ADR 0125)
# ---------------------------------------------------------------------------


def test_refuses_to_start_while_the_kept_branch_is_checked_out(
    repo: GitRepo, tmp_path: Path
) -> None:
    """`update-ref` moves a branch without touching the index or the working
    tree. When that branch is HEAD, the reviewer is left with a repository
    whose index reads as a STAGED REVERSAL of the change the loop just kept —
    reproduced: `git status --porcelain` returned `M  agents/demo/graph.py`
    with the worktree still at RETRY_BUDGET = 3 while loop/kept had 4."""
    from aef.harness.loop import KeptBranchCheckedOutError

    _git(repo.root, "branch", "loop/kept", "main")
    _git(repo.root, "checkout", "-q", "loop/kept")

    fake = _FakeCycle([Disposition.ESCALATE])
    with pytest.raises(KeptBranchCheckedOutError, match="loop/kept"):
        _run(_config(repo, tmp_path), tmp_path, fake)

    # Refused BEFORE anything ran, so nothing was gated and nothing moved.
    assert fake.calls == 0
    assert _git(repo.root, "rev-parse", "loop/kept") == _git(repo.root, "rev-parse", "main")
    assert _git(repo.root, "status", "--porcelain") == ""


def test_the_same_loop_runs_from_any_other_branch(repo: GitRepo, tmp_path: Path) -> None:
    """The control. A refusal that also blocks the ordinary case is not a
    guard, it is an outage."""
    _git(repo.root, "branch", "loop/kept", "main")
    _git(repo.root, "checkout", "-q", "main")
    run = _run(_config(repo, tmp_path), tmp_path, _FakeCycle([Disposition.ESCALATE]))
    assert run.kept_count == 1
    assert _git(repo.root, "status", "--porcelain") == ""


def test_a_non_default_kept_branch_name_is_the_one_refused(repo: GitRepo, tmp_path: Path) -> None:
    """`--kept-branch` is a flag; the guard must read it rather than a
    hard-coded 'loop/kept'."""
    from aef.harness.loop import KeptBranchCheckedOutError

    _git(repo.root, "checkout", "-qb", "review/mine")
    with pytest.raises(KeptBranchCheckedOutError, match="review/mine"):
        _run(
            _config(repo, tmp_path),
            tmp_path,
            _FakeCycle([Disposition.ESCALATE]),
            kept_branch="review/mine",
        )


# ---------------------------------------------------------------------------
# The archive is durable, and rejects are in it (ADR 0160)
#
# J0 (ADR 0151) scored dimension 6 at 5/10 on four clauses: the lineage
# archive is in-memory inside one `run_loop` call, has no CLI flag, only kept
# candidates enter it, and nothing persists across invocations. The CLI flag
# is `tests/cli/test_loop_run_archive_flags.py`; the other three are here.
# ---------------------------------------------------------------------------


def _lineage(config: LoopConfig) -> tuple[Any, ...]:
    from aef.harness import archive as archive_module

    return archive_module.read_lineage(config.paths.lineage_dir, config.graph_id)


def test_every_gated_candidate_is_written_to_the_lineage_file(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Clause 3, first half: rejects are members. Before ADR 0160 the archive
    held kept candidates only, so a turn the gates refused left nothing at
    all — the loop's record of where it had already been was a record of
    where it had succeeded."""
    config = _config(repo, tmp_path)
    fake = _ScoredCycle([Disposition.ESCALATE, Disposition.REJECT], [0.7, 0.4])
    run = _run(config, tmp_path, fake)

    kept = [m for m in run.archive if m.parent_ref is not None and m.kept]
    rejected = [m for m in run.archive if not m.kept]
    assert [m.score for m in kept] == [0.7]
    assert [m.score for m in rejected] == [0.4]
    assert [m.disposition for m in rejected] == ["reject"]
    # ...and the same two are on disk, with their verdicts.
    records = _lineage(config)
    assert {(r.kept, r.disposition, r.score) for r in records} >= {
        (True, "escalate", 0.7),
        (False, "reject", 0.4),
    }
    # The kept count is unmoved: an archived reject is not a kept candidate.
    assert run.kept_count == 1 and run.reverted_count == 1
    assert run.distinct_kept_trees == 1 and run.distinct_gated_trees == 2


def test_greedy_never_proposes_from_a_rejected_member(repo: GitRepo, tmp_path: Path) -> None:
    """The control on clause 3. Rejects entering the archive must not change
    what greedy does: `archive[-1]` after a rejection IS the rejected
    candidate, so the naive version silently starts proposing from content
    every gate refused."""
    fake = _ScoredCycle(
        [Disposition.ESCALATE, Disposition.REJECT, Disposition.ESCALATE], [0.7, 0.4, 0.8]
    )
    run = _run(_config(repo, tmp_path), tmp_path, fake)
    # Turn 1 keeps 4; turn 2 proposes 5 from it and is rejected; turn 3 must
    # propose from 4 again, NOT from the rejected 5.
    assert fake.bases_seen == ["RETRY_BUDGET = 3", "RETRY_BUDGET = 4", "RETRY_BUDGET = 4"]
    assert run.kept_count == 2
    assert repo.show("loop/kept", AGENT) == "RETRY_BUDGET = 5\n"


def test_a_rejected_member_that_reached_a_score_can_be_sampled_as_a_parent(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Clause 3, the point of it. DGM's stepping stone: turn 1 is REJECTED
    but G3 measured it at 0.95, so it is a real, measured position in the
    search space and a later turn builds on it. Greedy cannot do this — the
    control below is that the same schedule with sampling off never leaves
    the kept branch."""
    config = _config(repo, tmp_path)
    fake = _ScoredCycle([Disposition.REJECT] + [Disposition.ESCALATE] * 3, [0.95, 0.55, 0.55, 0.55])
    run = _run(config, tmp_path, fake, sample_parents=True, seed=0)

    stepping_stones = {m.ref for m in run.archive if not m.kept and m.score is not None}
    assert stepping_stones, "the rejected candidate must be in the archive"
    assert any(t.parent_ref in stepping_stones for t in run.turns), [
        (t.turn, t.parent_ref[:8], t.kept) for t in run.turns
    ]

    greedy = _ScoredCycle(
        [Disposition.REJECT] + [Disposition.ESCALATE] * 3, [0.95, 0.55, 0.55, 0.55]
    )
    control = _run(_config(repo, tmp_path / "greedy"), tmp_path / "greedy", greedy)
    stones = {m.ref for m in control.archive if not m.kept}
    assert not any(t.parent_ref in stones for t in control.turns)


def test_a_candidate_rejected_before_scoring_is_archived_but_never_sampled(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Clause 3's exclusion, on the weight function directly. A candidate a
    CHEAP gate refused (G0's zone, G1's build, G5's drift) has no task
    metric. Giving it the root's 0.5 fallback would let an unbuildable tree
    outbid a measured one on a number nothing measured, so its weight is
    zero — and it is still recorded, because where the loop could not stand
    is part of the account of where it went."""
    from aef.harness.loop import ArchiveMember, _parent_weight

    unscored_reject = ArchiveMember(ref="a", score=None, parent_ref="p", kept=False)
    scored_reject = ArchiveMember(ref="b", score=0.7, parent_ref="p", kept=False)
    root = ArchiveMember(ref="c", score=None, parent_ref=None, kept=True)

    assert _parent_weight(unscored_reject) == 0.0
    assert _parent_weight(scored_reject) > 0.0
    assert _parent_weight(root) == pytest.approx(0.5)


def test_an_unscored_reject_is_recorded_and_the_run_continues(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The other half of the same clause, through the driver: a rejection
    with `score=None` (what a cheap gate produces) is archived, is never a
    parent, and does not stop the loop."""
    config = _config(repo, tmp_path)
    fake = _ScoredCycle(
        [Disposition.REJECT, Disposition.ESCALATE],
        [None, 0.6],  # type: ignore[list-item]
    )
    run = _run(config, tmp_path, fake, sample_parents=True, seed=0)
    unscored = [m for m in run.archive if not m.kept]
    assert [m.score for m in unscored] == [None]
    assert all(t.parent_ref != unscored[0].ref for t in run.turns)
    assert any(r.kept is False and r.score is None for r in _lineage(config))


def test_the_lineage_persists_and_a_second_run_samples_a_parent_the_first_kept(
    repo: GitRepo, tmp_path: Path
) -> None:
    """Clause 2, the whole of it. Run 1 keeps two candidates and stops. Run 2
    is a separate `run_loop` call with no memory of run 1 except the state
    directory — and it proposes from a member run 1 kept that is NOT the
    kept-branch head, which is exactly the thing an in-memory archive cannot
    do."""
    config = _config(repo, tmp_path)
    run1 = _run(
        config,
        tmp_path,
        _ScoredCycle([Disposition.ESCALATE] * 2, [0.9, 0.55]),
        sample_parents=True,
        seed=0,
    )
    assert run1.kept_count == 2
    assert len(_lineage(config)) >= 2

    run2 = _run(
        config,
        tmp_path / "second",
        _ScoredCycle([Disposition.ESCALATE] * 2, [0.6, 0.6]),
        sample_parents=True,
        seed=0,
    )
    resumed = {m.ref for m in run2.archive if m.resumed}
    assert run2.resumed_members >= 1, [m.ref[:8] for m in run2.archive]
    assert any(t.parent_ref in resumed for t in run2.turns), [
        (t.turn, t.parent_ref[:8]) for t in run2.turns
    ]
    assert "lineage: resumed" in "\n".join(run2.lines)


def test_no_lineage_makes_a_run_self_contained(repo: GitRepo, tmp_path: Path) -> None:
    """The control for clause 2: with persistence off, run 2 inherits
    nothing and the file is never written."""
    config = _config(repo, tmp_path)
    _run(
        config,
        tmp_path,
        _ScoredCycle([Disposition.ESCALATE] * 2, [0.9, 0.55]),
        sample_parents=True,
        seed=0,
        persist_lineage=False,
    )
    assert _lineage(config) == ()
    run2 = _run(
        config,
        tmp_path / "second",
        _ScoredCycle([Disposition.ESCALATE], [0.6]),
        sample_parents=True,
        seed=0,
        persist_lineage=False,
    )
    assert run2.resumed_members == 0


def test_the_novelty_term_survives_the_invocation_boundary(repo: GitRepo, tmp_path: Path) -> None:
    """Children counts only exist once a run is over, so `run_loop` appends a
    closing record per member and `_resume_lineage` folds by ref taking the
    last. Without the fold the count resumes as zero every night and the term
    that pushes the sampler off an over-explored parent never accumulates —
    the knob quietly not working rather than the knob being off."""
    config = _config(repo, tmp_path)
    # Greedy, so the counts are arithmetic rather than a draw: turn 1 proposes
    # from the root, turn 2 from the candidate turn 1 kept. Each ends with one
    # child.
    run1 = _run(config, tmp_path, _ScoredCycle([Disposition.ESCALATE] * 2, [0.9, 0.55]))
    assert [m.children for m in run1.archive] == [1, 1, 0]
    assert any(r.children > 0 for r in _lineage(config)), [
        (r.ref[:8], r.children) for r in _lineage(config)
    ]

    # Run 2 starts a fresh kept branch, so its root is the SAME commit run 1
    # started from — a member run 1 left with one child. One more turn must
    # leave it at TWO. Without the closing records, or without the fold that
    # prefers them, it reads back as zero and comes out at one.
    run2 = _run(
        config,
        tmp_path / "second",
        _ScoredCycle([Disposition.ESCALATE], [0.6]),
        kept_branch="loop/b",
    )
    assert run2.archive[0].ref == run1.archive[0].ref
    assert run2.archive[0].children == 2, [(m.ref[:8], m.children) for m in run2.archive]


class _FixedTreeCycle(_ScoredCycle):
    """Always proposes from `main`, so every turn produces the SAME tree
    whatever parent the driver chose."""

    def __call__(self, config: LoopConfig, **kw: Any) -> CycleRun:  # type: ignore[override]
        from dataclasses import replace as _replace

        return super().__call__(_replace(config, base_ref="main"), **kw)


def test_duplicate_detection_spans_invocations(repo: GitRepo, tmp_path: Path) -> None:
    """Clause 4. Run 1 keeps tree T. Run 2 proposes T again — with only the
    in-memory archive it is new, gets kept, and the loop pays N+2 corpus
    passes to re-learn what it already knew. Against the persisted set it is
    a duplicate."""
    # The second run gets its OWN kept branch, starting at main. Without
    # that, run 2's root is already tree T and the duplicate would be caught
    # by the root member whether or not anything persisted — the assertion
    # would be true for the wrong reason.
    config = _config(repo, tmp_path)
    run1 = _run(
        config, tmp_path, _FixedTreeCycle([Disposition.ESCALATE], [0.7]), kept_branch="loop/a"
    )
    assert run1.kept_count == 1

    run2 = _run(
        config,
        tmp_path / "second",
        _FixedTreeCycle([Disposition.ESCALATE], [0.7]),
        kept_branch="loop/b",
    )
    assert run2.kept_count == 0
    assert sum(t.duplicate for t in run2.turns) == 1

    # The control: the same second run with persistence off keeps it, which
    # is what makes the assertion above about the persisted set and not about
    # something else.
    control = _run(
        config,
        tmp_path / "third",
        _FixedTreeCycle([Disposition.ESCALATE], [0.7]),
        kept_branch="loop/c",
        persist_lineage=False,
    )
    assert sum(t.duplicate for t in control.turns) == 0
    assert control.kept_count == 1


def test_a_tree_rejected_in_an_earlier_run_stops_the_next_one(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The rejected-tree stop, extended over the persisted set. ADR 0114's
    reason for it — "the proposer is deterministic from its evidence, so
    re-gating the same rejected diff would spend N+2 corpus passes to learn
    nothing" — does not become false overnight."""
    config = _config(repo, tmp_path)
    _run(config, tmp_path, _FixedTreeCycle([Disposition.REJECT], [0.3]))
    run2 = _run(config, tmp_path / "second", _FixedTreeCycle([Disposition.REJECT] * 2, [0.3, 0.3]))
    assert "already rejected" in run2.stopped_because
    assert len(run2.turns) == 1, "it must stop on the FIRST re-proposal, not the second"


def test_a_lineage_member_whose_ref_is_gone_is_history_not_a_parent(
    repo: GitRepo, tmp_path: Path
) -> None:
    """The lineage archive stores refs, not bytes — deliberately, since it is
    resume state and not the content archive. So it must say what it loses
    when a candidate branch is deleted: the member cannot be proposed from,
    its TREE still guards the duplicate check, and the run says so in a line
    rather than failing a turn on an unknown revision."""
    config = _config(repo, tmp_path)
    _run(config, tmp_path, _FixedTreeCycle([Disposition.ESCALATE], [0.7]), kept_branch="loop/a")
    records = _lineage(config)
    assert records
    # Rewrite the lineage with a ref that does not exist in this repository.
    from aef.harness import archive as archive_module

    path = archive_module.lineage_path(config.paths.lineage_dir, config.graph_id)
    path.unlink()
    for record in records:
        archive_module.append_lineage(
            config.paths.lineage_dir,
            config.graph_id,
            replace(record, ref="0" * 40),
        )

    run2 = _run(
        config,
        tmp_path / "second",
        _FixedTreeCycle([Disposition.ESCALATE], [0.7]),
        kept_branch="loop/b",
    )
    assert run2.resumed_members == 0
    assert "no longer resolves" in "\n".join(run2.lines)
    # ...and the tree it recorded still catches the duplicate.
    assert sum(t.duplicate for t in run2.turns) == 1


# ---------------------------------------------------------------------------
# A turn that tried several candidates (ADR 0200)
# ---------------------------------------------------------------------------


class _MultiCandidateCycle:
    """A turn that gates two candidates and keeps one, like `cycle` with
    `--candidates 2`. Turn 2 re-proposes the LOSER of turn 1."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, config: LoopConfig, *, now: datetime, workdir: Path, **_: Any) -> CycleRun:
        from aef.harness.loop import CandidateAttempt

        self.calls += 1
        if self.calls == 1:
            _materialise_candidate_branch(config, "loop/win", AGENT, "RETRY_BUDGET = 4\n")
            _materialise_candidate_branch(config, "loop/lose", AGENT, "RETRY_BUDGET = 9\n")
            return CycleRun(
                proposed="win",
                decision=Decision(disposition=Disposition.ESCALATE, reason="fake"),
                lines=("2 candidates",),
                exit_code=EXIT_OK,
                score=0.8,
                attempts=(
                    CandidateAttempt("win", "loop/win", "escalate", 0.8, 0.1, True, EXIT_OK, "ok"),
                    CandidateAttempt(
                        "lose", "loop/lose", "reject", 0.2, 0.1, False, EXIT_REJECTED, "no"
                    ),
                ),
            )
        # Turn 2 re-proposes exactly the tree turn 1 already rejected.
        _materialise_candidate_branch(config, "loop/again", AGENT, "RETRY_BUDGET = 9\n")
        return CycleRun(
            proposed="again",
            decision=Decision(disposition=Disposition.REJECT, reason="fake"),
            lines=("1 candidate",),
            exit_code=EXIT_REJECTED,
            score=0.2,
            attempts=(
                CandidateAttempt(
                    "again", "loop/again", "reject", 0.2, 0.1, False, EXIT_REJECTED, "no"
                ),
            ),
        )


def test_a_losing_candidates_tree_is_remembered_as_rejected(repo: GitRepo, tmp_path: Path) -> None:
    """A turn that gated three diffs and kept one has REJECTED the other two.

    Without this the next turn can spend cohort+2 corpus passes re-gating a
    tree this run already refused — the exact expense `rejected_trees` exists
    to avoid, made reachable by ADR 0200's multi-candidate turn.
    """
    config = _config(repo, tmp_path)

    run = run_loop(
        config,
        now=NOW,
        workdir=tmp_path / "work",
        cycle_fn=_MultiCandidateCycle(),
        turns=2,
        budget_seconds=3600.0,
    )

    assert run.kept_count == 1
    assert "already rejected" in run.stopped_because, run.stopped_because
