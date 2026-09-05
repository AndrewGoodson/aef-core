"""`aef loop score` — the task metric read directly (ADR 0113)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aef.cli.main import main
from aef.harness.checks import TaskCheck
from aef.harness.corpus import CorpusManifest, Scenario, Split, save_manifest, save_scenario
from aef.kernel import GraphExecutor
from aef.services.runtime import agent_services
from aef.state import AEFState

ENTRYPOINT = "agents.demo.graph:build_graph"


def _corpus(tmp_path: Path) -> Path:
    """Two train scenarios with checks the demo passes, one validation scenario
    whose check the demo cannot pass (it writes quality 0.0 and errors), one
    unchecked."""
    from agents.demo.graph import build_graph

    graph = build_graph()
    root = tmp_path / "corpus"
    manifest = CorpusManifest()

    def add(sid: str, split: Split, wm: dict[str, int], checks: tuple[TaskCheck, ...]) -> None:
        state = AEFState(run_id=sid, agent_id="a", objective=f"task {sid}", working_memory=wm)
        recorded = GraphExecutor(graph.compile(), agent_services()).run(state, record_trace=True)
        assert recorded.trace is not None
        scenario = Scenario(
            id=sid,
            split=split,
            graph_id="demo_agent",
            graph_version="0.1.0",
            initial_state=state,
            trace=recorded.trace,
            recorded_at=datetime(2026, 9, 3, tzinfo=UTC),
            checks=checks,
        )
        save_scenario(root, scenario)
        manifest.ids[sid] = split

    quality_ok = (TaskCheck(path="scores.quality", op="equals", value=1.0),)
    add("easy-a", Split.TRAIN, {"difficulty": 1, "quality_needed": 1}, quality_ok)
    add("easy-b", Split.TRAIN, {"difficulty": 2, "quality_needed": 2}, quality_ok)
    add("hard", Split.VALIDATION, {"difficulty": 9, "quality_needed": 9}, quality_ok)
    add("unchecked", Split.VALIDATION, {"difficulty": 1, "quality_needed": 1}, ())
    save_manifest(root, manifest)
    return root


def test_score_prints_one_scalar_per_split_with_statistics(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    code = main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--json", "--repeat", "3"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    train, val = report["train"], report["validation"]
    assert (train["n"], train["with_checks"]) == (2, 2)
    assert train["mean"] == 1.0
    assert val["per_scenario"] == {"hard": 0.0, "unchecked": 1.0}
    assert val["mean"] == 0.5
    assert "ci95" in val and "stdev" in val
    # Deterministic graph, pinned clock: three identical runs, zero spread.
    assert train["repeat_mean_spread"] == 0.0
    assert report["repeat"] == 3


def test_score_refuses_the_holdout_without_the_flag(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    code = main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--splits", "holdout"])
    assert code != 0
    assert "holdout" in capsys.readouterr().err


def test_score_refuses_a_corpus_that_lost_its_failing_cases(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Reproduced (ADR 0141): delete the scenario the graph fails and this
    command reported a better number, exit 0, with nothing complaining —
    while `recorder.refuse_existing_ids` justified its own rule by citing
    `check_never_shrinks`, which had no production caller anywhere.

    Retiring a scenario deliberately means editing `corpus/manifest.json`,
    which is a visible act in git rather than a silent deletion.
    """
    root = _corpus(tmp_path)
    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root)]) == 0
    capsys.readouterr()

    (root / "validation" / "hard.json").unlink()

    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root)]) != 0
    err = capsys.readouterr().err
    assert "corpus shrank" in err
    assert "hard" in err


def test_score_human_output_lists_each_scenario(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root)]) == 0
    out = capsys.readouterr().out
    assert "task metric" in out
    assert "0.0000  hard" in out
    assert "1.0000  easy-a" in out


# --- `--config`'s policy reaches the scored run (ADR 0125) ---

_POLICY_GRAPH = """
from aef.kernel import END, Graph, Node
from aef.security.tool import Tool, ToolCall
from aef.state import Plan, StateDelta


class NetTool(Tool):
    name = "net"
    required_scopes = ("net.read",)

    def invoke(self, arguments):
        return {}


def do(state, ctx, services):
    result = services.policy_engine.evaluate(NetTool(), ToolCall(tool_name="net", arguments={}))
    if result.allowed:
        return (
            StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
            END,
        )
    return (
        StateDelta(
            plan=Plan(goal=state.objective, status="failed"),
            errors=[{"node_id": "do", "error": "denied"}],
        ),
        END,
    )


def build_graph():
    return Graph(
        id="policy_agent", version="1",
        nodes={"do": Node(id="do", version="1", fn=do, deterministic=True)},
        edges=[], entry_node="do",
    )
"""

_ALLOWING_YAML = (
    "model_provider:\n  impl: claude_code\n  model: claude-fable-5-1\n"
    "memory:\n  impl: in_memory\nobjectives: x\ntools:\n  allow: [net.read]\n"
)


def _policy_corpus(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:  # type: ignore[no-untyped-def]
    import sys

    from aef.security.tool import PolicyConfig

    pkg = tmp_path / "pkg"
    (pkg / "polagent").mkdir(parents=True)
    (pkg / "polagent" / "__init__.py").write_text("")
    (pkg / "polagent" / "graph.py").write_text(_POLICY_GRAPH)
    monkeypatch.syspath_prepend(str(pkg))
    sys.modules.pop("polagent.graph", None)
    sys.modules.pop("polagent", None)

    from polagent.graph import build_graph  # type: ignore[import-not-found]

    graph = build_graph()
    root = tmp_path / "polcorpus"
    manifest = CorpusManifest()
    state = AEFState(run_id="p1", agent_id="a", objective="o")
    recorded = GraphExecutor(graph.compile(), agent_services(policy=PolicyConfig())).run(
        state, record_trace=True
    )
    assert recorded.trace is not None
    save_scenario(
        root,
        Scenario(
            id="p1",
            split=Split.TRAIN,
            graph_id="policy_agent",
            graph_version="1",
            initial_state=state,
            trace=recorded.trace,
            recorded_at=datetime(2026, 9, 3, tzinfo=UTC),
            checks=(TaskCheck(path="scores.quality", op="equals", value=1.0),),
        ),
    )
    manifest.ids["p1"] = Split.TRAIN
    save_manifest(root, manifest)

    config = tmp_path / "aef.yaml"
    config.write_text(_ALLOWING_YAML)
    return root, config


def test_score_applies_the_configs_policy_like_aef_run_does(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`run_scenario` was called with no policy, so `loop score` judged every
    tool call deny-by-default while `aef run --config` and the gates
    (`_policy_from_base_ref`) allowed it from the same `aef.yaml`. Reproduced
    at 0.0 here against 1.0 there, on identical code and one config file."""
    root, config = _policy_corpus(tmp_path, monkeypatch)
    code = main(
        [
            "loop",
            "score",
            "polagent.graph:build_graph",
            "--corpus",
            str(root),
            "--json",
            "--config",
            str(config),
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["train"]["mean"] == 1.0


def test_score_without_a_config_is_still_deny_by_default(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The control. Carrying the policy in must not become a way for a scope
    to arrive without an owner asking for it."""
    root, _config = _policy_corpus(tmp_path, monkeypatch)
    code = main(["loop", "score", "polagent.graph:build_graph", "--corpus", str(root), "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["train"]["mean"] == 0.0


# --- `--json` says WHY a scenario scored what it did (ADR 0166) -------------
#
# `loop score --json` emitted per-scenario scores and a cassette hit/miss
# count, and neither the `failure` string nor the check failures that
# `run_scenario` already computes. A 0.0000 meaning "the provider died" and a
# 0.0000 meaning "the answer was wrong" were indistinguishable, and telling
# them apart in ADR 0156 took inferring from split-level token accounting.

_MODEL_GRAPH = """
from aef.kernel import END, Graph, Node, SideEffect
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.state import Plan, Provenance, StateDelta


def do(state, ctx, services):
    result = services.require_model_provider().complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content=state.objective),),
            model="",
        )
    )
    prov = Provenance(
        node_id=ctx.node_id,
        graph_version=ctx.graph_version,
        model=result.model or None,
        ts=ctx.now,
        trace_id=ctx.trace_id,
        token_cost=result.input_tokens + result.output_tokens,
    )
    return (
        StateDelta(
            plan=Plan(goal=state.objective, status="done"),
            working_memory={"answer": result.content},
            provenance=[prov],
        ),
        END,
    )


def build_graph():
    return Graph(
        id="model_agent", version="1",
        nodes={"do": Node(
            id="do", version="1", fn=do, deterministic=False,
            side_effects=SideEffect.EXTERNAL_CALL,
            idempotency_key_fn=lambda s: f"{s.run_id}:do",
        )},
        edges=[], entry_node="do",
    )
"""


def _attribution_corpus(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    """Two scenarios of one model-calling graph, differing only in whether the
    cassette can answer: `wrong-answer` replays a recorded reply that fails an
    owner check; `provider-died` has an EMPTY cassette, so the call misses and
    the node raises — which is how ADR 0156's live arm was built."""
    import sys

    from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider
    from aef.providers.cassette_provider import RecordedCall

    pkg = tmp_path / "pkg"
    (pkg / "modagent").mkdir(parents=True)
    (pkg / "modagent" / "__init__.py").write_text("")
    (pkg / "modagent" / "graph.py").write_text(_MODEL_GRAPH)
    monkeypatch.syspath_prepend(str(pkg))
    sys.modules.pop("modagent.graph", None)
    sys.modules.pop("modagent", None)

    from modagent.graph import build_graph  # type: ignore[import-not-found]

    calls: list[RecordedCall] = []

    class Stub(ModelProvider):
        def complete(self, request: CompletionRequest) -> CompletionResult:
            result = CompletionResult(content="blue", model="stub", input_tokens=7, output_tokens=3)
            calls.append(RecordedCall.of(request, result))
            return result

    graph = build_graph()
    root = tmp_path / "attcorpus"
    manifest = CorpusManifest()
    checks = (TaskCheck(path="working_memory.answer", op="contains", value="red"),)

    for sid, keep_cassette in (("wrong-answer", True), ("provider-died", False)):
        calls.clear()
        state = AEFState(run_id=sid, agent_id="a", objective="name a colour")
        recorded = GraphExecutor(graph.compile(), agent_services(model_provider=Stub())).run(
            state, record_trace=True
        )
        assert recorded.trace is not None
        save_scenario(
            root,
            Scenario(
                id=sid,
                split=Split.TRAIN,
                graph_id="model_agent",
                graph_version="1",
                initial_state=state,
                trace=recorded.trace,
                recorded_at=datetime(2026, 9, 4, tzinfo=UTC),
                checks=checks,
                model_calls=tuple(calls) if keep_cassette else (),
            ),
        )
        manifest.ids[sid] = Split.TRAIN
    save_manifest(root, manifest)
    return root


def test_json_distinguishes_a_dead_provider_from_a_wrong_answer(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = _attribution_corpus(tmp_path, monkeypatch)
    code = main(["loop", "score", "modagent.graph:build_graph", "--corpus", str(root), "--json"])
    assert code == 0
    train = json.loads(capsys.readouterr().out)["train"]
    # Both score 0.0000. Before this key existed, that was the whole report.
    assert train["per_scenario"] == {"provider-died": 0.0, "wrong-answer": 0.0}

    died = train["attribution"]["provider-died"]
    assert "failure" in died and "ModelProviderError" in died["failure"]
    assert "checks_failed" not in died  # the run never got far enough to answer

    wrong = train["attribution"]["wrong-answer"]
    assert "failure" not in wrong  # it ran cleanly
    assert wrong["checks"] == "0/1 passed"
    assert wrong["checks_failed"] == ["working_memory.answer contains 'red': got 'blue'"]


def test_a_scenario_with_nothing_to_report_is_absent_from_the_attribution(  # type: ignore[no-untyped-def]
    tmp_path: Path, capsys
) -> None:
    """The control: attribution lists what went wrong, not a row per scenario,
    so a split where everything passed reports an empty object."""
    root = _corpus(tmp_path)
    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["train"]["attribution"] == {}
    assert set(report["validation"]["attribution"]) == {"hard"}


def test_human_output_says_why_a_scenario_failed(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _corpus(tmp_path)
    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root)]) == 0
    out = capsys.readouterr().out
    assert "0.0000  hard" in out
    assert "check failed: scores.quality equals 1.0" in out
