"""The candidate branch must be the thing that was proposed.

Three defects at this seam, all reproduced by running `aef loop cycle`
against a repo in a state the tests never put it in: a dirty working tree, a
feature branch, and a detached HEAD — which is the *normal* CI shape, since
`actions/checkout` with a ref or SHA detaches (ADR 0078).
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, _materialise_candidate_branch

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "agents" / "g.py").write_text("RETRY = 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _config(repo: Path, tmp_path: Path) -> LoopConfig:
    return LoopConfig(repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"))


def test_an_attached_checkout_is_put_back_on_its_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = _git(repo, "rev-parse", "HEAD")
    _materialise_candidate_branch(_config(repo, tmp_path), "loop/c1", "agents/g.py", "RETRY = 4\n")
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(repo, "rev-parse", "HEAD") == before
    assert (repo / "agents" / "g.py").read_text() == "RETRY = 3\n"


def test_a_detached_checkout_is_put_back_where_it_was(tmp_path: Path) -> None:
    """`rev-parse --abbrev-ref HEAD` returns the literal string "HEAD" when
    detached, so the restore was `git checkout HEAD` — a no-op. The job was
    left standing on the candidate branch with an un-gated mutation in its
    working tree, and the next cycle read that mutation as its starting
    point."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach", "HEAD")
    before = _git(repo, "rev-parse", "HEAD")

    _materialise_candidate_branch(_config(repo, tmp_path), "loop/c1", "agents/g.py", "RETRY = 4\n")

    assert _git(repo, "rev-parse", "HEAD") == before, "left standing on the candidate branch"
    assert (repo / "agents" / "g.py").read_text() == "RETRY = 3\n", "un-gated mutation left behind"


def test_successive_cycles_do_not_compound(tmp_path: Path) -> None:
    """Cycle 2 read cycle 1's leftover mutation and proposed on top of it
    while still diffing against the base — so the rationale described 4->5
    and the diff said 3->5."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach", "HEAD")
    config = _config(repo, tmp_path)

    for i, content in enumerate(("RETRY = 4\n", "RETRY = 4\n"), start=1):
        _materialise_candidate_branch(config, f"loop/c{i}", "agents/g.py", content)

    for i in (1, 2):
        diff = _git(repo, "diff", f"main...loop/c{i}")
        assert "+RETRY = 4" in diff and "-RETRY = 3" in diff, f"cycle {i} compounded: {diff}"


def test_the_proposer_reads_the_ref_the_diff_is_taken_against() -> None:
    """It read the working tree while the branch was built from `base_ref`,
    so every un-proposed working-tree change was laundered into the
    candidate: the rationale named one constant and the diff G0 sized and
    scanned carried an unrelated import as well."""
    import inspect

    from aef.harness.loop import cycle

    source = inspect.getsource(cycle)
    assert "config.repo.show(config.base_ref, agent_path)" in source
    assert "source_path.read_text()" not in source


# --------------------------------------------------------------------------
# The null hypothesis has to be a distribution
# --------------------------------------------------------------------------


def test_control_cohort_members_are_distinct_mutations() -> None:
    """`coerce_value` moves an integer by at least one whole unit, so a
    constant like `RETRIES = 1` has about two reachable mutations. The
    generator produced five members regardless, and G3's floor counts
    MEMBERS — so five copies of one mutation satisfied it while giving the
    percentile a point mass to be computed over (ADR 0078)."""
    from aef.harness.proposer import ControlCohortGenerator

    source = "RETRIES = 2\nTIMEOUT_S = 1.5\n"
    for seed in range(10):
        cohort = ControlCohortGenerator(seed=seed).generate(path="a.py", source=source, size=5)
        assert len({m.proposed for m in cohort}) == 5, f"seed {seed} produced repeats"


def test_a_cohort_that_cannot_be_distinct_refuses_rather_than_repeating() -> None:
    """Refusing is honest: G2/G3 then decline for lack of evidence and the
    candidate escalates, rather than being measured against a threshold that
    means nothing. The message names the cause and the fix, because this is
    a real limitation of a single-small-integer agent, not a bug."""
    import pytest

    from aef.harness.proposer import ControlCohortGenerator, ProposalError

    with pytest.raises(ProposalError, match="DISTINCT control mutations"):
        ControlCohortGenerator(seed=0).generate(path="a.py", source="RETRIES = 1\n", size=5)


# --------------------------------------------------------------------------
# The proposer must not refuse ordinary Python
# --------------------------------------------------------------------------


def test_a_trailing_comment_does_not_disable_the_proposer() -> None:
    """`find_constants` uses the AST and `rewrite_constant` re-validates with
    a line regex that rejected a trailing comment — completely ordinary
    Python. `propose()` raises on the first offender, so ONE such line made
    the proposer emit nothing for the file, including for rewritable
    constants beside it. The loop was off, reported as a rejection."""
    from aef.harness.proposer import find_constants, rewrite_constant

    source = "RETRY = 3  # how many attempts\nTIMEOUT_S = 1.5\n"
    constants = {c.name: c for c in find_constants(source)}
    assert set(constants) == {"RETRY", "TIMEOUT_S"}
    assert rewrite_constant(source, constants["RETRY"], 4).startswith(
        "RETRY = 4  # how many attempts"
    ), "the author's comment is not the proposer's to drop"


def test_constants_the_rewriter_cannot_handle_are_skipped_not_fatal() -> None:
    """The AST accepts strictly more than the line regex does. The two now
    agree by construction: anything `find_constants` returns is rewritable."""
    from aef.harness.proposer import find_constants, rewrite_constant

    for source in (
        "RETRY = 3; OTHER = 4\nTIMEOUT_S = 1.5\n",
        "RETRY = (\n    3\n)\nTIMEOUT_S = 1.5\n",
    ):
        found = find_constants(source)
        assert [c.name for c in found] == ["TIMEOUT_S"], source
        for constant in found:
            rewrite_constant(source, constant, constant.value + 1)  # must not raise


# --------------------------------------------------------------------------
# G0 must judge the artefact that runs
# --------------------------------------------------------------------------


def test_g0_reads_bytes_not_a_lossy_decode(tmp_path: Path) -> None:
    """`GitRepo.show` decodes with `errors="replace"` and the sandbox writes
    the workspace from raw bytes, so G0 and the runtime saw different source.
    A file containing invalid UTF-8 passed G0 as clean and then failed to
    compile, surfacing as a confusing G1 error on a file G0 had just called
    safe."""
    from aef.harness.candidate import inspect_candidate
    from aef.harness.gates.base import GateContext, GateOutcome
    from aef.harness.gates.g0_static_safety import G0StaticSafety
    from aef.harness.zones import ZonePolicy

    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "cand")
    (repo / "agents" / "g.py").write_bytes(b'MSG = "caf\xe9"\nRETRY = 4\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")

    git = GitRepo(root=repo)
    verdict = inspect_candidate(git, "main", "cand", ZonePolicy())
    result = G0StaticSafety().run(
        GateContext(
            repo=git,
            base_ref="main",
            head_ref="cand",
            verdict=verdict,
            workdir=tmp_path / "w",
            zone_policy=ZonePolicy(),
        )
    )

    raw = (repo / "agents" / "g.py").read_bytes()
    try:
        compile(raw, "x", "exec")
        compiles = True
    except SyntaxError:
        compiles = False

    assert not compiles, "the fixture must be a file CPython rejects"
    assert result.outcome is GateOutcome.FAIL, "G0 passed a file that cannot compile"
