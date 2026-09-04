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
        main(["loop", "bootstrap", MODULE, "--corpus", str(corpus), "--inputs", str(inputs)]) == 0
    )
    capsys.readouterr()

    code = main(["loop", "bootstrap", MODULE, "--corpus", str(corpus), "--inputs", str(inputs)])
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


def test_state_is_optional_because_day_one_has_no_loop_yet(tmp_path: Path) -> None:
    """Every other loop subcommand requires --state. This one cannot: it is
    what an adopter runs before a loop state dir exists."""
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
            ]
        )
        == 0
    )
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
