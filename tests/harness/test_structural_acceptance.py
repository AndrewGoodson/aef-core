"""Milestone 1's acceptance proof: a PLANTED failure, REPAIRED, through all six gates.

ADR 0098 is why this file runs `gate()` and not a bare `GraphExecutor`. The
previous acceptance test proved its transformation repaired the planted
failure and was structurally incapable of noticing that the pipeline rejected
the transformation outright — G4 had forbidden `fallback_node_id` in
agent-authored code since ADR 0036/0039. Sixteen tests passed. None of them
ran a proposal through a gate.

So the bar here is deliberately the expensive one:

  1. plant a flaky node in a real agent, in a real git repo
  2. RECORD the corpus by running it — not hand-author it
  3. let `RuleBasedProposer` choose the transformation from failure memory
  4. run the resulting candidate through the REAL six-gate pipeline
  5. assert the disposition, and assert the repair actually happened

Steps 4 and 5 are separate assertions on purpose. "It repairs the failure"
and "the harness would accept it" are different claims, and Milestone 1's
first attempt satisfied the first while failing the second.
"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness import archive
from aef.harness.corpus import Corpus, Expected, Scenario, Split, load_corpus, save_scenario
from aef.harness.gates.g1_builds import G1Builds
from aef.harness.git import GitRepo
from aef.harness.loop import LoopConfig, LoopPaths, gate
from aef.harness.proposer import Citation, CitationKind, RuleBasedProposer
from aef.harness.review import Disposition
from aef.harness.transformations import RETRY_CONSTANT, add_bounded_retry
from aef.kernel import Graph
from aef.kernel.executor import GraphExecutor
from aef.services.runtime import agent_services
from aef.state import AEFState

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

# The planted failure. `fetch` fails the FIRST attempt of every run and
# succeeds on any later one — a flaky dependency, which is the failure mode
# `add_bounded_retry` exists for. The attempt counter is keyed by run_id so
# each scenario starts fresh; a module-level counter would let scenario 2 pass
# without a retry purely because scenario 1 had already burned the failure.
FLAKY_AGENT = '''"""A tiny agent with one flaky, non-deterministic node."""

from aef.kernel import END, Edge, Graph, Node
from aef.kernel.contracts import SideEffect
from aef.state import StateDelta

QUALITY_THRESHOLD = 3
TIMEOUT_SECONDS = 30.0
BACKOFF_SECONDS = 1.5

_ATTEMPTS: dict[str, int] = {}


def fetch(state, ctx, services):
    seen = _ATTEMPTS.get(state.run_id, 0)
    _ATTEMPTS[state.run_id] = seen + 1
    if seen == 0:
        raise RuntimeError("flaky upstream refused the first attempt")
    return StateDelta(working_memory={"fetched": True}), "finish"


def finish(state, ctx, services):
    return StateDelta(working_memory={"done": True}), END


def build_graph():
    return Graph(
        id="flaky_agent",
        version="0.1.0",
        nodes={
            "fetch": Node(
                id="fetch",
                version="0.1.0",
                fn=fetch,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: f"{s.run_id}:fetch",
            ),
            "finish": Node(id="finish", version="0.1.0", fn=finish, deterministic=True),
        },
        edges=[Edge(from_node="fetch", to_node="finish")],
        entry_node="fetch",
    )
'''


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _load_module(source: str, name: str) -> dict[str, object]:
    """Exec the agent source in a fresh namespace and build its graph.

    Fresh each time so `_ATTEMPTS` starts empty — sharing it between the
    incumbent and the candidate would let the candidate inherit the
    incumbent's burned first attempts and pass for the wrong reason.
    """
    namespace: dict[str, object] = {"__name__": name}
    exec(compile(source, name, "exec"), namespace)  # noqa: S102 - test fixture
    return namespace


def _load_flaky_graph(source: str, name: str) -> Graph:
    build = _load_module(source, name)["build_graph"]
    assert callable(build)
    return build()  # type: ignore[no-any-return]


def _record_scenarios() -> tuple[Scenario, ...]:
    """RUN the agent and record real traces. Not hand-authored.

    Recorded **while the dependency was healthy** — `_ATTEMPTS` is pre-seeded
    so the flake does not fire — which is the honest sequence: the corpus
    captures the agent working, the dependency then goes flaky, and the loop
    is asked to repair it. Recording crashed runs instead pins zero clock
    values, and a scenario that pins no clocks fails any run that executes a
    step: "the candidate executed more steps than the recording".
    """
    scenarios: list[Scenario] = []
    for index in range(4):
        run_id = f"planted-{index}"
        namespace = _load_module(FLAKY_AGENT, f"flaky_record_{index}")
        attempts = namespace["_ATTEMPTS"]
        assert isinstance(attempts, dict)
        attempts[run_id] = 1  # the healthy day
        build = namespace["build_graph"]
        assert callable(build)
        executor = GraphExecutor(build().compile(), agent_services())
        state = AEFState(run_id=run_id, agent_id="flaky", objective="fetch the thing")
        result = executor.run(state, record_trace=True)
        assert not result.final_state.errors, "the healthy recording failed"
        assert result.trace, "no trace recorded"
        scenarios.append(
            Scenario(
                id=run_id,
                split=Split.TRAIN if index < 2 else Split.VALIDATION,
                graph_id="flaky_agent",
                graph_version="0.1.0",
                initial_state=state,
                trace=tuple(result.trace or ()),
                recorded_at=NOW,
                notes="recorded from a real run, before the dependency went flaky",
                expected=Expected.UNSPECIFIED,
            )
        )
    return tuple(scenarios)


@pytest.fixture
def flaky_repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "flaky-repo"
    (root / "agents" / "flaky").mkdir(parents=True)
    (root / "agents" / "__init__.py").write_text("")
    (root / "agents" / "flaky" / "__init__.py").write_text("")
    (root / "agents" / "flaky" / "graph.py").write_text(FLAKY_AGENT)

    corpus_root = root / "corpus"
    corpus_root.mkdir()
    for scenario in _record_scenarios():
        save_scenario(corpus_root, scenario)

    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "loop@test")
    _git(root, "config", "user.name", "loop")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "flaky incumbent")
    return GitRepo(root=root)


def _config(repo: GitRepo, tmp_path: Path, corpus: Corpus) -> LoopConfig:
    return LoopConfig(
        repo=repo,
        paths=LoopPaths(root=tmp_path / "state"),
        base_ref="main",
        graph_id="flaky_agent",
        corpus=corpus,
        entrypoint="agents.flaky.graph:build_graph",
        cohort_size=5,
        cohort_seed=7,
    )


def _bless(repo: GitRepo, state_root: Path) -> None:
    archive.record(
        state_root / "archive",
        "flaky_agent",
        files={"agents/flaky/graph.py": (repo.root / "agents/flaky/graph.py").read_bytes()},
        base_sha=repo.rev_parse("main"),
        head_sha=repo.rev_parse("main"),
        recorded_at=NOW,
        notes="owner-blessed baseline",
    )


def _proposal_from_memory() -> str:
    """What the PROPOSER produces — not a hand-written patch.

    The citation names the record; the record names the node; the
    transformation targets that node. That chain is the difference between a
    grounded proposal and a decorated one (ADR 0096 1c).
    """
    citation = Citation(source="mem-1", detail="node 'fetch' raised", kind=CitationKind.MEMORY)
    return add_bounded_retry(
        source=FLAKY_AGENT, failing_node="fetch", citation=str(citation)
    ).source


@contextmanager
def _agent_repo_build_commands() -> Iterator[None]:
    """Swap G1's build commands for this repo's.

    G1's defaults are aef-core's own green bar (`mypy --strict aef`,
    `pytest -q`); a four-file agent repo has a different one and `pytest -q`
    exits 5 there for want of tests. Asserting against aef-core's bar would
    be testing the wrong repo.
    """
    import aef.harness.loop as loop_module

    original = loop_module._cheap_gates

    def patched(cfg, verdict, now):  # type: ignore[no-untyped-def]
        return tuple(
            G1Builds(commands=(("python", "-c", "import agents.flaky.graph"),))
            if g.id == "G1"
            else g
            for g in original(cfg, verdict, now)
        )

    loop_module._cheap_gates = patched  # type: ignore[assignment]
    try:
        yield
    finally:
        loop_module._cheap_gates = original  # type: ignore[assignment]


def _run_gate(config: LoopConfig, tmp_path: Path, head: str):
    """The real `gate()`, with only G1's build commands swapped for this repo's."""
    with _agent_repo_build_commands():
        return gate(config, head, now=NOW, workdir=tmp_path / "work")


# --------------------------------------------------------------------------
# 1. The planted failure is real, and the transformation actually repairs it
# --------------------------------------------------------------------------


def test_the_planted_failure_fires_without_the_repair() -> None:
    """The control. A repair that fixes nothing looks identical to one that
    works if the failure never fired in the first place."""
    graph = _load_flaky_graph(FLAKY_AGENT, "flaky_control")
    with pytest.raises(Exception, match="flaky upstream"):
        GraphExecutor(graph.compile(), agent_services()).run(
            AEFState(run_id="control", agent_id="flaky", objective="fetch the thing")
        )


def test_the_repair_makes_the_run_succeed() -> None:
    """Not 'the diff applied' — the run that failed now completes."""
    graph = _load_flaky_graph(_proposal_from_memory(), "flaky_repaired")
    result = GraphExecutor(graph.compile(), agent_services()).run(
        AEFState(run_id="repaired", agent_id="flaky", objective="fetch the thing")
    )
    assert not result.final_state.errors, f"still failing: {result.final_state.errors}"
    assert result.final_state.working_memory.get("done") is True, "the graph did not reach the end"


def test_the_repair_does_the_work_rather_than_declaring_failure_tolerable() -> None:
    """The distinction ADR 0080 and ADR 0098 both turned on.

    A fallback records that control continued; a retry means the work
    happened. `fetched` is only set by the node that was failing, so its
    presence is evidence of the second kind.
    """
    graph = _load_flaky_graph(_proposal_from_memory(), "flaky_did_work")
    result = GraphExecutor(graph.compile(), agent_services()).run(
        AEFState(run_id="did-work", agent_id="flaky", objective="fetch the thing")
    )
    assert result.final_state.working_memory.get("fetched") is True


# --------------------------------------------------------------------------
# 2. THE GATE. The assertion Milestone 1's first attempt could not make.
# --------------------------------------------------------------------------


def test_the_full_six_gate_pipeline_accepts_the_structural_repair(
    flaky_repo: GitRepo, tmp_path: Path
) -> None:
    """The whole milestone, in one run: every gate executes and none rejects."""
    _bless(flaky_repo, tmp_path / "state")
    _git(flaky_repo.root, "checkout", "-qb", "loop/structural")
    (flaky_repo.root / "agents/flaky/graph.py").write_text(_proposal_from_memory())
    assert RETRY_CONSTANT in (flaky_repo.root / "agents/flaky/graph.py").read_text(), (
        "the candidate branch does not carry the transformation"
    )
    _git(flaky_repo.root, "add", "-A")
    _git(flaky_repo.root, "commit", "-qm", "structural repair")

    config = _config(flaky_repo, tmp_path, load_corpus(flaky_repo.root / "corpus"))
    run = _run_gate(config, tmp_path, "loop/structural")

    failures = [(r.gate, r.reason) for r in run.result.results if r.outcome.value != "pass"]
    assert not failures, f"gates rejected the structural repair: {failures}"
    assert set(run.result.ran) == {"G0", "G1", "G2", "G3", "G4", "G5"}, (
        f"not every gate ran: {run.result.ran}"
    )
    assert run.decision.disposition is not Disposition.REJECT


def test_g4_specifically_accepts_it(flaky_repo: GitRepo, tmp_path: Path) -> None:
    """Named separately because G4 is the gate that killed the last attempt.

    A regression here is the exact defect ADR 0098 records, and a
    whole-pipeline assertion would report it as 'something failed'.
    """
    _bless(flaky_repo, tmp_path / "state")
    _git(flaky_repo.root, "checkout", "-qb", "loop/g4")
    (flaky_repo.root / "agents/flaky/graph.py").write_text(_proposal_from_memory())
    _git(flaky_repo.root, "add", "-A")
    _git(flaky_repo.root, "commit", "-qm", "structural repair")

    config = _config(flaky_repo, tmp_path, load_corpus(flaky_repo.root / "corpus"))
    run = _run_gate(config, tmp_path, "loop/g4")
    g4 = next(r for r in run.result.results if r.gate == "G4")
    assert g4.outcome.value == "pass", g4.reason
    assert not g4.security_event


# --------------------------------------------------------------------------
# 3. The controls. A test that cannot fail is not evidence.
# --------------------------------------------------------------------------


def test_the_pipeline_rejects_the_transformation_adr_0098_reverted(
    flaky_repo: GitRepo, tmp_path: Path
) -> None:
    """The planted fault, built from the REAL declaration, not a paraphrase.

    ADR 0096's transformation added `fallback_node_id`. If this file's
    pipeline assertion is worth anything it must REJECT that — the previous
    acceptance test could not, which is the whole reason Milestone 1 shipped
    unmergeable and had to be reverted.
    """
    _bless(flaky_repo, tmp_path / "state")
    _git(flaky_repo.root, "checkout", "-qb", "loop/reverted")
    planted = FLAKY_AGENT.replace(
        "                deterministic=False,",
        '                deterministic=False,\n                fallback_node_id="finish",',
    )
    assert 'fallback_node_id="finish"' in planted, "planted fault did not apply"
    (flaky_repo.root / "agents/flaky/graph.py").write_text(planted)
    _git(flaky_repo.root, "add", "-A")
    _git(flaky_repo.root, "commit", "-qm", "the reverted transformation")

    config = _config(flaky_repo, tmp_path, load_corpus(flaky_repo.root / "corpus"))
    run = _run_gate(config, tmp_path, "loop/reverted")
    g4 = next(r for r in run.result.results if r.gate == "G4")
    assert g4.outcome.value != "pass", "G4 waved through an owner-only declaration"
    assert "fallback_node_id" in str(g4.evidence or g4.reason)
    assert run.decision.disposition is Disposition.REJECT


def test_no_catalogue_output_can_carry_an_owner_only_field() -> None:
    """Derived from G4's frozenset, not from a list maintained here.

    ADR 0098's root cause was a catalogue proposed first and checked against
    the gates never. Adding a field to `OWNER_ONLY_FIELDS` must automatically
    constrain the proposer, and this asserts the guard fires for EVERY field
    in it — each planted from the real name.
    """
    from aef.harness.gates.g4_separation import OWNER_ONLY_FIELDS
    from aef.harness.transformations import TransformationError, _assert_controls_untouched

    base = (
        'x = [Node(id="a", version="1", fn=f, deterministic=False), '
        'Edge(from_node="a", to_node="b")]'
    )
    for field in sorted(OWNER_ONLY_FIELDS):
        if field == "deterministic":
            after = base.replace("deterministic=False", "deterministic=True")
        elif field in ("requires_human_approval", "requires_deterministic_fallback"):
            after = base.replace('to_node="b")', f'to_node="b", {field}=False)')
        else:
            after = base.replace("deterministic=False", f"deterministic=False, {field}=None")
        assert after != base, f"planted fault for {field!r} did not apply"
        with pytest.raises(TransformationError, match="owner-only"):
            _assert_controls_untouched(base, after)

    benign = base.replace("x = [", "y = 1\nx = [")
    assert benign != base
    _assert_controls_untouched(base, benign)  # must NOT fire


def test_the_proposer_reaches_the_catalogue_from_failure_memory() -> None:
    """1c: the citation names the record, the record names the node, and the
    transformation targets that node. Checkable rather than asserted."""

    class _Record:
        id = "mem-42"
        content = {"failing_nodes": ["fetch"], "verbal_feedback": "fetch raised"}

    from aef.harness.proposer import MemoryEvidence

    evidence = MemoryEvidence(records=(_Record(),))  # type: ignore[arg-type]
    proposals = RuleBasedProposer().propose_structural(
        evidence, proposal_id="p", path="agents/flaky/graph.py", source=FLAKY_AGENT
    )
    assert len(proposals) == 1
    assert proposals[0].grounded_in[0].source == "mem-42"
    assert "'fetch'" in proposals[0].rationale
    assert RETRY_CONSTANT in proposals[0].proposed


def test_a_mutating_node_is_never_retried() -> None:
    """Found by the adversarial round for this milestone, REPRODUCED: a body
    with an external effect executes it once per attempt, so a retry turned
    one call into three before the failure surfaced. No gate can see that —
    G2 and G3 measure outcomes and nothing counts side effects.

    Both spellings, because agents write either.
    """
    from aef.harness.transformations import TransformationError

    for effects in ("SideEffect.MUTATING", '"mutating"'):
        source = FLAKY_AGENT.replace(
            "side_effects=SideEffect.EXTERNAL_CALL,", f"side_effects={effects},"
        )
        assert f"side_effects={effects}" in source, "planted declaration did not apply"
        with pytest.raises(TransformationError, match="mutating"):
            add_bounded_retry(source=source, failing_node="fetch", citation="c")


def test_a_non_pure_node_without_an_idempotency_key_is_never_retried() -> None:
    """The premise that makes retrying an external call safe is that every
    attempt carries the SAME idempotency key, so a deduplicating consumer
    collapses them (ADR 0010). Without the declaration that premise is
    absent, so the transformation refuses rather than assuming it."""
    from aef.harness.transformations import TransformationError

    source = FLAKY_AGENT.replace(
        '                idempotency_key_fn=lambda s: f"{s.run_id}:fetch",\n', ""
    )
    assert "idempotency_key_fn" not in source, "planted removal did not apply"
    with pytest.raises(TransformationError, match="idempotency_key_fn"):
        add_bounded_retry(source=source, failing_node="fetch", citation="c")


def test_the_retry_does_not_swallow_an_approval_requirement() -> None:
    """`except Exception` is a wide net. HumanApprovalRequiredError must still
    reach the executor — a retry that ate it would convert a HITL gate into a
    silent pass, which is HARD-STOP #7's whole concern."""
    from aef.harness.transformations import APPROVAL_ERROR, TransformationError

    source = FLAKY_AGENT.replace(
        '        raise RuntimeError("flaky upstream refused the first attempt")',
        f"        raise {APPROVAL_ERROR}('needs a human')",
    )
    assert APPROVAL_ERROR in source, "planted raise did not apply"
    with pytest.raises(TransformationError, match=APPROVAL_ERROR):
        add_bounded_retry(source=source, failing_node="fetch", citation="c")


def test_the_retry_never_introduces_the_approval_class_into_agent_code() -> None:
    """The first fix for the finding above emitted `except
    HumanApprovalRequiredError: raise` — and G4 rejects introducing that class
    into agent-authored code as a security event. ADR 0098's mistake in
    miniature; this pins that the emitted source stays clean of it."""
    from aef.harness.gates.g4_separation import scan_weakened_controls

    proposed = add_bounded_retry(source=FLAKY_AGENT, failing_node="fetch", citation="c").source
    assert not scan_weakened_controls("agents/flaky/graph.py", FLAKY_AGENT, proposed)


def test_the_real_cycle_emits_the_structural_candidate(flaky_repo: GitRepo, tmp_path: Path) -> None:
    """The layer ADR 0098 says not to stop short of.

    Everything above tests a piece. This drives `cycle()` — the function the
    loop actually calls — from a memory store the REFLECT NODE wrote, and
    asserts the candidate branch it materialises carries the transformation.
    A proposer that works only when a test calls it directly is the shape of
    defect this program keeps finding.
    """
    import datetime as dt

    from aef.harness.loop import cycle
    from aef.kernel import Context
    from aef.reasoning.nodes import make_reflect_node
    from aef.services.memory.in_memory import InMemoryMemoryStore

    memory = InMemoryMemoryStore()
    reflect = make_reflect_node()
    reflect.fn(
        AEFState(
            run_id="r1",
            agent_id="flaky",
            objective="fetch the thing",
            errors=[{"node_id": "fetch", "message": "flaky upstream refused"}],
        ),
        Context(
            run_id="r1",
            graph_version="0.1.0",
            trace_id="t",
            node_id="reflect",
            now=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
            idempotency_key=None,
        ),
        agent_services(memory=memory),
    )

    _bless(flaky_repo, tmp_path / "state")
    config = _config(flaky_repo, tmp_path, load_corpus(flaky_repo.root / "corpus"))
    with _agent_repo_build_commands():
        run = cycle(
            config,
            now=NOW,
            workdir=tmp_path / "work",
            memory=memory,
            agent_path="agents/flaky/graph.py",
        )

    assert run.proposed is not None, run.lines
    proposed = flaky_repo.show(f"loop/{run.proposed}", "agents/flaky/graph.py")
    assert RETRY_CONSTANT in proposed, "the cycle did not emit the structural candidate"
    assert run.decision is not None and run.decision.disposition is not Disposition.REJECT, (
        run.decision.reason if run.decision else run.lines
    )
