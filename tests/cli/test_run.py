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


def test_run_graph_module_rejects_explicit_empty_judge_rubric(graph_module: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        run_graph_module(
            graph_module,
            agent_id="a1",
            objective="do the thing",
            judge_rubric={},
        )


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


def test_run_without_checkpoints_dir_writes_no_files(
    graph_module: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default (no --checkpoints-dir) must stay in-memory-only — no
    stray files written for a quick one-off run. `graph_module` already
    wrote its own .py file into `tmp_path` (same fixture instance, shared
    across both fixture params) and Python's own import machinery creates
    `__pycache__` regardless of durability backend — snapshot before/after
    and ignore both, so only files `run_graph_module` itself might write
    (e.g. a stray checkpoints dir) would fail this."""
    monkeypatch.chdir(tmp_path)
    before = {p for p in tmp_path.iterdir() if p.name != "__pycache__"}
    run_graph_module(graph_module, agent_id="a1", objective="x")
    after = {p for p in tmp_path.iterdir() if p.name != "__pycache__"}
    assert after == before


def test_run_with_checkpoints_dir_persists_to_a_real_file_backend_readable_by_eval_and_trace(
    graph_module: str, tmp_path: Path
) -> None:
    """Reproduces the real bug: before this fix, aef run always used
    InMemoryDurabilityBackend, whose data vanished the instant the process
    exited — aef eval/aef trace could never find anything a prior aef run
    produced. Confirmed with the real installed `aef` console script in a
    scratch directory before writing this test, not just here."""
    from aef.cli.eval import eval_run
    from aef.cli.trace import trace_run
    from aef.kernel import FileDurabilityBackend

    checkpoints_dir = tmp_path / "checkpoints"
    final_state = run_graph_module(
        graph_module, agent_id="a1", objective="chained", checkpoints_dir=checkpoints_dir
    )

    backend = FileDurabilityBackend(checkpoints_dir)
    reloaded = backend.load_latest(final_state.run_id)
    assert reloaded is not None
    assert reloaded.run_id == final_state.run_id

    record = eval_run(checkpoints_dir, final_state.run_id)
    assert record.run_id == final_state.run_id

    provenance = trace_run(checkpoints_dir, final_state.run_id)
    assert provenance == []  # this graph makes no model calls; empty is correct, not broken


# --- The assembled `aef run` path: consolidated lessons, and one tenant's ---
# ADR 0125. Both reproduced through `run_graph_module` (what the CLI calls)
# before the fix, with the seam reproduction `repro_run_path.py`.

_RETRIEVE_WORK_REFLECT_CONSOLIDATE = """
from aef.kernel import END, Context, Edge, Graph, Node, Route, Services
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node, make_retrieve_node
from aef.state import AEFState, StateDelta


def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    return StateDelta(errors=[{"node_id": "work", "error": "fetch timed out"}]), "reflect"


def build_graph() -> Graph:
    nodes = [
        make_retrieve_node(route="work"),
        Node(id="work", version="1", fn=work, deterministic=True),
        make_reflect_node(route="consolidate"),
        make_consolidate_node(route=END),
    ]
    return Graph(
        id="seam",
        version="1",
        nodes={n.id: n for n in nodes},
        edges=[Edge("retrieve", "work"), Edge("work", "reflect"), Edge("reflect", "consolidate")],
        entry_node="retrieve",
    )
"""


@pytest.fixture
def wiki_graph_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    (tmp_path / "cli_wiki_graph_mod.py").write_text(_RETRIEVE_WORK_REFLECT_CONSOLIDATE)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "cli_wiki_graph_mod"
    sys.modules.pop("cli_wiki_graph_mod", None)


def _last_memory_record(path: Path) -> dict:
    import json

    loaded: dict = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    return loaded


def test_run_with_durable_memory_retrieves_the_lesson_consolidated_by_earlier_runs(
    wiki_graph_module: str, tmp_path: Path
) -> None:
    """A1 on the ASSEMBLED path, not just for a caller who builds `Services`
    by hand. `run_graph_module` built a fresh `InMemoryKnowledgeStore()` per
    process and the retrieve node runs BEFORE the consolidate node, so across
    CLI runs no consolidated lesson was ever in context: `retrieved_signatures`
    was `[]` in every run, and ADR 0118's helpful/harmful tally had no producer
    here at all.

    The consolidator needs a signature in TWO distinct runs (one is an episode,
    ADR 0110), so the entry exists only from the third run's point of view."""
    memory_path = tmp_path / "memory.jsonl"
    signatures = []
    for _ in range(3):
        run_graph_module(
            wiki_graph_module, agent_id="mine", objective="settle it", memory_path=memory_path
        )
        signatures.append(_last_memory_record(memory_path)["content"]["retrieved_signatures"])

    assert signatures[0] == []  # nothing recorded yet
    assert signatures[1] == []  # one run's failure is an episode, not knowledge
    assert signatures[2] == ["failure:work"]


def test_run_without_a_context_block_does_not_retrieve_another_tenants_record(
    wiki_graph_module: str, tmp_path: Path
) -> None:
    """`build_retriever` returns None without a `context:` block, so
    `agent_services` defaulted a retriever with `agent_id=None` — over the
    DURABLE, multi-agent file store `--memory` names. Another tenant's failure
    landed in this agent's context. ADR 0118's comment claimed that default
    "only ever fronts a throwaway store"; it did not."""
    from datetime import UTC, datetime

    from aef.harness.memory_store import FileMemoryStore
    from aef.services.memory.base import MemoryRecord

    memory_path = tmp_path / "memory.jsonl"
    FileMemoryStore(path=memory_path).write(
        MemoryRecord(
            kind="failure",
            agent_id="OTHER-TENANT",
            run_id="o1",
            created_at=datetime.now(UTC),
            content={
                "verbal_feedback": "fetch timed out settling the invoice for acme",
                "failing_nodes": ["work"],
                "objective": "settle it",
            },
        )
    )

    final = run_graph_module(
        wiki_graph_module, agent_id="mine", objective="settle it", memory_path=memory_path
    )
    assert final.retrieved_context == []


# ---------------------------------------------------------------------------
# ADR 0168 / M4 — `aef run` takes a file path, because some roots have no
# dotted spelling.
# ---------------------------------------------------------------------------
FILE_GRAPH = """
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, StateDelta


def hello(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    return StateDelta(working_memory={"seen": state.objective}), END


def build_graph() -> Graph:
    node = Node(id="hello", version="0.1.0", fn=hello, deterministic=True)
    return Graph(id="g", version="0.1.0", nodes={"hello": node}, edges=[], entry_node="hello")
"""


def test_a_dotted_name_under_a_dot_directory_is_the_reproduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What `aef migrate --agent-root .claude/agents` used to print. It is not
    a module name and never can be: a leading dot means relative import."""
    from aef.cli.run import import_graph_module

    monkeypatch.chdir(tmp_path)
    with pytest.raises(TypeError, match="package.*argument is required"):
        import_graph_module(".claude.agents.migrated.a.graph")


def test_run_graph_module_loads_a_graph_from_a_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aef.cli.run import run_graph_module

    target = tmp_path / ".claude" / "agents" / "migrated" / "a"
    target.mkdir(parents=True)
    (target / "graph.py").write_text(FILE_GRAPH, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    state = run_graph_module(
        ".claude/agents/migrated/a/graph.py", agent_id="a1", objective="do the thing"
    )
    assert state.working_memory == {"seen": "do the thing"}


def test_two_graph_py_files_in_different_directories_do_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`aef migrate` names EVERY generated file `graph.py`, so the `sys.modules`
    key has to come from the whole path.

    The detector is the registry, not the returned objects, and that was
    established by mutation rather than assumed: keyed on the basename,
    `spec_from_file_location` still loads the right file and still hands back a
    distinct module, so `first is not second` PASSES while
    `sys.modules["aef_graph_graph"]` silently points at whichever was loaded
    last. A test that cannot see the fault is not a test (reproduce-first).
    """
    from aef.cli.run import import_graph_module

    for name, marker in (("one", "ONE"), ("two", "TWO")):
        target = tmp_path / ".claude" / "agents" / "migrated" / name
        target.mkdir(parents=True)
        (target / "graph.py").write_text(
            FILE_GRAPH.replace('"seen": state.objective', f'"seen": "{marker}"'), encoding="utf-8"
        )
    monkeypatch.chdir(tmp_path)

    first = import_graph_module(".claude/agents/migrated/one/graph.py")
    second = import_graph_module(".claude/agents/migrated/two/graph.py")
    try:
        assert first is not second
        assert first.__name__ != second.__name__, (
            f"both graph.py files registered as {first.__name__!r}; the second load "
            f"overwrites the first in sys.modules"
        )
        for module in (first, second):
            assert sys.modules[module.__name__] is module
            assert sys.modules[module.__name__].__file__ == module.__file__
    finally:
        for module in (first, second):
            sys.modules.pop(module.__name__, None)


def test_a_missing_file_says_so_rather_than_reporting_an_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aef.cli.run import run_graph_module

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="looks like a file path and there is no file there"):
        run_graph_module("agents/nope/graph.py", agent_id="a1", objective="x")


def test_a_dotted_name_is_never_retried_as_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A module that fails to import for its OWN reason must report that
    reason, not `no such file` from a fallback that missed."""
    (tmp_path / "boom_mod.py").write_text("raise RuntimeError('the real reason')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    from aef.cli.run import import_graph_module

    with pytest.raises(RuntimeError, match="the real reason"):
        import_graph_module("boom_mod")
    sys.modules.pop("boom_mod", None)


# --------------------------------------------------------------------------
# `--record-runs` records the cassette (ADR 0190, closing ADR 0163's F-M6-1)
# --------------------------------------------------------------------------

# A graph whose node asks the model and records what the provider declares,
# which is what every `aef migrate`-generated graph does.
ASKING_MODULE = """
from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.providers.base import CompletionRequest, ProviderMessage
from aef.state import AEFState, StateDelta


def ask(state, ctx, services):
    provider = services.require_model_provider()
    reply = provider.complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content=state.objective),),
            model="",
        )
    )
    return StateDelta(
        working_memory={
            "answer": reply.content,
            "ask__containment": {
                "provider": provider.name,
                "isolation": sorted(provider.isolation),
            },
        }
    ), END


def build_graph() -> Graph:
    from aef.kernel.contracts import SideEffect
    node = Node(id="ask", version="0.1.0", fn=ask, deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda state: state.run_id)
    return Graph(id="asker", version="0.1.0", nodes={"ask": node}, edges=[], entry_node="ask")
"""


@pytest.fixture
def asking_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A graph that calls a model, plus an `aef.yaml` whose provider is a
    local echo command — offline, no credential, and with an `isolation:`
    list so the run has a declaration to record."""
    (tmp_path / "asking_mod.py").write_text(ASKING_MODULE)
    (tmp_path / "aef.yaml").write_text(
        "model_provider:\n"
        "  impl: command\n"
        "  model: stub-echo\n"
        "  command:\n"
        '    argv: ["/bin/echo", "{prompt}"]\n'
        "    isolation: [no_tools, single_turn]\n"
        "memory:\n  impl: in_memory\n"
        "objectives: test\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    sys.modules.pop("asking_mod", None)


def test_record_runs_writes_the_model_calls_the_run_made(asking_repo: Path) -> None:
    """F-M6-1: `RecordedRun(...)` was built with no `model_calls=`, so the
    field defaulted to `()` and harvest's determinism re-check replayed every
    real run against an empty cassette — the rejection `RecordedRun`'s own
    docstring had predicted."""
    from aef.harness.harvest import load_runs

    runs = asking_repo / "runs"
    run_graph_module(
        "asking_mod",
        agent_id="a1",
        objective="what is the rule?",
        config_path=asking_repo / "aef.yaml",
        record_runs_dir=runs,
    )
    (recorded,) = load_runs(runs)
    assert len(recorded.model_calls) == 1
    assert recorded.model_calls[0].messages[0].content == "what is the rule?"
    assert "what is the rule?" in recorded.model_calls[0].result.content


def test_record_runs_writes_the_providers_own_declaration(asking_repo: Path) -> None:
    """F-M6-2's half of the fix: the containment record is derived from the
    provider object, so the re-check needs the declaration as data."""
    from aef.harness.harvest import load_runs

    runs = asking_repo / "runs"
    run_graph_module(
        "asking_mod",
        agent_id="a1",
        objective="what is the rule?",
        config_path=asking_repo / "aef.yaml",
        record_runs_dir=runs,
    )
    (recorded,) = load_runs(runs)
    # The owner's two, plus the one the provider derives from its own argv:
    # this template has no `{system}` slot, so the persona travels in the user
    # turn and `CommandProvider` says so (ADR 0169).
    assert recorded.provider_isolation == ("no_tools", "single_turn", "user_turn_persona")
    # The wrapped provider's name, not the wrapper's: the containment record
    # says 'cassette' today (ADR 0182's open item 1) and this is what would
    # let a replay keep matching it if that were fixed.
    assert recorded.provider_name == "command"


def test_a_recorded_run_re_executes_identically_and_is_harvested(asking_repo: Path) -> None:
    """The two halves joined, which is the property that was missing: a run
    `aef run --record-runs` wrote is admitted by `aef loop harvest`. No run of
    a model-calling graph had ever been, on any repo (ADR 0163)."""
    import importlib
    from datetime import UTC, datetime

    from aef.harness.harvest import harvest

    runs = asking_repo / "runs"
    run_graph_module(
        "asking_mod",
        agent_id="a1",
        objective="what is the rule?",
        config_path=asking_repo / "aef.yaml",
        record_runs_dir=runs,
    )
    graph = importlib.import_module("asking_mod").build_graph()
    outcome = harvest(
        runs,
        asking_repo / "corpus",
        graph,
        now=datetime.now(UTC),
        include_successes=True,
    )
    assert outcome.rejected_nondeterministic == ()
    assert len(outcome.promoted) == 1


def test_a_plain_run_is_unwrapped_and_unconfigured_runs_still_refuse(
    asking_repo: Path,
) -> None:
    """The recorder wraps only when the run is being RECORDED. Without
    `--config` there is no provider to wrap and this module's contract stands:
    `require_model_provider()` refuses rather than reporting a cassette miss.
    """
    from aef.kernel.contracts import ServiceNotConfiguredError

    with pytest.raises(ServiceNotConfiguredError):
        run_graph_module(
            "asking_mod",
            agent_id="a1",
            objective="x",
            record_runs_dir=asking_repo / "runs",
        )
    # And a configured run with no recording still sees the raw provider.
    final = run_graph_module(
        "asking_mod",
        agent_id="a1",
        objective="x",
        config_path=asking_repo / "aef.yaml",
    )
    containment = final.working_memory["ask__containment"]
    assert isinstance(containment, dict)
    assert containment["provider"] == "command"
