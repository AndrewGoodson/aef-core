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

    assert "1 of 3 recorded run(s) FAILED." in out
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
    assert "1 of 3 recorded run(s) FAILED." in out

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


def test_bootstrap_reads_its_config_through_aef_runs_construction_site() -> None:
    """A source assertion, and it is the property: no behavioural test can see
    WHICH of two identical constructions crossed the boundary.

    `cmd_bootstrap` used to build the model provider and the reflection impl
    itself and drop `policies`, `tools.allow` and `evaluator.suites` on the
    floor — so a scenario recorded here pinned behaviour under the engine's
    default policy while `aef run` used the adopter's. Two constructions of
    one dependency drifting apart is ADR 0091's finding.
    """
    import ast
    import inspect

    from aef.cli.loop import cmd_bootstrap

    tree = ast.parse(inspect.getsource(cmd_bootstrap))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "build_run_config" in called, "bootstrap stopped reading aef run's code path"
    assert "build_model_provider" not in called, (
        "a second model-provider construction site has come back"
    )
    assert "load_agent_config" not in called, "bootstrap is parsing aef.yaml a second time"
