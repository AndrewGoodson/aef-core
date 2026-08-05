"""The adoption sequence, executed as ONE sequence.

Defect #10 (G1's defaults assumed aef-core's own tree) lived in this path and
survived because adoption had only ever had a smoke-level pass. This test
performs the whole documented workflow against a real adopted repo, so an
instruction that stops working fails here rather than in someone's repo.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

AGENT = """from __future__ import annotations

from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, Plan, Provenance, StateDelta

RETRY_BUDGET = 3


def work_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    difficulty = int(state.working_memory.get("difficulty", 1))
    prov = Provenance(node_id=ctx.node_id, graph_version=ctx.graph_version,
                      ts=ctx.now, trace_id=ctx.trace_id, token_cost=difficulty)
    if difficulty <= RETRY_BUDGET:
        return StateDelta(plan=Plan(goal=state.objective, status="done"),
                          scores={"quality": 1.0}, provenance=[prov]), END
    return StateDelta(plan=Plan(goal=state.objective, status="failed"),
                      errors=[{"node_id": ctx.node_id, "error": "too hard"}],
                      scores={"quality": 0.0}, provenance=[prov]), END


def build_graph() -> Graph:
    n = Node(id="work", version="0.1.0", fn=work_node, deterministic=True)
    return Graph(id="mine", version="0.1.0", nodes={"work": n}, edges=[], entry_node="work")
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _aef(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aef.cli.main", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


@pytest.fixture
def adopted(tmp_path: Path) -> tuple[Path, Path]:
    """A real repo that has run `aef adopt`, plus a state dir outside it."""
    repo = tmp_path / "adoptee"
    repo.mkdir()
    (repo / "README.md").write_text("# mine\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    from aef.cli.adopt import run_adopt

    run_adopt(repo)

    (repo / "agents" / "mine").mkdir(parents=True, exist_ok=True)
    (repo / "agents" / "__init__.py").write_text("")
    (repo / "agents" / "mine" / "__init__.py").write_text("")
    (repo / "agents" / "mine" / "graph.py").write_text(AGENT)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_smoke.py").write_text(
        "def test_builds() -> None:\n"
        "    from agents.mine.graph import build_graph\n"
        "    assert build_graph().id == 'mine'\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted")
    return repo, tmp_path / "loop-state"


@pytest.mark.slow
def test_the_documented_adoption_sequence_runs_clean(adopted: tuple[Path, Path]) -> None:
    repo, state = adopted

    status = _aef(repo, "loop", "status", "--repo", ".", "--state", str(state))
    assert status.returncode == 0, status.stderr
    assert "chain verified" in status.stdout

    # A FAILING run — the corpus needs failures, and until --working-memory
    # existed there was no way to produce one from the CLI.
    run = _aef(
        repo,
        "run",
        "agents.mine.graph",
        "--objective",
        "hard",
        "--working-memory",
        json.dumps({"difficulty": 9}),
        "--record-runs",
        str(state / "runs"),
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["plan"]["status"] == "failed"

    harvest = _aef(
        repo,
        "loop",
        "harvest",
        "agents.mine.graph",
        "--repo",
        ".",
        "--state",
        str(state),
        "--runs",
        str(state / "runs"),
        "--corpus",
        "corpus",
    )
    assert harvest.returncode == 0, harvest.stderr
    assert "promoted 1 run(s)" in harvest.stdout
    assert list((repo / "corpus" / "train").glob("*.json")), "the corpus did not grow"

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "corpus")

    cycle = _aef(
        repo,
        "loop",
        "cycle",
        "--repo",
        ".",
        "--state",
        str(state),
        "--workdir",
        str(state / "work"),
        "--module",
        "agents.mine.graph",
        "--corpus",
        "corpus",
        "--memory",
        str(state / "memory.jsonl"),
        "--build-command",
        "python -m pytest -q",
    )
    assert cycle.returncode in (0, 1), cycle.stderr  # 2 would mean halted
    assert "ledger verified" in cycle.stdout

    monitor = _aef(repo, "loop", "monitor", "--repo", ".", "--state", str(state))
    assert monitor.returncode == 0, monitor.stderr

    digest = _aef(
        repo,
        "loop",
        "digest",
        "--repo",
        ".",
        "--state",
        str(state),
        "--runs",
        str(state / "runs"),
    )
    assert digest.returncode == 0, digest.stderr
    assert "Production runs recorded: 1" in digest.stdout
    # The loop must nag about an unconfigured halt channel, every run.
    assert "No halt channel is configured" in digest.stdout


def test_loop_md_documents_every_obligation(adopted: tuple[Path, Path]) -> None:
    """Each was discovered by RUNNING the sequence and finding it stuck."""
    repo, _ = adopted
    text = (repo / "LOOP.md").read_text()

    for obligation in (
        "A corpus",
        "reflect node",
        "Observations",
        "Halt notification",
        "blessed baseline",
    ):
        assert obligation in text, f"LOOP.md does not mention: {obligation}"
    # The trap that catches everyone once.
    assert "Adding an `Edge` to it is not enough" in text
    # The flag without which no failing run can be produced.
    assert "--working-memory" in text
