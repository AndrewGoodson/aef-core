"""Trace codec + golden corpus.

M2's acceptance properties, each tested against a real `GraphExecutor` run
rather than a hand-built trace:

  1. write -> read -> re-execute produces identical results (round-trip)
  2. two re-executions are byte-identical (determinism)
  3. the never-shrinks check fails on a removal (the known-bad case)
  4. splits are fixed at record time and cannot leak into one another
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aef.harness.corpus import (
    Corpus,
    CorpusError,
    CorpusManifest,
    CorpusShrankError,
    Scenario,
    Split,
    check_never_shrinks,
    fixed_clock,
    load_corpus,
    load_manifest,
    load_scenario,
    save_manifest,
    save_scenario,
)
from aef.harness.trace_codec import (
    TraceCodecError,
    decode_record,
    decode_route,
    dumps,
    encode_record,
    encode_route,
    loads,
)
from aef.kernel import END, Context, Edge, Graph, GraphExecutor, Node, Route, Services
from aef.state import AEFState, Plan, Provenance, StateDelta


def _state(**overrides: object) -> AEFState:
    defaults: dict[str, object] = {"run_id": "r1", "agent_id": "a1", "objective": "obj"}
    defaults.update(overrides)
    return AEFState(**defaults)  # type: ignore[arg-type]


def _ctx(node_id: str = "n1", now: datetime | None = None) -> Context:
    return Context(
        run_id="r1",
        graph_version="0.1.0",
        trace_id="t1",
        node_id=node_id,
        now=now or datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        idempotency_key="k1",
    )


# --------------------------------------------------------------------------
# Route encoding — END must never collide with a node id
# --------------------------------------------------------------------------


def test_end_round_trips_as_the_singleton() -> None:
    assert decode_route(encode_route(END)) is END


def test_a_node_route_round_trips() -> None:
    assert decode_route(encode_route("search")) == "search"


def test_a_fanout_route_round_trips() -> None:
    assert decode_route(encode_route(("a", "b"))) == ("a", "b")


def test_a_node_named_end_does_not_decode_to_the_end_sentinel() -> None:
    # END is a dedicated type precisely so it cannot collide with a node id
    # (contracts.py). Encoding it as the bare string "END" would reintroduce
    # that collision, and the failure would be a silently wrong route.
    encoded = encode_route("END")
    assert decode_route(encoded) == "END"
    assert decode_route(encoded) is not END


@pytest.mark.parametrize(
    "payload",
    [{}, {"kind": "nope"}, {"kind": "node"}, {"kind": "node", "id": 3}, {"kind": "fanout"}],
)
def test_a_malformed_route_fails_loudly(payload: dict[str, object]) -> None:
    with pytest.raises(TraceCodecError):
        decode_route(payload)


def test_an_unencodable_route_fails_loudly() -> None:
    with pytest.raises(TraceCodecError):
        encode_route(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Record / context round-trip
# --------------------------------------------------------------------------


def test_a_record_round_trips_including_timezone() -> None:
    from aef.kernel import NodeExecutionRecord

    record = NodeExecutionRecord(
        node_id="n1",
        input_state=_state(scores={"q": 0.5}, plan=Plan(goal="g", status="active")),
        context=_ctx(),
        delta=StateDelta(reflections=["hi"], scores={"q": 0.75}),
        route=END,
    )
    restored = decode_record(encode_record(record))

    assert restored.node_id == record.node_id
    assert restored.input_state == record.input_state
    assert restored.context == record.context
    assert restored.context.now.tzinfo is not None
    assert restored.delta.model_dump() == record.delta.model_dump()
    assert restored.route is END


def test_the_fallback_flag_survives_the_round_trip() -> None:
    # Replay trusts fallback records instead of re-executing them (ADR 0039).
    # Losing the flag would make a corpus entry unreplayable.
    from aef.kernel import NodeExecutionRecord

    record = NodeExecutionRecord(
        node_id="n1",
        input_state=_state(),
        context=_ctx(),
        delta=StateDelta(errors=[{"error": "boom"}]),
        route="handler",
        is_fallback=True,
    )
    assert decode_record(encode_record(record)).is_fallback is True


def test_a_record_missing_a_field_fails_loudly() -> None:
    with pytest.raises(TraceCodecError, match="missing required field"):
        decode_record({"node_id": "n1"})


def test_encoding_is_byte_stable_regardless_of_key_insertion_order() -> None:
    # Every gate downstream compares serialized traces; unstable output
    # would make all of them flake intermittently.
    left = dumps({"b": 1, "a": {"z": 1, "y": 2}})
    right = dumps({"a": {"y": 2, "z": 1}, "b": 1})
    assert left == right


def test_invalid_json_fails_loudly() -> None:
    with pytest.raises(TraceCodecError, match="not valid JSON"):
        loads("{not json")


# --------------------------------------------------------------------------
# A real run, recorded — the round-trip acceptance property
# --------------------------------------------------------------------------


def _counting_graph() -> Graph:
    def step_one(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        prov = Provenance(
            node_id=ctx.node_id, graph_version=ctx.graph_version, ts=ctx.now, trace_id=ctx.trace_id
        )
        return StateDelta(scores={"step": 1.0}, provenance=[prov]), "two"

    def step_two(state: AEFState, ctx: Context, services: Services) -> tuple[StateDelta, Route]:
        prov = Provenance(
            node_id=ctx.node_id, graph_version=ctx.graph_version, ts=ctx.now, trace_id=ctx.trace_id
        )
        return StateDelta(plan=Plan(goal="g", status="done"), provenance=[prov]), END

    return Graph(
        id="counter",
        version="0.1.0",
        nodes={
            "one": Node(id="one", version="0.1.0", fn=step_one, deterministic=True),
            "two": Node(id="two", version="0.1.0", fn=step_two, deterministic=True),
        },
        edges=[Edge(from_node="one", to_node="two")],
        entry_node="one",
    )


def _record_scenario(scenario_id: str = "s1", split: Split = Split.TRAIN) -> Scenario:
    graph = _counting_graph()
    initial = _state()
    ticks = iter([datetime(2026, 3, 1, 12, 0, s, tzinfo=UTC) for s in range(10)])
    services = Services(clock=lambda: next(ticks))
    result = GraphExecutor(graph.compile(), services).run(initial, record_trace=True)
    assert result.trace is not None

    return Scenario(
        id=scenario_id,
        split=split,
        graph_id=graph.id,
        graph_version=graph.version,
        initial_state=initial,
        trace=result.trace,
        recorded_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    )


def test_a_recorded_scenario_survives_write_read_and_reexecution(tmp_path: Path) -> None:
    """M2 ACCEPTANCE: write -> read -> re-execute, identical results."""
    original = _record_scenario()
    save_scenario(tmp_path, original)
    restored = load_scenario(tmp_path / "train" / "s1.json")

    assert restored.initial_state == original.initial_state
    assert len(restored.trace) == len(original.trace)

    # Re-execute the RESTORED scenario against the same graph, with the
    # clock pinned to what the recording observed.
    services = Services(clock=fixed_clock(restored))
    result = GraphExecutor(_counting_graph().compile(), services).run(
        restored.initial_state, record_trace=True
    )
    assert result.trace is not None
    assert [r.node_id for r in result.trace] == [r.node_id for r in original.trace]
    assert (
        result.final_state
        == GraphExecutor(_counting_graph().compile(), Services(clock=fixed_clock(original)))
        .run(original.initial_state)
        .final_state
    )


def test_two_reexecutions_of_one_scenario_are_byte_identical(tmp_path: Path) -> None:
    """M2 ACCEPTANCE: determinism. Without this every gate flakes."""
    scenario = _record_scenario()
    save_scenario(tmp_path, scenario)
    restored = load_scenario(tmp_path / "train" / "s1.json")

    runs = []
    for _ in range(2):
        services = Services(clock=fixed_clock(restored))
        result = GraphExecutor(_counting_graph().compile(), services).run(
            restored.initial_state, record_trace=True
        )
        assert result.trace is not None
        from aef.harness.trace_codec import encode_trace

        runs.append(dumps(encode_trace(result.trace)))

    assert runs[0] == runs[1]


def test_saving_a_scenario_twice_produces_identical_bytes(tmp_path: Path) -> None:
    scenario = _record_scenario()
    first = save_scenario(tmp_path, scenario).read_bytes()
    second = save_scenario(tmp_path, scenario).read_bytes()
    assert first == second


def test_the_pinned_clock_refuses_to_invent_a_value(tmp_path: Path) -> None:
    # A candidate taking MORE steps than the recording is a behavioural
    # difference to report, not a timestamp to make up.
    scenario = _record_scenario()
    clock = fixed_clock(scenario)
    for _ in scenario.clock_values:
        clock()
    with pytest.raises(CorpusError, match="more steps than the recording"):
        clock()


# --------------------------------------------------------------------------
# Splits — fixed at record time, no leakage
# --------------------------------------------------------------------------


def test_the_three_splits_load_separately(tmp_path: Path) -> None:
    for i, split in enumerate(Split):
        save_scenario(tmp_path, _record_scenario(f"s{i}", split))
    corpus = load_corpus(tmp_path)

    assert len(corpus.scenarios) == 3
    assert len(corpus.split(Split.TRAIN)) == 1
    assert len(corpus.split(Split.HOLDOUT)) == 1


def test_train_and_holdout_never_share_a_scenario(tmp_path: Path) -> None:
    # The property G3's "beats the control cohort on held-out data" depends
    # on. Overlap would make it a measurement of memorisation.
    for i, split in enumerate([Split.TRAIN, Split.TRAIN, Split.HOLDOUT]):
        save_scenario(tmp_path, _record_scenario(f"s{i}", split))
    corpus = load_corpus(tmp_path)

    train = {s.id for s in corpus.split(Split.TRAIN)}
    holdout = {s.id for s in corpus.split(Split.HOLDOUT)}
    assert train.isdisjoint(holdout)


def test_moving_a_scenario_between_split_directories_fails_loudly(tmp_path: Path) -> None:
    # THE anti-leak test: relocating a holdout file into train/ would
    # otherwise silently make it citable by the proposer.
    scenario = _record_scenario("s1", Split.HOLDOUT)
    original = save_scenario(tmp_path, scenario)
    moved = tmp_path / "train" / "s1.json"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_bytes(original.read_bytes())
    original.unlink()

    with pytest.raises(CorpusError, match="leaks the holdout"):
        load_corpus(tmp_path)


def test_a_renamed_scenario_file_fails_loudly(tmp_path: Path) -> None:
    path = save_scenario(tmp_path, _record_scenario("s1"))
    path.rename(path.with_name("something-else.json"))
    with pytest.raises(CorpusError, match="does not match scenario id"):
        load_corpus(tmp_path)


def test_a_duplicate_id_across_splits_fails_loudly(tmp_path: Path) -> None:
    save_scenario(tmp_path, _record_scenario("dup", Split.TRAIN))
    payload = _record_scenario("dup", Split.VALIDATION)
    save_scenario(tmp_path, payload)
    with pytest.raises(CorpusError, match="duplicate scenario id"):
        load_corpus(tmp_path)


def test_a_corrupt_scenario_file_fails_loudly(tmp_path: Path) -> None:
    path = save_scenario(tmp_path, _record_scenario())
    path.write_text("{ truncated")
    with pytest.raises(CorpusError):
        load_corpus(tmp_path)


# --------------------------------------------------------------------------
# Never-shrinks — the known-bad case
# --------------------------------------------------------------------------


def test_a_growing_corpus_passes(tmp_path: Path) -> None:
    save_scenario(tmp_path, _record_scenario("s1"))
    baseline = load_corpus(tmp_path).manifest()

    save_scenario(tmp_path, _record_scenario("s2"))
    check_never_shrinks(load_corpus(tmp_path), baseline)


def test_deleting_a_scenario_is_caught(tmp_path: Path) -> None:
    """M2 ACCEPTANCE (known-bad): the never-shrinks check must reject."""
    save_scenario(tmp_path, _record_scenario("s1"))
    path = save_scenario(tmp_path, _record_scenario("s2"))
    baseline = load_corpus(tmp_path).manifest()

    path.unlink()

    with pytest.raises(CorpusShrankError, match="corpus shrank"):
        check_never_shrinks(load_corpus(tmp_path), baseline)


def test_moving_a_scenario_to_another_split_is_caught_as_shrinkage(tmp_path: Path) -> None:
    # Deletion from one split dressed as an addition to another.
    save_scenario(tmp_path, _record_scenario("s1", Split.VALIDATION))
    baseline = load_corpus(tmp_path).manifest()

    (tmp_path / "validation" / "s1.json").unlink()
    save_scenario(tmp_path, _record_scenario("s1", Split.TRAIN))

    with pytest.raises(CorpusShrankError, match="changed split"):
        check_never_shrinks(load_corpus(tmp_path), baseline)


def test_an_unchanged_corpus_passes(tmp_path: Path) -> None:
    save_scenario(tmp_path, _record_scenario("s1"))
    corpus = load_corpus(tmp_path)
    check_never_shrinks(corpus, corpus.manifest())


def test_the_manifest_round_trips(tmp_path: Path) -> None:
    save_scenario(tmp_path, _record_scenario("s1", Split.TRAIN))
    save_scenario(tmp_path, _record_scenario("s2", Split.HOLDOUT))
    original = load_corpus(tmp_path).manifest()

    save_manifest(tmp_path, original)
    assert load_manifest(tmp_path).ids == original.ids


def test_a_missing_manifest_reads_as_empty(tmp_path: Path) -> None:
    assert load_manifest(tmp_path).ids == {}


def test_an_empty_corpus_directory_loads_as_empty(tmp_path: Path) -> None:
    assert load_corpus(tmp_path) == Corpus(root=tmp_path, scenarios=())


def test_a_baseline_naming_an_absent_scenario_is_caught(tmp_path: Path) -> None:
    # The manifest is the ledger; an empty working corpus must not pass.
    baseline = CorpusManifest(ids={"s1": Split.TRAIN})
    with pytest.raises(CorpusShrankError):
        check_never_shrinks(load_corpus(tmp_path), baseline)


# --------------------------------------------------------------------------
# ADR 0141 — the never-shrinks ledger is written by the act that admits
# --------------------------------------------------------------------------


def test_saving_a_scenario_records_it_in_the_manifest(tmp_path: Path) -> None:
    """`CorpusManifest` and `check_never_shrinks` existed from the start and
    NOTHING ever wrote a manifest, so the ledger was empty everywhere and the
    check — wherever it ran — passed vacuously (ADR 0141)."""
    save_scenario(tmp_path, _record_scenario("s1", Split.TRAIN))
    save_scenario(tmp_path, _record_scenario("s2", Split.VALIDATION))

    assert load_manifest(tmp_path).ids == {"s1": Split.TRAIN, "s2": Split.VALIDATION}


def test_the_manifest_is_a_union_not_a_regeneration(tmp_path: Path) -> None:
    """A manifest rebuilt from the corpus on disk would forget precisely the
    scenario that had just been deleted — the deletion this ledger exists to
    notice. So the delete-then-add sequence must still fail the check."""
    save_scenario(tmp_path, _record_scenario("s1"))
    path = save_scenario(tmp_path, _record_scenario("s2"))

    path.unlink()
    save_scenario(tmp_path, _record_scenario("s3"))

    assert set(load_manifest(tmp_path).ids) == {"s1", "s2", "s3"}
    with pytest.raises(CorpusShrankError, match="corpus shrank"):
        check_never_shrinks(load_corpus(tmp_path), load_manifest(tmp_path))


def test_a_malformed_scenario_names_the_file_it_came_from(tmp_path: Path) -> None:
    """`from_payload` named the missing key and nothing else, so an adopter
    with forty scenarios read `malformed scenario payload: 'graph_id'` and had
    no way to tell which file (ADR 0141)."""
    (tmp_path / "train").mkdir()
    (tmp_path / "train" / "broken.json").write_text('{"id": "broken", "split": "train"}')

    with pytest.raises(CorpusError, match="broken.json"):
        load_corpus(tmp_path)


def test_the_source_field_round_trips_and_defaults_for_legacy_files(tmp_path: Path) -> None:
    """Provenance for harvest's rate limit (ADR 0141). Absent in every file
    written before it existed, which is exactly what UNSPECIFIED means."""
    import json
    from dataclasses import replace

    from aef.harness.corpus import Source

    path = save_scenario(tmp_path, replace(_record_scenario("s1"), source=Source.BOOTSTRAP))
    assert load_scenario(path).source is Source.BOOTSTRAP

    payload = json.loads(path.read_text())
    del payload["source"]
    path.write_text(json.dumps(payload))
    assert load_scenario(path).source is Source.UNSPECIFIED


def test_a_split_move_against_a_stale_kept_branch_names_the_branch_not_reconcile() -> None:
    """ADR 0204's F-Q1-6, found installing on a real repository. The baseline
    is read from the base ref, and during a multi-turn run that ref is the
    loop's OWN kept branch — created by an earlier turn and never advanced. It
    still carries the pre-move manifest, so the refusal fired, named
    `reconcile`, and `reconcile` answered "nothing to reconcile" because it
    rewrites the manifest on disk and cannot reach one committed on a branch.
    The check is correct and unchanged; the remedy it names now depends on
    where the baseline came from."""
    from aef.harness.corpus import CorpusManifest, Split, check_never_shrinks

    class _Corpus:
        root = Path("/tmp/corpus")
        ids = {"a", "b"}

        def manifest(self):
            return CorpusManifest(ids={"a": Split.TRAIN, "b": Split.VALIDATION})

    baseline = CorpusManifest(ids={"a": Split.TRAIN, "b": Split.TRAIN})

    with pytest.raises(CorpusShrankError) as stale:
        check_never_shrinks(_Corpus(), baseline, baseline_ref="loop/kept")  # type: ignore[arg-type]
    assert "git branch -D loop/kept" in str(stale.value)
    assert "will answer 'nothing to reconcile'" in str(stale.value)

    # From the working tree, reconcile IS the remedy and is still named.
    with pytest.raises(CorpusShrankError) as tree:
        check_never_shrinks(_Corpus(), baseline)  # type: ignore[arg-type]
    assert "corpus reconcile" in str(tree.value)
    assert "git branch -D" not in str(tree.value)
