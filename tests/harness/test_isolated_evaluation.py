"""The candidate cannot report on itself, because it is not asked to.

Three controls were added to stop a candidate authoring the evidence that
judged it, and three were defeated (ADR 0085, 0088, 0093). Each tried to make
an in-process channel trustworthy. None could: the candidate's code and the
reporting code shared an interpreter, so any channel the reporter could
write, the candidate could write.

So the reporting moved out. The candidate answers one node at a time in a
worker that never learns what a scenario is, how many there are, or what an
`Outcome` is. The parent owns the state, the routing, the step count, the
trace and the classification (ADR 0094).

What a candidate can still do is return a lying `StateDelta` — the node
contract, which is exactly the surface the corpus and the MUST_FAIL tripwires
are built to judge. `test_a_lie_through_the_node_contract_is_still_possible`
pins that as a deliberate boundary rather than an oversight.
"""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.corpus import Scenario, Split
from aef.harness.isolated import IsolationError, NodeWorkerSession, graph_from
from aef.harness.isolated_suite import run_corpus_isolated
from aef.kernel import END, Graph, GraphExecutor, Node
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

REPO_ROOT = Path(__file__).resolve().parents[2]

FORGED = (
    '{"s0": {"outcome": {"terminated": true, "plan_status": "done", "error_count": 0, '
    '"policy_denials": 0, "node_path": ["do"]}, "score": 1.0}}'
)

BROKEN = """
from aef.kernel import END, Graph, Node
from aef.state import Plan, StateDelta


def do(state, ctx, services):
    raise RuntimeError("this agent is broken")


def build_graph():
    return Graph(
        id="g", version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[], entry_node="do",
    )
"""

HONEST = BROKEN.replace(
    '    raise RuntimeError("this agent is broken")',
    '    return StateDelta(plan=Plan(goal=state.objective, status="done"), '
    'scores={"quality": 1.0}), END',
)


def _passing(state, ctx, services):  # type: ignore[no-untyped-def]
    return (
        StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
        END,
    )


@pytest.fixture
def corpus() -> tuple[Path, list[Scenario]]:
    """Three honestly-recorded scenarios the candidate is asked to reproduce."""
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
    scenarios = []
    for i in range(3):
        state = AEFState(run_id=f"s{i}", agent_id="a", objective=f"o{i}")
        recorded = GraphExecutor(graph.compile(), agent_services()).run(state, record_trace=True)
        scenarios.append(
            Scenario(
                id=f"s{i}",
                split=Split.VALIDATION,
                graph_id="g",
                graph_version="1",
                initial_state=state,
                trace=recorded.trace,
                recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
            )
        )
    return ws, scenarios


def _score(corpus: tuple[Path, list[Scenario]], source: str) -> tuple[int, int]:
    ws, scenarios = corpus
    (ws / "agents" / "graph.py").write_text(source)
    results = run_corpus_isolated(ws, scenarios, entrypoint="agents.graph:build_graph")
    return sum(1 for r in results.values() if r.outcome.passed), len(results)


def test_an_honest_agent_passes(corpus) -> None:  # type: ignore[no-untyped-def]
    """The control. Every refusal below is worthless if the honest path also
    fails."""
    assert _score(corpus, HONEST) == (3, 3)


def test_a_broken_agent_fails(corpus) -> None:  # type: ignore[no-untyped-def]
    assert _score(corpus, BROKEN) == (0, 3)


@pytest.mark.parametrize(
    ("name", "source"),
    [
        (
            "print a forged aggregate",
            BROKEN.replace("def build_graph():", f"def build_graph():\n    print({FORGED!r})"),
        ),
        (
            "print then SystemExit(0)",
            BROKEN.replace(
                "def build_graph():",
                f"def build_graph():\n    print({FORGED!r})\n    raise SystemExit(0)",
            ),
        ),
        (
            # The ADR 0093 attack: reach `os` through an allowlisted package
            # by string, write to the real fd 1, and exit before the harness
            # can. G0 cannot see it, and it no longer matters.
            "getattr -> os._exit (ADR 0093)",
            "from aef.kernel import durability as _d\n"
            '_o = getattr(_d, "os")\n'
            f"_o.write(1, ({FORGED!r} + chr(10)).encode())\n"
            'getattr(_o, "_exit")(0)\n' + BROKEN,
        ),
    ],
)
def test_no_forgery_produces_a_passing_scenario(corpus, name, source) -> None:  # type: ignore[no-untyped-def]
    passed, total = _score(corpus, source)
    assert total == 3, "the parent decides how many scenarios there are"
    assert passed == 0, f"{name} produced a passing scenario"


def test_the_adr_0093_attack_is_still_invisible_to_g0() -> None:
    """Stated so the boundary is not mistaken for a static-analysis win. G0
    still cannot see `getattr(module, "os")`, and ADR 0093 declined to keep
    patching the denylist. The attack fails because the evidence moved, not
    because the scanner improved."""
    from aef.harness.gates.g0_static_safety import DEFAULT_IMPORT_ALLOWLIST, scan_source

    source = (
        'from aef.kernel import durability as _d\n_o = getattr(_d, "os")\ngetattr(_o, "_exit")(0)\n'
    )
    assert not scan_source("agents/graph.py", source, DEFAULT_IMPORT_ALLOWLIST)


def test_killing_the_worker_mid_corpus_buys_nothing(corpus) -> None:  # type: ignore[no-untyped-def]
    """`os._exit` after the first scenario. The one it genuinely ran counts;
    the rest are recorded as unrun, because a run that stopped is not a run
    that passed."""
    source = HONEST.replace(
        "def do(state, ctx, services):",
        "CALLS = [0]\n"
        "def do(state, ctx, services):\n"
        "    CALLS[0] += 1\n"
        "    if CALLS[0] > 1:\n"
        "        from aef.kernel import durability as _d\n"
        '        getattr(getattr(_d, "os"), "_exit")(0)',
    )
    passed, total = _score(corpus, source)
    assert total == 3
    assert passed == 1, "dying mid-corpus must not pass the scenarios it never ran"


def test_a_lie_through_the_node_contract_is_still_possible(corpus) -> None:
    """The deliberate boundary, pinned so it is not mistaken for a gap.

    A node that returns `plan=done` for a task it cannot do is lying — and
    that is the surface the corpus and the MUST_FAIL tripwires judge (ADR
    0060). Isolation was never meant to stop it; it stops the candidate
    bypassing the judgement altogether.
    """
    assert _score(corpus, HONEST) == (3, 3)


def test_the_worker_never_learns_what_a_scenario_is() -> None:
    """Structural, not incidental. If the worker could see scenario ids or
    outcomes, the reporting would have moved back in with the candidate."""
    import ast

    source = (REPO_ROOT / "aef" / "harness" / "node_worker.py").read_text()
    tree = ast.parse(source)

    # CODE, not prose. The module docstring names these while explaining that
    # the worker cannot see them, and a substring check cannot tell the
    # difference — the third time in this program a test has needed that
    # distinction drawn.
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for imported in ast.walk(tree):
        if isinstance(imported, ast.ImportFrom):
            referenced.update(alias.name for alias in imported.names)

    for leaked in ("Scenario", "Outcome", "classify", "score_of", "RuleBasedEvaluator"):
        assert leaked not in referenced, f"the worker can see {leaked!r}"


def test_a_graph_that_cannot_be_built_fails_every_scenario(corpus) -> None:  # type: ignore[no-untyped-def]
    ws, scenarios = corpus
    (ws / "agents" / "graph.py").write_text("raise RuntimeError('cannot build')\n")
    results = run_corpus_isolated(ws, scenarios, entrypoint="agents.graph:build_graph")
    assert len(results) == 3
    assert all(not r.outcome.passed and r.failure for r in results.values())


def test_the_session_reports_a_worker_that_will_not_start() -> None:
    ws = Path(tempfile.mkdtemp())
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(ws)}
    with pytest.raises(IsolationError):
        NodeWorkerSession("nonexistent.module:build_graph", workdir=ws, env=env, timeout_s=10)


def test_the_parent_rebuilds_the_graph_and_records_its_own_trace(corpus) -> None:  # type: ignore[no-untyped-def]
    """The trace the gates read is the parent's observation, not the
    candidate's account of itself."""
    ws, _ = corpus
    (ws / "agents" / "graph.py").write_text(HONEST)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "PYTHONPATH": f"{ws}:{REPO_ROOT}",
    }
    with NodeWorkerSession(
        "agents.graph:build_graph", workdir=ws, env=env, timeout_s=30
    ) as session:
        graph = graph_from(session)
        assert graph.id == "g"
        result = GraphExecutor(graph.compile(), agent_services()).run(
            AEFState(run_id="s0", agent_id="a", objective="o"), record_trace=True
        )
        assert result.trace is not None
        assert [r.node_id for r in result.trace] == ["do"]
