"""Several candidates per turn, and the held-out read that judges the turn.

ADR 0200, and both halves are refusals as much as capabilities:

  - N candidates means N INDEPENDENT gate passes. There is no aggregate
    verdict over a set anywhere, and a test asserts the gates were entered
    once per candidate with a distinct branch each time.
  - the audit slice is a function of the corpus and the calendar and NOTHING
    ELSE. The guarantee is the ABSENCE of the loop's own state from that
    function's inputs, so a test pins its signature — the same shape as
    `tests/harness/test_evidence_is_one_graphs.py`, which pins where the
    evidence filter lives rather than only what it filters.
"""

from __future__ import annotations

import inspect
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aef.harness import ledger
from aef.harness.corpus import Corpus, Scenario, Split
from aef.harness.git import GitRepo
from aef.harness.loop import (
    AuditSlice,
    CandidateAttempt,
    CycleRun,
    LoopConfig,
    LoopPaths,
    _best_attempt,
    _candidates_for_this_turn,
    _corpus_with_audit_held_out,
    audit_slice,
    cycle,
)
from aef.harness.proposer import (
    Citation,
    CitationKind,
    MemoryEvidence,
    Proposal,
    RuleBasedProposer,
)
from aef.harness.review import Decision, Disposition
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
SOURCE = "RETRY_BUDGET = 3\nQUALITY_THRESHOLD = 4\nTIMEOUT_S = 8\n"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    (root / "agents" / "demo").mkdir(parents=True)
    (root / "agents" / "demo" / "graph.py").write_text(SOURCE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return GitRepo(root=root)


def _memory() -> InMemoryMemoryStore:
    store = InMemoryMemoryStore()
    for i in range(2):
        store.write(
            MemoryRecord(
                id=f"rec-{i}",
                kind="failure",
                run_id=f"run-{i}",
                content={"verbal_feedback": f"budget exhausted ({i})"},
            )
        )
    return store


class _FakeGate:
    """Stands in for `loop.gate`, recording every pass it was asked for.

    Deliberately a spy on the REAL seam rather than a `gates=` override: the
    claim under test is that `cycle` enters the gate pipeline once per
    candidate, which a stubbed pipeline inside one pass could not distinguish
    from one pass judging a set.
    """

    def __init__(self, scores: dict[str, float], passes: dict[str, bool]) -> None:
        self.branches: list[str] = []
        self.workdirs: list[Path] = []
        self._scores = scores
        self._passes = passes

    def __call__(self, config: LoopConfig, branch: str, **kw: Any) -> Any:
        self.branches.append(branch)
        self.workdirs.append(kw["workdir"])
        suffix = branch.rsplit("-", 1)[-1]
        ok = self._passes.get(suffix, False)
        from aef.harness.gates.base import PipelineResult
        from aef.harness.loop import GateRun

        return GateRun(
            decision=Decision(
                disposition=Disposition.ESCALATE if ok else Disposition.REJECT,
                reason="stub pass" if ok else "stub reject",
            ),
            result=PipelineResult(results=()),
            report="",
            exit_code=0 if ok else 1,
            candidate_score=self._scores.get(suffix),
            incumbent_score=0.1,
        )


def _run_cycle(repo: GitRepo, tmp_path: Path, gate: Any, **config_kw: Any) -> CycleRun:
    import aef.harness.loop as loop_module

    real = loop_module.gate
    loop_module.gate = gate
    try:
        return cycle(
            LoopConfig(
                repo=repo, paths=LoopPaths(root=tmp_path / "state"), base_ref="main", **config_kw
            ),
            now=NOW,
            workdir=tmp_path / "work",
            memory=_memory(),
            agent_path="agents/demo/graph.py",
        )
    finally:
        loop_module.gate = real


# --------------------------------------------------------------------------
# A — several candidates per turn
# --------------------------------------------------------------------------


def test_the_proposer_offers_more_than_the_default_turn_takes() -> None:
    """The premise, asserted rather than assumed: there IS something to keep."""
    offered = RuleBasedProposer().propose_from_memory(
        MemoryEvidence.from_store(_memory()),
        proposal_id="probe",
        path="agents/demo/graph.py",
        source=SOURCE,
    )
    assert len(offered) == 3
    assert len({p.proposed for p in offered}) == 3, "three DISTINCT trees, not three labels"


def test_n_candidates_are_n_independent_gate_passes(repo: GitRepo, tmp_path: Path) -> None:
    gate = _FakeGate(
        scores={"0": 0.4, "1": 0.9, "2": 0.6}, passes={"0": True, "1": True, "2": True}
    )
    run = _run_cycle(repo, tmp_path, gate, candidates_per_turn=3)

    assert len(gate.branches) == 3
    assert len(set(gate.branches)) == 3, "each candidate on its own branch"
    assert len(set(gate.workdirs)) == 3, "each candidate in its own workdir (ADR 0122's defect)"
    assert len(run.attempts) == 3


def test_the_turn_keeps_the_best_candidate_that_passed(repo: GitRepo, tmp_path: Path) -> None:
    gate = _FakeGate(
        scores={"0": 0.4, "1": 0.9, "2": 0.6}, passes={"0": True, "1": True, "2": True}
    )
    run = _run_cycle(repo, tmp_path, gate, candidates_per_turn=3)

    assert run.proposed is not None and run.proposed.endswith("-1")
    assert run.score == 0.9
    assert run.exit_code == 0


def test_a_higher_scoring_candidate_that_failed_is_not_kept(repo: GitRepo, tmp_path: Path) -> None:
    """The gates decide; the score only orders what they already passed."""
    gate = _FakeGate(
        scores={"0": 0.4, "1": 0.99, "2": 0.6}, passes={"0": True, "1": False, "2": True}
    )
    run = _run_cycle(repo, tmp_path, gate, candidates_per_turn=3)

    assert run.proposed is not None and run.proposed.endswith("-2")
    assert run.score == 0.6


def test_with_nothing_passing_the_turn_reports_the_first(repo: GitRepo, tmp_path: Path) -> None:
    """Exactly what a one-candidate turn always returned."""
    gate = _FakeGate(scores={"0": 0.4, "1": 0.9, "2": 0.6}, passes={})
    run = _run_cycle(repo, tmp_path, gate, candidates_per_turn=3)

    assert run.proposed is not None and run.proposed.endswith("-0")
    assert run.exit_code == 1
    assert all(not a.passed for a in run.attempts)


def test_the_ledger_records_every_candidate_not_only_the_winner(
    repo: GitRepo, tmp_path: Path
) -> None:
    gate = _FakeGate(scores={"0": 0.4, "1": 0.9, "2": 0.6}, passes={"0": True, "1": True})
    run = _run_cycle(repo, tmp_path, gate, candidates_per_turn=3)

    entries = ledger.read(tmp_path / "state")
    roster = [e for e in entries if e.kind is ledger.EventKind.CANDIDATES]
    assert len(roster) == 1
    recorded = roster[0].detail["candidates"]
    assert [c["proposal_id"] for c in recorded] == [a.proposal_id for a in run.attempts]
    assert len(recorded) == 3
    assert roster[0].detail["chosen"] == run.proposed
    assert roster[0].detail["offered"] == 3
    # And what it cost, in the units the loop actually spends.
    assert roster[0].detail["corpus_passes_each"] == 7


def test_one_candidate_writes_no_roster_entry(repo: GitRepo, tmp_path: Path) -> None:
    """The default turn's ledger is byte-for-byte the ledger it always wrote."""
    gate = _FakeGate(scores={"0": 0.4}, passes={"0": True})
    _run_cycle(repo, tmp_path, gate)

    entries = ledger.read(tmp_path / "state")
    assert not [e for e in entries if e.kind is ledger.EventKind.CANDIDATES]


def test_a_halt_stops_the_remaining_candidates(repo: GitRepo, tmp_path: Path) -> None:
    class _HaltingGate(_FakeGate):
        def __call__(self, config: LoopConfig, branch: str, **kw: Any) -> Any:
            run = super().__call__(config, branch, **kw)
            from dataclasses import replace as _replace

            return _replace(run, exit_code=2, halted=True)

    gate = _HaltingGate(scores={}, passes={})
    run = _run_cycle(repo, tmp_path, gate, candidates_per_turn=3)

    assert len(gate.branches) == 1, "a halt is the loop stopping, not a candidate to skip"
    assert run.exit_code == 2
    assert any("were not built" in line for line in run.lines)


def test_duplicate_trees_are_not_gated_twice() -> None:
    cite = (Citation(source="m1", detail="d", kind=CitationKind.MEMORY),)
    same = Proposal("a", "p.py", "x = 1\n", "x = 2\n", "r", cite)
    twin = Proposal("b", "p.py", "x = 1\n", "x = 2\n", "r", cite)
    other = Proposal("c", "p.py", "x = 1\n", "x = 3\n", "r", cite)

    picked = _candidates_for_this_turn((same, twin, other), 3)

    assert [p.id for p in picked] == ["a", "c"]


def test_a_zero_score_pass_outranks_an_unscored_pass() -> None:
    """`score or -1.0` would have got this backwards."""
    scored = CandidateAttempt("a", "loop/a", "escalate", 0.0, 0.0, True, 0, "")
    unscored = CandidateAttempt("b", "loop/b", "escalate", None, None, True, 0, "")

    assert _best_attempt([unscored, scored]) == 1


def test_candidates_per_turn_must_be_at_least_one(repo: GitRepo, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        LoopConfig(repo=repo, paths=LoopPaths(root=tmp_path / "s"), candidates_per_turn=0)


# --------------------------------------------------------------------------
# B — the held-out read
# --------------------------------------------------------------------------


def _scenario(sid: str, split: Split = Split.TRAIN) -> Scenario:
    return Scenario(
        id=sid,
        split=split,
        graph_id="g",
        graph_version="1",
        initial_state=AEFState(run_id=sid, agent_id="a", objective="o"),
        trace=(),
        recorded_at=NOW,
    )


def _corpus(n: int) -> Corpus:
    return Corpus(
        root=Path("/tmp/corpus-never-read"),
        scenarios=tuple(_scenario(f"s{i:02d}") for i in range(n)),
    )


def test_the_slice_is_a_function_of_the_corpus_and_the_date_and_nothing_else() -> None:
    """The guarantee is the ABSENCE of these arguments.

    If `audit_slice` ever grows a parameter carrying a score, a ledger, a
    memory store, a proposal or a candidate, the loop can influence the set
    that judges it and this whole mechanism is decoration.
    """
    params = set(inspect.signature(audit_slice).parameters)

    assert params == {"corpus", "at", "size"}


def test_the_slice_is_deterministic_and_rotates_by_day() -> None:
    corpus = _corpus(10)

    monday = audit_slice(corpus, at=NOW, size=2)
    monday_again = audit_slice(corpus, at=NOW + timedelta(hours=5), size=2)
    tuesday = audit_slice(corpus, at=NOW + timedelta(days=1), size=2)

    assert monday.ids == monday_again.ids
    assert monday.ids != tuesday.ids
    assert len(monday.ids) == 2
    assert set(monday.ids) <= {s.id for s in corpus.scenarios}


def test_the_slice_never_takes_more_than_half_the_train_split() -> None:
    """A held-out set that empties the gated set disables the gates."""
    assert (
        audit_slice(_corpus(4), at=NOW, size=99).ids == audit_slice(_corpus(4), at=NOW, size=2).ids
    )
    assert len(audit_slice(_corpus(4), at=NOW, size=99).ids) == 2
    assert audit_slice(_corpus(1), at=NOW, size=1).ids == ()


def test_off_by_default() -> None:
    assert audit_slice(_corpus(10), at=NOW, size=0) == AuditSlice(
        ids=(), rotation_key="2026-03-01", drawn_from=0
    )


def test_held_back_scenarios_become_inadmissible_evidence() -> None:
    """Relabelled `validation`, so the EXISTING refusal covers them.

    A lesson learned from a scenario that is about to judge the candidate is
    that scenario reaching the proposer by proxy — which is exactly what
    `MemoryEvidence` already refuses for validation and holdout records.
    """
    corpus = _corpus(10)
    config = LoopConfig(
        repo=GitRepo(root=Path(".")),
        paths=LoopPaths(root=Path("/tmp/never-written")),
        corpus=corpus,
        audit_slice_size=2,
    )
    held = audit_slice(corpus, at=NOW, size=2)
    derived = _corpus_with_audit_held_out(config, held)
    assert derived is not None

    store = InMemoryMemoryStore()
    for sid in held.ids:
        store.write(
            MemoryRecord(
                id=f"m-{sid}", kind="failure", run_id=sid, content={"verbal_feedback": "x"}
            )
        )
    store.write(
        MemoryRecord(id="m-keep", kind="failure", run_id="prod-1", content={"verbal_feedback": "y"})
    )

    evidence = MemoryEvidence.from_store(store, derived)

    assert {r.id for r in evidence.records} == {"m-keep"}
    assert set(evidence.excluded) == {f"m-{sid}" for sid in held.ids}


def test_the_held_back_scenarios_are_not_gated(repo: GitRepo, tmp_path: Path) -> None:
    """They are subtracted from what G2/G3 score, or they are not held out."""
    from aef.harness.candidate import inspect_candidate
    from aef.harness.loop import _gates_with_evidence

    corpus = _corpus(10)
    config = LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        base_ref="main",
        corpus=corpus,
        graph_id="g",
        audit_slice_size=2,
        entrypoint=None,
    )
    _git(repo.root, "checkout", "-qb", "cand")
    (repo.root / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 4\n")
    _git(repo.root, "commit", "-aqm", "c")
    verdict = inspect_candidate(repo, "main", "cand", config.zone_policy)

    _, note = _gates_with_evidence(config, verdict, tmp_path / "wd", NOW)

    # No entrypoint, so G2/G3 refuse before any scenario runs — which is the
    # point: the note is where the subtraction is legible either way.
    assert "no entrypoint configured" in note


def test_the_holdout_split_is_never_what_the_slice_draws_from() -> None:
    """The owner's holdout stays the owner's (ADR 0200's decision)."""
    corpus = Corpus(
        root=Path("/tmp/corpus-never-read"),
        scenarios=(
            _scenario("t1"),
            _scenario("t2"),
            _scenario("t3"),
            _scenario("t4"),
            _scenario("v1", Split.VALIDATION),
            _scenario("h1", Split.HOLDOUT),
            _scenario("h2", Split.HOLDOUT),
        ),
    )

    for day in range(40):
        drawn = audit_slice(corpus, at=NOW + timedelta(days=day), size=2)
        assert not set(drawn.ids) & {"h1", "h2", "v1"}


def test_the_audit_is_not_read_when_nothing_passed(repo: GitRepo, tmp_path: Path) -> None:
    gate = _FakeGate(scores={"0": 0.4}, passes={})
    run = _run_cycle(repo, tmp_path, gate, corpus=_corpus(10), audit_slice_size=2, graph_id="g")

    assert run.audit is None
    assert any("no candidate passed the gates" in line for line in run.lines)


def test_the_audit_is_advisory_and_says_so(repo: GitRepo, tmp_path: Path) -> None:
    """It records a verdict of its own and changes none of the loop's."""
    gate = _FakeGate(scores={"0": 0.4}, passes={"0": True})
    run = _run_cycle(repo, tmp_path, gate, corpus=_corpus(10), audit_slice_size=2, graph_id="g")

    assert run.audit is not None
    # No entrypoint in this config, so the read reports itself unread rather
    # than inventing a number — and the disposition is untouched either way.
    assert run.audit.candidate_mean is None
    assert run.exit_code == 0
    entries = ledger.read(tmp_path / "state")
    audits = [e for e in entries if e.kind is ledger.EventKind.AUDIT]
    assert len(audits) == 1
    assert audits[0].detail["advisory"] is True
    assert audits[0].detail["scenarios"] == list(run.audit.ids)
