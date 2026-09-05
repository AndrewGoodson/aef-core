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
from typing import Any

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
    # Wording updated deliberately by ADR 0167: the green branch now says HOW
    # MANY graphs it scanned, because "all clear" over an unstated number of
    # files is the claim that let one file out of nine pass for the other
    # eight (ADR 0168).
    assert "1 graph scanned" in obligation.detail
    assert "none reaches a model SDK the harness cannot see" in obligation.detail


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
    marker this file parses back.

    A HAND COPY, and it cannot catch drift: this docstring used to claim it
    could, and then ADR 0140 rewrote the real template, this fixture kept
    passing, and every refusal silently stopped being parsed. The guard that
    actually holds the contract is
    `test_the_generated_docstring_is_a_contract_between_migrate_and_preflight`,
    which runs the real `aef migrate` and reads its real output back. This
    stays because it keeps the other cases fast."""
    return f'''from aef.kernel import END, Edge, Graph, Node
from aef.reasoning.nodes import make_reflect_node
from aef.state import StateDelta


def work(state, ctx, services):
    """UNROUTED wrapper for one of this repo's model call sites.

    Wraps `{dotted}.ask` (line 6), unchanged.
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


def test_bless_refuses_an_agent_path_outside_the_tree_it_would_archive(tmp_path: Path) -> None:
    """K3's reproduction, in a test (ADR 0147).

    Run against an adopted repo, `aef loop bless --agent-path aef_migrated.py`
    printed `blessed aef_migrated.py as baseline v1` and archived one file:
    `agents/README.md`. `bless` checked `path_exists_at(ref, agent_path)` and
    then archived the Zone A tree — two different questions, and the message
    named the first while doing the second.
    """
    repo = _committed_repo(tmp_path, ROUTED)
    outside = repo / "aef_migrated.py"
    outside.write_text("RETRY_BUDGET = 3\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "migrated"], check=True, capture_output=True
    )

    with pytest.raises(BlessError) as exc:
        bless(
            repo_root=repo,
            state_root=tmp_path / "state",
            agent_path="aef_migrated.py",
            graph_id="g",
            at=NOW,
        )
    # BOTH paths, because either alone reads as a typo rather than a mismatch.
    assert "aef_migrated.py" in str(exc.value)
    assert "agents" in str(exc.value)

    # And nothing was archived, so the `blessed baseline` obligation stays
    # red rather than going green on evidence unrelated to the agent.
    assert archive.versions(tmp_path / "state" / "archive", "g") == ()


def test_bless_refuses_when_zone_a_is_empty(tmp_path: Path) -> None:
    """The sibling case, and the branch that used to carry `pragma: no cover -
    agent_path is inside agent_root in practice`. That assumption is the one
    the defect above lived inside, so the branch is reached deliberately: a
    committed agent at the repo root and no Zone A at all."""
    repo = tmp_path / "rootonly"
    (repo).mkdir()
    (repo / "aef_migrated.py").write_text("RETRY_BUDGET = 3\n")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "init"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    with pytest.raises(BlessError, match="no files under 'agents'"):
        bless(
            repo_root=repo,
            state_root=tmp_path / "state",
            agent_path="aef_migrated.py",
            graph_id="g",
            at=NOW,
        )


def test_bless_accepts_the_same_file_spelled_with_a_leading_dot_slash(tmp_path: Path) -> None:
    """The refusal must not fire on a spelling. Git reports
    `agents/graph.py`; a person types either form."""
    entry = bless(
        repo_root=_committed_repo(tmp_path, ROUTED),
        state_root=tmp_path / "state",
        agent_path="./agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    assert entry.version == 1


def _symlinked_repo(tmp_path: Path, source: str) -> Path:
    """A repo where the Zone A agent is a SYMLINK to a file outside Zone A.

    `git ls-tree` reports it with mode `120000`, and `git show` on it returns
    the LINK TARGET — 16 bytes of `../real/graph.py` — not the code.
    """
    repo = tmp_path / "linked"
    (repo / "agents").mkdir(parents=True)
    (repo / "real").mkdir()
    (repo / "real" / "graph.py").write_text(source)
    (repo / "agents" / "graph.py").symlink_to(Path("..") / "real" / "graph.py")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "init"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def test_bless_refuses_a_zone_a_symlink(tmp_path: Path) -> None:
    """ADR 0147 named this case untested in its own Confidence section; ADR
    0149 reproduced it.

    `bless --agent-path agents/graph.py` printed `blessed agents/graph.py as
    baseline v1` and archived one 16-byte file whose entire content was the
    string `../real/graph.py`. The containment check passes — both sides come
    from `git ls-tree`, and a link is a tree entry like any other — so the
    baseline held the agent by NAME and none of it by CONTENT, and G5 then
    measured every candidate's drift against a tree that never contained the
    code. `candidate.check_modes` already treats exactly this as a SECURITY
    EVENT on the candidate side; the asymmetry was the seam.
    """
    repo = _symlinked_repo(tmp_path, ROUTED)
    # The pre-condition, asserted rather than assumed: git really does record
    # a link, and its blob really is the target string.
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "HEAD", "--", "agents"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert listing.startswith("120000 "), listing

    with pytest.raises(BlessError) as exc:
        bless(
            repo_root=repo,
            state_root=tmp_path / "state",
            agent_path="agents/graph.py",
            graph_id="g",
            at=NOW,
        )
    assert "agents/graph.py" in str(exc.value)
    assert "symlink" in str(exc.value)
    assert archive.versions(tmp_path / "state" / "archive", "g") == ()


def test_bless_reuses_the_candidate_gates_escape_mode_list() -> None:
    """One list, not two. The defect was `bless` and `check_modes` disagreeing
    about what an escape is; a second hand-written list here would recreate it
    the first time a mode is added."""
    import ast
    import inspect
    import textwrap

    from aef.harness import preflight as preflight_module
    from aef.harness.candidate import ESCAPE_MODES

    assert preflight_module.ESCAPE_MODES is ESCAPE_MODES
    # The CODE, not the prose: the docstring names the mode on purpose.
    fn = ast.parse(textwrap.dedent(inspect.getsource(preflight_module._zone_a_escapes))).body[0]
    assert isinstance(fn, ast.FunctionDef)
    literals = {
        node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not literals & ESCAPE_MODES, (
        f"a second copy of the escape modes has been written here: {literals & ESCAPE_MODES}"
    )


def test_bless_still_accepts_a_regular_file(tmp_path: Path) -> None:
    """The control on the fix: a refusal that is too broad would refuse every
    correct blessing, which is the failure mode a hasty version ships."""
    entry = bless(
        repo_root=_committed_repo(tmp_path, ROUTED),
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    assert entry.version == 1
    assert (
        b"reflect" in archive.read_files(tmp_path / "state" / "archive", "g", 1)["agents/graph.py"]
    )


def test_bless_refuses_when_there_is_no_agent_source(tmp_path: Path) -> None:
    with pytest.raises(BlessError, match="nothing to bless"):
        bless(
            repo_root=tmp_path / "empty",
            state_root=tmp_path / "state",
            agent_path="agents/graph.py",
            graph_id="g",
            at=NOW,
        )


def test_the_generated_docstring_is_a_contract_between_migrate_and_preflight(
    tmp_path: Path,
) -> None:
    """ADR 0140 rewrote `aef migrate`'s generated docstring; ADR 0141's fix
    string parses that docstring back. Both landed the same day, the full
    suite passed, and every refusal silently stopped being parsed — so the
    obligation went back to printing the generic fix ADR 0141 exists to
    replace. Two modules, one format, nothing comparing them (ADR 0091).

    This runs the REAL migrate and reads its REAL output back through the
    REAL parser, so the format cannot drift again without failing here."""
    from aef.cli.migrate import run_migrate
    from aef.harness.preflight import _migrate_refusals

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text(
        "import anthropic\n"
        "def ask(prompt: str) -> str:\n"
        "    client = anthropic.Anthropic()\n"
        "    r = client.messages.create(\n"
        '        model="m", max_tokens=8,\n'
        '        system="a system prompt makes this unroutable",\n'
        '        messages=[{"role": "user", "content": prompt}])\n'
        "    return r.content[0].text\n"
    )
    result = run_migrate(tmp_path, write=True)
    assert result.sites, "migrate found no call site; the fixture is wrong, not the parser"
    assert not result.sites[0].routed, "the fixture must be UNROUTED for this contract"

    assert result.written is not None, "migrate wrote no file to parse back"
    refusals = _migrate_refusals(result.written)
    assert refusals, "preflight parsed no refusal out of migrate's own generated docstring"
    assert "src.agent" in refusals, refusals
    assert "system" in refusals["src.agent"], refusals["src.agent"]


# --------------------------------------------------------------------------
# The OTHER shape of "routed to reflect": a factory node, not a node function
# (ADR 0167)
#
# `aef migrate` generates a prompt agent as `make_prompt_agent_node(...,
# route="reflect")` — the closure lives in `aef/reasoning/prompt_agent.py` and
# the generated module contains no three-argument node function at all. The
# detector looked only for the function shape, so obligation 2 was
# PERMANENTLY RED on every graph migrate writes for a prompt-file repo while
# the graph routed correctly. Reproduced on the pilot clone:
#
#   $ aef loop doctor --repo <pilot> --state <s> --corpus <pilot>/corpus \
#         --agent-path agents/migrated/marlin_accela/graph.py
#     [--] reflect node routed to  a reflect node exists but nothing routes to it
#   EXIT=1
#   trace of that same graph, stub provider: ['prompt_agent', 'reflect', 'consolidate']
# --------------------------------------------------------------------------

FACTORY_ROUTED = """from aef.kernel import END, Edge, Graph
from aef.reasoning.nodes import make_consolidate_node, make_reflect_node
from aef.reasoning.prompt_agent import make_prompt_agent_node


def build_graph():
    return Graph(
        id="a", version="0.1.0",
        nodes={
            "prompt_agent": make_prompt_agent_node(
                agent_file=".claude/agents/a.md", agent_name="a", route="reflect"
            ),
            "reflect": make_reflect_node(route="consolidate"),
            "consolidate": make_consolidate_node(route=END),
        },
        edges=[Edge(from_node="prompt_agent", to_node="reflect")],
        entry_node="prompt_agent",
    )
"""


def test_a_factory_node_built_with_route_reflect_counts_as_routed(tmp_path: Path) -> None:
    obligation = _obligation(_check(tmp_path, FACTORY_ROUTED), "reflect node routed to")
    assert obligation.met, obligation.detail
    assert "make_prompt_agent_node" in obligation.detail


def test_the_same_graph_routed_to_END_instead_is_still_unmet(tmp_path: Path) -> None:
    """The mutation, as a test: this is the change that makes the loop go
    silent rather than break (ADR 0139/0143), so the detector must fail on it
    or it is detecting the import rather than the route."""
    source = FACTORY_ROUTED.replace('route="reflect"', "route=END")
    assert not _obligation(_check(tmp_path, source), "reflect node routed to").met


def test_a_factory_route_to_a_custom_reflect_id_is_honoured(tmp_path: Path) -> None:
    source = FACTORY_ROUTED.replace(
        'make_reflect_node(route="consolidate")', 'make_reflect_node(node_id="think", route="c")'
    ).replace('route="reflect"', 'route="think"')
    assert _obligation(_check(tmp_path, source), "reflect node routed to").met


def test_make_reflect_node_routing_to_itself_does_not_count(tmp_path: Path) -> None:
    """A self-loop is not something ARRIVING at reflect. Without this
    exclusion the detector would go green on a graph whose only mention of
    the route is the reflect node's own construction."""
    source = FACTORY_ROUTED.replace(
        '                agent_file=".claude/agents/a.md", agent_name="a", route="reflect"\n',
        '                agent_file=".claude/agents/a.md", agent_name="a", route=END\n',
    ).replace('make_reflect_node(route="consolidate")', 'make_reflect_node(route="reflect")')
    assert not _obligation(_check(tmp_path, source), "reflect node routed to").met


def test_a_route_keyword_on_someone_elses_function_is_not_evidence(tmp_path: Path) -> None:
    """The set of factories is read from `from aef.reasoning... import
    make_*_node`. A local helper that happens to take `route=` says nothing
    about how the graph is wired, and vouching for it would make the
    obligation trivially satisfiable."""
    source = FACTORY_ROUTED.replace(
        "from aef.reasoning.prompt_agent import make_prompt_agent_node",
        "from mine import make_prompt_agent_node",
    )
    assert not _obligation(_check(tmp_path, source), "reflect node routed to").met


def test_the_real_migrate_output_passes_the_real_preflight(tmp_path: Path) -> None:
    """C↔D: the REAL `run_migrate` on a prompt-file fixture, read back through
    the REAL preflight. The defect this closes lived exactly in the join —
    both modules were individually correct and individually tested, and
    nothing ran one's output through the other."""
    from aef.cli.migrate import run_migrate
    from aef.harness.preflight import _reflect_is_routed_to

    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "accela-agent.md").write_text(
        "---\nname: marlin-accela\ndescription: the accela persona\n---\n\nNever invent creds.\n",
        encoding="utf-8",
    )
    result = run_migrate(tmp_path)
    assert result.prompt_written, "migrate wrote no prompt-agent graph; the fixture is wrong"

    generated = result.prompt_agents[0].out_relative
    assert (tmp_path / generated).is_file(), generated

    routed, why = _reflect_is_routed_to(tmp_path / generated)
    assert routed, f"{generated} routes to reflect at run time but preflight says: {why}"


# --------------------------------------------------------------------------
# Obligation 5 knows WHICH tree the baseline is of (ADR 0167)
#
# Reproduced on the pilot clone, migrated with `--agent-root .claude/agents`:
# `aef loop bless --agent-root .claude/agents` wrote an `entry.json` whose
# keys were [base_sha, file_digests, gate_report, graph_id, head_sha, notes,
# recorded_at, rolled_back_from, version] — no agent_root anywhere — and the
# next `aef loop cycle` at the DEFAULT root was rejected with
# `cumulative drift: 1.000 exceeds the budget of 0.500`, because G5's two
# sides described disjoint trees. Two such rejections halt the loop.
# --------------------------------------------------------------------------


def _committed_repo_at(tmp_path: Path, agent_path: str, source: str) -> Path:
    """`_committed_repo`, with the agent somewhere other than `agents/`."""
    repo = tmp_path / "repo"
    target = repo / agent_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)

    def run(*a: str) -> None:
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-qm", "init")
    return repo


def test_bless_records_which_zone_a_tree_it_archived(tmp_path: Path) -> None:
    repo = _committed_repo(tmp_path, ROUTED)
    entry = bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    assert entry.agent_root == "agents"
    # ...and it survives the round trip through the file, which is what the
    # next command reads.
    stored = archive.load_entry(tmp_path / "state" / "archive", "g", entry.version)
    assert stored.agent_root == "agents"


def test_a_baseline_blessed_under_another_root_is_reported_unmet_by_name(tmp_path: Path) -> None:
    repo = _committed_repo_at(tmp_path, ".claude/agents/graph.py", ROUTED)
    bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path=".claude/agents/graph.py",
        agent_root=".claude/agents",
        graph_id="g",
        at=NOW,
    )

    result = preflight(
        repo_root=repo,
        state_root=tmp_path / "state",
        corpus_root=tmp_path / "corpus",
        agent_path=".claude/agents/graph.py",
        agent_root="agents",  # the default — what a later invocation would use
        graph_id="g",
        halt_channel_configured=False,
        observations=tmp_path / "obs.jsonl",
    )
    obligation = _obligation(result, "blessed baseline")
    assert not obligation.met, "a baseline of another tree is not a baseline of this one"
    assert ".claude/agents" in obligation.detail
    assert "drift" in obligation.detail
    assert "--agent-root '.claude/agents'" in obligation.fix


def test_a_baseline_under_the_same_root_is_met(tmp_path: Path) -> None:
    repo = _committed_repo(tmp_path, ROUTED)
    bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/graph.py",
        graph_id="g",
        at=NOW,
    )
    result = preflight(
        repo_root=repo,
        state_root=tmp_path / "state",
        corpus_root=tmp_path / "corpus",
        agent_path="agents/graph.py",
        agent_root="agents",
        graph_id="g",
        halt_channel_configured=False,
        observations=tmp_path / "obs.jsonl",
    )
    assert _obligation(result, "blessed baseline").met


def test_a_baseline_that_predates_the_field_is_not_retroactively_failed(tmp_path: Path) -> None:
    """`agent_root` defaults to "" for entries written before ADR 0167. That
    is "not recorded", not "the repo root": failing every pre-existing
    baseline would be a control firing on the ordinary case, which trains the
    reader to skip the line."""
    archive.record(
        tmp_path / "state" / "archive",
        "g",
        files={"agents/graph.py": b"x = 1\n"},
        base_sha="0" * 40,
        head_sha="0" * 40,
        recorded_at=NOW,
    )
    result = preflight(
        repo_root=_repo(tmp_path, ROUTED),
        state_root=tmp_path / "state",
        corpus_root=tmp_path / "corpus",
        agent_path="agents/graph.py",
        agent_root=".claude/agents",
        graph_id="g",
        halt_channel_configured=False,
        observations=tmp_path / "obs.jsonl",
    )
    obligation = _obligation(result, "blessed baseline")
    assert obligation.met
    assert "root not recorded" in obligation.detail


def test_the_bless_fix_carries_the_agent_root_when_it_is_not_the_default(tmp_path: Path) -> None:
    """The reproduced `doctor` output printed a fix line with no
    `--agent-root`, so following it blessed the OTHER tree."""
    fix = _obligation(
        preflight(
            repo_root=_repo(tmp_path, ROUTED),
            state_root=tmp_path / "state",
            corpus_root=tmp_path / "corpus",
            agent_path=".claude/agents/graph.py",
            agent_root=".claude/agents",
            graph_id="g",
            halt_channel_configured=False,
            observations=tmp_path / "obs.jsonl",
        ),
        "blessed baseline",
    ).fix
    assert "--agent-root .claude/agents" in fix


# --------------------------------------------------------------------------
# Obligation 6 over EVERY graph, not the one the CLI guessed (ADR 0167/0168)
#
# It scanned the single `agent_path`, defaulted by `cmd_doctor` and
# `_warn_unmet_obligations`. On a prompt-file repo the default names
# `agents/migrated/graph.py` — the call-site stub whose `build_graph()` raises
# `NotImplementedError` and which reaches no model at all — so obligation 6
# passed on it while the generated graphs that DO call a model were never
# opened. Reproduced with a model SDK import planted in one of them:
#
#   graphs on disk: ['agents/migrated/graph.py',
#                    'agents/migrated/marlin_accela/graph.py', ...]
#   obligation 6 on the DEFAULT --agent-path: visible=True
#     1 reachable module(s), none imports a model SDK
#   obligation 6 on agents/migrated/marlin_accela/graph.py: visible=False
#     src/client.py:1 imports anthropic — the harness cannot see it
#
# The same false pass ADR 0168 fixed in `aef doctor`, in the other diagnostic,
# closed with 0168's OWN discovery function rather than a second answer.
# --------------------------------------------------------------------------


def _migrated_prompt_repo(tmp_path: Path) -> Path:
    """The REAL `aef migrate` on a prompt-file repo, plus a module that builds
    its own client for one generated graph to reach."""
    from aef.cli.migrate import run_migrate

    root = tmp_path / "pilot"
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for name in ("accela", "azure"):
        (agents / f"{name}.md").write_text(
            f"---\nname: marlin-{name}\ndescription: d\n---\n\nbody\n", encoding="utf-8"
        )
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "client.py").write_text("import anthropic\n\nC = anthropic.Anthropic\n")

    result = run_migrate(root)
    assert result.prompt_agents, "migrate wrote no prompt-agent graph; the fixture is wrong"
    target = root / result.prompt_agents[0].out_relative
    target.write_text(target.read_text() + "\nfrom src.client import C  # noqa: E402,F401\n")
    return root


def _obligation_six(root: Path, tmp_path: Path, **kw: object):
    defaults: dict[str, object] = {
        "repo_root": root,
        "state_root": tmp_path / "state",
        "corpus_root": tmp_path / "corpus",
        "agent_path": "agents/migrated/graph.py",
        "graph_id": "g",
        "halt_channel_configured": False,
        "observations": tmp_path / "obs.jsonl",
    }
    defaults.update(kw)
    return _obligation(preflight(**defaults), "model calls visible")  # type: ignore[arg-type]


def test_scanning_only_the_defaulted_path_passes_on_the_stub(tmp_path: Path) -> None:
    """The reproduction, pinned. Not a bug to fix here — this is the LIBRARY
    default, and a caller that names a path gets an answer about that path.
    What was wrong is that the CLI took this branch when it had guessed."""
    root = _migrated_prompt_repo(tmp_path)
    assert _obligation_six(root, tmp_path).met


def test_scanning_every_graph_finds_the_invisible_model_call(tmp_path: Path) -> None:
    root = _migrated_prompt_repo(tmp_path)
    obligation = _obligation_six(root, tmp_path, scan_all_graphs=True)
    assert not obligation.met, obligation.detail
    assert "marlin_accela" in obligation.detail, obligation.detail
    assert "imports anthropic" in obligation.detail
    assert obligation.fix.strip()


def test_a_clean_prompt_file_repo_reports_how_many_graphs_it_scanned(tmp_path: Path) -> None:
    """The green branch has to name the number, or "all clear" is a claim
    about an unknown number of files."""
    from aef.cli.migrate import run_migrate
    from aef.harness.zones import discover_graph_files

    root = tmp_path / "clean"
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for name in ("accela", "azure"):
        (agents / f"{name}.md").write_text(
            f"---\nname: marlin-{name}\ndescription: d\n---\n\nbody\n", encoding="utf-8"
        )
    run_migrate(root)

    obligation = _obligation_six(root, tmp_path, scan_all_graphs=True)
    assert obligation.met, obligation.detail
    assert f"{len(discover_graph_files(root))} graphs scanned" in obligation.detail


def test_the_cli_scans_every_graph_when_agent_path_was_left_at_its_default(
    tmp_path: Path,
) -> None:
    """End to end: the defect was that the CLI defaulted the path and preflight
    then answered about the guess. Runs the real `aef loop doctor`."""
    from aef.cli.main import main

    root = _migrated_prompt_repo(tmp_path)
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(
            [
                "loop",
                "doctor",
                "--repo",
                str(root),
                "--state",
                str(tmp_path / "state"),
                "--corpus",
                str(tmp_path / "corpus"),
            ]
        )
    out = buffer.getvalue()
    assert code == 1
    line = next(ln for ln in out.splitlines() if "model calls visible" in ln)
    assert "[--]" in line, line
    assert "marlin_accela" in line, line


# --------------------------------------------------------------------------
# `--agent-path` is ONE flag with TWO meanings (ADR 0178)
#
# Reproduced on a real `aef migrate` output, with an `import anthropic`
# planted in one generated graph:
#
#   $ aef loop doctor ... --agent-root .claude/agents \
#         --agent-path .claude/agents/accela.md
#     [--] reflect node routed to  no reflect node in the graph
#          fix: add make_reflect_node() to your graph AND make a node
#               `return delta, 'reflect'` ...
#     [OK] model calls visible     1 graph scanned, none reaches a model SDK
#                                  the harness cannot see
#   EXIT=1
#
# The first line is about a graph that routes correctly and whose fix was
# already applied; the second is a clean bill of health over a repo with a
# planted invisible model call. `--proposer rule_based_prompt` documents this
# exact invocation (ADR 0157) — so every prompt-proposer cycle printed it,
# forever. ADR 0167's F2 shape, one flag over.
# --------------------------------------------------------------------------


def _prompt_repo(tmp_path: Path, *, agent_root: str = ".claude/agents") -> tuple[Path, Any]:
    """The REAL `aef migrate` on a two-persona repo. Returns (root, result)."""
    from aef.cli.migrate import run_migrate

    root = tmp_path / "pilot"
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for name in ("accela", "azure"):
        (agents / f"{name}.md").write_text(
            f"---\nname: marlin-{name}\ndescription: d\n---\n\nbody\n", encoding="utf-8"
        )
    result = run_migrate(root, agent_root=agent_root)
    assert result.prompt_agents, "migrate wrote no prompt-agent graph; the fixture is wrong"
    return root, result


def _preflight_at(root: Path, tmp_path: Path, agent_path: str, **kw: object) -> Any:
    defaults: dict[str, object] = {
        "repo_root": root,
        "state_root": tmp_path / "state",
        "corpus_root": tmp_path / "corpus",
        "agent_path": agent_path,
        "graph_id": "g",
        "halt_channel_configured": False,
        "observations": tmp_path / "obs.jsonl",
    }
    defaults.update(kw)
    return preflight(**defaults)  # type: ignore[arg-type]


def test_a_persona_resolves_to_the_graph_migrate_generated_for_it(tmp_path: Path) -> None:
    """C<->D again: the REAL `run_migrate` output read back through the REAL
    preflight, this time addressed the way `--proposer rule_based_prompt`
    documents (by the persona). Obligation 2 was PERMANENTLY red here."""
    root, result = _prompt_repo(tmp_path)
    site = result.prompt_agents[0]

    obligation = _obligation(
        _preflight_at(root, tmp_path, site.source, agent_root=".claude/agents"),
        "reflect node routed to",
    )
    assert obligation.met, obligation.detail
    # ...and it names WHICH file it read, because the answer is about a file
    # the caller did not type.
    assert site.out_relative in obligation.detail, obligation.detail
    assert "route='reflect'" in obligation.detail, obligation.detail


def test_the_mapping_is_migrates_own_not_a_second_spelling_of_it(tmp_path: Path) -> None:
    """`marlin-accela` -> `marlin_accela` is ADR 0152's sanitiser. Resolving
    by re-deriving it here would be the ADR 0149 shape: two answers to one
    question, drifting the first time either gains a case."""
    from aef.harness.preflight import resolve_agent_source

    root, result = _prompt_repo(tmp_path)
    for site in result.prompt_agents:
        resolved = resolve_agent_source(root, site.source, agent_root=".claude/agents")
        assert resolved.path == site.out_relative, (site.source, resolved)
        assert resolved.persona == site.source
        assert not resolved.problem


def test_the_persona_form_catches_a_planted_sdk_import_in_the_generated_graph(
    tmp_path: Path,
) -> None:
    """The false pass, closed. The wide scan was off because `--agent-path`
    was not at its default — while the path it named was not a graph at all."""
    root, result = _prompt_repo(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "client.py").write_text("import anthropic\n\nC = anthropic.Anthropic\n")
    target = root / result.prompt_agents[0].out_relative
    target.write_text(target.read_text() + "\nfrom src.client import C  # noqa: E402,F401\n")

    obligation = _obligation(
        _preflight_at(
            root,
            tmp_path,
            result.prompt_agents[0].source,
            agent_root=".claude/agents",
        ),
        "model calls visible",
    )
    assert not obligation.met, obligation.detail
    assert "marlin_accela" in obligation.detail, obligation.detail
    assert "imports anthropic" in obligation.detail, obligation.detail


def test_naming_one_persona_still_scans_the_OTHER_agents_graphs(tmp_path: Path) -> None:
    """The wide scan, and it needs the fault in a graph the named persona does
    NOT resolve to — otherwise the narrow scan finds it and the test proves
    nothing (a mutation removing the widening survived the first version).

    Why widen at all here: with a persona the graph is this package's
    derivation from it, not a path the owner typed, which is exactly the
    condition ADR 0167 §8 widens for. The owner asked about an agent; the
    answer "your other agent reaches a model SDK the harness cannot see" is
    about the repo they are about to run a loop over.
    """
    root, result = _prompt_repo(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "client.py").write_text("import anthropic\n\nC = anthropic.Anthropic\n")
    other = root / result.prompt_agents[1].out_relative
    other.write_text(other.read_text() + "\nfrom src.client import C  # noqa: E402,F401\n")

    named = result.prompt_agents[0]
    assert "azure" in result.prompt_agents[1].out_relative
    obligation = _obligation(
        _preflight_at(root, tmp_path, named.source, agent_root=".claude/agents"),
        "model calls visible",
    )
    assert not obligation.met, obligation.detail
    assert "marlin_azure" in obligation.detail, obligation.detail


def test_a_persona_with_no_generated_graph_says_so_in_words(tmp_path: Path) -> None:
    """`no reflect node in the graph` is not what is wrong when there is no
    graph. The fix line must send the reader to `aef migrate`, not to an edit
    of a file that does not exist."""
    root, result = _prompt_repo(tmp_path)
    site = result.prompt_agents[0]
    (root / site.out_relative).unlink()

    checked = _preflight_at(root, tmp_path, site.source, agent_root=".claude/agents")
    for name in ("reflect node routed to", "model calls visible"):
        obligation = _obligation(checked, name)
        assert not obligation.met, obligation.detail
        assert "has no generated graph" in obligation.detail, obligation.detail
        assert site.source in obligation.detail, obligation.detail
        assert "no reflect node" not in obligation.detail, obligation.detail
        assert "aef migrate" in obligation.fix, obligation.fix


def test_a_markdown_file_that_is_no_persona_is_not_reported_as_a_missing_node(
    tmp_path: Path,
) -> None:
    root, _ = _prompt_repo(tmp_path)
    (root / "NOTES.md").write_text("# not a persona\n")

    obligation = _obligation(
        _preflight_at(root, tmp_path, "NOTES.md", agent_root=".claude/agents"),
        "reflect node routed to",
    )
    assert not obligation.met
    assert "markdown file" in obligation.detail, obligation.detail
    assert "no reflect node" not in obligation.detail, obligation.detail


def test_the_bless_fix_names_the_graph_not_the_persona(tmp_path: Path) -> None:
    """Under the DEFAULT root a persona lives outside the tree `bless`
    archives, so a fix line naming it is a command that refuses."""
    root, result = _prompt_repo(tmp_path, agent_root="agents")
    site = result.prompt_agents[0]

    obligation = _obligation(_preflight_at(root, tmp_path, site.source), "blessed baseline")
    assert site.out_relative in obligation.fix, obligation.fix
    assert site.source not in obligation.fix, obligation.fix


def test_a_python_agent_path_is_untouched_by_persona_resolution(tmp_path: Path) -> None:
    """The CONTROL. ADR 0167 §8 decided that a caller who NAMES a graph gets
    an answer about that graph — the wide scan is for a path this package
    guessed. A persona IS such a guess (the graph is derived from it); an
    explicitly named `.py` is not, and widening it here would be a fix wave
    strengthening a control nobody reproduced a problem with (ADR 0141)."""
    from aef.harness.preflight import resolve_agent_source

    root, result = _prompt_repo(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "client.py").write_text("import anthropic\n\nC = anthropic.Anthropic\n")
    dirty = root / result.prompt_agents[0].out_relative
    dirty.write_text(dirty.read_text() + "\nfrom src.client import C  # noqa: E402,F401\n")

    clean = result.prompt_agents[1].out_relative
    resolved = resolve_agent_source(root, clean, agent_root=".claude/agents")
    assert resolved.path == clean and not resolved.from_persona and not resolved.problem

    obligation = _obligation(
        _preflight_at(root, tmp_path, clean, agent_root=".claude/agents"),
        "model calls visible",
    )
    assert obligation.met, obligation.detail
    assert "1 graph scanned" in obligation.detail, obligation.detail


def test_a_persona_resolves_to_a_graph_kept_at_the_default_root(tmp_path) -> None:
    """ADR 0157/0158's configuration: `aef migrate` at the default root, the
    loop widened to the personas. The persona's generated graph lives under
    `agents/`, not under the widened root; the resolver must find it there
    rather than report the persona as unmigrated."""
    from aef.cli.migrate import run_migrate
    from aef.harness.preflight import resolve_agent_source

    repo = tmp_path / "repo"
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "accela-agent.md").write_text(
        "---\nname: harbor-accela\ndescription: d\n---\n\n# Accela\n\nbody\n"
    )
    run_migrate(repo)  # default root: graphs under agents/migrated/<module>/graph.py
    src = resolve_agent_source(repo, ".claude/agents/accela-agent.md", agent_root=".claude/agents")
    assert not src.problem, src.problem
    assert src.path.startswith("agents/migrated/"), src.path
    assert (repo / src.path).is_file()
