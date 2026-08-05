"""The candidate wrote the evidence that judged it — and now cannot.

`run_variant` did `json.loads(result.stdout)` on a subprocess the candidate's
own code runs in. Two added lines — print a forged payload, `raise
SystemExit(0)` — scored a broken agent 1.0 and passed all six gates
(ADR 0085).

Three attempts to secure that channel were each defeated (ADR 0085, 0088,
0093), because the candidate's code and the reporting code shared an
interpreter. The channel is gone: the candidate now answers one node at a
time in a worker that never learns what a scenario is, and the parent
concludes (ADR 0094). Those tests live in `test_isolated_evaluation.py`.

What remains here is the static half — G0's import and attribute rules, and
the ordering that keeps a rejected candidate from executing at all — plus the
pipeline's handling of a gate that raises.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.gates.g0_static_safety import DEFAULT_IMPORT_ALLOWLIST, scan_source
from aef.kernel import END
from aef.state import Plan, StateDelta

REPO_ROOT = Path(__file__).resolve().parents[2]
NONCE = "deadbeefcafe0123"

FORGED = (
    '{"s1": {"outcome": {"terminated": true, "plan_status": "done", "error_count": 0, '
    '"policy_denials": 0, "node_path": ["do"]}, "score": 1.0, "cost_tokens": 0}}'
)

BROKEN_AGENT = """
from aef.kernel import Graph, Node


def do(state, ctx, services):
    raise RuntimeError("this agent is broken")


def build_graph():
    return Graph(
        id="g", version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[], entry_node="do",
    )
"""


def _passing(state, ctx, services):  # type: ignore[no-untyped-def]
    return (
        StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
        END,
    )


def test_the_cheap_gates_run_before_any_candidate_code_executes(tmp_path: Path) -> None:
    """Building evidence EXECUTES the candidate — N+2 corpus passes in
    subprocesses — and it used to happen before `run_pipeline` ran anything.
    So G0's import allowlist, the control that exists for exactly this, ran
    SECOND: a candidate G0 would reject for `import socket` had already run
    its module-level code.

    `gates/base.py` states the opposite ordering as the design. It was not
    true (ADR 0085).
    """
    import subprocess as sp

    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths, gate

    repo = tmp_path / "repo"
    (repo / "agents" / "demo").mkdir(parents=True)
    marker = tmp_path / "CANDIDATE_CODE_RAN"

    def git(*args: str) -> None:
        sp.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    sp.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, capture_output=True)
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY = 3\n")
    git("add", "-A")
    git("commit", "-qm", "init")

    git("checkout", "-q", "-b", "hostile")
    (repo / "agents" / "demo" / "graph.py").write_text(
        f"import os\nopen({str(marker)!r}, 'w').write('ran')\nRETRY = 4\n"
    )
    git("commit", "-qam", "hostile")
    git("checkout", "-q", "main")

    config = LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state"),
        build_commands=(("python", "-c", "pass"),),
    )
    assert not marker.exists()
    run = gate(config, "hostile", now=datetime(2026, 3, 1, tzinfo=UTC), workdir=tmp_path / "w")

    assert not marker.exists(), "the rejected candidate's module-level code executed"
    assert run.result.ran == ("G0",), f"gates ran: {run.result.ran}"


# --------------------------------------------------------------------------
# ADR 0088 — the claim ADR 0085 made, and why it was false
# --------------------------------------------------------------------------


_HIJACK = (
    "from aef.harness import scenario_runner as _m\n"
    "_m.sys.__stdout__.write(_m.result_marker(_m.sys.argv[3]) + '{}')\n"
    "_m.sys.stdout = _m.sys.stderr\n"
)


def test_the_marker_hijack_is_rejected_by_g0() -> None:
    """ADR 0085 claimed: "the only way to emit exactly one forged marker is
    to stop the runner emitting its own, which needs os._exit, which needs an
    import G0 rejects."

    That was FALSE. `aef` is on the allowlist — a Zone A graph legitimately
    needs `aef.kernel` — and root-module matching let a candidate import
    `aef.harness.scenario_runner`, read the per-run nonce out of its
    `sys.argv`, write a forged result to `sys.__stdout__`, and point the
    runner's own `sys.stdout` at stderr. Three lines, zero G0 findings, all
    six gates passing on a broken agent.

    The counting defence and the G0 defence were not independent, as the ADR
    asserted. They shared the assumption that `sys` was unreachable.
    """

    assert scan_source("agents/graph.py", _HIJACK, DEFAULT_IMPORT_ALLOWLIST)


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("import aef.harness", "import aef.harness.suite\n"),
        ("from aef.cli", "from aef.cli.loop import _config\n"),
        ("shadow __main__", "from aef.harness import scenario_runner as _m\n_m.sys.modules\n"),
        ("os via a module object", "from aef.kernel import durability as _d\n_ = _d.os\n"),
        ("sys via a module object", "from aef.kernel import executor as _e\n_e.sys.argv\n"),
    ],
)
def test_reaching_the_interpreter_through_an_allowlisted_package_is_rejected(
    name: str, source: str
) -> None:
    """A module object is shared process-wide, so importing anything hands
    agent code every module THAT module imported. `aef.kernel.durability`
    imports `os`, so `durability.os` reaches the filesystem without `os` ever
    appearing in an import statement."""

    assert scan_source("agents/graph.py", source, DEFAULT_IMPORT_ALLOWLIST), name


@pytest.mark.parametrize(
    ("name", "source"),
    [
        (
            "kernel types",
            "from aef.kernel import END, Graph, Node\nfrom aef.state import StateDelta\n",
        ),
        ("reflect node", "from aef.reasoning.nodes import make_reflect_node\n"),
        ("the policy engine", "from aef.security.tool import Tool\n"),
    ],
)
def test_the_imports_a_zone_a_graph_actually_needs_still_pass(name: str, source: str) -> None:
    """The denial must not take the package the agent is built from. A rule
    that rejects the reference agent is not a rule anyone can adopt."""

    assert not scan_source("agents/graph.py", source, DEFAULT_IMPORT_ALLOWLIST), name


def test_this_repos_own_demo_agent_still_passes_g0() -> None:
    """The strongest control available: the agent every gate test runs
    against."""

    source = (REPO_ROOT / "agents" / "demo" / "graph.py").read_text()
    assert not scan_source("agents/demo/graph.py", source, DEFAULT_IMPORT_ALLOWLIST)


# --------------------------------------------------------------------------
# ADR 0090 — a gate that raises, and a marker that is almost right
# --------------------------------------------------------------------------


def test_a_gate_that_raises_fails_instead_of_escaping() -> None:
    """A raising gate escaped `run_pipeline`, out of `gate()`, out of
    `cmd_gate`, and out of the process — so the candidate got no verdict and
    the ledger got no GATED entry at all. A hole in a tamper-evident audit
    trail, and candidate-triggerable: a graph whose factory fails to load
    reaches it (ADR 0090)."""
    from dataclasses import dataclass

    from aef.harness.candidate import CandidateDiff, CandidateVerdict
    from aef.harness.gates.base import Gate, GateContext, GateOutcome, run_pipeline
    from aef.harness.git import GitRepo
    from aef.harness.zones import ZonePolicy, ZoneVerdict

    @dataclass(frozen=True)
    class Exploding(Gate):
        id: str = "G2"

        def run(self, ctx: GateContext) -> object:
            raise RuntimeError("the gate could not judge")

    ctx = GateContext(
        repo=GitRepo(root=Path("/nowhere")),
        base_ref="main",
        head_ref="cand",
        verdict=CandidateVerdict(
            diff=CandidateDiff(
                base_ref="main", head_ref="cand", base_sha="a" * 40, head_sha="b" * 40, entries=()
            ),
            zones=ZoneVerdict(verdicts=()),
            mode_violations=(),
        ),
        workdir=Path("/tmp/w"),
        zone_policy=ZonePolicy(),
    )

    result = run_pipeline([Exploding()], ctx)  # type: ignore[list-item]
    assert result.results[0].outcome is GateOutcome.FAIL
    assert "RuntimeError" in result.results[0].reason, "the operator must see WHICH failure"
    assert not result.passed


def test_a_keyboard_interrupt_still_stops_the_run() -> None:
    """`Exception`, not `BaseException`. Swallowing an interrupt would make
    the loop hard to stop, which is what `KillSwitch` exists to avoid."""
    from dataclasses import dataclass

    from aef.harness.candidate import CandidateDiff, CandidateVerdict
    from aef.harness.gates.base import Gate, GateContext, run_pipeline
    from aef.harness.git import GitRepo
    from aef.harness.zones import ZonePolicy, ZoneVerdict

    @dataclass(frozen=True)
    class Interrupted(Gate):
        id: str = "G0"

        def run(self, ctx: GateContext) -> object:
            raise KeyboardInterrupt

    ctx = GateContext(
        repo=GitRepo(root=Path("/nowhere")),
        base_ref="main",
        head_ref="cand",
        verdict=CandidateVerdict(
            diff=CandidateDiff(
                base_ref="main", head_ref="cand", base_sha="a" * 40, head_sha="b" * 40, entries=()
            ),
            zones=ZoneVerdict(verdicts=()),
            mode_violations=(),
        ),
        workdir=Path("/tmp/w"),
        zone_policy=ZonePolicy(),
    )
    with pytest.raises(KeyboardInterrupt):
        run_pipeline([Interrupted()], ctx)  # type: ignore[list-item]
