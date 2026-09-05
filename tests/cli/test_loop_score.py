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


# ---------------------------------------------------------------------------
# `--memory`: a failed owner check becomes failure memory (ADR 0182, K3-5)
# ---------------------------------------------------------------------------
#
# ADR 0174 gave the check-failure producer to `aef loop bootstrap` and refused
# it to every GATE path — a gate that wrote to the adopter's durable store
# would let scoring a candidate manufacture the next one's evidence. That
# refusal stands and is asserted below.
#
# Wiring it into bootstrap ALONE left the other half open, which K2 measured
# (ADR 0180, S1b): staleness demotes a lesson by `runs_since_last_seen`, and
# with nothing producing the signature on a SCORED split the counter climbed
# to 17 by the seventeenth scenario while the lesson could never be re-seen —
# 0 with the producer here. `aef loop score` is neither a gate nor a
# recording: it scores the INCUMBENT the owner already trusts, in-process,
# over the owner's own corpus, with the owner naming the file.


def _records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _corpus_with_a_wrong_check(tmp_path: Path) -> Path:
    """One scenario the graph COMPLETES and whose owner check it fails.

    Not `_corpus`'s `hard`, deliberately: that run records an error of its
    own, and `check_failure_record` returns `None` for those on purpose — the
    run's own reflect node already wrote failure memory, and a second record
    would double-count one observation. The case this flag exists for is ADR
    0113's: a run that fails WITHOUT an error, which is exactly what an owner
    check is for.
    """
    from agents.demo.graph import build_graph

    root = tmp_path / "wrong-check-corpus"
    manifest = CorpusManifest()
    state = AEFState(
        run_id="wrong-one",
        agent_id="a",
        objective="an easy task",
        working_memory={"difficulty": 1, "quality_needed": 1},
    )
    recorded = GraphExecutor(build_graph().compile(), agent_services()).run(
        state, record_trace=True
    )
    assert recorded.trace is not None
    assert not recorded.final_state.errors, "the fixture must COMPLETE, or nothing is recorded"
    save_scenario(
        root,
        Scenario(
            id="wrong-one",
            split=Split.TRAIN,
            graph_id="demo_agent",
            graph_version="0.1.0",
            initial_state=state,
            trace=recorded.trace,
            recorded_at=datetime(2026, 9, 5, tzinfo=UTC),
            checks=(TaskCheck(path="scores.quality", op="equals", value=0.5),),
        ),
    )
    manifest.ids["wrong-one"] = Split.TRAIN
    save_manifest(root, manifest)
    return root


def test_scoring_without_memory_writes_nothing(tmp_path: Path) -> None:
    """The default is unchanged: no flag, no store, no record. `--repeat 3`,
    so a per-run write would be impossible to miss."""
    root = _corpus_with_a_wrong_check(tmp_path)
    memory = tmp_path / "memory.jsonl"

    assert main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--repeat", "3"]) == 0

    assert _records(memory) == []


def test_scoring_with_memory_writes_one_check_derived_failure(tmp_path: Path) -> None:
    """One scenario, one failed check, one record — the score is 0.0 and the
    run raised nothing, which is the case ADR 0113 added checks for."""
    root = _corpus_with_a_wrong_check(tmp_path)
    memory = tmp_path / "memory.jsonl"

    code = main(["loop", "score", ENTRYPOINT, "--corpus", str(root), "--memory", str(memory)])

    assert code == 0
    written = _records(memory)
    assert len(written) == 1, written
    assert written[0]["kind"] == "failure"
    assert written[0]["run_id"] == "wrong-one"
    assert "scores.quality" in str(written[0]["content"])


def test_a_run_that_errored_is_not_double_counted(tmp_path: Path) -> None:
    """The control, and the reason the fixture above is not `_corpus`'s
    `hard`: that scenario's run records an error of its own, so its reflect
    node already wrote failure memory and `check_failure_record` returns
    `None` (ADR 0174). A second record for one observation would inflate the
    occurrence count a lesson is formed from."""
    root = _corpus(tmp_path)
    memory = tmp_path / "memory.jsonl"

    assert (
        main(
            [
                "loop",
                "score",
                ENTRYPOINT,
                "--corpus",
                str(root),
                "--splits",
                "train,validation",
                "--memory",
                str(memory),
            ]
        )
        == 0
    )

    assert _records(memory) == []


def test_scoring_twice_writes_one(tmp_path: Path) -> None:
    """K2's idempotence, at the caller. `record_check_outcomes` keys on
    (run_id, signature), so a second `aef loop score` over the same corpus —
    and `--repeat`, which re-executes every scenario N times — leave the store
    exactly as the first pass did. Without that, a nightly score would inflate
    one lesson's occurrence count without a single new observation.
    """
    root = _corpus_with_a_wrong_check(tmp_path)
    memory = tmp_path / "memory.jsonl"
    argv = ["loop", "score", ENTRYPOINT, "--corpus", str(root), "--memory", str(memory)]

    assert main(argv) == 0
    after_one = _records(memory)
    assert main(argv) == 0
    assert main([*argv, "--repeat", "3"]) == 0

    assert _records(memory) == after_one, "a re-score manufactured a second record"


def test_cmd_score_is_the_only_caller_that_supplies_a_durable_store() -> None:
    """The refusal ADR 0174 made, and this does NOT reopen: a gate run that
    writes to the adopter's durable store lets scoring a candidate manufacture
    the next one's evidence.

    An AST scan over all of `aef/` rather than an assertion about one module,
    because the property is "no OTHER caller supplies one" — and the first
    version of this test scanned `isolated_suite`, which does not call
    `run_scenario` at all, so it proved nothing (mutation M13 SURVIVED, which
    is how that was found). The default is asserted too: a caller that passes
    nothing gets today's behaviour exactly.
    """
    import ast
    import inspect

    from aef.harness import scenario_runner

    assert inspect.signature(scenario_runner.run_scenario).parameters["memory"].default is None

    suppliers: set[str] = set()
    for path in sorted(Path("aef").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for holder in ast.walk(tree):
            if not isinstance(holder, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(holder):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name == "run_scenario" and any(kw.arg == "memory" for kw in node.keywords):
                    suppliers.add(f"{path.as_posix()}::{holder.name}")

    # `file::function`, not `file`: the first version of this asserted the FILE
    # and a planted `run_scenario(..., memory=...)` inside `cmd_gate` — the
    # same file — survived it (mutation M13).
    assert suppliers == {"aef/cli/loop.py::cmd_score"}, (
        f"a durable store reaches run_scenario from {sorted(suppliers)}; only `aef loop "
        f"score --memory`, which the OWNER names, may supply one (ADR 0174/0180)"
    )
