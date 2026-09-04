"""What the CLI actually hands the gates.

Every defect here survived a green suite because **no test imported
`aef.cli.loop._config`**. The acceptance proof for the six-gate pipeline
(`test_evidence_loop.py`) hand-built its own `LoopConfig` and filled in two
fields the CLI never set — so the tests exercised a configuration no user
could produce, and G2 and G3 had never executed outside a test (ADR 0074).

The rule these encode: a test that constructs the object under test itself
cannot see a defect in how the shipping caller constructs it. Where the
seam is the caller, the test has to start at the caller.
"""

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import archive
from aef.harness.corpus import Expected
from aef.harness.gates.base import GateOutcome
from aef.harness.gates.g5_rate_drift import G5RateAndDrift
from aef.harness.git import GitRepo
from aef.harness.preflight import BlessError, bless

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _parsed(*argv: str) -> argparse.Namespace:
    from aef.cli.main import build_parser

    return build_parser().parse_args(argv)


def _gate_args(*argv: str) -> argparse.Namespace:
    # `--state` must be outside any repository or the driver refuses it.
    return _parsed(
        "loop",
        "gate",
        "--state",
        "/tmp/aef-state-not-in-repo",
        "--head",
        "x",
        "--workdir",
        "/tmp/w",
        *argv,
    )


# --------------------------------------------------------------------------
# The unwired second clock
# --------------------------------------------------------------------------


def test_the_config_the_cli_builds_has_no_unwired_clock() -> None:
    """`LoopConfig.now_for_gates` was set by tests and by nothing else. G5
    fails without a clock, and the pipeline is fail-fast in canonical order
    G0,G1,G4,G5,G2,G3 — so from any real command the run stopped at G5 and
    the two most expensive gates never ran at all."""
    from aef.harness.loop import LoopConfig

    assert not hasattr(LoopConfig, "now_for_gates"), (
        "a clock on the config is a second source of truth that only tests "
        "populate; gate() already receives `now` from its caller"
    )


def test_the_evidence_wiring_takes_the_callers_clock() -> None:
    import inspect

    from aef.harness.loop import _gates_with_evidence

    assert "now" in inspect.signature(_gates_with_evidence).parameters


def test_g5_distinguishes_a_missing_clock_from_a_missing_baseline() -> None:
    """One message covered both, and it named the baseline — so a candidate
    that failed for a wiring fault was told the owner had never blessed
    anything, while version 1 sat in the archive. A refusal that misnames its
    cause sends the operator to fix the wrong thing."""
    ctx = None  # G5 returns before touching it in both branches
    no_baseline = G5RateAndDrift(now=NOW).run(ctx)  # type: ignore[arg-type]
    no_clock = G5RateAndDrift(baseline_files={}, candidate_files={}, now=None).run(ctx)  # type: ignore[arg-type]

    assert no_baseline.outcome is GateOutcome.FAIL
    assert no_clock.outcome is GateOutcome.FAIL
    assert "blessed" in no_baseline.reason
    assert "blessed" not in no_clock.reason
    assert "clock" in no_clock.reason


# --------------------------------------------------------------------------
# The entrypoint default that assumed a layout nothing has
# --------------------------------------------------------------------------


def test_there_is_no_default_entrypoint() -> None:
    """It defaulted to `agents.graph:build_graph`. Nothing in this repo or in
    anything `aef adopt` writes uses that path, so G2/G3 died on an import
    error buried in a ledger note and the run read as an ordinary rejection —
    ADR 0069 defect 3, one field over."""
    from aef.harness.loop import LoopConfig

    assert (
        LoopConfig(
            repo=GitRepo(root=Path("/nowhere")),
            paths=__import__("aef.harness.loop", fromlist=["LoopPaths"]).LoopPaths(
                root=Path("/tmp/state-not-in-repo")
            ),
        ).entrypoint
        is None
    )


def test_the_entrypoint_is_settable_from_the_cli() -> None:
    from aef.cli.loop import _config

    args = _gate_args("--entrypoint", "agents.mine.graph:build_graph")
    assert _config(args).entrypoint == "agents.mine.graph:build_graph"


def test_a_missing_entrypoint_says_so_instead_of_importing_nothing() -> None:
    from aef.cli.loop import _config
    from aef.harness.candidate import CandidateDiff, CandidateVerdict
    from aef.harness.loop import _gates_with_evidence
    from aef.harness.zones import ZoneVerdict

    args = _gate_args()
    verdict = CandidateVerdict(
        diff=CandidateDiff(
            base_ref="main", head_ref="x", base_sha="a" * 40, head_sha="b" * 40, entries=()
        ),
        zones=ZoneVerdict(verdicts=()),
        mode_violations=(),
    )
    _, note = _gates_with_evidence(_config(args), verdict, Path("/tmp/w"), NOW)
    assert "--entrypoint" in note, note


# --------------------------------------------------------------------------
# One cohort failure disabled three gates
# --------------------------------------------------------------------------


def test_a_cohort_failure_does_not_strip_g5s_evidence() -> None:
    """G5 was wired *after* the cohort was built, so a `SuiteError` returned
    early and G5 lost its baseline too — then reported that no baseline
    existed, while one sat in the archive. A cohort failure is not evidence
    about the baseline."""
    import inspect

    from aef.harness.loop import _gates_with_evidence

    source = inspect.getsource(_gates_with_evidence)
    g5_wiring = source.index("_with_g5")
    cohort_failure = source.index("could not build evidence")
    assert g5_wiring < cohort_failure, (
        "G5 must be wired before the cohort is attempted, or a cohort failure "
        "silently disables it and misattributes its own cause"
    )


# --------------------------------------------------------------------------
# The control cohort carried the candidate's other files
# --------------------------------------------------------------------------


def test_controls_are_built_from_the_incumbent_not_the_candidate() -> None:
    """`build_candidate_workspace` overlays the WHOLE candidate diff; only
    `targets[0]` was then replaced with a mutated incumbent file. On a
    two-file candidate every control carried the candidate's changes to the
    other file, so all five scored identically to the candidate, p95 rose to
    meet it, and G3 could never pass.

    The comment in `suite.py` records this exact failure being found and
    fixed for the single-file case; the fix had been applied to one file."""
    import inspect

    from aef.harness.suite import CohortBuilder

    source = inspect.getsource(CohortBuilder._control_workspaces)
    assert "build_candidate_workspace" not in source, (
        "a control built from the candidate workspace inherits the candidate's "
        "changes to every file except the one being mutated"
    )
    assert "_materialise_base" in source


# --------------------------------------------------------------------------
# bless: the whole tree, read from git
# --------------------------------------------------------------------------


def _repo(tmp_path: Path, *, extra: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "repo"
    (repo / "agents" / "demo").mkdir(parents=True)
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 3\n")
    (repo / "agents" / "demo" / "helper.py").write_text("SUPPORT = 1\n")
    for name, body in (extra or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(body)

    def git(*a: str) -> None:
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "init")
    return repo


def test_bless_archives_the_whole_zone_a_tree(tmp_path: Path) -> None:
    """It archived the single `--agent-path` file. G5 computes drift over the
    UNION of the baseline's and the candidate's path sets, and the candidate
    side describes the whole tree — so every other Zone A file read as fully
    deleted and the *first* candidate after a blessing was rejected for 0.583
    drift it had not caused."""
    repo = _repo(tmp_path)
    bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/demo/graph.py",
        graph_id="g",
        at=NOW,
    )
    files = archive.read_files(tmp_path / "state" / "archive", "g", 1)
    assert set(files) == {"agents/demo/graph.py", "agents/demo/helper.py"}


def test_the_two_sides_of_the_drift_metric_describe_the_same_tree(tmp_path: Path) -> None:
    """The end the arithmetic actually has to satisfy: an untouched candidate
    is zero drift from its own blessed baseline. It scored 1.000."""
    from aef.harness.candidate import inspect_candidate
    from aef.harness.gates.g5_rate_drift import structural_drift
    from aef.harness.loop import LoopConfig, LoopPaths, _blessed_baseline, _candidate_files

    repo = _repo(tmp_path)
    bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/demo/graph.py",
        graph_id="g",
        at=NOW,
    )
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "cand"], check=True)
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 5\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "c"], check=True, capture_output=True)

    config = LoopConfig(
        repo=GitRepo(root=repo), paths=LoopPaths(root=tmp_path / "state"), graph_id="g"
    )
    verdict = inspect_candidate(config.repo, "main", "cand", config.zone_policy)
    baseline = _blessed_baseline(config)
    assert baseline is not None
    drift = structural_drift(baseline, _candidate_files(config, verdict))

    # One changed line in a two-file, two-line tree. The old arithmetic —
    # whole-tree baseline against changed-files-only candidate — scored this
    # as helper.py being deleted on top of the real change.
    assert drift < 0.6, f"drift {drift} charges files the candidate never touched"
    assert "agents/demo/helper.py" in _candidate_files(config, verdict)


def test_bless_reads_the_baseline_from_git_not_the_working_tree(tmp_path: Path) -> None:
    """A baseline blessed from a dirty tree records a state that exists
    nowhere in history, so nothing can be compared against it reproducibly.
    Found by running it: an uncommitted `__pycache__` landed on one side of
    the drift metric only and charged 0.430 for a two-line change."""
    repo = _repo(tmp_path)
    (repo / "agents" / "demo" / "graph.py").write_text("RETRY_BUDGET = 999  # uncommitted\n")
    bless(
        repo_root=repo,
        state_root=tmp_path / "state",
        agent_path="agents/demo/graph.py",
        graph_id="g",
        at=NOW,
    )
    blessed = archive.read_files(tmp_path / "state" / "archive", "g", 1)
    assert b"999" not in blessed["agents/demo/graph.py"]


def test_bless_refuses_an_uncommitted_agent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "agents" / "demo" / "brand_new.py").write_text("X = 1\n")
    with pytest.raises(BlessError, match="commit it first"):
        bless(
            repo_root=repo,
            state_root=tmp_path / "state",
            agent_path="agents/demo/brand_new.py",
            graph_id="g",
            at=NOW,
        )


# --------------------------------------------------------------------------
# Obligation 1 had the same hole obligation 5 had
# --------------------------------------------------------------------------


def test_the_cli_can_label_a_tripwire() -> None:
    """`preflight` told adopters to 'label one MUST_FAIL' and no command could
    write the label: harvest hardcodes UNSPECIFIED and `record` had no flag.
    So obligation 1 was unmeetable in exactly the way obligation 5 was —
    documented, required, and with nothing behind it (ADR 0073)."""
    args = _parsed(
        "loop",
        "record",
        "m",
        "--corpus",
        "c",
        "--scenario-id",
        "s",
        "--objective",
        "o",
        "--expected",
        "must_fail",
    )
    assert args.expected == Expected.MUST_FAIL.value


def test_the_cli_can_drive_the_agent_into_a_failing_case() -> None:
    """LOOP.md tells owners to record failing scenarios, and `record` ran the
    agent with an empty working memory every time — so every recorded
    scenario landed on the happy path and no tripwire was reachable."""
    args = _parsed(
        "loop",
        "record",
        "m",
        "--corpus",
        "c",
        "--scenario-id",
        "s",
        "--objective",
        "o",
        "--working-memory",
        '{"difficulty": 99}',
    )
    assert args.working_memory == '{"difficulty": 99}'


def test_a_tripwire_must_be_impossible_not_merely_hard() -> None:
    """Labelling an achievable task MUST_FAIL makes every real improvement
    look like reward hacking — the opposite of what the tripwire is for."""
    from aef.harness.recorder import RecorderError, record_run
    from aef.kernel import END, Graph, Node, Services
    from aef.services.memory.in_memory import InMemoryMemoryStore
    from aef.state import AEFState, Plan, StateDelta

    def always_succeeds(state, ctx, services):  # type: ignore[no-untyped-def]
        return StateDelta(plan=Plan(goal=state.objective, status="done")), END

    graph = Graph(
        id="g",
        version="1",
        nodes={"work": Node(id="work", version="1", fn=always_succeeds, deterministic=True)},
        edges=[],
        entry_node="work",
    )

    with pytest.raises(RecorderError, match="impossible in principle"):
        record_run(
            graph,
            AEFState(run_id="r", agent_id="demo", objective="easy"),
            Services(memory=InMemoryMemoryStore()),
            scenario_id="bogus",
            recorded_at=NOW,
            expected=Expected.MUST_FAIL,
        )


# --------------------------------------------------------------------------
# One incident, one count
# --------------------------------------------------------------------------


def test_a_security_event_is_counted_once(tmp_path: Path) -> None:
    """`security_event` was written on the GATED entry and again on the
    REJECTED entry, and the digest counts one per entry carrying the key —
    so a single Zone B incident was reported to the owner as two."""
    from aef.harness import ledger
    from aef.harness.monitoring import build_digest

    root = tmp_path / "state"
    ledger.append(
        root,
        kind=ledger.EventKind.GATED,
        at=NOW,
        proposal_id="p",
        summary="s",
        detail={"security_gates": ["G0"]},
    )
    ledger.append(
        root,
        kind=ledger.EventKind.REJECTED,
        at=NOW,
        proposal_id="p",
        summary="s",
        detail={"security_event": True},
    )
    digest = build_digest(ledger.read(root), since=NOW.replace(year=2025), until=NOW)
    assert digest.security_events == 1


# --------------------------------------------------------------------------
# The class of defect, not one instance of it
# --------------------------------------------------------------------------


def test_every_fix_doctor_prints_is_a_command_the_cli_accepts(tmp_path: Path) -> None:
    """Three separate defects have now been "doctor/docs print a command the
    CLI rejects" (#10, #18, and the tripwire fix that named no flag able to
    write the label). Assert the class rather than the instances: parse every
    fix string doctor emits through the real parser.
    """
    import re
    import shlex

    from aef.cli.main import build_parser
    from aef.harness.preflight import preflight

    report = preflight(
        repo_root=tmp_path / "repo",
        state_root=tmp_path / "state",
        corpus_root=tmp_path / "corpus",
        agent_path="agents/demo/graph.py",
        graph_id="g",
        halt_channel_configured=False,
        observations=tmp_path / "obs.jsonl",
    )
    parser = build_parser()
    checked = 0
    for obligation in report.obligations:
        fix = obligation.fix.strip()
        if not fix.startswith("aef "):
            continue  # prose instructions, not commands
        # One command per fix, followed by prose explaining why. Split on a
        # sentence boundary, not on any ". " — `--repo . --state` contains one.
        command = re.split(r"(?<=[\w'\"])\. (?=[A-Z])", fix)[0]
        argv = shlex.split(command)[1:]
        parser.parse_args(argv)  # raises SystemExit if the CLI would refuse
        checked += 1
    assert checked >= 2, "no runnable fix strings were actually checked"


# --------------------------------------------------------------------------
# The gates run one graph's scenarios, not the whole corpus (ADR 0125)
# --------------------------------------------------------------------------


def _scenario_for(sid: str, graph_id: str):  # type: ignore[no-untyped-def]
    from aef.harness.corpus import Scenario, Split
    from aef.kernel import END, Graph, GraphExecutor, Node
    from aef.services.runtime import agent_services
    from aef.state import AEFState, Plan, StateDelta

    def passing(state, ctx, services):  # type: ignore[no-untyped-def]
        return (
            StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
            END,
        )

    graph = Graph(
        id=graph_id,
        version="1",
        nodes={"do": Node(id="do", version="1", fn=passing, deterministic=True)},
        edges=[],
        entry_node="do",
    )
    state = AEFState(run_id=sid, agent_id="a", objective="o")
    recorded = GraphExecutor(graph.compile(), agent_services()).run(state, record_trace=True)
    return Scenario(
        id=sid,
        split=Split.TRAIN,
        graph_id=graph_id,
        graph_version="1",
        initial_state=state,
        trace=recorded.trace,
        recorded_at=NOW,
    )


def _two_graph_corpus(tmp_path: Path):  # type: ignore[no-untyped-def]
    from aef.harness.corpus import Corpus

    return Corpus(
        root=tmp_path / "corpus",
        scenarios=(
            _scenario_for("demo-1", "demo_agent"),
            _scenario_for("demo-2", "demo_agent"),
            _scenario_for("sum-1", "summary_agent"),
            _scenario_for("sum-2", "summary_agent"),
            _scenario_for("sum-3", "summary_agent"),
        ),
    )


def _verdict():  # type: ignore[no-untyped-def]
    from aef.harness.candidate import CandidateDiff, CandidateVerdict
    from aef.harness.zones import ZoneVerdict

    return CandidateVerdict(
        diff=CandidateDiff(
            base_ref="main", head_ref="main", base_sha="a" * 40, head_sha="b" * 40, entries=()
        ),
        zones=ZoneVerdict(verdicts=()),
        mode_violations=(),
    )


class _SpyCohortBuilder:
    """Captures the scenarios the cohort was asked to run, then stops."""

    seen: list[str] = []

    def __init__(self, **_: object) -> None:
        pass

    def build(self, diff, scenarios, workdir):  # type: ignore[no-untyped-def]
        type(self).seen = [s.id for s in scenarios]
        raise RuntimeError("spy: the cohort is not built in this test")


def test_the_gates_run_only_the_scenarios_recorded_from_this_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`corpus/` holds `demo_agent` and `summary_agent` recordings since ADR
    0123, and the gates ran all of them against whichever graph the
    entrypoint named — diluting every mean with scenarios the candidate could
    not satisfy. `aef loop score` filtered; the gates did not."""
    import aef.harness.loop as loop_module
    from aef.harness.loop import LoopConfig, LoopPaths, _gates_with_evidence

    monkeypatch.setattr(loop_module, "CohortBuilder", _SpyCohortBuilder)
    _SpyCohortBuilder.seen = []
    config = LoopConfig(
        repo=GitRepo(root=_repo(tmp_path)),
        paths=LoopPaths(root=tmp_path / "state"),
        corpus=_two_graph_corpus(tmp_path),
        entrypoint="agents.demo.graph:build_graph",
        graph_id="demo_agent",
    )
    _gates_with_evidence(config, _verdict(), tmp_path / "w", NOW)
    assert _SpyCohortBuilder.seen == ["demo-1", "demo-2"]


def test_a_mixed_corpus_with_no_matching_graph_refuses_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not silent emptiness: an empty scenario list reads to G2/G3 as "no
    evidence", which escalates with none of the information about why."""
    import aef.harness.loop as loop_module
    from aef.harness.loop import (
        CorpusGraphMismatchError,
        LoopConfig,
        LoopPaths,
        _gates_with_evidence,
    )

    monkeypatch.setattr(loop_module, "CohortBuilder", _SpyCohortBuilder)
    config = LoopConfig(
        repo=GitRepo(root=_repo(tmp_path)),
        paths=LoopPaths(root=tmp_path / "state"),
        corpus=_two_graph_corpus(tmp_path),
        entrypoint="agents.demo.graph:build_graph",
        graph_id="default",
    )
    with pytest.raises(CorpusGraphMismatchError, match="--graph-id"):
        _gates_with_evidence(config, _verdict(), tmp_path / "w", NOW)


def test_a_single_graph_corpus_still_gates_on_all_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule stated in ADR 0125: `--graph-id` defaults to `"default"` and
    is the ARCHIVE key, a different namespace from `graph.id`. A corpus that
    records one graph has nothing to disambiguate, so requiring the two
    namespaces to agree would break every existing single-graph corpus to fix
    a mixed-corpus defect."""
    import aef.harness.loop as loop_module
    from aef.harness.corpus import Corpus
    from aef.harness.loop import LoopConfig, LoopPaths, _gates_with_evidence

    monkeypatch.setattr(loop_module, "CohortBuilder", _SpyCohortBuilder)
    _SpyCohortBuilder.seen = []
    config = LoopConfig(
        repo=GitRepo(root=_repo(tmp_path)),
        paths=LoopPaths(root=tmp_path / "state"),
        corpus=Corpus(
            root=tmp_path / "corpus",
            scenarios=(_scenario_for("only-1", "g"), _scenario_for("only-2", "g")),
        ),
        entrypoint="agents.demo.graph:build_graph",
        graph_id="default",
    )
    _gates_with_evidence(config, _verdict(), tmp_path / "w", NOW)
    assert _SpyCohortBuilder.seen == ["only-1", "only-2"]
