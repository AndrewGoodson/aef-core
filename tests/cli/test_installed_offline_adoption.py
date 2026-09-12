"""Exercise an installed wheel in a disposable adopter, without model or network calls.

The graph below is deliberately supplied by the test: adoption generates a stub,
not domain semantics. No editable source install or actual customer repo is used.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

GRAPH = """from aef.kernel import Context, Edge, Graph, Node, Route, Services
from aef.reasoning.nodes import make_reflect_node
from aef.state import AEFState, Plan, Provenance, StateDelta


def calculate(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    return StateDelta(
        working_memory={"total": sum(state.working_memory["values"])},
        provenance=[Provenance(node_id=ctx.node_id, graph_version=ctx.graph_version,
                               ts=ctx.now, trace_id=ctx.trace_id)],
    ), "validate"


def validate(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    passed = state.working_memory["total"] == state.working_memory["expected"]
    return StateDelta(
        plan=Plan(goal=state.objective, status="done" if passed else "failed"),
        errors=[] if passed else [{"node_id": ctx.node_id, "error": "total mismatch"}],
    ), "reflect"


def build_graph() -> Graph:
    return Graph(id="offline-check", version="1", entry_node="calculate", nodes={
        "calculate": Node(id="calculate", version="1", fn=calculate, deterministic=True),
        "validate": Node(id="validate", version="1", fn=validate, deterministic=True),
        "reflect": make_reflect_node(),
    }, edges=[Edge(from_node="calculate", to_node="validate"),
              Edge(from_node="validate", to_node="reflect")])
"""

PROBE = """
from dataclasses import replace
from aef.config import load_agent_config
from aef.cli.run import build_run_config
from aef.harness.harvest import load_runs
from aef.harness.memory_store import FileMemoryStore
from aef.kernel import FileDurabilityBackend, GraphExecutor, Services
from aef.kernel.executor import GraphExecutionError
from aef.kernel.replay import DeterminismViolationError, ReplayEngine
from aef.security.tool import FileAuditLogWriter, PolicyConfig, PolicyDecision, PolicyEngine
from aef.security.tool import Tool, ToolCall
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta
from graph import build_graph

config = load_agent_config("aef.yaml")
assert config.model_provider is None
assert build_run_config("aef.yaml").model_provider is None
assert config.evolution.enabled is False
assert config.gates.live_model_calls is False
assert Path(aef.__file__).with_name("py.typed").is_file()

# Reflect writes observed outcomes. Replay must never append that I/O again.
memory = FileMemoryStore(Path("memory.jsonl"))
before = memory.path.read_bytes()
runs = load_runs(Path("runs"))
assert len(runs) == 2
assert all(run.model_calls == () for run in runs)
compiled = build_graph().compile()
services = agent_services(memory=memory, agent_id="wheel-agent")
for run in runs:
    replayed = ReplayEngine(compiled, services).replay(run.trace)
    assert replayed.working_memory["total"] == 5
    expected_status = "done" if run.initial_state.working_memory["expected"] == 5 else "failed"
    assert replayed.plan.status == expected_status
    records = memory.query("success" if expected_status == "done" else "failure",
                           run_id=run.run_id, agent_id="wheel-agent")
    assert len(records) == 1
    assert records[0].content["graph_version"] == "1"
assert memory.path.read_bytes() == before

# Corrupt the deterministic implementation while retaining its node identity.
graph = build_graph()
def broken(state, ctx, services):
    return StateDelta(working_memory={"total": 999}), "validate"
graph = replace(graph, nodes={
    **graph.nodes, "calculate": replace(graph.nodes["calculate"], fn=broken),
})
try:
    ReplayEngine(graph.compile(), services).replay(runs[0].trace)
except DeterminismViolationError:
    pass
else:
    raise AssertionError("changed calculation escaped deterministic replay")

# END does not consume a step. Resume executes only the remaining node.
backend = FileDurabilityBackend(Path("budget-checkpoints"))
services = agent_services(durability=backend, memory=memory, agent_id="wheel-agent")
state = AEFState(run_id="exact", agent_id="wheel-agent", objective="sum two inputs",
                 working_memory={"values": [2, 3], "expected": 5})
result = GraphExecutor(compiled, services, max_steps=3).run(state, record_trace=True)
assert result.final_state.checkpoint_seq == 3
assert len(result.trace) == 3
assert backend.load_cursor("exact") is None
terminal = GraphExecutor(compiled, services, max_steps=1).resume("exact")
assert terminal.final_state == result.final_state
partial = state.model_copy(update={"run_id": "partial"})
try:
    GraphExecutor(compiled, services, max_steps=2).run(partial)
except GraphExecutionError as exc:
    assert "max_steps" in str(exc)
else:
    raise AssertionError("step limit did not stop the third node")
assert backend.load_cursor("partial") == "reflect"
resumed = GraphExecutor(compiled, services, max_steps=1).resume("partial", record_trace=True)
assert [record.node_id for record in resumed.trace] == ["reflect"]
assert resumed.final_state.plan.status == "done"

# A denied or HITL-gated call must not reach the actual tool body.
class Tripwire(Tool):
    name = "write"
    required_scopes = ("files:write",)
    calls = 0
    def invoke(self, arguments):
        self.calls += 1
        return {"ok": True}

tool = Tripwire()
audit = FileAuditLogWriter(Path("audit.jsonl"))
cases = [
    (PolicyConfig(), ToolCall("write", {}, risk=0), PolicyDecision.DENY),
    (PolicyConfig(allowed_scopes=frozenset({"files:write"})),
     ToolCall("write", {}, risk=0.1), PolicyDecision.REQUIRE_HITL),
    (PolicyConfig(allowed_scopes=frozenset({"files:write"})),
     ToolCall("different", {}, risk=0), PolicyDecision.DENY),
]
for policy, call, expected in cases:
    injected = Services(tools={tool.name: tool},
                        policy_engine=PolicyEngine(policy, audit_log=audit))
    verdict = injected.require_policy_engine().evaluate(injected.tools[tool.name], call)
    if verdict.allowed:
        injected.tools[tool.name].invoke(call.arguments)
    assert verdict.decision is expected
    assert tool.calls == 0
assert len(audit.path.read_text().splitlines()) == 3
assert {row["decision"] for row in map(json.loads, audit.path.read_text().splitlines())} == {
    "deny", "require_hitl"
}
print("installed wheel: offline, evidence, policy, budget, resume and replay verified")
"""


def _run(cwd: Path, command: list[str], *, expected_exit: int = 0) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=90)
    assert result.returncode == expected_exit, result.stdout + result.stderr
    return result.stdout


def test_installed_wheel_offline_adoption(tmp_path: Path) -> None:
    source = tmp_path / "wheel-source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(ROOT / "aef", source / "aef", ignore=shutil.ignore_patterns("__pycache__"))
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _run(
        source,
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            f"from hatchling.build import build_wheel; build_wheel({str(wheels)!r})",
        ],
    )
    (wheel,) = wheels.glob("*.whl")
    installed = tmp_path / "installed"
    _run(
        tmp_path,
        [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            "--target",
            str(installed),
            str(wheel),
        ],
    )
    target = tmp_path / "fresh adopter with spaces"
    target.mkdir()
    owner = b"# Owner contract\r\nKeep existing business rules.\r\n"
    (target / "AGENTS.md").write_bytes(owner)
    (target / "CLAUDE.md").write_bytes(owner)

    bootstrap = (
        "import sys, json, socket\nfrom pathlib import Path\n"
        f"sys.path[:0] = [{str(installed)!r}, {str(target)!r}]\n"
        "import aef\n"
        f"assert Path(aef.__file__).is_relative_to({str(installed)!r})\n"
        "def forbidden(*args, **kwargs):\n"
        "    raise AssertionError('offline test attempted network or provider construction')\n"
        "socket.create_connection = socket.socket.connect = forbidden\n"
        "import aef.config.factory\naef.config.factory._build_single = forbidden\n"
    )

    def cli(*args: str, expected_exit: int = 0) -> str:
        return _run(
            target,
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                bootstrap + "from aef.cli.main import main\nraise SystemExit(main())",
                *args,
            ],
            expected_exit=expected_exit,
        )

    cli("adopt", "--dir", ".", "--profile", "offline")
    for name in ("AGENTS.md", "CLAUDE.md"):
        assert (target / name).read_bytes().startswith(owner)
    for name in (
        "GROK.md",
        ".github/copilot-instructions.md",
        ".cursor/rules/aef.mdc",
        "AUTONOMY.md",
        "AGENT_INTEGRATION.md",
    ):
        assert (target / name).is_file()
    assert "## Evidence learning protocol" in (target / "AGENT_INTEGRATION.md").read_text()
    assert not (target / ".github/workflows").exists()
    assert not (target / "LOOP.md").exists()
    (target / "graph.py").write_text(GRAPH)
    config = target / "aef.yaml"
    config.write_text(
        config.read_text().replace(
            "TODO: define the target repository objective", "Verify a deterministic sum"
        )
    )
    cli("doctor", "--dir", ".")
    for expected, status in ((5, "done"), (6, "failed")):
        output = json.loads(
            cli(
                "run",
                "graph.py",
                "--config",
                "aef.yaml",
                "--agent-id",
                "wheel-agent",
                "--working-memory",
                json.dumps({"values": [2, 3], "expected": expected}),
                "--checkpoints-dir",
                "checkpoints",
                "--memory",
                "memory.jsonl",
                "--record-runs",
                "runs",
            )
        )
        assert output["plan"]["status"] == status
        assert output["working_memory"]["total"] == 5
        assert output["checkpoint_seq"] == 3
        evaluation = cli(
            "eval",
            "--checkpoints-dir",
            "checkpoints",
            "--run-id",
            output["run_id"],
            "--config",
            "aef.yaml",
            expected_exit=0 if status == "done" else 1,
        )
        assert f"task_completion={1.0 if status == 'done' else 0.0}" in evaluation
        assert f"passed={status == 'done'}" in evaluation
        provenance = cli("trace", "--checkpoints-dir", "checkpoints", "--run-id", output["run_id"])
        assert len(provenance.splitlines()) == 1
        assert "node=calculate" in provenance
    _run(target, [sys.executable, "-I", "-B", "-c", bootstrap + PROBE])
    assert not list(target.rglob("__pycache__"))

    # The model profile has package-data dependencies that offline adoption
    # does not touch. Generate it from the installed wheel with the same
    # network/provider tripwires; scaffolding must not need either service.
    model_target = tmp_path / "model adopter"
    model_target.mkdir()
    cli("adopt", "--dir", str(model_target), "--profile", "model")
    packaged_skill = model_target / ".claude/skills/new-model-check/SKILL.md"
    assert (
        packaged_skill.read_bytes()
        == (ROOT / "aef/cli/templates/skills/new-model-check/SKILL.md").read_bytes()
    )
    assert (model_target / "LOOP.md").is_file()
    assert not (model_target / ".github/workflows").exists()
    assert not list(model_target.rglob("__pycache__"))
