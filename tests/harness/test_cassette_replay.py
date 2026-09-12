"""A scenario pins its model calls and re-executes without a credential
(ADR 0123).

The reproduce-first case is the first test: a graph that calls a model could
not be recorded and replayed at all — the recording had no provider slot for
the calls and re-execution had no cassette — so the corpus held no content
task and every scenario failed only by raising. Every later test pins a
property of the fix. Fake providers throughout; the one isolated test spawns
the node worker the gates use, because the cassette has to reach it.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.cli.main import main
from aef.harness.checks import TaskCheck
from aef.harness.corpus import CorpusManifest, Scenario, save_manifest, save_scenario
from aef.harness.git import GitRepo
from aef.harness.isolated_suite import run_corpus_isolated
from aef.harness.loop import LoopConfig, LoopPaths
from aef.harness.recorder import record_run
from aef.harness.scenario_runner import run_scenario
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
    ProviderMessage,
)
from aef.providers.cassette_provider import CassetteProvider, RecordedCall
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

REPO = Path(__file__).resolve().parents[2]
RECORDED_AT = datetime(2026, 9, 3, tzinfo=UTC)


def _summary_scenarios_per_split() -> dict[str, int]:
    """How many `summary_agent` scenarios each split holds, per the corpus on
    disk. Read rather than pinned so growing the corpus is not a failure of the
    no-live-call test (ADR 0171)."""
    from collections import Counter

    from aef.harness.corpus import load_corpus

    counts = Counter(
        s.split.value
        for s in load_corpus(REPO / "corpus").scenarios
        if s.graph_id == "summary_agent"
    )
    return dict(counts)


class _Scripted(ModelProvider):
    """Answers with a fixed reply and counts calls."""

    name = "scripted"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        return CompletionResult(content=self.reply, model="fake-1", input_tokens=4, output_tokens=2)


class _Forbidden(ModelProvider):
    name = "forbidden"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise AssertionError("a live model call was made during replay")


def _asking_graph(prompt_suffix: str = "") -> Graph:
    """One node that asks the model to summarise and writes the answer."""

    def ask(state, ctx, services):  # type: ignore[no-untyped-def]
        result = services.require_model_provider().complete(
            CompletionRequest(
                messages=(
                    ProviderMessage(
                        role="user", content=f"summarise: {state.objective}{prompt_suffix}"
                    ),
                ),
                model="",
            )
        )
        return (
            StateDelta(
                working_memory={"summary": result.content},
                plan=Plan(goal=state.objective, status="done"),
            ),
            END,
        )

    return Graph(
        id="asker",
        version="1",
        nodes={
            "ask": Node(
                id="ask",
                version="1",
                fn=ask,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: f"{s.run_id}:ask",
            )
        },
        edges=[],
        entry_node="ask",
    )


CHECKS = (
    TaskCheck(path="working_memory.summary", op="contains", value="Kestrel"),
    # Was `regex ^(?:\s*\S+){1,6}\s*$`. Changed deliberately: that shape is the
    # ReDoS of ADR 0166 and is now refused at construction. It did not hang
    # HERE — a cap of 6 against nine short tokens is decided by the character
    # classes, not by backtracking — but a test carrying the dangerous form is
    # a test defending it through every later copy-paste, and this check only
    # ever meant "at most six words".
    TaskCheck(path="working_memory.summary", op="max_words", value=6),
)


def _record(reply: str, checks: tuple[TaskCheck, ...] = CHECKS) -> tuple[Scenario, _Scripted]:
    live = _Scripted(reply)
    scenario = record_run(
        _asking_graph(),
        AEFState(run_id="s1", agent_id="a", objective="the Kestrel passage"),
        agent_services(model_provider=live),
        scenario_id="s1",
        recorded_at=RECORDED_AT,
        checks=checks,
    )
    return scenario, live


# ---------------------------------------------------------------------------
# The defect, reproduced: before the cassette a model call could not be pinned
# ---------------------------------------------------------------------------
def test_recording_pins_every_model_call_the_run_made() -> None:
    scenario, live = _record("Kestrel flies at dawn")
    assert live.calls == 1
    assert len(scenario.model_calls) == 1
    call = scenario.model_calls[0]
    assert call.result.content == "Kestrel flies at dawn"
    assert call.messages[0].content == "summarise: the Kestrel passage"


def test_a_scenario_with_calls_round_trips_and_a_legacy_one_loads_with_none() -> None:
    scenario, _ = _record("Kestrel flies at dawn")
    payload = scenario.to_payload()
    assert len(payload["model_calls"]) == 1
    back = Scenario.from_payload(json.loads(json.dumps(payload)))
    assert back.model_calls == scenario.model_calls
    assert back.model_calls[0].key == scenario.model_calls[0].key

    legacy = dict(payload)
    del legacy["model_calls"]
    assert Scenario.from_payload(legacy).model_calls == ()


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def test_replay_serves_the_recording_and_makes_no_live_call() -> None:
    scenario, _ = _record("Kestrel flies at dawn")
    result = run_scenario(scenario, _asking_graph(), live_provider=_Forbidden())
    assert result["score"] == 1.0
    assert result["cassette"] == {"hits": 1, "misses": 0}


def test_a_check_on_the_summary_moves_the_score() -> None:
    """The content task: same graph, same checks, the recorded ANSWER is what
    decides — a summary without the term, or over length, scores below 1."""
    right, _ = _record("Kestrel flies at dawn")
    no_term, _ = _record("a bird flies at dawn")
    too_long, _ = _record("Kestrel flies at dawn over the quiet river valley")
    assert run_scenario(right, _asking_graph())["score"] == 1.0
    assert run_scenario(no_term, _asking_graph())["score"] == 0.5
    assert run_scenario(too_long, _asking_graph())["score"] == 0.5
    unchecked, _ = _record("a bird flies at dawn", checks=())
    assert run_scenario(unchecked, _asking_graph())["score"] == 1.0, (
        "a scenario that declares nothing about its answer makes no claim (ADR 0113)"
    )


def test_a_miss_under_fail_is_an_errored_run_naming_the_miss() -> None:
    """The candidate changed the prompt: the recording never saw it. The
    default reports that as a failed node — deterministic, no credential."""
    scenario, _ = _record("Kestrel flies at dawn")
    changed = _asking_graph(prompt_suffix=" (be brief)")
    result = run_scenario(scenario, changed, live_provider=_Forbidden())
    assert result["score"] == 0.0
    assert result["outcome"]["error_count"] == 1
    assert result["cassette"] == {"hits": 0, "misses": 1}


def test_a_miss_under_live_is_answered_and_reported_as_live() -> None:
    scenario, _ = _record("Kestrel flies at dawn")
    changed = _asking_graph(prompt_suffix=" (be brief)")
    live = _Scripted("Kestrel, briefly")
    result = run_scenario(scenario, changed, cassette_miss="live", live_provider=live)
    assert live.calls == 1
    assert result["score"] == 1.0
    assert result["cassette"] == {"hits": 0, "misses": 1}


def test_a_legacy_scenario_run_by_a_model_calling_graph_fails_rather_than_calling_out() -> None:
    scenario, _ = _record("Kestrel flies at dawn")
    legacy = Scenario.from_payload(
        {k: v for k, v in scenario.to_payload().items() if k != "model_calls"}
    )
    result = run_scenario(legacy, _asking_graph(), live_provider=_Forbidden())
    assert result["score"] == 0.0
    assert result["cassette"]["misses"] == 1


def test_loop_config_refuses_an_unknown_cassette_policy(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cassette_miss"):
        LoopConfig(
            repo=GitRepo(root=tmp_path), paths=LoopPaths(root=tmp_path), cassette_miss="maybe"
        )


# ---------------------------------------------------------------------------
# The gates' path: the cassette reaches the worker
# ---------------------------------------------------------------------------
ASKER_SOURCE = """
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.state import Plan, StateDelta


def ask(state, ctx, services):
    result = services.require_model_provider().complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content=f"summarise: {state.objective}"),),
            model="",
        )
    )
    return (
        StateDelta(
            working_memory={"summary": result.content},
            plan=Plan(goal=state.objective, status="done"),
        ),
        END,
    )


def build_graph():
    return Graph(
        id="asker", version="1",
        nodes={"ask": Node(id="ask", version="1", fn=ask, deterministic=False,
                           side_effects=SideEffect.EXTERNAL_CALL,
                           idempotency_key_fn=lambda s: f"{s.run_id}:ask")},
        edges=[], entry_node="ask",
    )
"""


@pytest.mark.slow
def test_the_isolated_suite_replays_the_cassette_inside_the_worker() -> None:
    ws = Path(tempfile.mkdtemp())
    (ws / "agents").mkdir()
    (ws / "agents" / "__init__.py").write_text("")
    (ws / "agents" / "graph.py").write_text(ASKER_SOURCE)

    pinned, _ = _record("Kestrel flies at dawn")
    legacy = Scenario.from_payload(
        {**{k: v for k, v in pinned.to_payload().items() if k != "model_calls"}, "id": "legacy"}
    )
    results = run_corpus_isolated(ws, [pinned, legacy], entrypoint="agents.graph:build_graph")
    assert results["s1"].score == 1.0, results["s1"]
    assert results["s1"].failure is None
    # No calls pinned: the worker has no credential and the default is
    # "fail", so this is an errored node — never a live call from a gate.
    assert results["legacy"].score == 0.0
    assert results["legacy"].outcome.error_count == 1


# ---------------------------------------------------------------------------
# `aef loop score` on the committed summary corpus never goes live
# ---------------------------------------------------------------------------
def test_scoring_the_summary_corpus_makes_no_live_call(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """Every model request the summary agent makes is a cassette hit. Proved
    by making every live path raise: the harness provider's process runner,
    the provider factory, and `subprocess.run` itself."""
    import subprocess

    import aef.config.factory as factory
    import aef.providers.harness_provider as harness

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("a live model path was reached while scoring the corpus")

    monkeypatch.setattr(harness, "subprocess_runner", _boom)
    monkeypatch.setattr(harness.ClaudeCodeProvider, "complete", _boom)
    monkeypatch.setattr(factory, "build_model_provider", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)

    code = main(
        [
            "loop",
            "score",
            "agents.summary.graph:build_graph",
            "--corpus",
            str(REPO / "corpus"),
            "--json",
            "--repeat",
            "2",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["graph_id"] == "summary_agent"
    assert report["cassette"]["misses"] == 0
    assert report["cassette"]["hits"] > 0
    # Every summary scenario in each split is scored, read off the corpus
    # rather than pinned as a literal: the numbers were 12 and 6 until ADR 0171
    # recorded the corpus's first true content negatives, and a size literal
    # here turns "the corpus grew" into a test failure that says nothing about
    # whether a live call was made — which is all this test is for.
    expected = _summary_scenarios_per_split()
    assert report["train"]["n"] == expected["train"]
    assert report["validation"]["n"] == expected["validation"]
    assert report["train"]["repeat_mean_spread"] == 0.0
    assert report["validation"]["repeat_mean_spread"] == 0.0
    # The demo's scenarios sit in the same corpus and are not this graph's.
    assert len(report["skipped_other_graph"]) == 11


def test_score_skips_scenarios_recorded_from_another_graph(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """A corpus can hold several graphs' recordings; scoring one graph against
    another's scenarios measures nothing about either."""
    root = tmp_path / "corpus"
    manifest = CorpusManifest()
    mine, _ = _record("Kestrel flies at dawn")
    other = Scenario.from_payload({**mine.to_payload(), "id": "other", "graph_id": "someone_else"})
    for s in (mine, other):
        save_scenario(root, s)
        manifest.ids[s.id] = s.split
    save_manifest(root, manifest)
    (tmp_path / "asker.py").write_text(ASKER_SOURCE)
    monkeypatch_path = str(tmp_path)
    import sys

    sys.path.insert(0, monkeypatch_path)
    try:
        code = main(["loop", "score", "asker:build_graph", "--corpus", str(root), "--json"])
    finally:
        sys.path.remove(monkeypatch_path)
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["train"]["per_scenario"] == {"s1": 1.0}
    assert report["skipped_other_graph"] == ["other"]


def test_cassette_provider_wraps_whatever_the_recorder_was_given() -> None:
    """The recorder wraps even an absent provider: a graph that asks with none
    configured fails naming the absence (before the cassette it failed with
    `ServiceNotConfiguredError`; a raise either way, now a named one)."""
    with pytest.raises(ModelProviderError, match="no live provider"):
        record_run(
            _asking_graph(),
            AEFState(run_id="none", agent_id="a", objective="o"),
            agent_services(),
            scenario_id="none",
            recorded_at=RECORDED_AT,
        )


def test_recorded_calls_are_data_a_person_can_read() -> None:
    scenario, _ = _record("Kestrel flies at dawn")
    payload = scenario.to_payload()["model_calls"][0]
    assert payload["request"]["messages"][0] == {
        "role": "user",
        "content": "summarise: the Kestrel passage",
    }
    assert payload["result"]["content"] == "Kestrel flies at dawn"
    # And the key is derived from the request, so it cannot be authored.
    assert payload["key"] == RecordedCall.from_payload(payload).key
    assert isinstance(CassetteProvider(None, [RecordedCall.from_payload(payload)]), ModelProvider)
    with pytest.raises(ModelProviderError):
        CassetteProvider(None, []).complete(scenario.model_calls[0].request)


def test_run_scenario_records_a_failed_owner_check_when_given_a_store() -> None:
    """ADR 0180's second wiring site. Default None keeps every gate path as
    it was (ADR 0174's refusal: a gate must not manufacture the next
    candidate's evidence). A caller that owns the store gets one failure
    record per failed run — and one on a repeat, K2's idempotence."""
    from aef.services.memory.in_memory import InMemoryMemoryStore

    scenario, _ = _record("a bird flies at dawn")  # the must-mention check fails
    store = InMemoryMemoryStore()
    assert run_scenario(scenario, _asking_graph(), memory=store)["score"] == 0.5
    failures = [r for r in store.query("failure", limit=50) if r.kind == "failure"]
    assert len(failures) == 1, [r.content for r in failures]
    run_scenario(scenario, _asking_graph(), memory=store)
    failures = [r for r in store.query("failure", limit=50) if r.kind == "failure"]
    assert len(failures) == 1, "a repeat must not double-count"
    passing, _ = _record("Kestrel flies at dawn")
    clean = InMemoryMemoryStore()
    run_scenario(passing, _asking_graph(), memory=clean)
    assert not [r for r in clean.query("failure", limit=5) if r.kind == "failure"]


def test_run_scenario_writes_nothing_without_a_store() -> None:
    scenario, _ = _record("a bird flies at dawn")
    assert "memory" not in run_scenario(scenario, _asking_graph())  # no side channel


def test_the_score_paths_failure_record_is_stamped_with_execution_time() -> None:
    """ADR 0191 (final hunt, F4): stamped with `recorded_at`, a scored run's
    record sorted before every lesson seeded after the recording and could
    never refresh one."""
    from datetime import UTC, datetime

    from aef.services.memory.in_memory import InMemoryMemoryStore

    scenario, _ = _record("a bird flies at dawn")
    before = datetime.now(UTC)
    store = InMemoryMemoryStore()
    run_scenario(scenario, _asking_graph(), memory=store)
    (rec,) = [r for r in store.query("failure", limit=5) if r.kind == "failure"]
    assert rec.created_at >= before, (rec.created_at, before, scenario.recorded_at)
    assert rec.created_at > scenario.recorded_at


def test_recorded_prompt_provider_capabilities_survive_offline_replay() -> None:
    from aef.reasoning.prompt_agent import PromptAgentDefinition, make_prompt_agent_node

    class NoTools(_Scripted):
        isolation = frozenset({"no_tools"})

    live = NoTools("supplied evidence only")
    node = make_prompt_agent_node(
        definition=PromptAgentDefinition(
            name="a", description="probe", body="Use tools to inspect the repo."
        ),
        route=END,
    )
    graph = Graph(id="prompt", version="1", nodes={node.id: node}, edges=[], entry_node=node.id)
    scenario = record_run(
        graph,
        AEFState(run_id="prompt-1", agent_id="a", objective="inspect"),
        agent_services(model_provider=live),
        scenario_id="prompt-1",
        recorded_at=RECORDED_AT,
    )
    assert scenario.provider_isolation == ("no_tools",)
    assert "No tools are available" in scenario.model_calls[0].request.messages[0].content
    replayed = run_scenario(scenario, graph)
    assert replayed["outcome"]["error_count"] == 0
    assert live.calls == 1
