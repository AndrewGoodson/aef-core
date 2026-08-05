"""The candidate wrote the evidence that judged it.

`run_variant` executed the candidate's graph in a subprocess and did
`json.loads(result.stdout)`. The candidate's own code runs in that
subprocess. Two added lines — print a forged payload, `raise SystemExit(0)` —
scored a broken agent 1.0 instead of 0.0 and **passed all six gates**
(ADR 0085).

`SystemExit` is a `BaseException`, so it sailed through `load_graph`'s
`except Exception` and exited the process cleanly with the forgery as its
entire stdout. The real agent never ran.

This is strictly stronger than ADR 0060's reward hack. There the agent ran
and lied about its plan status, so the corpus was still a real observation.
Here the candidate authors the observation — which defeats ADR 0060's own
stated escape hatch, since a MUST_FAIL tripwire is compared against the
forged `Outcome` too.
"""

import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.corpus import Scenario, Split
from aef.harness.gates.g0_static_safety import DEFAULT_IMPORT_ALLOWLIST, scan_source
from aef.harness.scenario_runner import result_marker
from aef.harness.suite import SuiteError, _parse
from aef.harness.trace_codec import dumps
from aef.kernel import END, Graph, GraphExecutor, Node, Services
from aef.state import AEFState, Plan, StateDelta

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


@pytest.fixture(scope="module")
def workspace() -> Path:
    """A workspace holding one honestly-recorded scenario the candidate is
    then asked to reproduce."""
    ws = Path(tempfile.mkdtemp())
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")

    graph = Graph(
        id="g",
        version="1",
        nodes={"do": Node(id="do", version="1", fn=_passing, deterministic=True)},
        edges=[],
        entry_node="do",
    )
    state = AEFState(run_id="r", agent_id="a", objective="o")
    recorded = GraphExecutor(graph.compile(), Services()).run(state, record_trace=True)
    scenario = Scenario(
        id="s1",
        split=Split.VALIDATION,
        graph_id="g",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    (ws / "_scenarios.json").write_text(dumps([scenario.to_payload()]))
    return ws


def _run(workspace: Path, source: str) -> str:
    (workspace / "agents" / "graph.py").write_text(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aef.harness.scenario_runner",
            str(workspace / "_scenarios.json"),
            "agents.graph:build_graph",
            NONCE,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": f"{workspace}:{REPO_ROOT}", "PATH": "/usr/bin:/bin"},
    )
    return result.stdout


def test_the_honest_broken_agent_scores_zero(workspace: Path) -> None:
    """The control. Without it, every assertion below could be passing
    because the harness scores everything 0."""
    run = _parse("honest", _run(workspace, BROKEN_AGENT), NONCE)
    assert run.scores.per_scenario["s1"] == 0.0


def test_print_then_system_exit_is_refused(workspace: Path) -> None:
    """The original attack, verbatim. `SystemExit` is a BaseException, so
    agent-authored code decided the process was finished."""
    source = BROKEN_AGENT.replace(
        "def build_graph():",
        f"def build_graph():\n    print({FORGED!r})\n    raise SystemExit(0)",
    )
    with pytest.raises(SuiteError, match="produced no runner result"):
        _parse("forged", _run(workspace, source), NONCE)


def test_printing_a_payload_does_not_make_it_the_result(workspace: Path) -> None:
    """The runner's output is framed; anything printed before it is the
    candidate's output, not evidence."""
    run = _parse("noisy", _run(workspace, f"print({FORGED!r})\n" + BROKEN_AGENT), NONCE)
    assert run.scores.per_scenario["s1"] == 0.0


def test_forging_the_marker_is_reported_as_a_security_event(workspace: Path) -> None:
    """The nonce is in argv, so a candidate CAN print a valid-looking marker.
    Counting is what makes that visible: the runner writes exactly one, so a
    forgery makes two, and two is not one."""
    forge = (
        "import sys as _s\n"
        "_s.stdout.write('\\x00AEF-SCENARIO-RESULT:' + _s.argv[3] + '\\x00' + "
        f"{FORGED!r})\n"
        "_s.stdout.flush()\n"
    )
    with pytest.raises(SuiteError, match="forging the evidence"):
        _parse("double", _run(workspace, forge + BROKEN_AGENT), NONCE)


def test_suppressing_the_runners_marker_requires_an_import_g0_rejects(workspace: Path) -> None:
    """The one variant the parse layer cannot catch: forge the marker AND
    stop the runner writing its own, which needs `os._exit` — uncatchable by
    any handler.

    It is stopped by the layer below instead. This test pins BOTH halves,
    because a defence that rests on the attacker not thinking of something is
    not a defence, and because the parse layer's limit should be written
    down rather than assumed away.
    """
    source = (
        "import sys as _s\n"
        "_s.stdout.write('\\x00AEF-SCENARIO-RESULT:' + _s.argv[3] + '\\x00' + "
        f"{FORGED!r})\n"
        "_s.stdout.flush()\n"
        "import os as _o\n_o._exit(0)\n" + BROKEN_AGENT
    )
    # The parse layer sees exactly one marker and cannot tell it is forged.
    assert _parse("exited", _run(workspace, source), NONCE).scores.per_scenario["s1"] == 1.0
    # G0 rejects it, and G0 runs before any candidate code executes.
    assert scan_source("agents/graph.py", source, DEFAULT_IMPORT_ALLOWLIST)


def test_the_marker_carries_a_per_run_nonce() -> None:
    assert result_marker("abc") != result_marker("def")
    assert "abc" in result_marker("abc")


# --------------------------------------------------------------------------
# The ordering that makes G0 a control rather than a report
# --------------------------------------------------------------------------


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
