"""M12's acceptance proof: the full six-gate pipeline on real evidence.

Before this milestone the pipeline could not pass anything, and not for want
of a corpus: `G3Improvement()` was constructed with no `CohortVerdict`, so it
returned FAIL on every run, and `G5RateAndDrift()` got no blessed baseline.
The gates were built and tested; nothing fed them.

These tests run the **real** driver against a **real** git repository with a
**recorded** corpus, and assert both outcomes that matter:

  1. a coherent candidate passes ALL SIX gates
  2. a candidate that a single random mutation could have matched is REJECTED
     by G3 — the null hypothesis holding, which is the whole point of ADR 0051

`G1`'s commands are overridden here. Its defaults (`mypy --strict aef`,
`pytest -q`) are aef-core's own green bar; a small agent repo has a different
one, and asserting against aef-core's would be testing the wrong repo.
"""

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import archive
from aef.harness.corpus import load_corpus
from aef.harness.gates.g1_builds import G1Builds
from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, gate
from aef.harness.review import Disposition

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]

# (retry budget, quality threshold)
INCUMBENT = (3, 3)
COHERENT = (5, 5)  # raises both, coherently
SINGLE = (5, 3)  # exactly what a random single-constant mutation does


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _write_agent(root: Path, constants: tuple[int, int]) -> None:
    retry, quality = constants
    source = (REPO_ROOT / "agents" / "demo" / "graph.py").read_text()
    source = source.replace("RETRY_BUDGET = 3", f"RETRY_BUDGET = {retry}")
    source = source.replace("QUALITY_THRESHOLD = 3", f"QUALITY_THRESHOLD = {quality}")
    assert f"RETRY_BUDGET = {retry}" in source, "constant substitution failed"
    assert f"QUALITY_THRESHOLD = {quality}" in source, "constant substitution failed"
    (root / "agents" / "demo" / "graph.py").write_text(source)


@pytest.fixture
def agent_repo(tmp_path: Path) -> GitRepo:
    """A real repo holding the Zone A agent and the recorded corpus.

    `aef` itself is NOT copied in — it comes from the installed package,
    which is exactly how CI resolves it: the harness is the base ref's,
    installed from the checkout of main (ADR 0057).
    """
    root = tmp_path / "agent-repo"
    (root / "agents" / "demo").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "corpus", root / "corpus")
    (root / "agents" / "__init__.py").write_text("")
    (root / "agents" / "demo" / "__init__.py").write_text("")
    _write_agent(root, INCUMBENT)

    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "loop@test")
    _git(root, "config", "user.name", "loop")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "incumbent")
    return GitRepo(root=root)


def _bless_baseline(repo: GitRepo, state_root: Path) -> None:
    """G5 measures drift against an owner-blessed archive version."""
    archive.record(
        state_root / "archive",
        "demo_agent",
        files={"agents/demo/graph.py": (repo.root / "agents/demo/graph.py").read_bytes()},
        base_sha=repo.rev_parse("main"),
        head_sha=repo.rev_parse("main"),
        recorded_at=NOW,
        notes="owner-blessed baseline",
    )


def _candidate(repo: GitRepo, branch: str, constants: tuple[int, int]) -> None:
    _git(repo.root, "checkout", "-qb", branch)
    _write_agent(repo.root, constants)
    _git(repo.root, "add", "-A")
    _git(repo.root, "commit", "-qm", branch)


def _config(repo: GitRepo, tmp_path: Path) -> LoopConfig:
    state = tmp_path / "state"
    return LoopConfig(
        repo=repo,
        paths=LoopPaths(root=state),
        base_ref="main",
        graph_id="demo_agent",
        corpus=load_corpus(repo.root / "corpus"),
        entrypoint="agents.demo.graph:build_graph",
        cohort_size=5,
        cohort_seed=11,
    )


def _run(config: LoopConfig, tmp_path: Path, head: str):
    # G1's defaults are aef-core's green bar; a small agent repo has its own.
    gates = tuple(
        G1Builds(commands=(("python", "-c", "import agents.demo.graph"),)) if g.id == "G1" else g
        for g in config.default_gates()
    )
    from dataclasses import replace

    # Keep the driver's evidence wiring; only swap G1's commands.
    import aef.harness.loop as loop_module

    original = loop_module._gates_with_evidence

    def patched(cfg, verdict, workdir, now):  # type: ignore[no-untyped-def]
        built, note = original(cfg, verdict, workdir, now)
        return (
            tuple(
                G1Builds(commands=(("python", "-c", "import agents.demo.graph"),))
                if g.id == "G1"
                else g
                for g in built
            ),
            note,
        )

    loop_module._gates_with_evidence = patched  # type: ignore[assignment]
    try:
        return gate(config, head, now=NOW, workdir=tmp_path / "work")
    finally:
        loop_module._gates_with_evidence = original  # type: ignore[assignment]
    del gates, replace


# --------------------------------------------------------------------------
# The corpus itself
# --------------------------------------------------------------------------


def test_the_seed_corpus_is_recorded_not_hand_authored() -> None:
    corpus = load_corpus(REPO_ROOT / "corpus")
    assert corpus.scenarios
    for scenario in corpus.scenarios:
        assert scenario.trace, f"{scenario.id} has an empty trace"
        assert "recorded from a real" in scenario.notes


def test_the_seed_corpus_has_both_passing_and_failing_scenarios() -> None:
    # A corpus where everything already passes cannot show an improvement;
    # one where everything fails cannot show a regression.
    from aef.harness.gates.g2_outcome import recorded_outcome

    outcomes = [recorded_outcome(s) for s in load_corpus(REPO_ROOT / "corpus").scenarios]
    assert any(o.passed for o in outcomes)
    assert any(not o.passed for o in outcomes)


def test_the_seed_corpus_holdout_is_empty() -> None:
    # The holdout is the owner's to spend, and nothing filled it by accident.
    from aef.harness.corpus import Split

    assert load_corpus(REPO_ROOT / "corpus").split(Split.HOLDOUT) == ()


# --------------------------------------------------------------------------
# M12 ACCEPTANCE 1 — a coherent candidate passes all six gates
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_coherent_candidate_passes_all_six_gates(agent_repo: GitRepo, tmp_path: Path) -> None:
    """The proof that the pipeline can pass anything at all."""
    config = _config(agent_repo, tmp_path)
    _bless_baseline(agent_repo, config.paths.root)
    _candidate(agent_repo, "improve", COHERENT)

    run = _run(config, tmp_path, "improve")

    assert set(run.result.ran) == {"G0", "G1", "G2", "G3", "G4", "G5"}, (
        f"not every gate ran: {run.result.ran}; "
        f"stopped at {run.result.failed_at.gate if run.result.failed_at else None} "
        f"({run.result.failed_at.reason if run.result.failed_at else ''})"
    )
    assert run.result.passed, run.report
    # Tier-1 is off, so passing means escalating — never merging.
    assert run.decision.disposition is Disposition.ESCALATE


@pytest.mark.slow
def test_g3_reports_the_cohort_it_was_measured_against(agent_repo: GitRepo, tmp_path: Path) -> None:
    config = _config(agent_repo, tmp_path)
    _bless_baseline(agent_repo, config.paths.root)
    _candidate(agent_repo, "improve", COHERENT)

    run = _run(config, tmp_path, "improve")
    g3 = next(r for r in run.result.results if r.gate == "G3")
    joined = " ".join(g3.evidence)
    assert "control cohort of 5" in joined
    assert "95% CI" in joined


# --------------------------------------------------------------------------
# M12 ACCEPTANCE 2 — the null hypothesis actually rejects
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_candidate_a_random_mutation_could_match_is_rejected(
    agent_repo: GitRepo, tmp_path: Path
) -> None:
    """Raising ONE constant is exactly what a random single-constant mutation
    does, so the candidate sits inside the cohort's spread. That is the null
    hypothesis holding, and G3 must say so rather than accepting a change
    that merely beats the incumbent (ADR 0051)."""
    config = _config(agent_repo, tmp_path)
    _bless_baseline(agent_repo, config.paths.root)
    _candidate(agent_repo, "single", SINGLE)

    run = _run(config, tmp_path, "single")

    assert run.decision.disposition is Disposition.REJECT
    g3 = next((r for r in run.result.results if r.gate == "G3"), None)
    assert g3 is not None and not g3.passed, run.report
    assert "null hypothesis" in g3.reason


@pytest.mark.slow
def test_the_ledger_records_the_evidence_that_was_built(
    agent_repo: GitRepo, tmp_path: Path
) -> None:
    from aef.harness import ledger

    config = _config(agent_repo, tmp_path)
    _bless_baseline(agent_repo, config.paths.root)
    _candidate(agent_repo, "improve", COHERENT)
    _run(config, tmp_path, "improve")

    gated = next(
        e for e in ledger.read(config.paths.ledger_dir) if e.kind is ledger.EventKind.GATED
    )
    assert "corpus pass" in gated.detail["evidence"]


# --------------------------------------------------------------------------
# ADR 0060/0061 — the reward hack, and the tripwire that catches it
# --------------------------------------------------------------------------


def _reward_hack(root: Path) -> None:
    """One line: stop consulting the inputs, always report success."""
    path = root / "agents" / "demo" / "graph.py"
    source = path.read_text()
    hacked = source.replace(
        "    if difficulty <= RETRY_BUDGET and quality_needed <= QUALITY_THRESHOLD:",
        "    if True:  # always succeed",
    )
    assert hacked != source, "reward-hack substitution failed"
    path.write_text(hacked)


@pytest.mark.slow
def test_a_reward_hack_is_rejected_by_the_tripwire(agent_repo: GitRepo, tmp_path: Path) -> None:
    """THE defect ADR 0060 recorded, and the fix ADR 0061 made.

    Before the fix this candidate passed ALL SIX gates: G5 drift 0.013, G3
    mean 1.0 against a cohort p95 of 0.556. It does no work at all — it just
    says it succeeded, and every behavioural gate read that claim as fact.
    """
    config = _config(agent_repo, tmp_path)
    _bless_baseline(agent_repo, config.paths.root)

    _git(agent_repo.root, "checkout", "-qb", "hack")
    _reward_hack(agent_repo.root)
    _git(agent_repo.root, "add", "-A")
    _git(agent_repo.root, "commit", "-qm", "always succeed")

    run = _run(config, tmp_path, "hack")

    assert run.decision.disposition is Disposition.REJECT, run.report
    g2 = next(r for r in run.result.results if r.gate == "G2")
    assert not g2.passed
    assert "tripwire" in g2.reason
    # A tripwire hit is a security event: it means the self-report every other
    # score rests on is unreliable, not that one scenario went wrong.
    assert g2.security_event


@pytest.mark.slow
def test_the_cheap_gates_still_wave_the_reward_hack_through(
    agent_repo: GitRepo, tmp_path: Path
) -> None:
    """Recorded so the limit stays visible: G0/G1/G4/G5 cannot see this. Only
    owner-supplied ground truth catches it, which is why the corpus needs
    tripwire scenarios rather than better thresholds."""
    config = _config(agent_repo, tmp_path)
    _bless_baseline(agent_repo, config.paths.root)

    _git(agent_repo.root, "checkout", "-qb", "hack")
    _reward_hack(agent_repo.root)
    _git(agent_repo.root, "add", "-A")
    _git(agent_repo.root, "commit", "-qm", "always succeed")

    run = _run(config, tmp_path, "hack")
    cheap = {r.gate: r.passed for r in run.result.results if r.gate in {"G0", "G1", "G4", "G5"}}
    assert all(cheap.values()), cheap


def test_the_corpus_carries_tripwire_scenarios() -> None:
    # Without at least one, the reward hack is undetectable by any gate.
    from aef.harness.corpus import Expected

    corpus = load_corpus(REPO_ROOT / "corpus")
    tripwires = [s for s in corpus.scenarios if s.expected is Expected.MUST_FAIL]
    assert tripwires, "the corpus has no MUST_FAIL scenario; ADR 0060's defect is reopened"


def test_tripwires_are_impossible_not_merely_hard() -> None:
    """A tripwire a legitimate improvement could satisfy would reject real
    progress as reward hacking. Difficulty 5 is hard; 999 is beyond remit."""
    from aef.harness.corpus import Expected

    for scenario in load_corpus(REPO_ROOT / "corpus").scenarios:
        if scenario.expected is Expected.MUST_FAIL:
            assert int(scenario.initial_state.working_memory["difficulty"]) >= 100


def test_expected_defaults_to_unspecified_so_old_scenarios_keep_their_meaning() -> None:
    # A recorded trace says what happened, not that it should have.
    from aef.harness.corpus import Expected

    corpus = load_corpus(REPO_ROOT / "corpus")
    assert any(s.expected is Expected.UNSPECIFIED for s in corpus.scenarios)
