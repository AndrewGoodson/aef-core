"""One list, so the two paths cannot drift apart.

The same defect happened four times:

- ADR 0073: `aef run` wired no critic/judge, so LOOP.md obligation 2 made
  obligation 3 impossible.
- ADR 0075: the gate runner had the same gap — the fix had reached two of
  three construction sites.
- ADR 0079: `policy_engine` was missing at all four sites.
- ADR 0089: a deep-copy raise produced the same symptom by another route.

Every time the symptom was identical: a service the node needs is absent in
the gate path, `scenario_runner` swallows the `ServiceNotConfiguredError`,
and candidate, incumbent and all five cohort members score 0.0 — so G3
rejects every candidate forever while `aef loop doctor` reports the agent
green.

Fixing it service-by-service did not work, because the failure is drift
between two lists nobody compares (ADR 0091).
"""

from datetime import UTC, datetime

import pytest

from aef.harness.corpus import Scenario, Split
from aef.harness.scenario_runner import run_scenario
from aef.kernel import END, Graph, GraphExecutor, Node, Services
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

# Everything a Zone A node can ask for. Derived from `Services` itself, so a
# service added later joins this test without anyone remembering to.
REQUIRABLE = sorted(
    name.removeprefix("require_")
    for name in dir(Services)
    if name.startswith("require_") and name != "require_model_provider"
)


def _graph_requiring(service: str) -> Graph:
    def node(state, ctx, services):  # type: ignore[no-untyped-def]
        getattr(services, f"require_{service}")()
        return (
            StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
            END,
        )

    return Graph(
        id="g",
        version="1",
        nodes={"do": Node(id="do", version="1", fn=node, deterministic=True)},
        edges=[],
        entry_node="do",
    )


def test_the_requirable_set_is_not_empty() -> None:
    """The control. A parametrisation that silently collects nothing passes
    every case below."""
    assert len(REQUIRABLE) >= 6, REQUIRABLE


@pytest.mark.parametrize("service", REQUIRABLE)
def test_every_service_a_node_can_require_works_in_the_gate(service: str) -> None:
    """`model_provider` is excluded deliberately and is the only exclusion:
    the gate sandbox has no credentials, and a node calling a model is
    `deterministic=False` and unreplayable anyway. It is the one service the
    two paths genuinely differ on."""
    graph = _graph_requiring(service)
    state = AEFState(run_id="r", agent_id="a", objective="o")

    recorded = GraphExecutor(graph.compile(), agent_services()).run(state, record_trace=True)
    scenario = Scenario(
        id="s",
        split=Split.VALIDATION,
        graph_id="g",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    result = run_scenario(scenario, graph)
    assert result.get("failure") is None, (
        f"a node calling require_{service}() runs under `aef run` and fails in the gate: "
        f"{result.get('failure')}"
    )


def test_model_provider_is_the_only_service_the_gate_omits() -> None:
    """Stated as an assertion so adding a second exception is a deliberate
    act rather than a quiet one."""
    services = agent_services()
    assert services.model_provider is None
    for service in REQUIRABLE:
        getattr(services, f"require_{service}")()


@pytest.mark.parametrize(
    "site",
    [
        "aef.harness.scenario_runner",
        "aef.harness.harvest",
        "aef.cli.run",
        "aef.cli.loop",
    ],
)
def test_every_construction_site_goes_through_the_one_factory(site: str) -> None:
    """A site building its own `Services(...)` is how the list drifted. This
    is a source assertion, and it is the right shape here: the property IS
    "these modules call that function", not a behaviour."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(site))
    assert "agent_services(" in source, f"{site} does not use the shared factory"


def test_the_gate_does_not_write_to_the_adopters_stores() -> None:
    """Memory and durability are satisfiable but THROWAWAY. A gate
    re-execution that wrote to the adopter's memory store would mutate the
    evidence a later proposal is built from."""
    import threading

    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.services.runtime import _EphemeralDurability

    services = agent_services()
    assert isinstance(services.memory, InMemoryMemoryStore)
    assert isinstance(services.durability, _EphemeralDurability)

    # And non-serialising. `InMemoryDurabilityBackend` JSON-encodes every
    # checkpoint, so making it the default re-killed the state ADR 0089 had
    # just made legal — a Lock in working_memory raised on the first
    # super-step and became a uniform 0.0 (ADR 0093). Nothing reads these
    # checkpoints; encoding them bought a constraint and no capability.
    from aef.state import AEFState

    services.durability.save_checkpoint(  # type: ignore[union-attr]
        AEFState(run_id="r", agent_id="a", objective="o", working_memory={"l": threading.Lock()})
    )


# --------------------------------------------------------------------------
# ADR 0092 — declared injection points nothing injected into
# --------------------------------------------------------------------------


def test_the_gate_context_receives_a_tracer_when_one_is_configured(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`GateContext.tracer` had exactly one production construction site and
    it passed nothing, so `_run_traced`'s traced branch never executed
    outside a test — the observability of the gate pipeline was unreachable
    by construction (ADR 0092)."""
    import subprocess
    from datetime import UTC, datetime

    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths, gate
    from aef.observability.in_memory import InMemoryTracer

    repo = tmp_path / "repo"
    (repo / "agents" / "demo").mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, capture_output=True
    )
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY = 3\n")
    git("add", "-A")
    git("commit", "-qm", "i")
    git("checkout", "-q", "-b", "cand")
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY = 4\n")
    git("commit", "-qam", "c")
    git("checkout", "-q", "main")

    tracer = InMemoryTracer()
    config = LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state"),
        build_commands=(("python", "-c", "pass"),),
        tracer=tracer,
    )
    gate(config, "cand", now=datetime(2026, 3, 1, tzinfo=UTC), workdir=tmp_path / "w")

    names = [span.name for span in tracer.spans]
    assert names, "no gate span was emitted"
    assert all(name.startswith("aef.harness.gate.") for name in names), names


def test_gate_limits_reach_the_gate_that_reads_them(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`GateContext.limits` was declared and never supplied, so G0's
    `max_changed_lines` / `max_changed_files` overrides could not be set by
    any caller."""
    import subprocess
    from datetime import UTC, datetime

    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths, gate

    repo = tmp_path / "repo"
    (repo / "agents" / "demo").mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    subprocess.run(
        ["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, capture_output=True
    )
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY = 3\n")
    git("add", "-A")
    git("commit", "-qm", "i")
    git("checkout", "-q", "-b", "cand")
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY = 4\nEXTRA = 1\nMORE = 2\n")
    git("commit", "-qam", "c")
    git("checkout", "-q", "main")

    config = LoopConfig(
        repo=GitRepo(root=repo),
        paths=LoopPaths(root=tmp_path / "state"),
        build_commands=(("python", "-c", "pass"),),
        gate_limits={"max_changed_lines": 1},
    )
    run = gate(config, "cand", now=datetime(2026, 3, 1, tzinfo=UTC), workdir=tmp_path / "w")

    assert run.result.ran == ("G0",)
    assert not run.result.passed
