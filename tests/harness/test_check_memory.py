"""A failed owner check becomes failure memory (ADR 0174).

The reproduce-first case is the first test, and it was found from two ends on
one night. ADR 0157: a migrated prompt-file agent bootstrapped against an owner
check it did not satisfy wrote `kind="success"` with
`verbal_feedback="no failure signals: 0 error(s) recorded…"`, and the cycle said
`no admissible failure memory`. ADR 0155: zero knowledge entries formed in any
of the four ACE arms, because every record on the summary split was a success
with a unique signature — while two of those six runs failed an owner check.

One producer, both ends. Everything after the first two tests pins a property
of it, and the loudest of them is `test_the_record_never_contains_the_checks_
expected_value`: a lesson that carries the check's own answer is teaching to the
test, and nothing downstream distinguishes the two (ADR 0157's caveat)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aef.harness.check_memory import (
    _OP_PROSE,
    CHECK_OBSERVER_NODE_ID,
    CHECK_RECORD_ID_PREFIX,
    OUTPUT_LOCATION,
    check_failure_record,
    check_key,
    check_record_id,
    record_check_outcomes,
)
from aef.harness.checks import OPS, TaskCheck, evaluate_checks
from aef.reasoning.nodes import render_retrieved_context
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.knowledge.consolidate import RuleBasedConsolidator, default_signature
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
from aef.services.memory.base import MemoryRecord, MemoryStore
from aef.services.memory.in_memory import InMemoryMemoryStore
from aef.state import AEFState

NOW = datetime(2026, 9, 4, tzinfo=UTC)
CRITIC = RuleBasedCritic()
JUDGE = RuleBasedJudge(rubric={"quality": 1.0})


def _state(answer: str = "the connector stays disabled", **kwargs: object) -> AEFState:
    return AEFState(
        run_id="r1",
        agent_id="a",
        objective="may the connector be enabled?",
        working_memory={"prompt_agent": answer},
        **kwargs,  # type: ignore[arg-type]
    )


def _record(state: AEFState, *checks: TaskCheck, run_id: str = "r1"):  # type: ignore[no-untyped-def]
    return check_failure_record(
        checks=checks,
        final_state=state,
        critic=CRITIC,
        judge=JUDGE,
        run_id=run_id,
        agent_id="a",
        created_at=NOW,
        graph_version="0.1.0",
    )


VERDICT = TaskCheck(path="working_memory.prompt_agent", op="contains", value="VERDICT:")


# --- the reproduction -------------------------------------------------------


def test_a_clean_run_that_fails_an_owner_check_now_produces_failure_memory() -> None:
    """ADR 0157's reproduction, inverted. The run raises nothing, so
    `failure_signals` is empty and the reflect node writes `success`; the check
    is the task metric and fails anyway. Before this producer that outcome
    reached memory as nothing at all."""
    state = _state()
    assert not state.errors  # the reflect node would write kind="success"
    record = _record(state, VERDICT)

    assert record is not None
    assert record.kind == "failure"
    assert record.run_id == "r1"
    assert record.content["failed_checks"] == ["check:working_memory.prompt_agent:contains"]


def test_zero_knowledge_entries_becomes_one_when_the_same_check_fails_twice() -> None:
    """ADR 0155's finding, inverted. Six successes with six distinct
    objectives can never meet ADR 0110's two-run threshold; two runs failing
    one owner check do."""
    memory = InMemoryMemoryStore()
    for run in ("r1", "r2"):
        written = record_check_outcomes(
            memory=memory,
            checks=(VERDICT,),
            final_state=_state(),
            critic=CRITIC,
            judge=JUDGE,
            run_id=run,
            agent_id="a",
            created_at=NOW,
        )
        assert written is not None

    entries = RuleBasedConsolidator().consolidate(memory, InMemoryKnowledgeStore(), agent_id="a")
    assert len(entries) == 1
    assert entries[0].signature == "failure:check:working_memory.prompt_agent:contains"
    assert len(entries[0].source_record_ids) == 2


# --- when it writes nothing, and why ----------------------------------------


def test_a_run_whose_checks_all_hold_writes_nothing() -> None:
    assert _record(_state("VERDICT: no"), VERDICT) is None


def test_a_run_with_no_checks_writes_nothing() -> None:
    """A scenario that declares nothing about its answer makes no claim, so
    there is no owner metric to have failed."""
    assert _record(_state()) is None


def test_a_run_that_errored_writes_nothing() -> None:
    """Its own reflect node already wrote a failure record, and
    `score_scenario` ignores the check fraction when the state carries errors —
    a second record built from checks the scorer disregarded would be evidence
    of something nobody measured."""
    state = _state(errors=[{"node_id": "prompt_agent", "error": "boom"}])
    assert _record(state, VERDICT) is None


# --- the teaching-to-the-test rule ------------------------------------------


def test_the_record_never_contains_the_checks_expected_value() -> None:
    """`RuleBasedPromptProposer` pastes an entry's feedback verbatim into the
    agent's persona (ADR 0157). A literal expected value in this record is
    therefore the check's own answer appended to the prompt, which is ACE and
    teaching to the test being the same operation."""
    secret = "ZQX-UNMISTAKABLE-MARKER-8817"
    record = _record(
        _state(), TaskCheck(path="working_memory.prompt_agent", op="contains", value=secret)
    )
    assert record is not None
    blob = json.dumps({"content": record.content, "tags": list(record.tags)})
    assert secret not in blob
    assert secret not in str(default_signature(record))


def test_a_numeric_threshold_is_not_leaked_either() -> None:
    """The rule is uniform. An owner's word cap is as much the answer to a
    word-cap check as a marker string is to a `contains` check; the lesson says
    the direction and the observed magnitude instead."""
    record = _record(
        _state("one two three four five"),
        TaskCheck(path="working_memory.prompt_agent", op="max_words", value=3),
    )
    assert record is not None
    feedback = str(record.content["verbal_feedback"])
    assert "longer than the owner's maximum" in feedback
    assert "5 words" in feedback  # what the run produced
    assert " 3" not in feedback.replace("0/0", "")  # never the cap itself


def test_the_signature_carries_no_expected_value_into_a_rendered_prompt() -> None:
    """The signature is what `render_retrieved_context` prints as the bullet's
    `[label]` and what the prompt proposer writes into its provenance marker,
    so it is a prompt surface too."""
    secret = "ZQX-UNMISTAKABLE-MARKER-8817"
    record = _record(
        _state(), TaskCheck(path="working_memory.prompt_agent", op="contains", value=secret)
    )
    assert record is not None
    state = _state()
    state.retrieved_context.append(
        {
            "content": json.dumps({"verbal_feedback": record.content["verbal_feedback"]}),
            "source": "knowledge:x",
            "metadata": {"signature": default_signature(record)},
        }
    )
    rendered = render_retrieved_context(state)
    assert "check:working_memory.prompt_agent:contains" in rendered
    assert secret not in rendered


# --- what the lesson does say -----------------------------------------------


def test_the_feedback_names_the_check_and_the_shape_of_what_was_observed() -> None:
    """Updated deliberately by ADR 0180: this used to assert the observed TEXT
    was in the feedback. It is the counts that stay — the excerpt was the
    model's own output travelling into its next prompt, which ADR 0162
    measured making the failure it describes more likely."""
    record = _record(_state("the connector stays disabled"), VERDICT)
    assert record is not None
    feedback = str(record.content["verbal_feedback"])
    assert "working_memory.prompt_agent" in feedback
    assert "does not contain a required substring" in feedback
    assert "observed 4 words, 28 chars" in feedback
    assert "the connector stays disabled" not in feedback


def test_a_missing_value_is_reported_as_missing_not_as_empty() -> None:
    record = _record(_state(), TaskCheck(path="working_memory.nowhere", op="exists"))
    assert record is not None
    assert "was never recorded" in str(record.content["verbal_feedback"])


def test_every_check_operator_has_prose_that_omits_its_value() -> None:
    """A new op in `checks.OPS` with no entry here would fall through to a
    generic sentence, which is a silent loss of the lesson's content."""
    assert set(_OP_PROSE) == set(OPS)


# --- provenance -------------------------------------------------------------


def test_failing_nodes_stays_empty_and_the_observer_is_the_harness() -> None:
    """`failing_nodes` names the node that CAUSED an error (ADR 0096) and no
    node did. Naming one would attribute the observation to code that ran
    cleanly."""
    record = _record(_state(), VERDICT)
    assert record is not None
    assert record.content["failing_nodes"] == []
    assert record.content["node_id"] == CHECK_OBSERVER_NODE_ID


def test_grounded_in_resolves_against_the_recorded_check_failures() -> None:
    """The critic indexes the DERIVED state's errors. The same lines sit at the
    same indices in `check_failures`, so every citation still resolves to
    something a reader of the record can see."""
    record = _record(
        _state(),
        VERDICT,
        TaskCheck(path="working_memory.nowhere", op="exists"),
    )
    assert record is not None
    grounded = record.content["grounded_in"]
    failures = record.content["check_failures"]
    assert grounded == ["errors[0]", "errors[1]"]
    assert len(failures) == len(grounded)


def test_the_counted_fields_come_from_the_report_not_from_the_critic() -> None:
    record = _record(
        _state("VERDICT: no"),
        VERDICT,
        TaskCheck(path="working_memory.nowhere", op="exists"),
    )
    assert record is not None
    assert record.content["checks_passed"] == 1
    assert record.content["checks_total"] == 2


# --- the run's own state is never touched -----------------------------------


def test_the_runs_state_is_not_mutated() -> None:
    """The alternative design injects the check failures into `state.errors`
    before reflection. Measured: `score_scenario` then stops counting the check
    fraction BECAUSE the checks failed, and `classify` reports the run raised.
    A metric that changes when you measure it (ADR 0174)."""
    state = _state()
    _record(state, VERDICT)
    assert state.errors == []
    assert evaluate_checks((VERDICT,), state).passed == 0  # unchanged, still measurable


# --- the deliberate merge ---------------------------------------------------


def test_two_different_required_substrings_on_one_field_are_one_lesson() -> None:
    """The signature drops the expected value, so two runs whose summaries each
    omitted a different required term recur as one lesson: "this field keeps
    omitting a required term". That is one behaviour, not a catch-all across
    unrelated failures — and it is what makes the two-run rule reachable on a
    corpus of distinct scenarios (ADR 0155's summary split)."""
    memory = InMemoryMemoryStore()
    for run, value in (("r1", "swimming"), ("r2", "landslip")):
        record_check_outcomes(
            memory=memory,
            checks=(TaskCheck(path="working_memory.summary", op="contains", value=value),),
            final_state=AEFState(
                run_id=run,
                agent_id="a",
                objective=f"summarise {run}",
                working_memory={"summary": "a summary that omits it"},
            ),
            critic=CRITIC,
            judge=JUDGE,
            run_id=run,
            agent_id="a",
            created_at=NOW,
        )
    entries = RuleBasedConsolidator().consolidate(memory, InMemoryKnowledgeStore(), agent_id="a")
    assert [e.signature for e in entries] == ["failure:check:working_memory.summary:contains"]


def test_a_different_field_is_a_different_lesson() -> None:
    memory = InMemoryMemoryStore()
    for run, path in (("r1", "working_memory.summary"), ("r2", "working_memory.answer")):
        record_check_outcomes(
            memory=memory,
            checks=(TaskCheck(path=path, op="contains", value="x"),),
            final_state=AEFState(run_id=run, agent_id="a", objective="o"),
            critic=CRITIC,
            judge=JUDGE,
            run_id=run,
            agent_id="a",
            created_at=NOW,
        )
    assert RuleBasedConsolidator().consolidate(memory, InMemoryKnowledgeStore(), agent_id="a") == []


def test_one_occurrence_is_still_an_episode() -> None:
    """ADR 0110's threshold is not weakened by this producer."""
    memory = InMemoryMemoryStore()
    record_check_outcomes(
        memory=memory,
        checks=(VERDICT,),
        final_state=_state(),
        critic=CRITIC,
        judge=JUDGE,
        run_id="r1",
        agent_id="a",
        created_at=NOW,
    )
    assert RuleBasedConsolidator().consolidate(memory, InMemoryKnowledgeStore(), agent_id="a") == []


# --- keys -------------------------------------------------------------------


def test_check_key_is_path_and_op_only() -> None:
    assert check_key(VERDICT) == "check:working_memory.prompt_agent:contains"


def test_repeated_checks_on_one_path_produce_one_key() -> None:
    record = _record(
        _state(),
        TaskCheck(path="working_memory.prompt_agent", op="contains", value="QQQ"),
        TaskCheck(path="working_memory.prompt_agent", op="contains", value="ZZZ"),
    )
    assert record is not None
    assert record.content["failed_checks"] == ["check:working_memory.prompt_agent:contains"]
    assert len(record.content["check_failures"]) == 2


@pytest.mark.parametrize("op", sorted(OPS))
def test_no_operator_renders_its_expected_value(op: str) -> None:
    value: object = {"regex": "ZQXMARKER", "exists": None, "max_words": 1, "min_words": 99}.get(
        op, "ZQXMARKER"
    )
    record = _record(
        _state("one two"), TaskCheck(path="working_memory.prompt_agent", op=op, value=value)
    )
    if record is None:  # the check held; nothing to leak
        return
    assert "ZQXMARKER" not in json.dumps(record.content)


# --- the run's own OUTPUT is never in the lesson either (ADR 0180) -----------

# The first is `sum-35-priory-gatehouse`'s with-lesson summary, verbatim from
# `docs/research/j4/harm.jsonl` — the run ADR 0162 rig B found was harmful.
# The second OPENS with the marlin pilot's answer as ADR 0174 quotes it
# (`**No. The Accela connector…`) and continues plausibly; only its opening is
# from the record, and the property under test does not depend on the rest.
REAL_OUTPUTS = (
    "From February, the Priory gatehouse gets twelve weeks of stonework, "
    "repointing and lead roof renewal, staying open except two April weeks; "
    "the precinct wall is assessed separately later.",
    "**No. The Accela connector must remain `enabled: false` until the "
    "credentials are provisioned and the sandbox has been exercised.**",
)

OUTPUT_WINDOW = 12


def _windows(text: str, n: int = OUTPUT_WINDOW) -> set[str]:
    body = " ".join(text.split())
    return {body[i : i + n] for i in range(max(len(body) - n + 1, 0))}


@pytest.mark.parametrize("output", REAL_OUTPUTS)
@pytest.mark.parametrize(("op", "value"), [("contains", "ZQXMARKER"), ("max_words", 3)])
def test_no_record_repeats_a_window_of_the_output_it_was_computed_from(
    output: str, op: str, value: object
) -> None:
    """The generic property, not one string.

    A `verbal_feedback` is a prompt surface: `RuleBasedPromptProposer` pastes
    it into the persona and `render_retrieved_context` renders it as a lesson
    bullet. ADR 0162 rig B measured a lesson whose text carried a 38-word
    example summary making two at-cap runs LONGER and breaking the very cap
    check the lesson is about — so no window of the run's own output may
    survive into the record, and 12 characters is short enough that an excerpt
    of any useful length trips it.
    """
    record = _record(
        _state(output), TaskCheck(path="working_memory.prompt_agent", op=op, value=value)
    )
    assert record is not None, "expected the check to fail and a record to exist"
    blob = " ".join(json.dumps(record.content).split())
    leaked = sorted(w for w in _windows(output) if w in blob)
    assert leaked == [], f"{len(leaked)} window(s) of the output survived, e.g. {leaked[:3]}"


def test_the_counts_survive_even_though_the_text_does_not() -> None:
    """Dropping the excerpt must not drop the observation. The words, the
    characters, the path, the operator and the check tallies are all still
    there — they are what the harness computed, as opposed to what the model
    wrote."""
    record = _record(
        _state("one two three four five"),
        TaskCheck(path="working_memory.prompt_agent", op="max_words", value=3),
        TaskCheck(path="working_memory.nowhere", op="exists"),
    )
    assert record is not None
    feedback = str(record.content["verbal_feedback"])
    assert "5 words, 23 chars" in feedback
    assert "working_memory.prompt_agent" in feedback
    assert "longer than the owner's maximum" in feedback
    assert record.content["checks_passed"] == 0
    assert record.content["checks_total"] == 2


def test_the_record_says_where_a_human_can_read_the_output() -> None:
    """A redaction that leaves no forwarding address makes the evidence
    unreachable, which is the failure mode ADR 0110 names for a summary that
    replaces its own source."""
    record = _record(_state("something"), VERDICT)
    assert record is not None
    assert record.content["output_location"] == OUTPUT_LOCATION
    # In the record for a human, NOT in the lines a model is shown: the critic
    # excerpts each quoted signal at 160 characters, so a sentence spent in the
    # failure line pushes the observation out of `verbal_feedback`.
    assert OUTPUT_LOCATION not in str(record.content["verbal_feedback"])
    assert "observed 1 words, 9 chars" in str(record.content["verbal_feedback"])


def test_a_non_text_value_is_reported_by_type_not_by_repr() -> None:
    """`repr(True)` is the run's output as much as a sentence is, and its
    LENGTH is the answer on a boolean field (4 characters versus 5)."""
    state = AEFState(run_id="r1", agent_id="a", objective="o", working_memory={"flag": True})
    record = check_failure_record(
        checks=(TaskCheck(path="working_memory.flag", op="equals", value="no"),),
        final_state=state,
        critic=CRITIC,
        judge=JUDGE,
        run_id="r1",
        agent_id="a",
        created_at=NOW,
    )
    assert record is not None
    feedback = str(record.content["verbal_feedback"])
    assert "a non-text value of type bool" in feedback
    assert "True" not in feedback
    assert "chars" not in feedback


# --- one producer, callable from every scored path (ADR 0180) ---------------


class _CountingStore(InMemoryMemoryStore):
    """A real store that also counts writes. Not a mock of the thing under
    test: `record_check_outcomes` is exercised against a working store, and
    the counter only observes."""

    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def write(self, record: MemoryRecord) -> str:
        self.writes += 1
        return super().write(record)


def _record_into(memory: MemoryStore, run_id: str = "r1") -> MemoryRecord | None:
    return record_check_outcomes(
        memory=memory,
        checks=(VERDICT,),
        final_state=_state(),
        critic=CRITIC,
        judge=JUDGE,
        run_id=run_id,
        agent_id="a",
        created_at=NOW,
    )


def test_recording_one_run_twice_writes_one_record() -> None:
    """The wiring this unblocks is more than one call site — `bootstrap`, and
    whatever scores a run against owner checks with a store present — so
    wiring it twice must not manufacture evidence. `source_record_ids` is the
    entry's only measure of how well-evidenced it is."""
    memory = _CountingStore()
    first = _record_into(memory)
    second = _record_into(memory)
    assert first is not None and second is not None
    assert memory.writes == 1
    assert second.id == first.id
    assert len(memory.query("failure", run_id="r1", agent_id="a", limit=10)) == 1


def test_the_second_call_returns_the_record_already_in_the_store() -> None:
    """Not `None`: the run DID fail an owner check, and a caller that reports
    on the return value (bootstrap's `check_failed` line) must still say so."""
    memory = _CountingStore()
    _record_into(memory)
    again = _record_into(memory)
    assert again is not None
    assert again.kind == "failure"
    assert again.content["failed_checks"] == ["check:working_memory.prompt_agent:contains"]


def test_the_record_id_is_derived_from_the_run_and_the_failed_checks() -> None:
    """Derived rather than a uuid4, so a store keyed by id collapses a repeat
    even where the query-based guard cannot see it — `RunScopedMemory` answers
    queries from its per-input scratch while mirroring writes into a durable
    sink."""
    record = _record(_state(), VERDICT)
    assert record is not None
    assert record.id == check_record_id(
        agent_id="a", run_id="r1", keys=["check:working_memory.prompt_agent:contains"]
    )
    assert record.id.startswith(CHECK_RECORD_ID_PREFIX)
    other = _record(_state(), VERDICT, run_id="r2")
    assert other is not None
    assert other.id != record.id


def test_two_different_runs_are_two_records() -> None:
    """Idempotence is per run, not per signature — recurrence across DISTINCT
    runs is exactly what ADR 0110's threshold counts."""
    memory = _CountingStore()
    _record_into(memory, run_id="r1")
    _record_into(memory, run_id="r2")
    assert memory.writes == 2
    entries = RuleBasedConsolidator().consolidate(memory, InMemoryKnowledgeStore(), agent_id="a")
    assert len(entries) == 1
    assert entries[0].occurrence_count == 2


def test_a_scored_run_recording_its_check_failure_keeps_the_lesson_fresh() -> None:
    """ADR 0175's defect 1, in the small.

    A lesson seeded from two runs, then a scored split where every run writes a
    `success` record. `runs_since_last_seen` climbs with the split — ADR 0116
    demotes on exactly that number, and over 17 scenarios the measured entry
    went from rank 0 to rank 39 — and the lesson can never be re-seen, because
    before ADR 0180 only `bootstrap` could produce a check-derived failure. The
    producer being one callable function is what closes it: the run that DOES
    fail the same check records it, and the counter resets.
    """
    seeded = InMemoryMemoryStore()
    for run in ("b1", "b2"):
        _record_into(seeded, run_id=run)

    def split(memory: MemoryStore, *, producer_on_the_scored_path: bool) -> int:
        for i in range(6):
            at = NOW + timedelta(minutes=i + 1)
            memory.write(
                MemoryRecord(
                    kind="success",
                    content={"objective": f"scored-{i}", "verbal_feedback": "clean run"},
                    run_id=f"scored-{i}",
                    agent_id="a",
                    created_at=at,
                )
            )
            if producer_on_the_scored_path and i == 5:
                record_check_outcomes(
                    memory=memory,
                    checks=(VERDICT,),
                    final_state=_state(),
                    critic=CRITIC,
                    judge=JUDGE,
                    run_id=f"scored-{i}",
                    agent_id="a",
                    created_at=at,
                )
        entries = RuleBasedConsolidator().consolidate(
            memory, InMemoryKnowledgeStore(), agent_id="a"
        )
        entry = next(e for e in entries if e.kind == "failure")
        return entry.runs_since_last_seen

    without = split(_copy_of(seeded), producer_on_the_scored_path=False)
    with_producer = split(_copy_of(seeded), producer_on_the_scored_path=True)
    assert without == 6, "every scored run is a run this lesson has gone without recurring"
    assert with_producer == 0, "the run that failed the same check re-freshens it"


def _copy_of(memory: InMemoryMemoryStore) -> InMemoryMemoryStore:
    fresh = InMemoryMemoryStore()
    for kind in ("failure", "success"):
        for record in memory.query(kind, limit=100):  # type: ignore[arg-type]
            fresh.write(record)
    return fresh


def test_wiring_the_producer_twice_does_not_inflate_the_evidence() -> None:
    """The end-to-end version of the idempotence property: two call sites
    firing on each of two runs must still consolidate to a two-run lesson, not
    a four-run one."""
    memory = _CountingStore()
    for run in ("r1", "r2"):
        _record_into(memory, run_id=run)  # e.g. bootstrap
        _record_into(memory, run_id=run)  # e.g. the scored path
    entries = RuleBasedConsolidator().consolidate(memory, InMemoryKnowledgeStore(), agent_id="a")
    assert len(entries) == 1
    assert entries[0].occurrence_count == 2
    assert memory.writes == 2
