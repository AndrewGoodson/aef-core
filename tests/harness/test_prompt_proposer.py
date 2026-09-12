"""`RuleBasedPromptProposer` (ADR 0157).

The evidence in these tests is hand-built `MemoryRecord`s rather than a stubbed
`KnowledgeStore`, and that is deliberate: the proposer does not take a store,
it consolidates the records `MemoryEvidence` admits through
`RuleBasedConsolidator` — so a test that handed it pre-made entries would skip
the two-run rule, which is the property most worth pinning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aef.harness.corpus import Corpus, Scenario, Split
from aef.harness.prompt_proposer import (
    DEFAULT_SECTION_HEADING,
    PromptOutsideZoneAError,
    RuleBasedPromptProposer,
)
from aef.harness.proposer import MemoryEvidence
from aef.harness.zones import ZonePolicy
from aef.services.memory.base import MemoryRecord
from aef.state import AEFState

AGENT_ROOT = ".claude/agents"
PERSONA = f"{AGENT_ROOT}/accela-agent.md"
POLICY = ZonePolicy(agent_root=AGENT_ROOT)

BODY = """---
name: marlin-accela
---

# Marlin Accela agent

Purpose: operate the Accela connector.
"""


def test_codex_lessons_edit_only_instructions_and_remain_idempotent() -> None:
    import tomllib

    source = '''# owner configuration
name = "reviewer"
description = "Review evidence"
developer_instructions = """Use evidence.\nPreserve owner's constraints."""
sandbox_mode = "read-only" # preserve this comment
[mcp_servers.example]
command = "owner-command"
'''
    path = ".codex/agents/reviewer.toml"
    proposer = make(zone_policy=ZonePolicy(agent_root=".codex/agents"))
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (proposal,) = propose(proposer, ev, source=source, path=path)
    old, new = tomllib.loads(source), tomllib.loads(proposal.proposed)
    assert DEFAULT_SECTION_HEADING in new["developer_instructions"]
    assert new["developer_instructions"].startswith(old["developer_instructions"])
    new["developer_instructions"] = old["developer_instructions"]
    assert new == old
    assert "# preserve this comment" in proposal.proposed
    assert propose(proposer, ev, source=proposal.proposed, path=path) == ()


_T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def record(
    *,
    run_id: str,
    nodes: tuple[str, ...] = ("prompt_agent",),
    feedback: str = "1 failure signal: errors[0] node 'prompt_agent' raised TimeoutError",
    minutes: int = 0,
    record_id: str | None = None,
    agent_id: str | None = "marlin-accela",
) -> MemoryRecord:
    return MemoryRecord(
        kind="failure",
        content={
            "verbal_feedback": feedback,
            "failing_nodes": list(nodes),
            "objective": "operate the connector",
        },
        run_id=run_id,
        agent_id=agent_id,
        id=record_id or f"rec-{run_id}-{'-'.join(nodes)}",
        created_at=_T0 + timedelta(minutes=minutes),
    )


def evidence(*records: MemoryRecord) -> MemoryEvidence:
    return MemoryEvidence(records=records)


def propose(
    proposer: RuleBasedPromptProposer,
    ev: MemoryEvidence,
    *,
    source: str = BODY,
    path: str = PERSONA,
):
    return proposer.propose_from_memory(ev, proposal_id="c1", path=path, source=source)


def make(**kwargs: object) -> RuleBasedPromptProposer:
    kwargs.setdefault("zone_policy", POLICY)
    return RuleBasedPromptProposer(**kwargs)  # type: ignore[arg-type]


# -- the two-run rule -------------------------------------------------------


def test_one_occurrence_is_an_episode_and_proposes_nothing() -> None:
    ev = evidence(record(run_id="r1"))
    proposer = make()
    assert propose(proposer, ev) == ()
    reason = proposer.no_proposal_reason(ev, path=PERSONA, source=BODY)
    assert "1 distinct run" in reason
    assert "2 are required" in reason


def test_two_records_in_one_run_are_still_one_occurrence() -> None:
    ev = evidence(
        record(run_id="r1", record_id="a", minutes=0),
        record(run_id="r1", record_id="b", minutes=1),
    )
    proposer = make()
    assert propose(proposer, ev) == ()
    assert "1 distinct run" in proposer.no_proposal_reason(ev, path=PERSONA, source=BODY)


def test_two_distinct_runs_make_a_lesson() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (proposal,) = propose(make(), ev)
    assert DEFAULT_SECTION_HEADING in proposal.proposed
    assert "sig=failure:prompt_agent" in proposal.proposed
    assert "TimeoutError" in proposal.proposed
    # Provenance: both records are cited, and the rationale states the count
    # it computed rather than an adjective.
    assert {c.source for c in proposal.grounded_in} == {
        "rec-r1-prompt_agent",
        "rec-r2-prompt_agent",
    }
    assert "2 distinct run(s)" in proposal.rationale


def test_a_record_with_no_failing_node_cannot_be_signed() -> None:
    ev = evidence(
        record(run_id="r1", nodes=(), record_id="a"),
        record(run_id="r2", nodes=(), record_id="b"),
    )
    proposer = make()
    assert propose(proposer, ev) == ()
    assert "no signable failing node" in proposer.no_proposal_reason(ev, path=PERSONA, source=BODY)


# -- section creation and append -------------------------------------------


def test_the_section_is_created_when_absent_and_nothing_above_it_moves() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (proposal,) = propose(make(), ev)
    assert proposal.proposed.startswith(BODY.rstrip("\n"))
    assert proposal.proposed.endswith("\n")
    assert proposal.proposed.count(DEFAULT_SECTION_HEADING) == 1


def test_an_existing_section_is_appended_to_and_its_bullets_are_untouched() -> None:
    source = BODY + f"\n{DEFAULT_SECTION_HEADING}\n\n- an owner's own bullet, hand written\n"
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (proposal,) = propose(make(), ev, source=source)
    assert proposal.proposed.count(DEFAULT_SECTION_HEADING) == 1
    assert "- an owner's own bullet, hand written\n" in proposal.proposed
    lines = proposal.proposed.splitlines()
    assert lines.index("- an owner's own bullet, hand written") < len(lines) - 1


def test_a_later_heading_ends_the_section_so_the_bullet_lands_inside_it() -> None:
    source = (
        BODY
        + f"\n{DEFAULT_SECTION_HEADING}\n\n- first\n\n## Something the owner wrote after\n\nprose\n"
    )
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (proposal,) = propose(make(), ev, source=source)
    lines = proposal.proposed.splitlines()
    assert lines.index("## Something the owner wrote after") > next(
        i for i, line in enumerate(lines) if "sig=failure:prompt_agent" in line
    )
    assert lines[-1] == "prose"


# -- idempotence ------------------------------------------------------------


def test_the_same_evidence_twice_proposes_the_bullet_once() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    proposer = make()
    (first,) = propose(proposer, ev)
    assert propose(proposer, ev, source=first.proposed) == ()
    reason = proposer.no_proposal_reason(ev, path=PERSONA, source=first.proposed)
    assert "already in" in reason
    assert "failure:prompt_agent" in reason


def test_the_same_evidence_twice_produces_the_same_bytes() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (a,) = propose(make(), ev)
    (b,) = propose(make(), ev)
    assert a.proposed == b.proposed


def test_a_second_lesson_is_appended_after_the_first_is_present() -> None:
    ev = evidence(
        record(run_id="r1", record_id="a"),
        record(run_id="r2", record_id="b", minutes=5),
        record(run_id="r3", nodes=("consolidate",), record_id="c", minutes=6),
        record(run_id="r4", nodes=("consolidate",), record_id="d", minutes=7),
    )
    proposer = make()
    (first,) = propose(proposer, ev)
    (second,) = propose(proposer, ev, source=first.proposed)
    assert "sig=failure:prompt_agent " in second.proposed
    assert "sig=failure:consolidate " in second.proposed


def test_the_highest_recurrence_lesson_wins() -> None:
    ev = evidence(
        record(run_id="r1", nodes=("alpha",), record_id="a"),
        record(run_id="r2", nodes=("alpha",), record_id="b", minutes=1),
        record(run_id="r3", nodes=("alpha",), record_id="c", minutes=2),
        # More recent, but seen in fewer runs.
        record(run_id="r4", nodes=("beta",), record_id="d", minutes=90),
        record(run_id="r5", nodes=("beta",), record_id="e", minutes=91),
    )
    (proposal,) = propose(make(), ev)
    assert "sig=failure:alpha " in proposal.proposed
    assert "sig=failure:beta " not in proposal.proposed


# -- the bullet -------------------------------------------------------------


def test_the_feedback_is_verbatim_and_the_bullet_is_one_line() -> None:
    ev = evidence(
        record(run_id="r1", feedback="line one\nline two", record_id="a"),
        record(run_id="r2", feedback="line one\nline two", record_id="b", minutes=5),
    )
    (proposal,) = propose(make(), ev)
    bullet = next(line for line in proposal.proposed.splitlines() if line.startswith("- <!-- aef"))
    assert bullet.endswith("line one line two")
    assert "runs=2" in bullet


def test_a_long_lesson_is_truncated_at_the_named_ceiling() -> None:
    long = "x" * 900
    ev = evidence(
        record(run_id="r1", feedback=long, record_id="a"),
        record(run_id="r2", feedback=long, record_id="b", minutes=5),
    )
    (proposal,) = propose(make(max_bullet_chars=100), ev)
    bullet = next(line for line in proposal.proposed.splitlines() if line.startswith("- <!-- aef"))
    assert bullet.endswith("…")
    assert len(bullet.split("--> ", 1)[1]) == 100


def test_a_signature_that_cannot_be_written_into_a_marker_is_refused() -> None:
    ev = evidence(
        record(run_id="r1", nodes=("a--b",), record_id="a"),
        record(run_id="r2", nodes=("a--b",), record_id="b", minutes=5),
    )
    proposer = make()
    assert propose(proposer, ev) == ()
    assert "provenance marker" in proposer.no_proposal_reason(ev, path=PERSONA, source=BODY)


# -- eviction ---------------------------------------------------------------


def _filled(count: int) -> str:
    bullets = "\n".join(
        f"- <!-- aef sig=failure:old{i} runs=2 --> an older lesson {i}" for i in range(count)
    )
    return BODY + f"\n{DEFAULT_SECTION_HEADING}\n\n{bullets}\n"


def test_a_full_section_evicts_the_stalest_bullet_this_loop_wrote() -> None:
    # `old0`..`old3` are not in the current evidence at all, so they have no
    # supporting knowledge: the stalest thing in the file. The lowest index
    # breaks the tie, so eviction is deterministic.
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    (proposal,) = propose(make(max_bullets=5), ev, source=_filled(5))
    assert "sig=failure:old0 " not in proposal.proposed
    assert "sig=failure:old4 " in proposal.proposed
    assert "sig=failure:prompt_agent " in proposal.proposed
    assert proposal.proposed.count("- <!-- aef") == 5


def test_a_live_lesson_outranks_a_stale_one_for_eviction() -> None:
    # `failure:kept` last recurred at r6 with no later run, so
    # `runs_since_last_seen` is 0; `failure:stale` last recurred at r2 and
    # three runs have happened since.
    ev = evidence(
        record(run_id="r1", nodes=("stale",), record_id="a", minutes=0),
        record(run_id="r2", nodes=("stale",), record_id="b", minutes=1),
        record(run_id="r5", nodes=("kept",), record_id="c", minutes=10),
        record(run_id="r6", nodes=("kept",), record_id="d", minutes=11),
        record(run_id="r7", nodes=("new",), record_id="e", minutes=20),
        record(run_id="r8", nodes=("new",), record_id="f", minutes=21),
    )
    source = (
        BODY
        + f"\n{DEFAULT_SECTION_HEADING}\n\n"
        + "- <!-- aef sig=failure:stale runs=2 --> the stale one\n"
        + "- <!-- aef sig=failure:kept runs=2 --> the live one\n"
    )
    (proposal,) = propose(make(max_bullets=2), ev, source=source)
    assert "sig=failure:stale " not in proposal.proposed
    assert "sig=failure:kept " in proposal.proposed
    assert "sig=failure:new " in proposal.proposed


def test_an_owner_written_bullet_is_never_evicted() -> None:
    source = BODY + f"\n{DEFAULT_SECTION_HEADING}\n\n- the owner said so\n- and again\n"
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    proposer = make(max_bullets=2)
    assert propose(proposer, ev, source=source) == ()
    reason = proposer.no_proposal_reason(ev, path=PERSONA, source=source)
    assert "never evicted" in reason


# -- Zone A and the file type ----------------------------------------------


def test_a_path_outside_zone_a_is_a_named_refusal() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    with pytest.raises(PromptOutsideZoneAError) as caught:
        propose(make(), ev, path="docs/persona.md")
    assert "Zone C" in str(caught.value)


def test_the_harness_is_a_refusal_even_with_a_wide_agent_root() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    proposer = RuleBasedPromptProposer(zone_policy=ZonePolicy(agent_root=""))
    with pytest.raises(PromptOutsideZoneAError) as caught:
        propose(proposer, ev, path="aef/harness/gates/g0_static_safety.py")
    assert "Zone B" in str(caught.value)


def test_a_python_agent_path_proposes_nothing_and_names_the_other_proposer() -> None:
    ev = evidence(record(run_id="r1"), record(run_id="r2", minutes=5))
    proposer = make()
    assert propose(proposer, ev, path=f"{AGENT_ROOT}/migrated/graph.py", source="X = 1\n") == ()
    reason = proposer.no_proposal_reason(
        ev, path=f"{AGENT_ROOT}/migrated/graph.py", source="X = 1\n"
    )
    assert "--proposer rule_based" in reason


# -- scope ------------------------------------------------------------------


def _scenario(scenario_id: str, graph_id: str) -> Scenario:
    return Scenario(
        id=scenario_id,
        split=Split.TRAIN,
        graph_id=graph_id,
        graph_version="0.1.0",
        initial_state=AEFState(run_id=scenario_id, agent_id=graph_id, objective="o"),
        trace=(),
        recorded_at=_T0,
    )


def _corpus() -> Corpus:
    return Corpus(
        root=Path("corpus"),
        scenarios=(
            _scenario("mine", "marlin-accela"),
            _scenario("theirs", "marlin-azure"),
        ),
    )


def test_another_graphs_scenario_is_not_this_prompts_evidence() -> None:
    ev = evidence(
        record(run_id="mine", record_id="a"),
        record(run_id="theirs", record_id="b", minutes=5),
    )
    proposer = make(graph_id="marlin-accela", corpus=_corpus())
    assert propose(proposer, ev) == ()
    reason = proposer.no_proposal_reason(ev, path=PERSONA, source=BODY)
    assert "another graph's scenario" in reason
    # Without the scope, the same two records are two runs and DO make a lesson
    # — so the filter is what changed the answer, not the records.
    assert propose(make(), ev) != ()


def test_a_run_the_corpus_never_heard_of_is_production_experience() -> None:
    ev = evidence(
        record(run_id="mine", record_id="a"),
        record(run_id="live-1234", record_id="b", minutes=5),
    )
    proposer = make(graph_id="marlin-accela", corpus=_corpus())
    assert propose(proposer, ev) != ()


# -- construction -----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"max_bullets": 0}, {"max_bullet_chars": 0}, {"heading": "Lessons"}],
)
def test_a_meaningless_configuration_is_refused_at_construction(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        make(**kwargs)


# -- a provider fact is not a lesson (ADR 0179, R3) -------------------------

# What `RuleBasedCritic` wrote when the containment note was an `errors` entry,
# copied from a real `aef run` through a `command` provider with no `{system}`
# slot. Planted here because the node no longer produces it — which is the
# point: this filter defends a memory file written by an older `aef`, and it
# has to be verified against a planted fault or it is not a detector.
PROVIDER_FACT_FEEDBACK = (
    "1 error(s) recorded; 0/0 tool call(s) failed. errors[0]: {'node_id': 'prompt_agent', "
    "'type': 'prompt_agent.persona_in_user_turn', 'provider': 'command', "
    "'isolation': ['user_turn_persona'], 'message': \"provider 'command' declares no "
    "system channel, so persona 'marlin-accela' was prepended to the USER turn.\"}"
)


def test_a_containment_note_never_becomes_a_bullet_in_the_persona() -> None:
    """Reproduced before the fix: three runs of an agent that ANSWERED
    CORRECTLY through a slotless `command` provider wrote three failure
    records, cleared ADR 0110's two-run threshold, and the next cycle
    proposed

        - <!-- aef sig=failure:prompt_agent runs=3 --> 1 error(s) recorded …
          'type': 'prompt_agent.persona_in_user_turn' …

    A property of the CLI the owner installed, occupying one of five bullet
    slots in the agent's own prompt, forever — its `runs_since_last_seen`
    never grows while the provider is unchanged. No sentence a persona can
    contain will give a CLI a `--system-prompt` flag."""
    ev = evidence(
        record(run_id="run-1", record_id="a", feedback=PROVIDER_FACT_FEEDBACK),
        record(run_id="run-2", record_id="b", feedback=PROVIDER_FACT_FEEDBACK, minutes=5),
        record(run_id="run-3", record_id="c", feedback=PROVIDER_FACT_FEEDBACK, minutes=9),
    )
    proposer = make()
    assert propose(proposer, ev) == ()
    reason = proposer.no_proposal_reason(ev, path=PERSONA, source=BODY)
    assert "3 record(s) dropped as a provider fact" in reason

    # The control: the SAME three runs, same signature, same everything but a
    # feedback string that names a real failure, do produce a bullet. So what
    # changed the answer is the filter, not the shape of the evidence.
    real = evidence(
        record(run_id="run-1", record_id="a"),
        record(run_id="run-2", record_id="b", minutes=5),
        record(run_id="run-3", record_id="c", minutes=9),
    )
    assert propose(make(), real) != ()


def test_the_filter_reads_every_string_in_the_record_not_one_field() -> None:
    """`content` is `dict[str, Any]` and nothing constrains it. A filter that
    reads only `verbal_feedback` is one refactor away from reading none of the
    right fields, so `rationale`, `grounded_in` and anything else stringy is
    scanned too."""
    planted = MemoryRecord(
        kind="failure",
        content={
            "verbal_feedback": "the run went badly",
            "rationale": "prompt_agent.persona_in_user_turn on every call",
            "failing_nodes": ["prompt_agent"],
        },
        run_id="run-1",
        agent_id="marlin-accela",
        id="a",
        created_at=_T0,
    )
    in_a_list = MemoryRecord(
        kind="failure",
        content={
            "verbal_feedback": "the run went badly",
            "grounded_in": ["errors[0]", "prompt_agent.persona_in_user_turn"],
            "failing_nodes": ["prompt_agent"],
        },
        run_id="run-2",
        agent_id="marlin-accela",
        id="b",
        created_at=_T0 + timedelta(minutes=5),
    )
    proposer = make()
    assert propose(proposer, evidence(planted, in_a_list)) == ()
    assert "2 record(s) dropped as a provider fact" in proposer.no_proposal_reason(
        evidence(planted, in_a_list), path=PERSONA, source=BODY
    )
