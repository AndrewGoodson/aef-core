"""`aef loop bootstrap` at the CLI boundary (ADR 0138).

The harness rules are tested in `tests/harness/test_bootstrap.py`. What is
tested here is what an adopter actually types on day one, and the two things
only the boundary decides: the exit code, and whether the printed output is
enough to act on without reading the source.
"""

import json
from pathlib import Path

from aef.cli.main import main
from aef.harness.corpus import Expected, Split, load_corpus

MODULE = "agents.demo.graph"


def _inputs(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "objective": "an easy task",
                    "working_memory": {"difficulty": 1, "quality_needed": 1},
                    "checks": [{"path": "scores.quality", "op": "equals", "value": 1.0}],
                },
                {"objective": "a moderate task", "working_memory": {"difficulty": 3}},
                {
                    "id": "beyond-the-budget",
                    "objective": "a task past the retry budget",
                    "working_memory": {"difficulty": 9},
                    "budget_ms": 500,
                },
            ]
        )
    )
    return path


def test_bootstrap_fills_a_corpus_from_one_command(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The whole point: an adopter with an empty `corpus/` reaches scenarios
    without one `aef loop record` invocation per scenario, each needing its
    own hand-written --working-memory blob (ADR 0074 made that possible, not
    cheap)."""
    corpus = tmp_path / "corpus"
    code = main(
        [
            "loop",
            "bootstrap",
            MODULE,
            "--corpus",
            str(corpus),
            "--inputs",
            str(_inputs(tmp_path / "inputs.json")),
            "--no-loop-state",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out

    scenarios = load_corpus(corpus).scenarios
    assert len(scenarios) == 3
    assert {s.split for s in scenarios} == {Split.TRAIN}
    assert all(s.expected is Expected.UNSPECIFIED for s in scenarios)
    assert {s.id for s in scenarios} == {"bootstrap-1", "bootstrap-2", "beyond-the-budget"}

    assert "1 of 3 recorded run(s) FAILED: 1 raised or ended with a failed plan" in out
    assert "beyond-the-budget" in out
    # Ready to paste, with the objective and working memory filled in.
    assert "--scenario-id beyond-the-budget-tripwire" in out
    assert "--expected must_fail" in out


def test_the_suggested_tripwire_command_is_one_the_cli_accepts(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """A generated command nobody ran is a documentation claim. This runs it,
    and the corpus obligation `aef loop doctor` reports then has its tripwire
    without a single hand-written scenario."""
    corpus = tmp_path / "corpus"
    main(
        [
            "loop",
            "bootstrap",
            MODULE,
            "--corpus",
            str(corpus),
            "--inputs",
            str(_inputs(tmp_path / "inputs.json")),
            "--no-loop-state",
        ]
    )
    capsys.readouterr()

    assert (
        main(
            [
                "loop",
                "record",
                MODULE,
                "--corpus",
                str(corpus),
                "--scenario-id",
                "beyond-the-budget-tripwire",
                "--objective",
                "a task past the retry budget",
                "--working-memory",
                json.dumps({"difficulty": 9}),
                "--split",
                "validation",
                "--expected",
                "must_fail",
            ]
        )
        == 0
    )
    tripwires = [s for s in load_corpus(corpus).scenarios if s.expected is Expected.MUST_FAIL]
    assert [s.id for s in tripwires] == ["beyond-the-budget-tripwire"]


def test_bootstrap_refuses_to_rerun_over_its_own_output(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    corpus = tmp_path / "corpus"
    inputs = _inputs(tmp_path / "inputs.json")
    assert (
        main(
            [
                "loop",
                "bootstrap",
                MODULE,
                "--corpus",
                str(corpus),
                "--inputs",
                str(inputs),
                "--no-loop-state",
            ]
        )
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "loop",
            "bootstrap",
            MODULE,
            "--corpus",
            str(corpus),
            "--inputs",
            str(inputs),
            "--no-loop-state",
        ]
    )
    assert code != 0
    assert "already exist" in capsys.readouterr().err
    assert len(load_corpus(corpus).scenarios) == 3


def test_a_bootstrap_that_recorded_nothing_does_not_exit_zero(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """A workflow keying off exit 0 would believe a corpus had been seeded.
    The ready loop's rule is that the tooling does not report green for
    something that did not happen."""
    module = tmp_path / "raises_graph.py"
    module.write_text(
        "from aef.kernel import Graph, Node\n"
        "def work(state, ctx, services):\n"
        "    raise RuntimeError('no credential')\n"
        "def build_graph():\n"
        "    return Graph(id='x', version='0.1.0',\n"
        "                 nodes={'work': Node(id='work', version='0.1.0', fn=work,\n"
        "                                     deterministic=False)},\n"
        "                 edges=[], entry_node='work')\n"
    )
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        code = main(
            [
                "loop",
                "bootstrap",
                "raises_graph",
                "--corpus",
                str(tmp_path / "corpus"),
                "--inputs",
                str(_inputs(tmp_path / "inputs.json")),
                "--no-loop-state",
            ]
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("raises_graph", None)

    assert code != 0
    out = capsys.readouterr().out
    assert "NOTHING was recorded" in out
    assert "no credential" in out


def test_an_engaged_kill_switch_stops_a_bootstrap(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """corpus/ IS the evidence every behavioural gate is measured against,
    and a halted loop must not have it changed underneath it (ADR 0069) —
    the same check `harvest` makes for the same reason."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "HALTED").write_text("owner stopped the loop\n")
    corpus = tmp_path / "corpus"

    code = main(
        [
            "loop",
            "bootstrap",
            MODULE,
            "--corpus",
            str(corpus),
            "--inputs",
            str(_inputs(tmp_path / "inputs.json")),
            "--state",
            str(state),
        ]
    )
    assert code == 2, "a halt is exit 2, not a rejection's 1"
    assert "HALTED" in capsys.readouterr().out
    assert not corpus.exists(), "the corpus was written while the loop was halted"


def test_day_one_says_no_loop_state_rather_than_omitting_the_flag(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Every other loop subcommand requires --state. This one cannot: it is
    what an adopter runs before a loop state dir exists.

    This test used to be named `test_state_is_optional_because_day_one_has_no_
    loop_yet` and pinned the defect: omitting `--state` skipped the kill-switch
    check entirely, so the documented invocation grew a HALTED loop's corpus
    and exited 0 (ADR 0141). Day one is still reachable — it is now something
    the owner SAYS, with `--no-loop-state`, rather than something silence is
    read as.
    """
    corpus = tmp_path / "corpus"
    assert (
        main(
            [
                "loop",
                "bootstrap",
                MODULE,
                "--corpus",
                str(corpus),
                "--inputs",
                str(_inputs(tmp_path / "inputs.json")),
                "--no-loop-state",
            ]
        )
        == 0
    )
    capsys.readouterr()

    # And neither flag is a refusal, not a silent skip.
    assert (
        main(
            [
                "loop",
                "bootstrap",
                MODULE,
                "--corpus",
                str(tmp_path / "corpus2"),
                "--inputs",
                str(_inputs(tmp_path / "inputs.json")),
            ]
        )
        != 0
    )
    assert "--no-loop-state" in capsys.readouterr().err
    assert not (tmp_path / "corpus2").exists()
    assert len(load_corpus(corpus).scenarios) == 3


def test_the_help_documents_the_inputs_shape_and_the_refusals(capsys) -> None:  # type: ignore[no-untyped-def]
    """An adopter learns the file format from `--help`, not from the source."""
    import pytest

    with pytest.raises(SystemExit):
        main(["loop", "bootstrap", "--help"])
    out = capsys.readouterr().out
    assert "objective" in out
    assert "working_memory" in out
    assert "TRAIN split only" in out
    assert "ADR 0060" in out


def test_an_engaged_kill_switch_stops_a_bootstrap_on_both_invocations(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    """The halt used to bind only when the caller asked it to.

    `cmd_bootstrap` read `if getattr(args, "state", None):`, and `--state` was
    optional — so with the switch engaged, the form WITH `--state` exited 2
    and the form WITHOUT it, which is the one ADR 0138's own Evidence block
    shows, exited 0 and grew the corpus of a halted loop (reproduced, ADR
    0141). Both forms are pinned here so the fix cannot regress to the one
    that was always correct.
    """
    state = tmp_path / "state"
    state.mkdir()
    (state / "HALTED").write_text("G6 tripwire fired\n")
    inputs = str(_inputs(tmp_path / "inputs.json"))

    with_state = tmp_path / "corpus-with"
    assert (
        main(
            [
                "loop",
                "bootstrap",
                MODULE,
                "--corpus",
                str(with_state),
                "--inputs",
                inputs,
                "--state",
                str(state),
            ]
        )
        == 2
    ), "a halt is exit 2, not a rejection's 1"
    assert "HALTED" in capsys.readouterr().out
    assert not with_state.exists()

    # The documented invocation. It must not be able to grow the corpus of a
    # halted loop either — by refusing to guess that there is no loop.
    without_state = tmp_path / "corpus-without"
    assert (
        main(["loop", "bootstrap", MODULE, "--corpus", str(without_state), "--inputs", inputs]) != 0
    )
    assert not without_state.exists(), "a halted loop's corpus grew from the documented form"

    # And the escape hatch is not a way round the halt when a loop DOES exist:
    # it is an assertion about the world, and it is the owner who makes it.
    lying = tmp_path / "corpus-lying"
    assert (
        main(
            [
                "loop",
                "bootstrap",
                MODULE,
                "--corpus",
                str(lying),
                "--inputs",
                inputs,
                "--no-loop-state",
            ]
        )
        == 0
    )


def test_one_malformed_scenario_is_a_named_refusal_not_a_traceback(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """`refuse_existing_ids` calls `load_corpus`, so any malformed file in the
    corpus fails the whole command. It reached `main()`'s catch-all — exit 1
    rather than this command's own rejection code — and named no file
    (ADR 0141)."""
    corpus = tmp_path / "corpus"
    (corpus / "train").mkdir(parents=True)
    (corpus / "train" / "broken.json").write_text('{"id": "broken", "split": "train"}')

    code = main(
        [
            "loop",
            "bootstrap",
            MODULE,
            "--corpus",
            str(corpus),
            "--inputs",
            str(_inputs(tmp_path / "inputs.json")),
            "--no-loop-state",
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "broken.json" in err, "the refusal must name the file"
    assert "malformed scenario payload" in err


# --- --memory: the failing run's reflection outlives the process (ADR 0145) --

REFLECTING_AGENT = """from aef.kernel import END, Edge, Graph, Node
from aef.reasoning.nodes import make_reflect_node
from aef.state import Plan, StateDelta

RETRY_BUDGET = 3


def work_node(state, ctx, services):
    if int(state.working_memory.get("difficulty", 1)) > RETRY_BUDGET:
        return StateDelta(plan=Plan(goal=state.objective, status="failed"),
                          errors=[{"node_id": ctx.node_id, "error": "gave up"}],
                          scores={"quality": 0.0}), "reflect"
    return StateDelta(plan=Plan(goal=state.objective, status="done"),
                      scores={"quality": 1.0}), "reflect"


def build_graph():
    work = Node(id="work", version="0.1.0", fn=work_node, deterministic=True)
    return Graph(id="mine", version="0.1.0",
                 nodes={"work": work, "reflect": make_reflect_node(route=END)},
                 edges=[Edge(from_node="work", to_node="reflect")],
                 entry_node="work")
"""


def _reflecting_module(tmp_path: Path, monkeypatch) -> str:  # type: ignore[no-untyped-def]
    (tmp_path / "reflecting_agent.py").write_text(REFLECTING_AGENT)
    monkeypatch.syspath_prepend(str(tmp_path))
    return "reflecting_agent"


def test_bootstrap_memory_is_the_file_the_cycle_reads(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """The measured close of ADR 0139's requirement 4. Before this, an adopter
    had to follow bootstrap with a hand-written failing `aef run --memory`,
    because bootstrap gave every input its own throwaway store.

    Read back through `MemoryEvidence.from_store` — the proposer's own reader,
    over a NEW `FileMemoryStore` — rather than through a printed line, because
    a printed line proves only that a string was printed (ADR 0139's own
    finding about the test it replaced).
    """
    from aef.harness.memory_store import FileMemoryStore
    from aef.harness.proposer import MemoryEvidence

    module = _reflecting_module(tmp_path, monkeypatch)
    memory = tmp_path / "state" / "memory.jsonl"
    code = main(
        [
            "loop",
            "bootstrap",
            module,
            "--corpus",
            str(tmp_path / "corpus"),
            "--inputs",
            str(_inputs(tmp_path / "inputs.json")),
            "--no-loop-state",
            "--memory",
            str(memory),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "1 of 3 recorded run(s) FAILED: 1 raised or ended with a failed plan" in out

    evidence = MemoryEvidence.from_store(FileMemoryStore(path=memory))
    assert [r.run_id for r in evidence.records] == ["beyond-the-budget"]
    assert evidence.failing_nodes()[0][0] == "work"


def test_without_memory_the_cycle_still_has_nothing_to_read(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The control. `--memory` is what changed; its absence must behave
    exactly as it did, or the measurement above is measuring the fixture."""
    module = _reflecting_module(tmp_path, monkeypatch)
    assert (
        main(
            [
                "loop",
                "bootstrap",
                module,
                "--corpus",
                str(tmp_path / "corpus"),
                "--inputs",
                str(_inputs(tmp_path / "inputs.json")),
                "--no-loop-state",
            ]
        )
        == 0
    )
    assert not list(tmp_path.glob("**/*.jsonl"))


# --- --config: the recording pass, wired through `aef run`'s code path -------


def test_config_records_a_model_calling_graph_through_aef_runs_own_wiring(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    """ADR 0139: `aef loop bootstrap` on a model-calling graph exits 1 with
    `no live provider to fall through to`, because the cassette the gates
    replay from does not exist until something makes the call once.

    The provider here is a FAKE, substituted at `aef.cli.run`'s own import of
    `build_model_provider` — the single construction site both commands read
    through. What this proves is the wiring and the accounting. **The live
    recording path is not exercised**: all three shipped impls
    (`claude_code`, `codex`, `anthropic`) make real calls and there was no
    quota to spend on one.
    """
    from aef.providers.base import CompletionRequest, CompletionResult, ModelProvider

    seen: list[str] = []

    class _FakeProvider(ModelProvider):
        name = "fake"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            seen.append(request.model)
            return CompletionResult(
                content="a short summary mentioning the kernel.",
                model="fake-1",
                input_tokens=3,
                output_tokens=5,
            )

    import aef.cli.run as cli_run

    monkeypatch.setattr(cli_run, "build_model_provider", lambda config: _FakeProvider())

    config = tmp_path / "aef.yaml"
    config.write_text(
        "model_provider:\n"
        "  impl: claude_code\n"
        "  model: fake-1\n"
        "memory:\n"
        "  impl: in_memory\n"
        'objectives: "summarise a passage"\n'
    )
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps(
            [
                {
                    "objective": "summarise",
                    "working_memory": {"text": "the kernel executes nodes", "max_words": 10},
                }
            ]
        )
    )
    corpus = tmp_path / "corpus"

    code = main(
        [
            "loop",
            "bootstrap",
            "agents.summary.graph",
            "--corpus",
            str(corpus),
            "--inputs",
            str(inputs),
            "--no-loop-state",
            "--config",
            str(config),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert seen, "the configured provider was never reached"

    # The cassette exists now — which is the whole point: the gates replay it
    # with no credential (ADR 0123).
    scenario = load_corpus(corpus).scenarios[0]
    assert len(scenario.model_calls) == len(seen)
    assert f"recording spent {len(seen)} live model call(s)" in out
    assert "SUPPOSED to be live" in out


def _config_reading_handlers() -> dict[str, object]:
    """Every `aef loop` subcommand whose parser declares `--config`, read from
    the PARSER rather than from a list kept by hand.

    A hand-kept list is how this test passed for `cmd_bootstrap` while
    `cmd_record` — two functions below it in the same file, with the same flag
    and the same comment — had its own private `load_agent_config` +
    `build_model_provider` and dropped the adopter's policy on the floor
    (ADR 0149). A new `--config` command joins this test the moment its parser
    is written, and cannot be forgotten.
    """
    import argparse

    from aef.cli.loop import add_loop_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_loop_parser(subparsers)
    loop = subparsers.choices["loop"]
    loop_subs = next(
        action for action in loop._actions if isinstance(action, argparse._SubParsersAction)
    )
    found: dict[str, object] = {}
    for name, sub in loop_subs.choices.items():
        options = {opt for action in sub._actions for opt in action.option_strings}
        if "--config" in options:
            found[name] = sub.get_default("handler")
    return found


def test_every_loop_command_reads_its_config_through_aef_runs_construction_site() -> None:
    """A source assertion, and it is the property: no behavioural test can see
    WHICH of two identical constructions crossed the boundary.

    `cmd_bootstrap` used to build the model provider and the reflection impl
    itself and drop `policies`, `tools.allow` and `evaluator.suites` on the
    floor — so a scenario recorded here pinned behaviour under the engine's
    default policy while `aef run` used the adopter's. Two constructions of
    one dependency drifting apart is ADR 0091's finding.

    ADR 0145 fixed that for `cmd_bootstrap` and wrote this test for
    `cmd_bootstrap` alone, and its "the private construction is abolished"
    claim covered ONE of two callers: `cmd_record` still had its own, and
    `cmd_score` a third. Applying the old test verbatim to `cmd_record` failed.
    So the assertion is made over EVERY `--config` command the parser
    declares, and the enumeration is the parser's, not a list somebody has to
    remember to extend.

    Two lawful shapes, and only two. A command that builds `Services` here
    reads the config through `aef.cli.run.build_run_config`. A command that
    hands the path to the harness (`gate`, `cycle`, `run`) constructs nothing
    at all — the harness reads that config from the BASE REF, deliberately,
    so a candidate cannot widen the rules it is judged by. Parsing `aef.yaml`
    inside `aef/cli/loop.py` is what neither may do.
    """
    import ast
    import inspect

    forbidden = {"load_agent_config", "build_model_provider", "build_policy_config"}
    handlers = _config_reading_handlers()
    assert set(handlers) >= {"record", "bootstrap", "score", "gate", "cycle", "run"}, handlers

    for name, handler in sorted(handlers.items()):
        tree = ast.parse(inspect.getsource(handler))  # type: ignore[arg-type]
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        leaked = called & forbidden
        assert not leaked, (
            f"`aef loop {name}` parses aef.yaml itself ({sorted(leaked)}) — a second "
            f"construction site, which is how `record` came to record under the engine's "
            f"default policy while `aef run` used the adopter's (ADR 0149)"
        )
        reads_config = any(
            isinstance(node, ast.Attribute) and node.attr == "config" for node in ast.walk(tree)
        )
        if not reads_config:
            continue
        hands_off = "_config" in called  # `gate`/`cycle`/`run`: LoopConfig.config_path
        assert "build_run_config" in called or hands_off, (
            f"`aef loop {name}` reads --config but neither goes through "
            f"`build_run_config` nor hands the path to the harness"
        )


# --------------------------------------------------------------------------
# The two recorders must agree — ADR 0149's F1, behaviourally
# --------------------------------------------------------------------------

POLICY_AGENT = """
from typing import Any

from aef.kernel import END, Context, Edge, Graph, Node, Route, Services, SideEffect
from aef.reasoning.nodes import make_reflect_node
from aef.security.tool import Tool, ToolCall
from aef.state import AEFState, Plan, Provenance, StateDelta


class Reader(Tool):
    name = "reader"
    required_scopes = ("read:docs",)

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}


def work_node(state, ctx, services):
    decision = str(
        services.require_policy_engine()
        .evaluate(Reader(), ToolCall(tool_name="reader", arguments={}, risk=0.5))
        .decision
    )
    prov = Provenance(node_id=ctx.node_id, graph_version=ctx.graph_version,
                      ts=ctx.now, trace_id=ctx.trace_id, token_cost=1)
    if decision == "allow":
        return StateDelta(working_memory={"decision": decision},
                          plan=Plan(goal=state.objective, status="done"),
                          scores={"quality": 1.0}, provenance=[prov]), "reflect"
    return StateDelta(working_memory={"decision": decision},
                      plan=Plan(goal=state.objective, status="failed"),
                      errors=[{"node_id": ctx.node_id, "error": "tool call " + decision}],
                      scores={"quality": 0.0}, provenance=[prov]), "reflect"


def build_graph():
    return Graph(
        id="pol", version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work_node,
                            deterministic=False, side_effects=SideEffect.PURE),
               "reflect": make_reflect_node(route=END)},
        edges=[Edge(from_node="work", to_node="reflect")],
        entry_node="work",
    )
"""

PERMISSIVE_YAML = """extends: _base
objectives: "read the docs"
model_provider: {impl: claude_code, model: claude-opus-5, fallback: []}
memory: {impl: in_memory}
tools: {allow: ["read:docs"]}
policies: {require_hitl_above_risk: 0.9}
evaluator: {suites: []}
"""


def _policy_agent(tmp_path: Path, monkeypatch) -> tuple[str, Path]:  # type: ignore[no-untyped-def]
    """A graph whose recorded outcome IS the adopter's policy: one tool call
    needing `read:docs` at risk 0.5, which the config below allows and the
    engine's deny-by-default default does not."""
    (tmp_path / "policy_agent.py").write_text(POLICY_AGENT)
    monkeypatch.syspath_prepend(str(tmp_path))
    config = tmp_path / "aef.yaml"
    config.write_text(PERMISSIVE_YAML)
    return "policy_agent", config


def test_record_and_bootstrap_record_the_same_scenario_from_one_config(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """The behavioural half of ADR 0149's F1, and the test the seam hunt found
    missing: nothing anywhere compared what the two recorders produce.

    Same graph, same `aef.yaml`, same objective. `cmd_bootstrap` went through
    `build_run_config`; `cmd_record` had its own `load_agent_config` +
    `build_model_provider` and passed `agent_services` NO policy, so the
    agent's `read:docs` tool call was denied deny-by-default. Reproduced:
    bootstrap recorded `{'decision': 'allow'}` / plan `done`, record recorded
    `{'decision': 'deny'}` / plan `failed`, from one config file.
    """
    module, config = _policy_agent(tmp_path, monkeypatch)
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps([{"id": "same", "objective": "read the docs"}]))

    assert (
        main(
            [
                "loop",
                "bootstrap",
                module,
                "--corpus",
                str(tmp_path / "boot"),
                "--inputs",
                str(inputs),
                "--no-loop-state",
                "--config",
                str(config),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "loop",
                "record",
                module,
                "--corpus",
                str(tmp_path / "rec"),
                "--scenario-id",
                "same",
                "--objective",
                "read the docs",
                "--split",
                "train",
                "--config",
                str(config),
            ]
        )
        == 0
    )

    booted = load_corpus(tmp_path / "boot").scenarios[0]
    recorded = load_corpus(tmp_path / "rec").scenarios[0]

    def shape(scenario):  # type: ignore[no-untyped-def]
        first = scenario.trace[0]
        return (
            tuple(r.node_id for r in scenario.trace),
            first.delta.working_memory,
            first.delta.plan.status if first.delta.plan else None,
            len(first.delta.errors),
        )

    assert shape(booted) == shape(recorded), (
        "the two recorders disagree about the same graph under the same config"
    )
    # And they agree on the ADOPTER's answer, not the engine's default.
    assert booted.trace[0].delta.working_memory == {"decision": "allow"}


def test_record_refuses_must_fail_when_only_the_dropped_policy_made_it_fail(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    """The consequence that made F1 critical rather than untidy.

    `aef loop record --expected must_fail` is the only documented way to mint
    a tripwire, and its guard refuses the label when the agent COMPLETES the
    task. Under the dropped config the task did not complete — the tool call
    was denied — so the guard accepted a tripwire that is not impossible, only
    misconfigured. `scenario_runner` then applies the owner's policy at gate
    time, the scenario passes, `tripwire_hit` fires, `regressed` is true, and
    G2 rejects every candidate forever reporting reward hacking.

    Reproduced before the fix: exit 0, `recorded tripwire-1 (validation)`.
    """
    module, config = _policy_agent(tmp_path, monkeypatch)
    code = main(
        [
            "loop",
            "record",
            module,
            "--corpus",
            str(tmp_path / "tw"),
            "--scenario-id",
            "tripwire-1",
            "--objective",
            "read the docs",
            "--split",
            "validation",
            "--expected",
            "must_fail",
            "--config",
            str(config),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out
    assert "refusing to label" in captured.err
    assert not (tmp_path / "tw" / "validation").exists()
