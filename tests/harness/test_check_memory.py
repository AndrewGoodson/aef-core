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
from datetime import UTC, datetime

import pytest

from aef.harness.check_memory import (
    _OP_PROSE,
    CHECK_OBSERVER_NODE_ID,
    check_failure_record,
    check_key,
    write_check_failure_record,
)
from aef.harness.checks import OPS, TaskCheck, evaluate_checks
from aef.reasoning.nodes import render_retrieved_context
from aef.reasoning.rule_based_reflection import RuleBasedCritic, RuleBasedJudge
from aef.services.knowledge.consolidate import RuleBasedConsolidator, default_signature
from aef.services.knowledge.in_memory import InMemoryKnowledgeStore
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
        written = write_check_failure_record(
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


def test_the_feedback_names_the_check_and_the_observed_value() -> None:
    record = _record(_state("the connector stays disabled"), VERDICT)
    assert record is not None
    feedback = str(record.content["verbal_feedback"])
    assert "working_memory.prompt_agent" in feedback
    assert "does not contain a required substring" in feedback
    assert "the connector stays disabled" in feedback


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
        write_check_failure_record(
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
        write_check_failure_record(
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
    write_check_failure_record(
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
