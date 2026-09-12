"""Configured retrieval must survive recording, harvest, and both gate runners."""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.cli.run import run_graph_module
from aef.config.factory import build_retriever
from aef.config.schema import ContextConfig
from aef.harness.corpus import CorpusError, Expected, Scenario, Source, Split, load_corpus
from aef.harness.harvest import HarvestError, RecordedRun, harvest, load_runs
from aef.harness.isolated_suite import run_corpus_isolated
from aef.harness.memory_store import FileMemoryStore
from aef.harness.node_worker import _configure
from aef.harness.recorder import record_run
from aef.harness.scenario_runner import run_scenario
from aef.harness.trace_codec import dumps, encode_trace
from aef.kernel import END, Graph, GraphExecutor, Node
from aef.services.memory.base import MemoryRecord
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState, StateDelta

_GRAPH = """from aef.kernel import END, Graph, Node
from aef.state import StateDelta

def probe(state, ctx, services):
    chunks = services.retriever.retrieve(state.objective, token_budget=2000)
    return StateDelta(
        working_memory={"retrieved": [c.content for c in chunks]},
        errors=[{"node_id": "probe", "error": "billing question unresolved"}],
    ), END

def build_graph():
    node = Node(id="probe", version="1", fn=probe, deterministic=True)
    return Graph(id="context-probe", version="1", nodes={"probe": node},
                 edges=[], entry_node="probe")
"""


@pytest.mark.parametrize("ceiling,expected_count", [(None, 1), (1, 0)])
def test_cli_context_survives_harvest_and_both_runners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ceiling: int | None, expected_count: int
) -> None:
    module_name = "context_replay_probe"
    (tmp_path / f"{module_name}.py").write_text(_GRAPH)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)
    graph = importlib.import_module(module_name).build_graph()
    memory_path = tmp_path / "memory.jsonl"
    FileMemoryStore(memory_path).write(
        MemoryRecord(
            id="safe-record",
            kind="failure",
            agent_id="review",
            run_id="previous",
            content={"fact": "Retrieve invoice history before answering a billing question"},
        )
    )
    config_path = tmp_path / "aef.yaml"
    config_path.write_text(
        "model_provider: null\nmemory:\n  impl: in_memory\nobjectives: review\n"
        + (f"context:\n  impl: memory\n  token_budget: {ceiling}\n" if ceiling else "")
    )
    final = run_graph_module(
        module_name,
        agent_id="review",
        objective="billing question",
        config_path=config_path,
        memory_path=memory_path,
        record_runs_dir=tmp_path / "runs",
    )
    assert len(final.working_memory["retrieved"]) == expected_count
    before = memory_path.read_bytes()
    outcome = harvest(tmp_path / "runs", tmp_path / "corpus", graph, now=datetime.now(UTC))
    assert outcome.rejected_nondeterministic == ()
    assert len(outcome.promoted) == 1
    scenario = load_corpus(tmp_path / "corpus").scenarios[0]
    assert scenario.context_config is not None
    assert scenario.context_config.token_budget == ceiling
    run = load_runs(tmp_path / "runs")[0]
    assert run.context_config == scenario.context_config
    if ceiling is None:
        # A pre-binding recording has no field. It must still load and
        # execute using the historical default in both runners.
        payload = scenario.to_payload()
        payload.pop("context_config")
        scenario = Scenario.from_payload(payload)
        assert scenario.context_config is None
    executions = []
    original_run = GraphExecutor.run

    def capture(self, *args, **kwargs):
        result = original_run(self, *args, **kwargs)
        executions.append(result)
        return result

    monkeypatch.setattr(GraphExecutor, "run", capture)
    run_scenario(scenario, graph)
    assert dumps(encode_trace(executions[-1].trace)) == dumps(encode_trace(scenario.trace))
    run_corpus_isolated(tmp_path, [scenario], entrypoint=f"{module_name}:build_graph")
    observed, recorded = encode_trace(executions[-1].trace), encode_trace(scenario.trace)
    for trace in (observed, recorded):
        for record in trace:
            record["context"].pop("idempotency_key")
    assert dumps(observed) == dumps(recorded)
    assert memory_path.read_bytes() == before
    sys.modules.pop(module_name, None)


def test_recorder_captures_resolved_configured_retriever() -> None:
    memory = InMemoryMemoryStore()
    context = ContextConfig(
        impl="memory",
        token_budget=19,
        knowledge_boost=0.7,
        staleness_half_life=3,
        knowledge_min_occurrences=4,
    )
    retriever = build_retriever(context, memory=memory, agent_id="review")
    services = agent_services(memory=memory, retriever=retriever, agent_id="review")
    node = Node(id="probe", version="1", fn=lambda *_: (StateDelta(), END), deterministic=True)
    graph = Graph(id="context", version="1", nodes={"probe": node}, edges=[], entry_node="probe")
    scenario = record_run(
        graph,
        AEFState(run_id="run", agent_id="review", objective="billing"),
        services,
        scenario_id="review",
        split=Split.TRAIN,
        recorded_at=datetime.now(UTC),
    )
    restored = Scenario.from_payload(scenario.to_payload())
    assert restored.context_config == context
    worker_services = _configure(
        agent_services(),
        {
            "agent_id": "review",
            "context_config": restored.to_payload()["context_config"],
        },
    )
    assert worker_services.retriever.max_token_budget == 19
    assert worker_services.retriever.knowledge_boost == 0.7
    assert worker_services.retriever.staleness_half_life == 3
    assert worker_services.retriever.knowledge_min_occurrences == 4
    assert worker_services.model_provider.inner is None


@pytest.mark.parametrize(
    "invalid",
    [
        {"impl": "memory", "model_provider": {"impl": "command"}},
        {"impl": "memory", "policy": {"require_hitl_above_risk": 1}},
        {"impl": "memory", "token_budget": 0},
        {"impl": "arbitrary"},
    ],
)
def test_replay_context_rejects_capabilities_and_invalid_settings(invalid: dict) -> None:
    state = AEFState(run_id="run", agent_id="review", objective="billing")
    run = RecordedRun("run", "graph", "1", state, (), datetime.now(UTC))
    payload = run.to_payload() | {"context_config": invalid}
    with pytest.raises(HarvestError, match="malformed recorded run"):
        RecordedRun.from_payload(payload)
    scenario = Scenario("scenario", Split.TRAIN, "graph", "1", state, (), datetime.now(UTC))
    with pytest.raises(CorpusError, match="malformed scenario payload"):
        Scenario.from_payload(scenario.to_payload() | {"context_config": invalid})
    with pytest.raises(ValueError):
        _configure(agent_services(), {"context_config": invalid})


@pytest.mark.parametrize("missing", [False, True])
def test_legacy_recorded_context_loads_without_configuration(missing: bool) -> None:
    state = AEFState(run_id="run", agent_id="review", objective="billing")
    run = RecordedRun("run", "graph", "1", state, (), datetime.now(UTC))
    scenario = Scenario("scenario", Split.TRAIN, "graph", "1", state, (), datetime.now(UTC))
    for original in (run, scenario):
        payload = original.to_payload()
        if missing:
            payload.pop("context_config")
        assert type(original).from_payload(payload).context_config is None


def test_legacy_scenario_positional_source_keeps_its_meaning() -> None:
    scenario = Scenario(
        "legacy",
        Split.TRAIN,
        "graph",
        "1",
        AEFState(run_id="run", agent_id="review", objective="billing"),
        (),
        datetime.now(UTC),
        "",
        Expected.UNSPECIFIED,
        (),
        None,
        (),
        Source.HARVEST,
    )
    assert scenario.source is Source.HARVEST
    assert scenario.initial_memory is None
    assert Scenario.from_payload(scenario.to_payload()).source is Source.HARVEST
