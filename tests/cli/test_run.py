import sys
from pathlib import Path

import pytest

from aef.cli.run import run_graph_module


@pytest.fixture
def graph_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    module_code = """
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, StateDelta


def hello_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    return StateDelta(working_memory={"objective_seen": state.objective}), END


def build_graph() -> Graph:
    node = Node(id="hello", version="0.1.0", fn=hello_node, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"hello": node}, edges=[], entry_node="hello")
"""
    (tmp_path / "cli_test_graph_mod.py").write_text(module_code)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "cli_test_graph_mod"
    sys.modules.pop("cli_test_graph_mod", None)


def test_run_graph_module_executes_and_returns_final_state(graph_module: str) -> None:
    final_state = run_graph_module(graph_module, agent_id="a1", objective="do the thing")
    assert final_state.agent_id == "a1"
    assert final_state.working_memory == {"objective_seen": "do the thing"}


def test_run_graph_module_missing_build_graph_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "no_build_graph_mod.py").write_text("x = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ValueError, match="build_graph"):
        run_graph_module("no_build_graph_mod", agent_id="a1", objective="x")
