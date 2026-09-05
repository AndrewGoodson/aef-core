"""Two gates, two workspaces (ADR 0170 defect 1).

Reproduced by running `G1` and `G2` in the real pipeline with the one
`GateContext.workdir` that `loop.gate()` gives them:

    G1 pass  1 build command(s) succeeded against the merged workspace
    G2 fail  gate raised TrustBoundaryError: scratch destination
             .../work/workspace must be empty. A gate that could not judge has
             not cleared this candidate.

Both gates named `ctx.workdir / "workspace"`, and
`trust._prepare_empty_destination` refuses a non-empty destination. So every
candidate that reached G2 without a precomputed cohort — which is EVERY
prompt candidate, since the cohort could not be built for one (ADR 0157
defects 1 and 2) — was rejected by a gate that never judged it. Seen and
misread as a red herring in ADR 0148.

The fix is a directory per gate, not a shared tree, and the second test is
why: G1 runs build commands in its copy, and those commands are configuration
executing candidate code.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from aef.harness.candidate import inspect_candidate
from aef.harness.corpus import Corpus, Scenario, Split
from aef.harness.gates.base import GateContext, run_pipeline
from aef.harness.gates.g1_builds import G1Builds
from aef.harness.gates.g2_outcome import G2OutcomeNonRegression
from aef.harness.git import GitRepo
from aef.state import AEFState

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
PERSONA = "agents/persona.md"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[GitRepo, str]:
    root = tmp_path / "repo"
    (root / "agents").mkdir(parents=True)
    (root / PERSONA).write_text("# Persona\n\nAnswer.\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@test")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "incumbent")
    _git(root, "checkout", "-qb", "loop/c1")
    (root / PERSONA).write_text("# Persona\n\nAnswer.\n\n## Lessons (aef)\n\n- <!-- x --> y\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "candidate")
    _git(root, "checkout", "-q", "main")
    return GitRepo(root=root), "loop/c1"


def _ctx(repo: GitRepo, head: str, workdir: Path) -> GateContext:
    return GateContext(
        repo=repo,
        base_ref="main",
        head_ref=head,
        verdict=inspect_candidate(repo, "main", head),
        workdir=workdir,
    )


def _corpus(tmp_path: Path) -> Corpus:
    return Corpus(
        root=tmp_path / "corpus",
        scenarios=(
            Scenario(
                id="s1",
                split=Split.TRAIN,
                graph_id="g",
                graph_version="1",
                initial_state=AEFState(run_id="s1", agent_id="a", objective="o"),
                trace=(),
                recorded_at=NOW,
            ),
        ),
    )


def test_g2_can_judge_after_g1_has_run_in_the_same_workdir(tmp_path: Path) -> None:
    """The reproduction, inverted. G2 may reach any verdict; what it may not
    do is fail to reach one because the scratch directory was occupied."""
    repo, head = _repo(tmp_path)
    result = run_pipeline(
        [
            G1Builds(commands=(("python", "-c", "pass"),)),
            # No `precomputed`: exactly what the driver leaves behind when the
            # cohort could not be built.
            G2OutcomeNonRegression(corpus=_corpus(tmp_path), entrypoint="agents.x:build"),
        ],
        _ctx(repo, head, tmp_path / "work"),
    )
    ran = {r.gate: r for r in result.results}
    assert "G2" in ran, "G2 never ran"
    assert "TrustBoundaryError" not in ran["G2"].reason, ran["G2"].reason


def test_g2_does_not_re_execute_in_the_tree_g1s_build_commands_wrote_to(
    tmp_path: Path,
) -> None:
    """Why the fix is a directory per gate rather than sharing G1's.

    A build command is repo configuration running candidate code, and
    whatever it writes lands in G1's copy. The emptiness rule exists so that
    a gate runs against base-ref + Zone A overlay and nothing else; reusing
    G1's tree would have quietly repealed it for G2.
    """
    repo, head = _repo(tmp_path)
    workdir = tmp_path / "work"
    run_pipeline(
        [
            G1Builds(commands=(("python", "-c", "open('artefact.txt','w').write('x')"),)),
            G2OutcomeNonRegression(corpus=_corpus(tmp_path), entrypoint="agents.x:build"),
        ],
        _ctx(repo, head, workdir),
    )
    trees = sorted(p.name for p in workdir.iterdir() if p.is_dir())
    assert trees == ["workspace-G1", "workspace-G2"], trees
    assert (workdir / "workspace-G1" / "artefact.txt").is_file(), "the build wrote nothing"
    assert not (workdir / "workspace-G2" / "artefact.txt").exists(), (
        "G2 re-executed the corpus in a tree a build command had written into"
    )
