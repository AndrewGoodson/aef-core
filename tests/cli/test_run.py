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


def test_run_graph_module_without_config_leaves_model_provider_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_code = """
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, StateDelta


def check_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    is_none = services.model_provider is None
    return StateDelta(working_memory={"model_provider_is_none": is_none}), END


def build_graph() -> Graph:
    node = Node(id="check", version="0.1.0", fn=check_node, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"check": node}, edges=[], entry_node="check")
"""
    (tmp_path / "cli_no_config_mod.py").write_text(module_code)
    monkeypatch.syspath_prepend(str(tmp_path))
    final_state = run_graph_module("cli_no_config_mod", agent_id="a1", objective="x")
    assert final_state.working_memory == {"model_provider_is_none": True}


def test_run_graph_module_with_config_wires_a_real_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_code = """
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.providers.anthropic_provider import AnthropicProvider
from aef.state import AEFState, StateDelta


def check_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    is_anthropic = isinstance(services.model_provider, AnthropicProvider)
    return StateDelta(working_memory={"got_anthropic_provider": is_anthropic}), END


def build_graph() -> Graph:
    node = Node(id="check", version="0.1.0", fn=check_node, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"check": node}, edges=[], entry_node="check")
"""
    (tmp_path / "cli_with_config_mod.py").write_text(module_code)
    monkeypatch.syspath_prepend(str(tmp_path))

    config_path = tmp_path / "aef.yaml"
    config_path.write_text(
        "model_provider:\n  impl: anthropic\n  model: claude-x\n"
        "memory:\n  impl: in_memory\n"
        "objectives: test\n"
    )

    final_state = run_graph_module(
        "cli_with_config_mod", agent_id="a1", objective="x", config_path=config_path
    )
    assert final_state.working_memory == {"got_anthropic_provider": True}


def test_run_graph_module_with_config_unsupported_impl_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aef.config import UnsupportedProviderImplError

    (tmp_path / "cli_unused_mod.py").write_text(
        "from aef.kernel import Graph, Node, END\n"
        "def n(s, c, sv):\n    return None, END\n"
        "def build_graph():\n"
        "    node = Node(id='n', version='0.1.0', fn=n, deterministic=True)\n"
        "    return Graph(id='g', version='0.1.0', nodes={'n': node}, edges=[], entry_node='n')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config_path = tmp_path / "aef.yaml"
    config_path.write_text(
        "model_provider:\n"
        "  impl: openai\n"
        "  model: gpt-x\n"
        "memory:\n"
        "  impl: in_memory\n"
        "objectives: test\n"
    )

    with pytest.raises(UnsupportedProviderImplError, match="openai"):
        run_graph_module("cli_unused_mod", agent_id="a1", objective="x", config_path=config_path)


def test_run_graph_module_finds_a_package_relative_to_cwd_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the exact real-world sequence: `aef init` scaffolds
    agents/<name>/ one directory below where you're standing, then `aef run
    agents.<name>.graph` must find it from CWD alone — no manual sys.path
    setup, which is what a real CLI invocation gives you (unlike other
    tests here, which use monkeypatch.syspath_prepend to simulate an
    already-importable module). Running `aef` as an installed console
    script does NOT put CWD on sys.path automatically, unlike `python
    script.py` — this was a real bug (`No module named 'agents'`) caught
    by actually running `aef init` then `aef run`, not by reading the code."""
    agents_pkg = tmp_path / "agents" / "my_agent"
    agents_pkg.mkdir(parents=True)
    (tmp_path / "agents" / "__init__.py").write_text("")
    (agents_pkg / "__init__.py").write_text("")
    (agents_pkg / "graph.py").write_text(
        "from aef.kernel import END, Graph, Node\n"
        "from aef.state import StateDelta\n"
        "def hello(state, ctx, services):\n"
        "    return StateDelta(working_memory={'greeted': True}), END\n"
        "def build_graph():\n"
        "    node = Node(id='hello', version='0.1.0', fn=hello, deterministic=True)\n"
        "    return Graph(\n"
        "        id='g', version='0.1.0', nodes={'hello': node}, edges=[], entry_node='hello'\n"
        "    )\n"
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delitem(sys.modules, "agents", raising=False)
    monkeypatch.delitem(sys.modules, "agents.my_agent", raising=False)
    monkeypatch.delitem(sys.modules, "agents.my_agent.graph", raising=False)

    final_state = run_graph_module("agents.my_agent.graph", agent_id="a1", objective="x")
    assert final_state.working_memory == {"greeted": True}
