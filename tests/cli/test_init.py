from pathlib import Path

import pytest

from aef.cli.init import InvalidAgentNameError, run_init


def test_run_init_writes_three_files(tmp_path: Path) -> None:
    result = run_init("myagent", tmp_path)
    assert result.agent_dir == tmp_path / "agents" / "myagent"
    written_names = {p.name for p in result.written_files}
    assert written_names == {"__init__.py", "aef.yaml", "graph.py"}
    for path in result.written_files:
        assert path.exists()


def test_run_init_graph_module_is_importable_and_runnable(tmp_path: Path) -> None:
    import importlib.util
    import sys

    result = run_init("myagent", tmp_path)
    graph_path = result.agent_dir / "graph.py"

    spec = importlib.util.spec_from_file_location("myagent_graph", graph_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["myagent_graph"] = module
    spec.loader.exec_module(module)

    from aef.kernel import GraphExecutor, Services
    from aef.state import AEFState

    graph = module.build_graph()
    executor = GraphExecutor(graph.compile(), Services())
    result_state = executor.run(AEFState(run_id="r1", agent_id="myagent", objective="test"))
    assert result_state.final_state.working_memory == {"greeted": True}


def test_run_init_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "myagent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "aef.yaml").write_text("custom: true\n")

    result = run_init("myagent", tmp_path)

    assert (agent_dir / "aef.yaml").read_text() == "custom: true\n"
    assert any(p.name == "aef.yaml" for p in result.skipped_files)


def test_run_init_rejects_path_traversal_in_agent_name(tmp_path: Path) -> None:
    """Reproduces a real, confirmed path-traversal bug: agent_name was
    joined into a filesystem path with zero validation. "../../evil" wrote
    files two directories above the intended <dir>/agents/ tree; an
    absolute path discarded base_dir entirely (pathlib's `/` operator
    silently drops everything left of an absolute right-hand component).
    See docs/adr/0029."""
    with pytest.raises(InvalidAgentNameError):
        run_init("../../evil", tmp_path)
    # Confirm nothing escaped: no file was written anywhere outside tmp_path.
    escaped = tmp_path.parent / "evil"
    assert not escaped.exists()


def test_run_init_rejects_absolute_path_as_agent_name(tmp_path: Path) -> None:
    with pytest.raises(InvalidAgentNameError):
        run_init("/etc/evil", tmp_path)


def test_run_init_rejects_non_identifier_agent_names(tmp_path: Path) -> None:
    for bad in ["has space", "has-hyphen", "", "123startswithdigit", 'has"quote']:
        with pytest.raises(InvalidAgentNameError):
            run_init(bad, tmp_path)
