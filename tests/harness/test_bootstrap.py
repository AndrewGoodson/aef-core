"""`aef loop bootstrap` — a corpus on day one (ADR 0138).

Four rules, each inherited from a component that learned it the hard way, and
each with its own test because their opposites break the corpus in four
different ways: harvest's train-only rule, ADR 0060's owner-only `expected`,
recorder's no-overwrite rule, and the failure count without which a corpus
cannot demonstrate an improvement.
"""

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.bootstrap import (
    NO_PROVIDER_MARKER,
    BootstrapError,
    BootstrapInput,
    RunScopedMemory,
    bootstrap,
    load_inputs,
)
from aef.harness.checks import TaskCheck
from aef.harness.corpus import Expected, Split, load_corpus
from aef.harness.memory_store import FileMemoryStore
from aef.harness.proposer import MemoryEvidence
from aef.harness.recorder import RecorderError
from aef.kernel import END, Context, Edge, Graph, Node, Route, Services, SideEffect
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderMessage,
)
from aef.reasoning.nodes import make_reflect_node
from aef.services.memory.base import MemoryRecord, MemoryStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.services.runtime import agent_services
from aef.state import AEFState, Plan, StateDelta

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _graph() -> Graph:
    """Fails when `difficulty` exceeds the budget — the demo agent's shape,
    small enough that the failure is unambiguous."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        if int(state.working_memory.get("difficulty", 1)) > 3:
            return (
                StateDelta(
                    plan=Plan(goal=state.objective, status="failed"),
                    errors=[{"node_id": ctx.node_id, "error": "too hard"}],
                    scores={"quality": 0.0},
                ),
                END,
            )
        return (
            StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
            END,
        )

    return Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )


def _services(memory: MemoryStore) -> Services:
    """The store is HANDED IN by `bootstrap`, which builds a `RunScopedMemory`
    per input. A factory that picked its own would put the isolation rule at
    the call site and leave the durability rule (ADR 0145) inexpressible."""
    return agent_services(memory=memory)


def _inputs(*specs: tuple[str, int]) -> tuple[BootstrapInput, ...]:
    return tuple(
        BootstrapInput(id=sid, objective=f"task {sid}", working_memory={"difficulty": difficulty})
        for sid, difficulty in specs
    )


def _run(root: Path, *specs: tuple[str, int]):  # type: ignore[no-untyped-def]
    return bootstrap(
        root,
        _graph(),
        _services,
        inputs=_inputs(*specs),
        now=NOW,
        agent_id="fixture",
    )


# --- rule 1: always TRAIN, and no way to ask for anything else ---------------


def test_bootstrap_writes_only_the_train_split(tmp_path: Path) -> None:
    """Harvest's rule: if the system could fill the set that gates it, the
    gate would measure the system's own choices."""
    root = tmp_path / "corpus"
    _run(root, ("easy", 1), ("hard", 9))

    corpus = load_corpus(root)
    assert len(corpus.scenarios) == 2
    assert {s.split for s in corpus.scenarios} == {Split.TRAIN}
    assert not (root / Split.VALIDATION.value).exists()
    assert not (root / Split.HOLDOUT.value).exists()


def test_bootstrap_offers_no_flag_to_write_another_split() -> None:
    """As in `harvest`, there is not even a way to ask. A keyword argument
    for a rule is a default, and a default is something a caller changes."""
    assert "split" not in inspect.signature(bootstrap).parameters

    from aef.cli.main import build_parser

    for action in _bootstrap_parser(build_parser())._actions:
        assert action.dest not in {"split", "allow_holdout", "i_am_spending_the_holdout"}


def _bootstrap_parser(parser):  # type: ignore[no-untyped-def]
    loop = next(a for a in parser._actions if getattr(a, "choices", None) and "loop" in a.choices)
    return loop.choices["loop"]._actions[-1].choices["bootstrap"]  # type: ignore[union-attr]


# --- rule 2: never labels `expected` -----------------------------------------


def test_bootstrap_never_labels_expected(tmp_path: Path) -> None:
    """Only an owner can say a task SHOULD have failed (ADR 0060). The
    corpus includes a run that DID fail, so a label derived from the outcome
    would show up here."""
    root = tmp_path / "corpus"
    outcome = _run(root, ("easy", 1), ("hard", 9))
    assert outcome.failed == ("hard",)

    for scenario in load_corpus(root).scenarios:
        assert scenario.expected is Expected.UNSPECIFIED, (
            f"{scenario.id} carries a claim bootstrap invented"
        )


def test_bootstrap_prints_the_ids_the_owner_should_consider(tmp_path: Path) -> None:
    outcome = _run(tmp_path / "corpus", ("easy", 1), ("hard", 9))
    text = "\n".join(outcome.lines)
    assert "hard" in text
    assert "ADR 0060" in text
    assert "labels nothing" in text


def test_the_suggested_tripwire_command_carries_the_input_back(tmp_path: Path) -> None:
    """Generated, never executed — and `record_run` still refuses must_fail
    on a task the agent completes, so the suggestion is checked by the
    command that acts on it."""
    inputs = _inputs(("easy", 1), ("hard", 9))
    outcome = bootstrap(
        tmp_path / "corpus", _graph(), _services, inputs=inputs, now=NOW, agent_id="fixture"
    )
    commands = outcome.tripwire_commands("agents.mine.graph", "corpus", inputs)
    assert len(commands) == 1
    assert "--scenario-id hard-tripwire" in commands[0]
    assert "--expected must_fail" in commands[0]
    assert "--split validation" in commands[0]
    # Shell-quoted: the JSON blob survives one round of shell unquoting.
    assert '--working-memory "{\\"difficulty\\": 9}"' in commands[0]


def test_an_expected_key_in_the_inputs_file_is_refused_not_ignored(tmp_path: Path) -> None:
    """Silently dropping an owner's claim is worse than refusing it: they
    would believe the corpus carries a tripwire it does not."""
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps([{"objective": "t", "expected": "must_fail"}]))
    with pytest.raises(BootstrapError, match="ADR 0060"):
        load_inputs(path)


def test_a_split_key_in_the_inputs_file_is_refused_not_ignored(tmp_path: Path) -> None:
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps([{"objective": "t", "split": "validation"}]))
    with pytest.raises(BootstrapError, match="train split only"):
        load_inputs(path)


# --- rule 3: refuses to overwrite --------------------------------------------


def test_bootstrap_refuses_an_existing_id_and_writes_nothing_first(tmp_path: Path) -> None:
    """Refused for the WHOLE batch, before anything runs. A collision found
    halfway through would leave the earlier inputs written, so re-running the
    file could never be safe."""
    root = tmp_path / "corpus"
    _run(root, ("taken", 1))
    before = sorted(p.name for p in (root / "train").glob("*.json"))

    with pytest.raises(RecorderError, match="already exist"):
        _run(root, ("fresh", 1), ("taken", 9))

    assert sorted(p.name for p in (root / "train").glob("*.json")) == before
    assert "fresh" not in load_corpus(root).ids


def test_bootstrap_refuses_a_duplicate_id_within_one_batch(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="more than once"):
        _run(tmp_path / "corpus", ("same", 1), ("same", 9))


# --- rule 4: reports the failure count ---------------------------------------


def test_bootstrap_reports_how_many_runs_failed(tmp_path: Path) -> None:
    outcome = _run(tmp_path / "corpus", ("a", 1), ("b", 9), ("c", 9))
    assert outcome.failed == ("b", "c")
    assert "2 of 3 recorded run(s) FAILED." in outcome.lines


def test_bootstrap_says_so_when_nothing_failed(tmp_path: Path) -> None:
    """A corpus where everything passes cannot demonstrate an improvement.
    That is a finding about the inputs, printed as one."""
    outcome = _run(tmp_path / "corpus", ("a", 1), ("b", 2))
    assert outcome.failed == ()
    text = "\n".join(outcome.lines)
    assert "0 of 2 recorded run(s) failed" in text
    assert "cannot demonstrate an improvement" in text


# --- the seam: one set of services per input ---------------------------------


def test_each_input_gets_its_own_services(tmp_path: Path) -> None:
    """The gates re-execute each scenario in isolation with a fresh
    `InMemoryMemoryStore` (`harvest._reexecution_services`). A bootstrap that
    shared one store would record later runs that depended on what earlier
    ones remembered — scenarios that cannot reproduce alone."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        memory = services.require_memory()
        seen = len(memory.query("episodic", limit=100))
        memory.write(MemoryRecord(kind="episodic", content={"objective": state.objective}))
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="done"), working_memory={"seen": seen}
            ),
            END,
        )

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )
    root = tmp_path / "corpus"
    bootstrap(
        root,
        graph,
        _services,
        inputs=_inputs(("first", 1), ("second", 1)),
        now=NOW,
        agent_id="fixture",
    )

    seen = {s.id: s.trace[0].delta.working_memory["seen"] for s in load_corpus(root).scenarios}
    assert seen == {"first": 0, "second": 0}, (
        "the second run saw the first run's memory — the scenarios do not reproduce alone"
    )


def test_isolation_survives_the_durable_sink(tmp_path: Path) -> None:
    """The seam ADR 0145 could have broken. Making the reflections durable by
    sharing ONE store across inputs would have satisfied the cycle and
    destroyed the property above: the second input would read the first
    input's records back and record a scenario that cannot reproduce alone.
    Same graph, same assertion, with a sink attached."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        memory = services.require_memory()
        seen = len(memory.query("episodic", limit=100))
        memory.write(MemoryRecord(kind="episodic", content={"objective": state.objective}))
        return (
            StateDelta(
                plan=Plan(goal=state.objective, status="done"), working_memory={"seen": seen}
            ),
            END,
        )

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=True)},
        edges=[],
        entry_node="work",
    )
    root = tmp_path / "corpus"
    sink = FileMemoryStore(path=tmp_path / "memory.jsonl")
    outcome = bootstrap(
        root,
        graph,
        _services,
        inputs=_inputs(("first", 1), ("second", 1)),
        now=NOW,
        agent_id="fixture",
        memory_sink=sink,
    )

    seen = {s.id: s.trace[0].delta.working_memory["seen"] for s in load_corpus(root).scenarios}
    assert seen == {"first": 0, "second": 0}, (
        "the sink leaked into the next input's reads — the scenarios do not reproduce alone"
    )
    # ...and the writes still landed, which is the other half of the trade.
    assert outcome.memory_records == 2
    assert len(sink.query("episodic", limit=100)) == 2


# --- the durable sink: reflections that outlive the process (ADR 0145) -------


def _reflecting_graph() -> Graph:
    """The MINIMUM_AGENT shape: a work node that ROUTES to reflect. An Edge
    alone does not wire it (ADR 0070), which is why the route is a literal."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        if int(state.working_memory.get("difficulty", 1)) > 3:
            return (
                StateDelta(
                    plan=Plan(goal=state.objective, status="failed"),
                    errors=[{"node_id": ctx.node_id, "error": "too hard"}],
                    scores={"quality": 0.0},
                ),
                "reflect",
            )
        return (
            StateDelta(plan=Plan(goal=state.objective, status="done"), scores={"quality": 1.0}),
            "reflect",
        )

    return Graph(
        id="fixture",
        version="0.1.0",
        nodes={
            "work": Node(id="work", version="0.1.0", fn=work, deterministic=True),
            "reflect": make_reflect_node(route=END),
        },
        edges=[Edge(from_node="work", to_node="reflect")],
        entry_node="work",
    )


def test_a_failing_input_leaves_failure_memory_the_proposer_can_read(tmp_path: Path) -> None:
    """The measured gap ADR 0139 named as requirement 4: bootstrap gave every
    input its own `InMemoryMemoryStore`, so the failing run's reflection died
    with the process and `aef loop cycle --memory M` said `no admissible
    failure memory: no candidate this cycle`."""
    sink = FileMemoryStore(path=tmp_path / "memory.jsonl")
    outcome = bootstrap(
        tmp_path / "corpus",
        _reflecting_graph(),
        _services,
        inputs=_inputs(("easy", 1), ("hard", 9)),
        now=NOW,
        agent_id="fixture",
        memory_sink=sink,
    )
    assert outcome.failed == ("hard",)

    # Read back the way the proposer reads it — from a NEW store over the same
    # file, because "survives the process" is the whole claim.
    reopened = FileMemoryStore(path=tmp_path / "memory.jsonl")
    evidence = MemoryEvidence.from_store(reopened)
    assert [r.run_id for r in evidence.records] == ["hard"]
    assert evidence.failing_nodes() and evidence.failing_nodes()[0][0] == "work"

    assert "memory record(s) written to the durable store" in "\n".join(outcome.lines)


def test_bootstrap_writes_no_memory_of_its_own(tmp_path: Path) -> None:
    """ADR 0060, from the memory side. A graph that reflects on nothing leaves
    an EMPTY sink: bootstrap records what the run did and never authors a
    failure to fill the gap — which would be the system writing the evidence
    it then proposes from."""
    sink = FileMemoryStore(path=tmp_path / "memory.jsonl")
    outcome = bootstrap(
        tmp_path / "corpus",
        _graph(),  # no reflect node, and one input DOES fail
        _services,
        inputs=_inputs(("easy", 1), ("hard", 9)),
        now=NOW,
        agent_id="fixture",
        memory_sink=sink,
    )
    assert outcome.failed == ("hard",)
    assert outcome.memory_records == 0
    assert not (tmp_path / "memory.jsonl").exists()
    assert MemoryEvidence.from_store(sink).records == ()

    text = "\n".join(outcome.lines)
    assert "no memory records" in text
    assert "never invents a failure" in text


def test_no_sink_is_reported_as_a_different_fact_from_an_empty_one(tmp_path: Path) -> None:
    """ "asked for durable memory and got none" is a finding about the graph;
    "did not ask" is not. Printing the first for the second is the
    green-light-for-nothing shape this repo keeps finding."""
    outcome = _run(tmp_path / "corpus", ("easy", 1), ("hard", 9))
    assert outcome.memory_records is None
    assert "no memory records" not in "\n".join(outcome.lines)


def test_run_scoped_memory_reads_scratch_and_mirrors_writes() -> None:
    """The class, directly: both rules in one object, so neither can be
    dropped by a caller that assembles `Services` differently."""
    scratch, sink = InMemoryMemoryStore(), InMemoryMemoryStore()
    sink.write(MemoryRecord(kind="failure", content={"from": "an earlier input"}))

    store = RunScopedMemory(scratch=scratch, sink=sink)
    record = MemoryRecord(kind="failure", content={"from": "this run"})
    assert store.write(record) == record.id

    # Reads see this run only — the earlier record is invisible.
    assert [r.content["from"] for r in store.query("failure", limit=10)] == ["this run"]
    assert store.get(record.id) is not None
    # ...and the sink has both, with the record's own id preserved.
    assert len(sink.query("failure", limit=10)) == 2
    assert store.mirrored == [record.id]


def test_run_scoped_memory_without_a_sink_is_the_pre_0145_behaviour() -> None:
    scratch = InMemoryMemoryStore()
    store = RunScopedMemory(scratch=scratch)
    store.write(MemoryRecord(kind="failure", content={}))
    assert len(scratch.query("failure", limit=10)) == 1
    assert store.mirrored == []


# --- the recording pass is the live one (ADR 0145) ---------------------------


def test_the_model_calls_the_recording_spent_are_reported(tmp_path: Path) -> None:
    """Recording is the one pass that is SUPPOSED to be live — the cassette
    the gates replay from does not exist until something makes the call once
    (ADR 0123) — so the price is printed rather than discovered later.

    A FAKE provider: this repo's three impls are all live and the quota to
    exercise them is not available, so what is proved here is the WIRING and
    the count, not the live path."""
    calls: list[str] = []

    class _FakeProvider(ModelProvider):
        name = "fake"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            calls.append(request.messages[0].content)
            return CompletionResult(
                content="ok",
                model=request.model or "fake",
                input_tokens=1,
                output_tokens=1,
            )

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        services.require_model_provider().complete(
            CompletionRequest(
                messages=(ProviderMessage(role="user", content=state.objective),),
                model="fake-1",
                max_tokens=16,
            )
        )
        return StateDelta(plan=Plan(goal=state.objective, status="done")), END

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={
            "work": Node(
                id="work",
                version="0.1.0",
                fn=work,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: f"{s.run_id}:work",
            )
        },
        edges=[],
        entry_node="work",
    )

    root = tmp_path / "corpus"
    outcome = bootstrap(
        root,
        graph,
        lambda memory: agent_services(memory=memory, model_provider=_FakeProvider()),
        inputs=_inputs(("one", 1), ("two", 1)),
        now=NOW,
        agent_id="fixture",
    )
    assert len(calls) == 2
    assert outcome.model_calls == 2
    # Counted from the cassettes the recorder pinned, not from an estimate:
    # these are the calls the gates will replay without a credential.
    assert sum(len(s.model_calls) for s in load_corpus(root).scenarios) == 2
    assert "recording spent 2 live model call(s)" in "\n".join(outcome.lines)


def test_a_model_calling_graph_with_no_provider_is_told_which_flag_fixes_it(
    tmp_path: Path,
) -> None:
    """ADR 0139's other measured blocker: bootstrapping the migrated,
    model-calling graph exits 1 with `no live provider to fall through to`.
    `--config` was already in the parser and nothing pointed at it."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        services.require_model_provider().complete(
            CompletionRequest(
                messages=(ProviderMessage(role="user", content=state.objective),),
                model="fake-1",
                max_tokens=16,
            )
        )
        return StateDelta(plan=Plan(goal=state.objective, status="done")), END

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={
            "work": Node(
                id="work",
                version="0.1.0",
                fn=work,
                deterministic=False,
                side_effects=SideEffect.EXTERNAL_CALL,
                idempotency_key_fn=lambda s: f"{s.run_id}:work",
            )
        },
        edges=[],
        entry_node="work",
    )

    outcome = bootstrap(
        tmp_path / "corpus",
        graph,
        _services,  # no model provider at all
        inputs=_inputs(
            ("one", 1),
        ),
        now=NOW,
        agent_id="fixture",
    )
    assert outcome.recorded == ()
    text = "\n".join(outcome.lines)
    # The provider's own message, which names aef.yaml and cannot name a flag
    # of a command it has never heard of...
    assert NO_PROVIDER_MARKER in text
    # ...and the flag that gets that file to THIS command.
    assert "--config <aef.yaml>" in text
    assert "SUPPOSED to be live" in text


# --- owner claims that ARE accepted per input (ADR 0113) ---------------------


def test_owner_checks_and_budget_travel_with_the_scenario(tmp_path: Path) -> None:
    """`checks` and `budget_ms` are a specification of the task written
    BEFORE the run, not a judgement about what the run turned out to do —
    which is exactly why they are accepted and `expected` is not."""
    root = tmp_path / "corpus"
    bootstrap(
        root,
        _graph(),
        _services,
        inputs=(
            BootstrapInput(
                id="checked",
                objective="t",
                working_memory={"difficulty": 1},
                checks=(TaskCheck(path="scores.quality", op="equals", value=1.0),),
                budget_ms=250.0,
            ),
        ),
        now=NOW,
        agent_id="fixture",
    )
    scenario = load_corpus(root).scenarios[0]
    assert scenario.checks == (TaskCheck(path="scores.quality", op="equals", value=1.0),)
    assert scenario.budget_ms == 250.0


# --- a run that raises -------------------------------------------------------


def test_a_run_that_raises_is_reported_and_records_nothing(tmp_path: Path) -> None:
    """The adoptee case: the migrated node builds its own vendor client and
    there is no credential, so the node raises before producing a trace. A
    scenario with an empty trace pins nothing and would pass every gate
    vacuously, so nothing is written."""

    def work(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        raise RuntimeError("no credential")

    graph = Graph(
        id="fixture",
        version="0.1.0",
        nodes={"work": Node(id="work", version="0.1.0", fn=work, deterministic=False)},
        edges=[],
        entry_node="work",
    )
    root = tmp_path / "corpus"
    outcome = bootstrap(
        root, graph, _services, inputs=_inputs(("boom", 1)), now=NOW, agent_id="fixture"
    )

    assert outcome.recorded == ()
    assert outcome.errored[0][0] == "boom"
    assert "no credential" in outcome.errored[0][1]
    assert not load_corpus(root).scenarios if root.is_dir() else True

    text = "\n".join(outcome.lines)
    assert "NOTHING was recorded" in text
    # "everything passed" and "nothing ran" are different facts.
    assert "cannot demonstrate an improvement" not in text


# --- the inputs file ---------------------------------------------------------


def test_inputs_accept_a_bare_list_or_an_object(tmp_path: Path) -> None:
    listed = tmp_path / "a.json"
    listed.write_text(json.dumps([{"objective": "one"}]))
    wrapped = tmp_path / "b.json"
    wrapped.write_text(json.dumps({"inputs": [{"objective": "one"}]}))
    assert load_inputs(listed) == load_inputs(wrapped)


def test_ids_default_to_the_prefix_and_position(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"objective": "a"}, {"id": "named", "objective": "b"}]))
    assert [i.id for i in load_inputs(path, prefix="seed")] == ["seed-1", "named"]


def test_an_input_without_an_objective_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"working_memory": {"difficulty": 9}}]))
    with pytest.raises(BootstrapError, match="objective"):
        load_inputs(path)


def test_an_unknown_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"objective": "a", "working_memroy": {}}]))
    with pytest.raises(BootstrapError, match="unknown key"):
        load_inputs(path)


def test_a_malformed_check_fails_before_anything_runs(tmp_path: Path) -> None:
    """A check that loaded wrong would score its scenario 0 forever and read
    as a regression (ADR 0113)."""
    path = tmp_path / "i.json"
    path.write_text(json.dumps([{"objective": "a", "checks": [{"path": "x", "op": "nope"}]}]))
    with pytest.raises(BootstrapError, match="nope"):
        load_inputs(path)


def test_an_empty_inputs_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "i.json"
    path.write_text("[]")
    with pytest.raises(BootstrapError, match="no inputs"):
        load_inputs(path)
