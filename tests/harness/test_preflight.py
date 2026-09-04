"""The six obligations, and the command that makes the fifth meetable.

Every obligation here was discovered by someone being stuck — one refusal at
a time, in the worst order. `doctor` reports all six at once; `bless` makes
obligation 5 possible at all, since LOOP.md told owners to archive a baseline
and no command existed to do it (ADR 0073).

Obligation 6 is the exception to "discovered by being stuck": a node that
builds its own vendor client never gets stuck. It runs, `aef doctor` reports
green, and the bill arrives at gate time (ADR 0137).
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
    (repo / "agents").mkdir(parents=True, exist_ok=True)
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


def test_all_six_obligations_are_reported(tmp_path: Path) -> None:
    names = {o.name for o in _check(tmp_path, ROUTED).obligations}
    assert names == {
        "corpus + tripwire",
        "reflect node routed to",
        "observations",
        "halt channel",
        "blessed baseline",
        "model calls visible",
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
# Obligation 6 — the model call must be visible to the harness (ADR 0137)
#
# Reproduced before it was written: an adopted repo whose node called its own
# `run_agent()`, which built its own `anthropic.Anthropic()`. `aef doctor`
# exit 0; `Services.model_provider` 0 calls; the recorded scenario carried 0
# RecordedCalls; replay with on_miss="fail" reached the vendor live, and with
# no SDK installed scored 0.0. Nothing anywhere warned.
# --------------------------------------------------------------------------

BYPASSING_NODE = ROUTED.replace(
    "def work(state, ctx, services):",
    "def work(state, ctx, services):\n"
    "    from vendor_client import ask\n\n"
    "    ask(state.objective)",
)


def _with_vendor_module(tmp_path: Path, source: str, body: str) -> Path:
    repo = _repo(tmp_path, source)
    (repo / "vendor_client.py").write_text(body)
    return repo


def test_a_node_reaching_a_module_that_builds_its_own_client_is_unmet(tmp_path: Path) -> None:
    repo = _with_vendor_module(
        tmp_path,
        BYPASSING_NODE,
        "import anthropic\n\n\ndef ask(p):\n    return anthropic.Anthropic()\n",
    )
    obligation = _obligation(
        _check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible"
    )
    assert not obligation.met
    assert "vendor_client.py" in obligation.detail
    assert "anthropic" in obligation.detail


def test_the_obligation_is_met_when_nothing_reachable_imports_a_vendor_sdk(
    tmp_path: Path,
) -> None:
    """The routed node `aef migrate` now generates: it asks
    `services.require_model_provider()` and imports no SDK at all."""
    obligation = _obligation(_check(tmp_path, ROUTED), "model calls visible")
    assert obligation.met
    assert "none imports a model SDK" in obligation.detail


def test_a_vendor_import_two_modules_deep_is_still_found(tmp_path: Path) -> None:
    """Reachability is transitive. The adopted repo that motivated this had the
    SDK two hops from the graph — the generated node imported `src.my_agent`,
    which imported `anthropic` — and a one-level check would have passed it."""
    repo = _with_vendor_module(tmp_path, BYPASSING_NODE, "from deeper import ask  # noqa: F401\n")
    (repo / "deeper.py").write_text("import anthropic\n\n\ndef ask(p):\n    return anthropic\n")
    obligation = _obligation(
        _check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible"
    )
    assert not obligation.met
    assert "deeper.py" in obligation.detail


def test_a_third_party_import_is_not_followed_out_of_the_repo(tmp_path: Path) -> None:
    """`anthropic` imports `anthropic`. Following imports that resolve outside
    the repo would report every adopter's whole site-packages tree."""
    source = ROUTED.replace(
        "def work(state, ctx, services):",
        "def work(state, ctx, services):\n    import json\n\n    json.dumps({})",
    )
    assert _obligation(_check(tmp_path, source), "model calls visible").met


def test_a_circular_import_terminates(tmp_path: Path) -> None:
    circular = "import other\n\n\ndef ask(p):\n    return other\n"
    repo = _with_vendor_module(tmp_path, BYPASSING_NODE, circular)
    (repo / "other.py").write_text("import vendor_client\n")
    assert _obligation(_check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible").met


# --------------------------------------------------------------------------
# ADR 0141 — obligation 6 asks the MODEL question, with the model list
# --------------------------------------------------------------------------


# The 14 constraint-#3 names that are NOT model SDKs. `google` is deliberately
# absent: it IS in MODEL_SDK_ROOTS so a Gemini client construction is seen at
# all, and vendor_scan.py already records the cost of that (a non-model
# `google.*` import reads as a call site). That over-report predates ADR 0141
# and is a stated trade, not the defect this test is about.
NON_MODEL_VENDORS = (
    "mem0ai",
    "neo4j",
    "falkordb",
    "memgraph",
    "temporalio",
    "psycopg",
    "psycopg2",
    "opentelemetry",
    "dspy",
    "gepa",
    "llmlingua",
    "ragas",
    "deepeval",
    "langfuse",
)


@pytest.mark.parametrize("vendor", NON_MODEL_VENDORS)
def test_a_non_model_vendor_import_does_not_block_the_adopter(tmp_path: Path, vendor: str) -> None:
    """`import psycopg2` in a reachable module used to make obligation 6
    unmeetable forever, with a fix telling the adopter to route a Postgres
    connection through `require_model_provider().complete(...)`.

    The obligation scans `MODEL_SDK_ROOTS`; 14 of the 19 names in the
    constraint #3 list are not model SDKs. ADR 0137's "it over-reports
    nothing" was false for every one of them (ADR 0141).
    """
    repo = _with_vendor_module(
        tmp_path, BYPASSING_NODE, f"import {vendor}\n\n\ndef ask(p):\n    return {vendor}\n"
    )
    obligation = _obligation(
        _check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible"
    )
    assert obligation.met, obligation.detail


@pytest.mark.parametrize("vendor", ["anthropic", "openai", "cohere", "mem0"])
def test_a_model_sdk_import_still_blocks(tmp_path: Path, vendor: str) -> None:
    """The narrowing must not have narrowed away the thing the obligation is
    for. Every model SDK is still an unmet obligation."""
    repo = _with_vendor_module(
        tmp_path, BYPASSING_NODE, f"import {vendor}\n\n\ndef ask(p):\n    return {vendor}\n"
    )
    obligation = _obligation(
        _check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible"
    )
    assert not obligation.met
    assert vendor in obligation.detail


# --------------------------------------------------------------------------
# ADR 0141 — the fix names the remedy that actually applies
# --------------------------------------------------------------------------


def _unrouted_graph(dotted: str, reason: str) -> str:
    """What `aef migrate` writes when it refuses to route a call site — the
    marker this file parses back. Kept verbatim from `migrate._render_unrouted`
    so a change to that template fails here rather than silently degrading the
    fix message to the generic one."""
    return f'''from aef.kernel import END, Edge, Graph, Node
from aef.reasoning.nodes import make_reflect_node
from aef.state import StateDelta


def work(state, ctx, services):
    """UNROUTED wrapper for `{dotted}.ask` (line 6).

    Detected by: `anthropic.Anthropic`
    Not routed because {reason}.

    WARNING — this node calls your function.
    """
    from {dotted} import ask

    ask(state.objective)
    return StateDelta(), "reflect"


def build_graph():
    return Graph(id="g", version="1",
                 nodes={{"work": Node(id="work", version="1", fn=work, deterministic=True),
                        "reflect": make_reflect_node()}},
                 edges=[Edge(from_node="work", to_node="reflect")], entry_node="work")
'''


def test_the_fix_does_not_send_an_adopter_round_a_loop(tmp_path: Path) -> None:
    """`aef migrate --dir . --force` was the printed fix for EVERY unmet
    obligation 6, including the population migrate's falsification clause
    deliberately creates. Running it regenerates the same unrouted wrapper
    and the obligation is red again, with the same message (reproduced,
    ADR 0141). When migrate has already refused, the fix says so and names
    the two edits that are actually required."""
    reason = "its body loops — a retry, backoff or pagination policy"
    source = _unrouted_graph("vendor_client", reason)
    repo = _with_vendor_module(
        tmp_path, source, "import anthropic\n\n\ndef ask(p):\n    return anthropic\n"
    )
    fix = _obligation(_check(tmp_path, source, repo_root=repo), "model calls visible").fix

    assert "will NOT fix this" in fix
    assert "loop" in fix
    assert reason.split("—")[0].strip() in fix, "the refusal reason is quoted back"
    # Both halves of the real remedy, and the second is the one stated nowhere.
    assert "services.require_model_provider().complete(" in fix
    assert "DELETE" in fix and "from vendor_client import" in fix


def test_the_generic_fix_applies_when_migrate_has_not_refused_this_module(
    tmp_path: Path,
) -> None:
    """No UNROUTED marker naming the module means migrate has not looked at
    it, and running migrate genuinely is the next step."""
    repo = _with_vendor_module(
        tmp_path, BYPASSING_NODE, "import anthropic\n\n\ndef ask(p):\n    return anthropic\n"
    )
    fix = _obligation(_check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible").fix
    assert "will NOT fix this" not in fix
    assert "aef migrate --dir . --force" in fix


# --------------------------------------------------------------------------
# ADR 0141 — render() says what is true about who reads `ready`
# --------------------------------------------------------------------------


def test_render_does_not_claim_the_gates_refuse(tmp_path: Path) -> None:
    """`Preflight.ready` has exactly one reader in `aef/`: `cmd_doctor`.
    The closing line claimed the gates refuse on it, and `loop cycle` on a
    repo with obligation 6 red proposes and gates (reproduced, ADR 0141)."""
    rendered = _check(tmp_path, NO_REFLECT).render()
    assert "the gates refuse for lack of evidence" not in rendered
    assert "ADVISORY" in rendered
    assert "aef loop cycle" in rendered


def test_the_fix_names_the_call_that_replaces_the_client(tmp_path: Path) -> None:
    """A fix that says "don't do that" is not a fix. This one names the call,
    the command that generates it, and what the adopter loses by not doing it."""
    repo = _with_vendor_module(
        tmp_path, BYPASSING_NODE, "import anthropic\n\n\ndef ask(p):\n    return anthropic\n"
    )
    fix = _obligation(_check(tmp_path, BYPASSING_NODE, repo_root=repo), "model calls visible").fix
    assert "services.require_model_provider().complete(" in fix
    assert "aef migrate" in fix
    assert "RecordedCall" in fix


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
