from pathlib import Path

import pytest

from aef.cli.main import main


def test_init_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["init", "myagent", "--dir", str(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert (tmp_path / "agents" / "myagent" / "graph.py").exists()


def test_adopt_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "agent.py").write_text("import anthropic\n")
    exit_code = main(["adopt", "--dir", str(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "detected framework: raw_sdk" in out
    assert "migration checklist" in out


def test_doctor_via_cli_fails_on_empty_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["doctor", "--dir", str(tmp_path)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out


def test_doctor_via_cli_passes_after_adopt(tmp_path: Path) -> None:
    main(["adopt", "--dir", str(tmp_path)])
    exit_code = main(["doctor", "--dir", str(tmp_path)])
    assert exit_code == 0


def test_run_via_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module_code = """
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, StateDelta


def hello_node(state, ctx, services):
    return StateDelta(working_memory={"ran": True}), END


def build_graph() -> Graph:
    node = Node(id="hello", version="0.1.0", fn=hello_node, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"hello": node}, edges=[], entry_node="hello")
"""
    (tmp_path / "cli_main_test_mod.py").write_text(module_code)
    monkeypatch.syspath_prepend(str(tmp_path))

    exit_code = main(["run", "cli_main_test_mod", "--objective", "go"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert '"ran": true' in out


def test_run_via_cli_reports_error_for_bad_module(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["run", "no_such_module_at_all", "--objective", "go"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_eval_and_trace_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from aef.kernel import END, FileDurabilityBackend, Graph, GraphExecutor, Node, Services
    from aef.state import AEFState, Plan, StateDelta

    def _fn(state, ctx, services):
        return StateDelta(plan=Plan(goal="g", status="done")), END

    node = Node(id="n", version="1.0.0", fn=_fn, deterministic=True)
    graph = Graph(id="g", version="1.0.0", nodes={"n": node}, edges=[], entry_node="n")
    executor = GraphExecutor(graph.compile(), Services(durability=FileDurabilityBackend(tmp_path)))
    executor.run(AEFState(run_id="cli-run-1", agent_id="a1", objective="x"))

    eval_exit = main(["eval", "--checkpoints-dir", str(tmp_path), "--run-id", "cli-run-1"])
    assert eval_exit == 0
    eval_out = capsys.readouterr().out
    assert "task_completion=1.0" in eval_out

    trace_exit = main(["trace", "--checkpoints-dir", str(tmp_path), "--run-id", "cli-run-1"])
    assert trace_exit == 0
