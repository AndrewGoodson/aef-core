"""`run_loop` — keep/revert on the metric, inside the gates (ADR 0114).

The driver is tested against a fake `cycle` that materialises a candidate
branch and returns the disposition the test chooses. What is under test is
the driver's own promises: keep advances a LOCAL branch and never main,
revert leaves it alone, improvements stack (the next turn proposes from the
kept state), and it stops on budget / halt / no-candidate / a repeated
rejected tree. The gates themselves have their own tests."""

from __future__ import annotations

import subprocess
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
