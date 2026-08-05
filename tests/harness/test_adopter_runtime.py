"""What an adopting repo actually runs.

ADR 0074 drew the rule "where the seam is the caller, the test has to start
at the caller" and applied it to `aef.cli.loop`. It was not applied to
`aef.cli.adopt_loop`, whose caller is the *adopter's CI* — and that join then
produced six more defects (ADR 0075). These tests start at the emitted
artifact.
"""

import shlex
from datetime import UTC, datetime

import pytest
import yaml

from aef.cli.adopt_loop import (
    render_corpus_readme,
    render_loop_gate_workflow,
    render_loop_md,
    render_loop_monitor_workflow,
)
from aef.cli.main import build_parser

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _commands(text: str) -> list[list[str]]:
    """Every `aef ...` invocation in an emitted document, line continuations
    joined."""
    joined = text.replace("\\\n", " ")
    out = []
    for raw in joined.splitlines():
        line = raw.strip().lstrip("$ ")
        if line.startswith("aef "):
            out.append(shlex.split(line)[1:])
    return out


# --------------------------------------------------------------------------
# Every emitted command must be one the CLI accepts
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "render", [render_loop_md, render_corpus_readme], ids=["LOOP.md", "corpus/README.md"]
)
def test_every_emitted_command_parses(render) -> None:  # type: ignore[no-untyped-def]
    """Three defects have been "a document prints a command the CLI rejects"
    (#10, #18, #27). Assert the class for the emitted docs, not instances."""
    parser = build_parser()
    commands = _commands(render("adoptee"))
    assert commands, "no commands found — the extractor is broken, not the docs"
    for argv in commands:
        parser.parse_args(argv)


# --------------------------------------------------------------------------
# The emitted CI workflows
# --------------------------------------------------------------------------


def test_the_gate_workflow_supplies_an_entrypoint() -> None:
    """Without `--entrypoint`, G2 and G3 cannot execute the corpus. The
    workflow shipped beside a LOOP.md that does pass it, and was never
    updated — so every adopter's CI would gate on the cheap gates only."""
    assert "--entrypoint" in render_loop_gate_workflow("adoptee")


def test_the_gate_workflow_supplies_a_build_command() -> None:
    """G1's default is `pytest -q`, which exits 5 — and so fails G1 — in a
    repo with no tests yet. LOOP.md says the green bar is the adopter's, and
    the workflow gave them nowhere to say so."""
    assert "--build-command" in render_loop_gate_workflow("adoptee")


@pytest.mark.parametrize(
    "render",
    [render_loop_gate_workflow, render_loop_monitor_workflow],
    ids=["loop-gate", "loop-monitor"],
)
def test_the_workflows_install_aef(render) -> None:  # type: ignore[no-untyped-def]
    """`pip install -e ".[dev]"` installs THIS repo. It worked only in
    aef-core, where this repo and aef are the same package; in an adopting
    repo it installs the adopter's own package and leaves `aef` missing, or
    fails outright when there is no pyproject.toml."""
    text = render("adoptee")
    assert "pip install aef-core" in text
    # The old line, in the run steps rather than in the comment explaining it.
    steps = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    assert 'pip install -e ".[dev]"' not in steps


@pytest.mark.parametrize(
    "render",
    [render_loop_gate_workflow, render_loop_monitor_workflow],
    ids=["loop-gate", "loop-monitor"],
)
def test_the_workflows_are_valid_yaml(render) -> None:  # type: ignore[no-untyped-def]
    assert yaml.safe_load(render("adoptee"))["jobs"]


def test_the_weekly_digest_is_weekly() -> None:
    """Written as `${{ a }} || b`, the `if:` is a non-empty STRING, and a
    non-empty string is truthy in Actions — so the weekly digest fired on
    every hourly cron."""
    text = render_loop_monitor_workflow("adoptee")
    condition = next(line.strip() for line in text.splitlines() if line.strip().startswith("if:"))
    assert condition.count("${{") == 1, f"two interpolations joined by literal ||: {condition}"
    assert condition.endswith("}}"), condition


# --------------------------------------------------------------------------
# The reflect node an adopter is told to add
# --------------------------------------------------------------------------


def test_the_gate_runner_can_run_an_agent_with_a_reflect_node() -> None:
    """ADR 0073 wired critic/judge into `aef run` and `aef loop record`
    because every reflect node needs them. `scenario_runner.run_scenario` was
    the THIRD construction site and was missed — and it is the one the gates
    use. So an adopter who satisfied obligation 2 made every scenario crash
    with ServiceNotConfiguredError, scoring the candidate, the incumbent and
    all five cohort members 0.0, and G3 rejected every candidate forever
    while `doctor` reported the obligation green."""
    from aef.harness.corpus import Scenario, Split
    from aef.harness.scenario_runner import run_scenario
    from aef.kernel import Edge, Graph, GraphExecutor, Node, Services
    from aef.reasoning.nodes import make_reflect_node
    from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.state import AEFState, Plan, StateDelta

    def work(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(plan=Plan(goal=state.objective, status="done")), "reflect"

    def build() -> Graph:
        return Graph(
            id="g",
            version="1",
            nodes={
                "work": Node(id="work", version="1", fn=work, deterministic=True),
                "reflect": make_reflect_node(),
            },
            edges=[Edge(from_node="work", to_node="reflect")],
            entry_node="work",
        )

    state = AEFState(run_id="r", agent_id="a", objective="o")
    wired = Services(
        memory=InMemoryMemoryStore(),
        critic=RuleBasedCritic(),
        judge=RuleBasedJudge(rubric={"quality": 1.0}),
    )
    recorded = GraphExecutor(build().compile(), wired).run(state, record_trace=True)
    scenario = Scenario(
        id="s",
        split=Split.VALIDATION,
        graph_id="g",
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=NOW,
    )

    out = run_scenario(scenario, build())
    assert out.get("failure") is None, out.get("failure")
    assert out["outcome"]["node_path"] == ["work", "reflect"]


def test_g2_has_no_entrypoint_default_either() -> None:
    """ADR 0074 deleted the default from `LoopConfig` and G2 kept its own —
    so the driver correctly reported "no entrypoint configured: G2/G3 will
    refuse" and G2 went and imported `agents.graph` anyway, crashing instead
    of refusing."""
    from aef.harness.gates.g2_outcome import G2OutcomeNonRegression

    assert G2OutcomeNonRegression().entrypoint is None


# --------------------------------------------------------------------------
# The scaffolded agent
# --------------------------------------------------------------------------


def test_the_scaffolded_graph_produces_a_passing_outcome() -> None:
    """`Outcome.passed` requires `plan_status == "done"`, and G2 skips any
    scenario whose incumbent did not pass. A scaffold that never sets a plan
    yields a corpus G2 can never reject anything against — while reporting
    "every previously-passing one still passes"."""
    from aef.cli.init import _GRAPH_TEMPLATE
    from aef.harness.outcome import classify
    from aef.kernel import GraphExecutor, Services
    from aef.state import AEFState

    namespace: dict[str, object] = {}
    exec(compile(_GRAPH_TEMPLATE.format(agent_name="demo"), "<scaffold>", "exec"), namespace)
    build = namespace["build_graph"]
    result = GraphExecutor(build().compile(), Services()).run(  # type: ignore[operator]
        AEFState(run_id="r", agent_id="a", objective="o"), record_trace=True
    )
    assert classify(result.final_state, result.trace, terminated=True).passed


# --------------------------------------------------------------------------
# The durable store the whole loop depends on, which had no test at all
# --------------------------------------------------------------------------


def test_the_file_memory_store_round_trips_every_declared_field(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`valid_from`/`valid_until` were written by nothing and read as None —
    silently, in the store whose own comment says dropping records silently
    is what it exists to avoid. A semantic memory with a validity window came
    back looking permanently valid."""
    from aef.harness.memory_store import FileMemoryStore
    from aef.services.memory.base import MemoryRecord

    store = FileMemoryStore(path=tmp_path / "mem.jsonl")
    record = MemoryRecord(
        kind="semantic",
        content={"lesson": "x"},
        run_id="r",
        agent_id="a",
        tags=("t",),
        created_at=NOW,
        valid_from=NOW,
        valid_until=datetime(2026, 4, 1, tzinfo=UTC),
    )
    store.write(record)
    read_back = store.get(record.id)
    assert read_back is not None
    for field in (
        "kind",
        "content",
        "run_id",
        "agent_id",
        "tags",
        "id",
        "created_at",
        "valid_from",
        "valid_until",
    ):
        assert getattr(read_back, field) == getattr(record, field), field


# --------------------------------------------------------------------------
# The audit trail
# --------------------------------------------------------------------------


def test_a_missing_memory_flag_is_not_reported_as_a_rejection() -> None:
    """`Path(None)` raised TypeError, which main() turns into exit 1 — the
    code meaning "this candidate is no good". A configuration error reported
    as a verdict makes CI retry it forever."""
    import inspect

    from aef.cli.loop import cmd_cycle

    assert "if args.memory else None" in inspect.getsource(cmd_cycle)


def test_a_grounded_proposals_citations_reach_the_report() -> None:
    """`cycle()` passed only a branch name to `gate()`, which rebuilt an
    empty stub — so the owner's review report described a memory-grounded
    proposal as "none (control-cohort member)", and no memory id appeared
    anywhere in loop state."""
    import inspect

    from aef.harness.loop import _render, cycle, gate

    assert "proposal" in inspect.signature(gate).parameters
    assert "proposal" in inspect.signature(_render).parameters
    assert "proposal=proposal" in inspect.getsource(cycle)


# --------------------------------------------------------------------------
# The other half of the audit trail
# --------------------------------------------------------------------------


def test_a_hole_in_the_archive_is_detected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The ledger's hash chain was verified on every command and the
    ARCHIVE's append-only property never was — `check_never_shrinks` had
    tests and no production caller. So a deleted version left `status`
    reporting healthy while the rollback target it names no longer existed.

    Verified against a planted fault, not just asserted on the happy path.
    """
    import shutil
    import subprocess

    from aef.harness import archive, ledger
    from aef.harness.git import GitRepo
    from aef.harness.loop import LoopConfig, LoopPaths, _preflight

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    state = tmp_path / "state"

    for version in (1, 2, 3):
        archive.record(
            state / "archive",
            "g",
            files={f"a{version}.py": b"x"},
            base_sha="0" * 40,
            head_sha="0" * 40,
            recorded_at=NOW,
            notes="n",
        )
        ledger.append(
            state,
            kind=ledger.EventKind.MERGED,
            at=NOW,
            proposal_id=f"p{version}",
            summary="s",
            detail={"archive_version": version},
        )

    config = LoopConfig(repo=GitRepo(root=repo), paths=LoopPaths(root=state), graph_id="g")
    _preflight(config)  # intact: does not raise

    shutil.rmtree(state / "archive" / "g" / "v000002")
    with pytest.raises(archive.ArchiveError, match=r"lost version\(s\) \[2\]"):
        _preflight(config)


def test_the_digest_reports_that_a_baseline_was_blessed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Every drift number is measured against the baseline, and the owner's
    weekly report never mentioned one had been set."""
    from aef.harness import ledger
    from aef.harness.monitoring import build_digest

    ledger.append(
        tmp_path,
        kind=ledger.EventKind.BLESSED,
        at=NOW,
        proposal_id="baseline@g",
        summary="owner-blessed baseline archived",
        detail={"archive_version": 1, "blessed": True},
    )
    digest = build_digest(
        ledger.read(tmp_path), since=NOW.replace(year=2025), until=NOW.replace(year=2027)
    )
    assert digest.blessed == 1
    assert "no baseline blessed" not in digest.render()
