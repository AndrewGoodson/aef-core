"""The adoption sequence, executed as ONE sequence.

Defect #10 (G1's defaults assumed aef-core's own tree) lived in this path and
survived because adoption had only ever had a smoke-level pass. This test
performs the whole documented LOOP workflow against a real adopted repo.

**Read the fixture before trusting this file's coverage.** It hand-writes
`agents/mine/graph.py` and `tests/test_smoke.py` — the two preconditions a
real `aef adopt` output does NOT have. That is necessary here, because the
loop needs an agent to run at all, but it means this file cannot see any
defect in the state an adopter actually starts from. Five defects survived a
984-test suite behind exactly that gap (ADR 0079).

`test_pristine_adoption.py` is the other half: unmodified `aef adopt` output,
nothing added. Neither file is sufficient alone.

**K3 (ADR 0139)** adds the other end of the sequence:
`test_an_adopted_repo_gates_a_candidate_end_to_end` runs adopt → migrate →
bootstrap → tripwire → bless → `aef loop cycle` and asserts a candidate was
proposed AND gated on real evidence. What it hand-writes between migrate and
bootstrap is not convenience — it is the *measured minimum* an adopter must
supply before the loop can propose anything, each element of it demonstrated
by removing it and watching the cycle go quiet (ADR 0139's Evidence). The
same minimum leads the generated `LOOP.md`.
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

AGENT = """from __future__ import annotations

from aef.kernel import END, Context, Graph, Node, Route, Services
from aef.state import AEFState, Plan, Provenance, StateDelta

RETRY_BUDGET = 3


def work_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    difficulty = int(state.working_memory.get("difficulty", 1))
    prov = Provenance(node_id=ctx.node_id, graph_version=ctx.graph_version,
                      ts=ctx.now, trace_id=ctx.trace_id, token_cost=difficulty)
    if difficulty <= RETRY_BUDGET:
        return StateDelta(plan=Plan(goal=state.objective, status="done"),
                          scores={"quality": 1.0}, provenance=[prov]), END
    return StateDelta(plan=Plan(goal=state.objective, status="failed"),
                      errors=[{"node_id": ctx.node_id, "error": "too hard"}],
                      scores={"quality": 0.0}, provenance=[prov]), END


def build_graph() -> Graph:
    n = Node(id="work", version="0.1.0", fn=work_node, deterministic=True)
    return Graph(id="mine", version="0.1.0", nodes={"work": n}, edges=[], entry_node="work")
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _aef(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aef.cli.main", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


@pytest.fixture
def adopted(tmp_path: Path) -> tuple[Path, Path]:
    """A real repo that has run `aef adopt`, plus a state dir outside it."""
    repo = tmp_path / "adoptee"
    repo.mkdir()
    (repo / "README.md").write_text("# mine\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    from aef.cli.adopt import run_adopt

    run_adopt(repo)

    # ADDED BY THE TEST, not by `aef adopt` — see the module docstring. Any
    # assertion below that depends on these files says nothing about a real
    # adoption.
    (repo / "agents" / "mine").mkdir(parents=True, exist_ok=True)
    (repo / "agents" / "__init__.py").write_text("")
    (repo / "agents" / "mine" / "__init__.py").write_text("")
    (repo / "agents" / "mine" / "graph.py").write_text(AGENT)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_smoke.py").write_text(
        "def test_builds() -> None:\n"
        "    from agents.mine.graph import build_graph\n"
        "    assert build_graph().id == 'mine'\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted")
    return repo, tmp_path / "loop-state"


@pytest.mark.slow
def test_the_documented_adoption_sequence_runs_clean(adopted: tuple[Path, Path]) -> None:
    repo, state = adopted

    status = _aef(repo, "loop", "status", "--repo", ".", "--state", str(state))
    assert status.returncode == 0, status.stderr
    assert "chain verified" in status.stdout

    # A FAILING run — the corpus needs failures, and until --working-memory
    # existed there was no way to produce one from the CLI.
    run = _aef(
        repo,
        "run",
        "agents.mine.graph",
        "--objective",
        "hard",
        "--working-memory",
        json.dumps({"difficulty": 9}),
        "--record-runs",
        str(state / "runs"),
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["plan"]["status"] == "failed"

    harvest = _aef(
        repo,
        "loop",
        "harvest",
        "agents.mine.graph",
        "--repo",
        ".",
        "--state",
        str(state),
        "--runs",
        str(state / "runs"),
        "--corpus",
        "corpus",
    )
    assert harvest.returncode == 0, harvest.stderr
    assert "promoted 1 run(s)" in harvest.stdout
    assert list((repo / "corpus" / "train").glob("*.json")), "the corpus did not grow"

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "corpus")

    cycle = _aef(
        repo,
        "loop",
        "cycle",
        "--repo",
        ".",
        "--state",
        str(state),
        "--workdir",
        str(state / "work"),
        "--module",
        "agents.mine.graph",
        "--corpus",
        "corpus",
        "--memory",
        str(state / "memory.jsonl"),
        "--build-command",
        "python -m pytest -q",
    )
    assert cycle.returncode in (0, 1), cycle.stderr  # 2 would mean halted
    assert "ledger verified" in cycle.stdout

    monitor = _aef(repo, "loop", "monitor", "--repo", ".", "--state", str(state))
    assert monitor.returncode == 0, monitor.stderr

    digest = _aef(
        repo,
        "loop",
        "digest",
        "--repo",
        ".",
        "--state",
        str(state),
        "--runs",
        str(state / "runs"),
    )
    assert digest.returncode == 0, digest.stderr
    assert "Production runs recorded: 1" in digest.stdout
    # The loop must nag about an unconfigured halt channel, every run.
    assert "No halt channel is configured" in digest.stdout


def test_loop_md_documents_every_obligation(adopted: tuple[Path, Path]) -> None:
    """Each was discovered by RUNNING the sequence and finding it stuck."""
    repo, _ = adopted
    text = (repo / "LOOP.md").read_text()

    for obligation in (
        "A corpus",
        "reflect node",
        "Observations",
        "Halt notification",
        "blessed baseline",
        # ADR 0137. The only obligation an adopter cannot discover by being
        # stuck: a node that builds its own client runs, and doctor was green.
        "Model calls that go through `Services`",
    ):
        assert obligation in text, f"LOOP.md does not mention: {obligation}"
    # The count doctor prints and the count LOOP.md promises must agree — two
    # numbers nobody compares is how this repo keeps finding drift (ADR 0091).
    assert "Six things you must supply" in text
    assert "all six obligations" in text
    # The trap that catches everyone once.
    # An edge alone does not route, AND a route with no edge is refused by
    # the executor. LOOP.md documented only the first half, so an adopter
    # following it literally hit `node 'work' routed to 'reflect', but no
    # declared edge ... has a true condition` (ADR 0075).
    assert "BOTH an edge and a route" in text
    assert 'return delta, "reflect"' in text
    assert "Edge(from_node=" in text
    # The flag without which no failing run can be produced.
    assert "--working-memory" in text


@pytest.mark.slow
def test_doctor_drives_a_fresh_repo_to_all_five_green(adopted: tuple[Path, Path]) -> None:
    """The end state nobody had reached: every obligation met, so the gates
    judge on real evidence rather than refusing for lack of it."""
    repo, state = adopted

    first = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--corpus",
        "corpus",
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert first.returncode != 0, "a fresh repo cannot already be ready"

    blessed = _aef(
        repo,
        "loop",
        "bless",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert blessed.returncode == 0, blessed.stderr
    assert "baseline v1" in blessed.stdout

    again = _aef(
        repo,
        "loop",
        "bless",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert again.returncode != 0, "blessing twice must be refused"

    after = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--corpus",
        "corpus",
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert "[OK] blessed baseline" in after.stdout


def test_loop_md_leads_with_doctor(adopted: tuple[Path, Path]) -> None:
    repo, _ = adopted
    text = (repo / "LOOP.md").read_text()
    assert "aef loop doctor" in text
    # The command must be the one the CLI accepts, not an aspirational one.
    assert "bless <module>" not in text


def test_loop_md_leads_with_the_measured_minimum(adopted: tuple[Path, Path]) -> None:
    """ADR 0139 put this at the TOP for a reason: every item below makes
    `aef loop cycle` exit 0 having done nothing, which reads as success. An
    obligation whose failure mode is a green light cannot live in step five."""
    text = (adopted[0] / "LOOP.md").read_text()

    minimum = text.index("what the loop needs before it can propose ANYTHING")
    assert minimum < text.index("## Six things you must supply"), (
        "the minimum has drifted below the obligations it must precede"
    )
    assert minimum < text.index("## Running it")

    # Each line of the table is a refusal that was RUN, quoted verbatim.
    for quoted in (
        "candidate touches paths outside Zone A",
        "the proposer produced nothing from the available evidence",
        "no admissible failure memory: no candidate this cycle",
        "no entrypoint configured: G2/G3 will refuse",
    ):
        assert quoted in text, f"LOOP.md no longer quotes the measured refusal: {quoted}"

    # The three things `aef migrate` cannot do for you, and the one thing no
    # amount of documentation removes.
    assert "aef migrate` writes none of the first four" in text
    assert "which is Zone C" in text
    assert "no live provider to fall through to" in text
    assert "__pycache__/" in text and "0.468 of a 0.500 budget" in text


# ---------------------------------------------------------------------------
# K3 (ADR 0139) — the other end of the sequence: a candidate, gated.
# ---------------------------------------------------------------------------

RAW_SDK_AGENT = """import anthropic


def run_agent(objective: str) -> str:
    client = anthropic.Anthropic()
    reply = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": objective}],
    )
    return reply.content[0].text
"""

# THE MEASURED MINIMUM (ADR 0139). Every part of this that is not obviously
# "an agent" is here because removing it was RUN and the cycle went quiet:
#
#   no module-level numeric constant  -> "the proposer produced nothing from
#                                         the available evidence"
#   `return delta, END` (no route)    -> "no admissible failure memory"
#   no failing `aef run --memory`     -> "no admissible failure memory"
#   the file outside `agents/`        -> "G0 rejected it: candidate touches
#                                         paths outside Zone A"
#
# `aef migrate` generates none of it: its node has no constants, no reflect
# node, and lands at the repo root, which is Zone C.
MINIMUM_AGENT = """from __future__ import annotations

from aef.kernel import END, Context, Edge, Graph, Node, Route, Services
from aef.reasoning.nodes import make_reflect_node
from aef.state import AEFState, Plan, Provenance, StateDelta

RETRY_BUDGET = 3
QUALITY_THRESHOLD = 3


def work_node(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
    difficulty = int(state.working_memory.get("difficulty", 1))
    quality_needed = int(state.working_memory.get("quality_needed", 1))
    prov = Provenance(node_id=ctx.node_id, graph_version=ctx.graph_version,
                      ts=ctx.now, trace_id=ctx.trace_id, token_cost=difficulty * 10)
    if difficulty <= RETRY_BUDGET and quality_needed <= QUALITY_THRESHOLD:
        return StateDelta(plan=Plan(goal=state.objective, status="done"),
                          scores={"quality": 1.0}, provenance=[prov]), "reflect"
    return StateDelta(plan=Plan(goal=state.objective, status="failed"),
                      errors=[{"node_id": ctx.node_id, "error": "gave up"}],
                      scores={"quality": 0.0}, provenance=[prov]), "reflect"


def build_graph() -> Graph:
    work = Node(id="work", version="0.1.0", fn=work_node, deterministic=True)
    reflect = make_reflect_node(route=END)
    return Graph(id="mine", version="0.1.0",
                 nodes={"work": work, "reflect": reflect},
                 edges=[Edge(from_node="work", to_node="reflect")],
                 entry_node="work")
"""

BOOTSTRAP_INPUTS = [
    {"objective": "an ordinary task"},
    {"objective": "another ordinary task", "working_memory": {"difficulty": 2}},
    {
        "id": "beyond-the-budget",
        "objective": "a task past the retry budget",
        "working_memory": {"difficulty": 9, "quality_needed": 1},
    },
    {
        "objective": "a task past the quality bar",
        "working_memory": {"difficulty": 1, "quality_needed": 9},
    },
]


@pytest.fixture
def raw_sdk_adoptee(tmp_path: Path) -> tuple[Path, Path]:
    """A fresh repo with ONE real agent that builds its own `anthropic` client,
    then `aef adopt`. Nothing else is added — the test itself supplies whatever
    the sequence turns out to require, and that is the finding."""
    repo = tmp_path / "adoptee"
    repo.mkdir()
    (repo / "README.md").write_text("# mine\n")
    # NOT written by `aef adopt`, and the reason it is here is measured
    # (ADR 0139). Without it the adopter's first `git add -A` commits
    # `agents/**/__pycache__/*.pyc` into ZONE A, and because those files did
    # not exist when the baseline was blessed, G5 charges them as drift:
    # **0.4675 of a 0.500 budget for a one-line candidate**, against 0.0238
    # for the same candidate with the bytecode excluded. ADR 0074 fixed the
    # aef-core side of this by reading both sides from git; nothing stops an
    # adopting repo from having the bytecode IN git.
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "src").mkdir()
    (repo / "src" / "__init__.py").write_text("")
    (repo / "src" / "my_agent.py").write_text(RAW_SDK_AGENT)

    from aef.cli.adopt import run_adopt

    run_adopt(repo)
    return repo, tmp_path


def _gated_entry(state: Path) -> dict[str, object]:
    """The `gated` ledger entry — where the gates record what they ran ON.

    Asserting against the CLI's one-line summary would prove only that a
    string was printed; the ledger holds the evidence note and each gate's own
    reason, which is what "the gates ran on real evidence" has to mean.
    """
    entries = [
        json.loads(line)
        for line in (state / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]
    gated = [e for e in entries if e["kind"] == "gated"]
    assert len(gated) == 1, f"expected one gated entry, got {[e['kind'] for e in entries]}"
    detail: dict[str, object] = gated[0]["detail"]
    return detail


@pytest.mark.slow
def test_an_adopted_repo_gates_a_candidate_end_to_end(
    raw_sdk_adoptee: tuple[Path, Path],
) -> None:
    """The adopter's actual first day, in one sequence, with no credential.

    `test_the_documented_adoption_sequence_runs_clean` stops at a blessed
    baseline; `test_doctor_drives_a_fresh_repo_to_all_five_green` stops at a
    green obligation. Neither proves the expensive promise — that the loop can
    then *judge* something. Before this test, that had only ever run against
    this repo's own `agents/demo` and `agents/flaky` fixtures, which this repo
    wrote to be easy (ADR 0139).
    """
    repo, tmp_path = raw_sdk_adoptee
    state = tmp_path / "loop-state"

    # 1. migrate — K1's routed form, so the model call is visible.
    migrate = _aef(repo, "migrate", "--dir", ".")
    assert migrate.returncode == 0, migrate.stderr
    assert "1 routed through Services.model_provider" in migrate.stdout
    assert (repo / "aef_migrated.py").is_file()

    # 2. ...and it still cannot carry the loop. Recording ANY scenario from a
    #    routed model call needs a live provider — the cassette it will later
    #    replay from does not exist until something makes the call once. That
    #    is why the gated graph below calls no model, and it is the first line
    #    of the minimum LOOP.md now leads with.
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(BOOTSTRAP_INPUTS))
    migrated = _aef(
        repo, "loop", "bootstrap", "aef_migrated", "--corpus", "corpus", "--inputs", str(inputs)
    )
    assert migrated.returncode == 1, migrated.stdout
    assert "NOTHING was recorded" in migrated.stdout
    assert "no live provider" in migrated.stdout

    # 3. The minimum, hand-written. See MINIMUM_AGENT for why each part is here.
    (repo / "agents" / "mine").mkdir(parents=True, exist_ok=True)
    (repo / "agents" / "__init__.py").write_text("")
    (repo / "agents" / "mine" / "__init__.py").write_text("")
    (repo / "agents" / "mine" / "graph.py").write_text(MINIMUM_AGENT)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_smoke.py").write_text(
        "def test_builds() -> None:\n"
        "    from agents.mine.graph import build_graph\n"
        "    assert build_graph().id == 'mine'\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted")

    # 4. bootstrap — a corpus from one command (K2), no scenario hand-written.
    boot = _aef(
        repo,
        "loop",
        "bootstrap",
        "agents.mine.graph",
        "--corpus",
        "corpus",
        "--inputs",
        str(inputs),
        "--state",
        str(state),
    )
    assert boot.returncode == 0, boot.stderr
    assert "recorded 4 scenario(s) in the train split" in boot.stdout
    assert "2 of 4 recorded run(s) FAILED." in boot.stdout

    # 5. The tripwire line bootstrap printed, run VERBATIM. The owner's one
    #    act, and the only place a `must_fail` label may come from (ADR 0060).
    printed = [
        line.strip()
        for line in boot.stdout.splitlines()
        if line.strip().startswith("aef loop record") and "--expected must_fail" in line
    ]
    assert printed, boot.stdout
    tripwire = _aef(repo, *shlex.split(printed[0])[1:])
    assert tripwire.returncode == 0, f"{printed[0]}\n{tripwire.stderr}"
    assert "(validation)" in tripwire.stdout

    # 6. A FAILING run into the durable memory file the proposer will read.
    #    bootstrap cannot do this for you: it gives every input its own
    #    InMemoryMemoryStore, so nothing it learns survives the process.
    run = _aef(
        repo,
        "run",
        "agents.mine.graph",
        "--objective",
        "hard",
        "--working-memory",
        json.dumps({"difficulty": 9}),
        "--memory",
        str(state / "memory.jsonl"),
    )
    assert run.returncode == 0, run.stderr
    memory = [json.loads(line) for line in (state / "memory.jsonl").read_text().splitlines()]
    assert [r for r in memory if r["kind"] == "failure"], memory

    # 7. bless, then doctor — every obligation this sequence can meet is met.
    blessed = _aef(
        repo,
        "loop",
        "bless",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert blessed.returncode == 0, blessed.stderr

    doctor = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--corpus",
        "corpus",
        "--agent-path",
        "agents/mine/graph.py",
    )
    assert "[OK] corpus + tripwire" in doctor.stdout
    assert "[OK] reflect node routed to" in doctor.stdout
    assert "[OK] blessed baseline" in doctor.stdout
    assert "[OK] model calls visible" in doctor.stdout

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "corpus")

    # 8. One cycle. THE assertion this file existed without.
    cycle = _aef(
        repo,
        "loop",
        "cycle",
        "--repo",
        ".",
        "--state",
        str(state),
        "--workdir",
        str(state / "work"),
        "--module",
        "agents.mine.graph",
        "--corpus",
        "corpus",
        "--entrypoint",
        "agents.mine.graph:build_graph",
        "--memory",
        str(state / "memory.jsonl"),
        "--agent-path",
        "agents/mine/graph.py",
        "--build-command",
        "python -m pytest -q",
    )
    assert cycle.returncode in (0, 1), cycle.stderr  # 2 would mean halted
    assert "proposed cycle-" in cycle.stdout, cycle.stdout
    assert "gated: " in cycle.stdout, cycle.stdout

    # 9. ...and the gates judged EVIDENCE, not an absence of it.
    detail = _gated_entry(state)
    evidence = str(detail["evidence"])
    assert "could not build evidence" not in evidence, evidence
    assert "1 candidate + 1 incumbent + 5 random control(s)" in evidence, evidence
    assert "gating all 5 gated scenario(s)" in evidence, evidence

    gates = {str(g["gate"]): g for g in detail["gates"]}  # type: ignore[union-attr,index]
    assert set(gates) == {"G0", "G1", "G2", "G3", "G4", "G5"}, sorted(gates)

    # G2 re-executed the corpus rather than reporting it missing.
    assert str(gates["G2"]["reason"]).startswith("5 scenario(s) re-executed"), gates["G2"]
    assert gates["G2"]["outcome"] == "pass", gates["G2"]

    # G3 delivered a verdict ABOUT a cohort. The refusal it returns when
    # nothing built one is the exact thing this test exists to rule out.
    assert "no null-hypothesis control cohort" not in str(gates["G3"]["reason"]), gates["G3"]
    assert "control cohort" in str(gates["G3"]["reason"]), gates["G3"]

    # And the proposal was grounded in the failing run of step 6.
    grounded = detail["grounded_in"]
    assert any("(memory)" in str(c) for c in grounded), grounded  # type: ignore[union-attr]
