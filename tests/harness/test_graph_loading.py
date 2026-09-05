"""One loader, every call site (ADR 0177 R1), and one unusable check is one
zero (ADR 0177 R5b).

Both defects were reproduced by running commands before anything changed.

R1, on the repo `aef migrate --dir . --agent-root .claude/agents` produces —
which is ADR 0152 §4's documented opt-in and the only way a persona becomes
Zone A:

    $ aef loop score '.claude/agents/migrated/reviewer/graph.py:build_graph' \\
        --corpus corpus --splits train --config aef.yaml
    error: the 'package' argument is required to perform a relative import
    for '.claude/agents/migrated/reviewer/graph.py'
    EXIT=1

Exit 1 is `EXIT_REJECTED`. ADR 0168 §M4 taught `aef/cli/run.py` that an
entrypoint may be a file path and taught **one** of three loaders;
`scenario_runner` and `node_worker` kept their own `importlib.import_module`.
Through `aef loop cycle` that asymmetry is worse than a refusal, because G2's
two sides used different loaders — the incumbent reconstructed from a
recording `aef loop record` could load, the candidate run through the worker
that could not:

    G2 outcome : fail
    G2 reason  : 1 previously-passing scenario(s) no longer pass (zero tolerance)

with the worker's actual complaint — `IsolationError: ... cannot import ...:
TypeError: the 'package' argument is required ...` — dropped on the floor at
`g2_outcome.py`'s `return {sid: r.outcome ...}`.

R5b, on a two-scenario corpus whose first summary is 12,000 characters:

    $ aef loop score agents.summary.graph:build_graph --corpus <scratch> --splits train
    error: refusing to run regex check '(?i)(not (have been )?overloaded|...)'
    against 12000 characters: ...
    EXIT=1

`score_scenario` sat OUTSIDE the try/except in BOTH scoring paths, so one
scenario's raise killed the suite and the second scenario — which scores
fine — never ran.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.checks import CatastrophicPatternError, TaskCheck
from aef.harness.corpus import Scenario, Split
from aef.harness.graph_loading import (
    DEFAULT_GRAPH_FACTORY,
    import_graph_module,
    looks_like_a_path,
    split_entrypoint,
)
from aef.harness.isolated_suite import run_corpus_isolated
from aef.harness.scenario_runner import EntrypointError, load_graph, run_scenario
from aef.kernel import END, Graph, GraphExecutor, Node
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

REPO_ROOT = Path(__file__).resolve().parents[2]

# What `aef migrate --agent-root .claude/agents` writes, reduced to the part
# that matters here: a `build_graph()` at a path with no dotted spelling.
GRAPH_SOURCE = """
from aef.kernel import END, Graph, Node
from aef.state import Plan, StateDelta


def do(state, ctx, services):
    return (
        StateDelta(
            plan=Plan(goal=state.objective, status="done"),
            working_memory={"answer": "42"},
            scores={"quality": 1.0},
        ),
        END,
    )


def build_graph():
    return Graph(
        id="reviewer", version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[], entry_node="do",
    )
"""

WIDENED = Path(".claude") / "agents" / "migrated" / "reviewer" / "graph.py"


@pytest.fixture
def widened_repo() -> Path:
    """A tree shaped like ADR 0152 §4's opt-in: the graph under `.claude/`,
    where no dotted module name can reach it."""
    root = Path(tempfile.mkdtemp(prefix="j1-widened-"))
    target = root / WIDENED
    target.parent.mkdir(parents=True)
    target.write_text(GRAPH_SOURCE)
    return root


# ---------------------------------------------------------------------------
# There is ONE loader, and every graph-loading call site uses it
# ---------------------------------------------------------------------------


def test_the_cli_re_exports_the_harness_loader_rather_than_defining_one() -> None:
    """The seam, asserted on identity rather than on behaviour. Two loaders
    that agree today are ADR 0091's drift shape; one object cannot drift from
    itself. The harness may not import the CLI, so the CLI imports the
    harness."""
    from aef.cli import run as cli_run

    assert cli_run.import_graph_module is import_graph_module
    assert cli_run.looks_like_a_path is looks_like_a_path


def test_no_graph_loading_call_site_still_calls_import_module_directly() -> None:
    """The `grep` that found the defect, as a test. `aef/config/domain_gates.py`
    imports an EVALUATOR module, not a graph, and is deliberately not in
    scope."""
    import ast

    offenders = []
    for path in sorted((REPO_ROOT / "aef").rglob("*.py")):
        if path.name in {"graph_loading.py", "domain_gates.py"}:
            continue
        # An AST scan, not a `grep`: three of these files now DISCUSS
        # `importlib.import_module` in a comment explaining why they no longer
        # call it, and a text scan would count the explanation as the defect.
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "import_module"
                or isinstance(func, ast.Name)
                and func.id == "import_module"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], f"a second graph loader reappeared in {offenders}"


@pytest.mark.parametrize(
    ("entrypoint", "expected"),
    [
        ("pkg.mod:build_graph", ("pkg.mod", "build_graph")),
        ("a/b/graph.py:build_graph", ("a/b/graph.py", "build_graph")),
        (r"C:\x\graph.py:build_graph", (r"C:\x\graph.py", "build_graph")),
    ],
)
def test_an_entrypoint_splits_on_the_last_colon(entrypoint: str, expected: tuple[str, str]) -> None:
    """A Windows drive letter is not the separator, and a path form has to
    survive the split or the file case is unreachable."""
    assert split_entrypoint(entrypoint) == expected


@pytest.mark.parametrize("entrypoint", [":build_graph", "mod:"])
def test_a_half_written_entrypoint_is_refused(entrypoint: str) -> None:
    """`no_colon_here` used to be on this list and was moved out DELIBERATELY
    (ADR 0182): a reference with no colon is now a dotted module whose factory
    defaults to `build_graph`, which is what made `--entrypoint` accept the
    same three forms as `--module`. A colon with nothing on one side of it is
    still half-written and still refused by name."""
    with pytest.raises(ValueError):
        split_entrypoint(entrypoint)


@pytest.mark.parametrize(
    ("entrypoint", "expected"),
    [
        ("pkg.mod", ("pkg.mod", DEFAULT_GRAPH_FACTORY)),
        ("a/b/graph.py", ("a/b/graph.py", DEFAULT_GRAPH_FACTORY)),
        (r"C:\x\graph.py", (r"C:\x\graph.py", DEFAULT_GRAPH_FACTORY)),
        ("pkg.mod:make", ("pkg.mod", "make")),
    ],
)
def test_a_reference_with_no_factory_takes_the_default_one(
    entrypoint: str, expected: tuple[str, str]
) -> None:
    """The third and fourth forms `--entrypoint` refused until ADR 0182, and
    the reason `aef loop cycle --module agents/x/graph.py --entrypoint
    agents/x/graph.py` accepted the first and refused the second."""
    assert split_entrypoint(entrypoint) == expected


# ---------------------------------------------------------------------------
# R1 — the in-process runner (`aef loop score`)
# ---------------------------------------------------------------------------


def test_scenario_runner_loads_a_graph_under_a_widened_agent_root(
    widened_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduction, inverted. `load_graph` called
    `importlib.import_module` and this raised `TypeError: the 'package'
    argument is required to perform a relative import` — out of the gate, out
    of `cmd_score`, exit 1."""
    monkeypatch.chdir(widened_repo)
    graph = load_graph(f"{WIDENED.as_posix()}:build_graph")
    assert isinstance(graph, Graph)
    assert graph.id == "reviewer"


def test_a_dotted_entrypoint_still_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: the file form must not cost the dotted one."""
    monkeypatch.chdir(REPO_ROOT)
    assert load_graph("agents.summary.graph:build_graph").id == "summary_agent"


def test_a_missing_file_entrypoint_is_an_entrypoint_error_not_a_typeerror(
    widened_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TypeError` used to escape `load_graph` entirely — it caught
    `ImportError` only, and `importlib.import_module` raises `TypeError` for a
    leading dot. Every failure to load an entrypoint is an `EntrypointError`
    now, and it names the entrypoint."""
    monkeypatch.chdir(widened_repo)
    with pytest.raises(EntrypointError) as excinfo:
        load_graph(".claude/agents/migrated/nope/graph.py:build_graph")
    assert ".claude/agents/migrated/nope/graph.py:build_graph" in str(excinfo.value)


# ---------------------------------------------------------------------------
# R1 — the worker (the CANDIDATE side of G2)
# ---------------------------------------------------------------------------


def test_the_node_worker_loads_a_graph_under_a_widened_agent_root(
    widened_repo: Path,
) -> None:
    """Run as a real subprocess through `run_corpus_isolated`, because the
    worker is a process and the defect only exists when it is one."""
    state = AEFState(run_id="s0", agent_id="a", objective="o")
    recorded = GraphExecutor(
        load_graph(f"{(widened_repo / WIDENED).as_posix()}:build_graph").compile(),
        agent_services(),
    ).run(state, record_trace=True)
    scenario = Scenario(
        id="s0",
        split=Split.TRAIN,
        graph_id="reviewer",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    results = run_corpus_isolated(
        widened_repo, [scenario], entrypoint=f"{WIDENED.as_posix()}:build_graph"
    )
    assert results["s0"].failure is None, results["s0"].failure
    assert results["s0"].outcome.passed


def test_the_worker_names_the_entrypoint_when_it_cannot_import(widened_repo: Path) -> None:
    """(b): `TypeError` alongside `ImportError`, and the ENTRYPOINT in the
    message. The parent reports this string and "cannot import '.claude/...'"
    without the entrypoint does not say which candidate could not be loaded."""
    state = AEFState(run_id="s0", agent_id="a", objective="o")
    scenario = Scenario(
        id="s0",
        split=Split.TRAIN,
        graph_id="reviewer",
        graph_version="1",
        initial_state=state,
        trace=(),
        recorded_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    bad = ".claude/agents/migrated/absent/graph.py:build_graph"
    results = run_corpus_isolated(widened_repo, [scenario], entrypoint=bad)
    failure = results["s0"].failure or ""
    assert "cannot import" in failure

    # And the worker's OWN message, asserted directly. Asserting only on the
    # string above is not enough and the mutation pass proved it: `IsolationError`
    # wraps the failure in "worker for '<entrypoint>' failed", so deleting the
    # entrypoint from `load_graph`'s message left the assertion passing. This is
    # the message a caller that is not the session sees.
    from aef.harness import node_worker

    with pytest.raises(node_worker.WorkerError) as excinfo:
        node_worker.load_graph(bad)
    assert bad in str(excinfo.value)
    assert "cannot import" in str(excinfo.value)


def test_both_sides_of_g2_resolve_a_widened_root_entrypoint_identically(
    widened_repo: Path,
) -> None:
    """R1's tail. The asymmetry is what turned an import error into a
    "regression": `recorded_outcome` is derived from a recording `aef loop
    record` could load (through `aef run`'s importer), while the candidate ran
    through `node_worker`'s own `import_module`. One loader now, so the two
    sides either both load an entrypoint or both refuse it.

    Asserted in the subprocess the worker actually is, not against a mock.
    """
    entrypoint = f"{WIDENED.as_posix()}:build_graph"
    incumbent = load_graph(f"{(widened_repo / WIDENED).as_posix()}:build_graph")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            "from aef.harness.node_worker import load_graph;"
            "print(load_graph(sys.argv[1]).id)",
            entrypoint,
        ],
        cwd=widened_repo,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == incumbent.id == "reviewer"


# ---------------------------------------------------------------------------
# R5b — a check that raises scores THAT scenario 0, never the suite
# ---------------------------------------------------------------------------


# Bypasses `__post_init__`, exactly as a corpus loaded before a detector change
# or a hand-built check would. What matters is that `_holds` raises.
def _unrunnable_check() -> TaskCheck:
    check = TaskCheck(path="working_memory.answer", op="regex", value=r"^\d+$")
    object.__setattr__(check, "value", r"^(?:\s+\S+)+$")
    return check


def _local_graph(answer: str) -> Graph:
    def do(state, ctx, services):  # type: ignore[no-untyped-def]
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="done"),
                working_memory={"answer": answer},
                scores={"quality": 1.0},
            ),
            END,
        )

    return Graph(
        id="g",
        version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[],
        entry_node="do",
    )


def _scenario_with(sid: str, checks: tuple[TaskCheck, ...], answer: str) -> Scenario:
    state = AEFState(run_id=sid, agent_id="a", objective="o")
    recorded = GraphExecutor(_local_graph(answer).compile(), agent_services()).run(
        state, record_trace=True
    )
    return Scenario(
        id=sid,
        split=Split.TRAIN,
        graph_id="g",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=datetime(2026, 9, 5, tzinfo=UTC),
        checks=checks,
    )


LONG_ANSWER = " x" * 6000


def test_the_in_process_runner_scores_an_unusable_check_zero_and_says_so() -> None:
    scenario = _scenario_with("bad", (_unrunnable_check(),), LONG_ANSWER)
    result = run_scenario(scenario, _local_graph(LONG_ANSWER))
    assert result["score"] == 0.0
    assert result["failure"].startswith("unusable check: ")
    assert "refusing to run regex check" in result["failure"]
    # The run itself terminated. Reporting it as an errored run would blame the
    # candidate for the owner's check.
    assert result["outcome"]["terminated"] is True


def test_one_unusable_check_does_not_kill_the_rest_of_the_in_process_suite() -> None:
    """The reproduction, inverted: the second scenario never ran at all."""
    good = _scenario_with(
        "good", (TaskCheck(path="working_memory.answer", op="contains", value="x"),), LONG_ANSWER
    )
    bad = _scenario_with("bad", (_unrunnable_check(),), LONG_ANSWER)
    scores = {s.id: run_scenario(s, _local_graph(LONG_ANSWER))["score"] for s in (bad, good)}
    assert scores == {"bad": 0.0, "good": 1.0}


def test_the_isolated_suite_scores_an_unusable_check_zero_and_keeps_going() -> None:
    """The same property in the gate's path. Two scorers drift (ADR 0113), and
    two try/excepts around them drift too — so both are tested."""
    ws = Path(tempfile.mkdtemp(prefix="j1-unusable-"))
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")
    (ws / "agents" / "graph.py").write_text(
        GRAPH_SOURCE.replace('"answer": "42"', f'"answer": {LONG_ANSWER!r}').replace(
            'id="reviewer"', 'id="g"'
        )
    )
    bad = _scenario_with("bad", (_unrunnable_check(),), LONG_ANSWER)
    good = _scenario_with(
        "good", (TaskCheck(path="working_memory.answer", op="contains", value="x"),), LONG_ANSWER
    )
    results = run_corpus_isolated(ws, [bad, good], entrypoint="agents.graph:build_graph")
    assert set(results) == {"bad", "good"}
    assert results["bad"].score == 0.0
    assert (results["bad"].failure or "").startswith("unusable check: ")
    assert results["bad"].outcome.terminated is True
    assert results["good"].score == 1.0
    assert results["good"].failure is None


def test_the_refusal_itself_is_still_raised_by_holds() -> None:
    """The control for both: the two try/excepts must catch a refusal, not
    prevent one. Weakening `_holds` to return False would make every test above
    pass and delete the defence."""
    with pytest.raises(CatastrophicPatternError):
        from aef.harness.checks import _holds

        _holds(_unrunnable_check(), LONG_ANSWER)


# ---------------------------------------------------------------------------
# G2's verdict says WHY
# ---------------------------------------------------------------------------


def test_the_g2_verdict_names_the_import_error_that_caused_the_regression(
    tmp_path: Path,
) -> None:
    """(c). "1 previously-passing scenario(s) no longer pass" is what a
    candidate that changed behaviour gets AND what a candidate whose entrypoint
    could not be imported got. The ledger has to show `cannot import` when that
    is the cause."""
    from aef.harness.candidate import inspect_candidate
    from aef.harness.gates.base import GateContext, GateOutcome
    from aef.harness.gates.g2_outcome import G2OutcomeNonRegression
    from aef.harness.git import GitRepo
    from aef.harness.zones import ZonePolicy

    root = tmp_path / "repo"
    (root / ".claude" / "agents").mkdir(parents=True)
    (root / ".claude" / "agents" / "persona.md").write_text("# Persona\n\nAnswer.\n")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@test")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "incumbent")
    git("checkout", "-qb", "loop/c1")
    (root / ".claude" / "agents" / "persona.md").write_text("# Persona\n\nAnswer.\n\n- lesson\n")
    git("add", "-A")
    git("commit", "-qm", "candidate")
    git("checkout", "-q", "main")

    from aef.harness.corpus import Corpus

    scenario = _scenario_with("s1", (), "42")
    repo = GitRepo(root=root)
    gate = G2OutcomeNonRegression(
        corpus=Corpus(root=tmp_path / "corpus", scenarios=(scenario,)),
        entrypoint=".claude/agents/migrated/absent/graph.py:build_graph",
    )
    result = gate.run(
        GateContext(
            repo=repo,
            base_ref="main",
            head_ref="loop/c1",
            verdict=inspect_candidate(repo, "main", "loop/c1"),
            workdir=tmp_path / "work",
            zone_policy=ZonePolicy(agent_root=".claude/agents"),
        )
    )
    assert result.outcome is GateOutcome.FAIL
    assert "no longer pass" in result.reason
    assert "cannot import" in result.reason, result.reason
    assert any("cannot import" in line for line in result.evidence), result.evidence


def test_a_real_behavioural_regression_still_reads_as_one() -> None:
    """The control for the verdict text: a candidate that ran and answered
    differently must NOT be told it could not be imported."""
    from aef.harness.gates.g2_outcome import _why_note
    from aef.harness.outcome import Comparison, Outcome

    passing = Outcome(
        terminated=True, plan_status="done", error_count=0, policy_denials=0, node_path=("a",)
    )
    failing = Outcome(
        terminated=True, plan_status="failed", error_count=0, policy_denials=0, node_path=("a",)
    )
    regressed = [Comparison(scenario_id="s1", incumbent=passing, candidate=failing)]
    assert _why_note(regressed, {}) == ""
    assert "cannot import" in _why_note(regressed, {"s1": "IsolationError: cannot import 'x'"})
