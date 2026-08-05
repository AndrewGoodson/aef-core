"""The five obligations, and the command that makes the fifth meetable.

Every obligation here was discovered by someone being stuck — one refusal at
a time, in the worst order. `doctor` reports all five at once; `bless` makes
obligation 5 possible at all, since LOOP.md told owners to archive a baseline
and no command existed to do it (ADR 0073).
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import archive, ledger
from aef.harness.preflight import BlessError, bless, preflight

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

ROUTED = """from aef.kernel import END, Edge, Graph, Node
from aef.reasoning.nodes import make_reflect_node
from aef.state import StateDelta


def work(state, ctx, services):
    return StateDelta(), "reflect"


def build_graph():
    return Graph(id="g", version="1",
                 nodes={"work": Node(id="work", version="1", fn=work, deterministic=True),
                        "reflect": make_reflect_node()},
                 edges=[Edge(from_node="work", to_node="reflect")], entry_node="work")
"""

# The trap: a reflect node present, an Edge drawn, and nothing routing to it.
EDGE_ONLY = ROUTED.replace('return StateDelta(), "reflect"', "return StateDelta(), END")
NO_REFLECT = """from aef.kernel import END, Graph, Node
from aef.state import StateDelta


def work(state, ctx, services):
    return StateDelta(), END
"""


def _repo(tmp_path: Path, source: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "graph.py").write_text(source)
    return repo


def _committed_repo(tmp_path: Path, source: str) -> Path:
    """`bless` reads the baseline from git, not from the working tree — a
    baseline blessed from a dirty tree records a state that exists nowhere in
    history, so nothing can be compared against it (ADR 0074)."""
    repo = _repo(tmp_path, source)

    def run(*a: str) -> None:
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-qm", "init")
    return repo


def _check(tmp_path: Path, source: str, **kw: object):
    defaults: dict[str, object] = {
        "repo_root": _repo(tmp_path, source),
        "state_root": tmp_path / "state",
        "corpus_root": tmp_path / "corpus",
        "agent_path": "agents/graph.py",
        "graph_id": "g",
        "halt_channel_configured": False,
        "observations": tmp_path / "obs.jsonl",
    }
    defaults.update(kw)
    return preflight(**defaults)  # type: ignore[arg-type]


def _obligation(result, name: str):
    return next(o for o in result.obligations if o.name == name)


# --------------------------------------------------------------------------
# The reflect trap — the one that has caught two people
# --------------------------------------------------------------------------


def test_a_routed_reflect_node_passes(tmp_path: Path) -> None:
    assert _obligation(_check(tmp_path, ROUTED), "reflect node routed to").met


def test_a_reflect_node_with_only_an_edge_fails(tmp_path: Path) -> None:
    """An Edge does not wire it. Routing is chosen by node code, so a work
    node returning END never reaches reflect however the edges are drawn."""
    obligation = _obligation(_check(tmp_path, EDGE_ONLY), "reflect node routed to")
    assert not obligation.met
    assert "nothing routes to it" in obligation.detail


def test_no_reflect_node_at_all_fails(tmp_path: Path) -> None:
    assert not _obligation(_check(tmp_path, NO_REFLECT), "reflect node routed to").met


def test_a_custom_reflect_node_id_is_honoured(tmp_path: Path) -> None:
    source = ROUTED.replace("make_reflect_node()", "make_reflect_node(node_id='think')")
    source = source.replace('"reflect"', '"think"').replace('to_node="reflect"', 'to_node="think"')
    assert _obligation(_check(tmp_path, source), "reflect node routed to").met


# --------------------------------------------------------------------------
# Every obligation reports, and every failure carries its fix
# --------------------------------------------------------------------------


def test_all_five_obligations_are_reported(tmp_path: Path) -> None:
    names = {o.name for o in _check(tmp_path, ROUTED).obligations}
    assert names == {
        "corpus + tripwire",
        "reflect node routed to",
        "observations",
        "halt channel",
        "blessed baseline",
    }


def test_every_unmet_obligation_carries_a_runnable_fix(tmp_path: Path) -> None:
    for obligation in _check(tmp_path, NO_REFLECT).obligations:
        if not obligation.met:
            assert obligation.fix.strip(), f"{obligation.name} has no fix"


def test_the_bless_fix_string_is_the_command_the_cli_accepts(tmp_path: Path) -> None:
    """doctor printed `aef loop bless <module> ...` and the CLI rejected it —
    the same shape as defect #10: a documented command the tool refuses."""
    fix = _obligation(_check(tmp_path, ROUTED), "blessed baseline").fix
    assert "bless <module>" not in fix
    assert fix.startswith("aef loop bless --repo")


def test_a_fresh_repo_is_not_ready(tmp_path: Path) -> None:
    assert not _check(tmp_path, ROUTED).ready


# --------------------------------------------------------------------------
# bless
# --------------------------------------------------------------------------


def test_bless_archives_the_current_state_as_version_one(tmp_path: Path) -> None:
    repo = _committed_repo(tmp_path, ROUTED)
    entry = bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    assert entry.version == 1
    assert archive.read_files(tmp_path / "state" / "archive", "g", 1)["agents/graph.py"]


def test_blessing_twice_is_refused(tmp_path: Path) -> None:
    """Rebaselining is a separate, rate-limited owner decision (G5). A bless
    that silently replaced the baseline would reset the drift budget to zero
    without anyone choosing to."""
    repo = _committed_repo(tmp_path, ROUTED)
    kw = dict(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    bless(**kw)  # type: ignore[arg-type]
    with pytest.raises(BlessError, match="already has 1 archived version"):
        bless(**kw)  # type: ignore[arg-type]


def test_bless_records_a_BLESSED_entry_not_a_MERGED_one(tmp_path: Path) -> None:
    """A baseline is not a merge. As MERGED, the monitor would try to roll it
    back to version 0 and raise — a seam defect caught before it shipped."""
    bless(
        repo_root=_committed_repo(tmp_path, ROUTED),
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    kinds = [e.kind for e in ledger.read(tmp_path / "state")]
    assert ledger.EventKind.BLESSED in kinds
    assert ledger.EventKind.MERGED not in kinds


def test_the_monitor_ignores_a_blessed_baseline(tmp_path: Path) -> None:
    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths, monitor

    repo = _committed_repo(tmp_path, ROUTED)
    bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    config = LoopConfig(
        repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"), graph_id="g"
    )
    run = monitor(config, now=NOW)
    assert run.checked == 0, "a baseline has no predecessor and must not be rolled back"


def test_bless_refuses_when_there_is_no_agent_source(tmp_path: Path) -> None:
    with pytest.raises(BlessError, match="nothing to bless"):
        bless(
            repo_root=tmp_path / "empty",
            state_root=tmp_path / "state",
            agent_path="agents/graph.py",
            graph_id="g",
            at=NOW,
        )
