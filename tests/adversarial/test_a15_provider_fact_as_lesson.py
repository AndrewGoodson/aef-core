"""A15 — a property of the operator's CLI, read as the agent's failure.

Reproduced (ADR 0179, R3). Not an attacker with intent: the adversary here is
the system's own plumbing, which is the harder case to notice. A prompt agent
run through a provider with no `{system}` slot — `codex`, or any `command:`
template without one — has its persona prepended to the USER turn. That fact
was recorded as an ERROR, so:

  * the task metric read 0.0 on every run, however good the answer;
  * `RuleBasedCritic` wrote a failure record with the provider's warning in
    `verbal_feedback`;
  * three distinct runs cleared ADR 0110's two-run threshold, and the next
    cycle proposed the provider's warning as a BULLET IN THE AGENT'S OWN
    PROMPT — where it holds one of five slots forever, because
    `runs_since_last_seen` never grows while the provider is unchanged.

No sentence a persona can contain will give a CLI a `--system-prompt` flag.

Two controls, in depth. First, `PromptAgentNode` records the fact as a
`warning` inside its containment record rather than as an error, so no reflect
node ever writes it as failure memory. Second — the one attacked here, because
it is the one that still binds for memory written by an older `aef` — the
proposer drops any record whose text names a `prompt_agent.*` type.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aef.harness.prompt_proposer import RuleBasedPromptProposer
from aef.harness.proposer import MemoryEvidence
from aef.harness.zones import ZonePolicy
from aef.services.memory.base import MemoryRecord

AGENT_ROOT = ".claude/agents"
PERSONA = f"{AGENT_ROOT}/marlin-accela.md"
POLICY = ZonePolicy(agent_root=AGENT_ROOT)
BODY = "---\nname: marlin-accela\n---\n\n# Marlin Accela agent\n\nOperate the connector.\n"
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

PROVIDER_FACT = (
    "1 failure signal: errors[0] {'type': 'prompt_agent.persona_in_user_turn', "
    "'isolation': ['user_turn_persona'], 'message': \"provider 'command' declares no "
    "system channel, so persona 'marlin-accela' was prepended to the USER turn.\"}"
)
REAL_FAILURE = "1 failure signal: errors[0] node 'prompt_agent' raised TimeoutError"


def _record(run_id: str, feedback: str, *, minutes: int = 0, **content: object) -> MemoryRecord:
    body: dict[str, object] = {
        "verbal_feedback": feedback,
        "failing_nodes": ["prompt_agent"],
        "objective": "operate the connector",
    }
    body.update(content)
    return MemoryRecord(
        kind="failure",
        content=body,
        run_id=run_id,
        agent_id="marlin-accela",
        id=f"rec-{run_id}",
        created_at=T0 + timedelta(minutes=minutes),
    )


def _propose(records: tuple[MemoryRecord, ...]) -> tuple[object, ...]:
    proposer = RuleBasedPromptProposer(zone_policy=POLICY)
    return proposer.propose_from_memory(
        MemoryEvidence(records=records), proposal_id="c1", path=PERSONA, source=BODY
    )


def _reason(records: tuple[MemoryRecord, ...]) -> str:
    proposer = RuleBasedPromptProposer(zone_policy=POLICY)
    return proposer.no_proposal_reason(MemoryEvidence(records=records), path=PERSONA, source=BODY)


THREE_PROVIDER_FACTS = (
    _record("run-1", PROVIDER_FACT),
    _record("run-2", PROVIDER_FACT, minutes=5),
    _record("run-3", PROVIDER_FACT, minutes=9),
)
THREE_REAL_FAILURES = (
    _record("run-1", REAL_FAILURE),
    _record("run-2", REAL_FAILURE, minutes=5),
    _record("run-3", REAL_FAILURE, minutes=9),
)


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a15_a_providers_property_never_becomes_a_bullet(attack_log: list[str]) -> None:
    assert _propose(THREE_PROVIDER_FACTS) == ()
    reason = _reason(THREE_PROVIDER_FACTS)
    attack_log.append(reason)
    assert "dropped as a provider fact" in reason, attack_log


def test_a15_the_same_evidence_shape_with_a_real_failure_does_propose() -> None:
    """The control for the control. Three runs, one signature, the same
    threshold — only the TEXT differs. If this proposed nothing either, the
    test above would be measuring the two-run rule, not the filter."""
    assert _propose(THREE_REAL_FAILURES) != ()


def test_a15_the_filter_reads_every_string_in_the_record() -> None:
    """`content` is `dict[str, Any]` and nothing constrains it. A filter that
    reads `verbal_feedback` alone is one refactor from reading none of the
    right fields, so the attack hides the fact in other keys."""
    hidden_in_a_string = (
        _record("run-1", "the run went badly", rationale="prompt_agent.persona_in_user_turn"),
        _record(
            "run-2", "the run went badly", minutes=5, rationale="prompt_agent.persona_in_user_turn"
        ),
    )
    hidden_in_a_list = (
        _record(
            "run-1",
            "the run went badly",
            grounded_in=["errors[0]", "prompt_agent.persona_in_user_turn"],
        ),
        _record(
            "run-2",
            "the run went badly",
            minutes=5,
            grounded_in=["errors[0]", "prompt_agent.persona_in_user_turn"],
        ),
    )
    assert _propose(hidden_in_a_string) == ()
    assert _propose(hidden_in_a_list) == ()


def test_a15_a_genuine_prompt_agent_lesson_is_not_collateral_damage() -> None:
    """The refusal must not be a prefix ban on the node id. The reproduced
    signature is `failure:prompt_agent`, which is a NODE, so banning that
    prefix would discard every genuine lesson the prompt-agent node ever
    produces — a filter that silences the only node with anything to say."""
    proposals = _propose(THREE_REAL_FAILURES)
    assert proposals, "a real prompt_agent failure was dropped along with the provider fact"


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a15_the_control_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, attack_log: list[str]
) -> None:
    """Blind `_names_a_provider_fact` and the provider's own warning is
    proposed into the persona, verbatim, exactly as reproduced.

    The assertion is on the BULLET TEXT: what made this defect corrosive is
    not that a proposal happened, it is what the proposal said.
    """
    import aef.harness.prompt_proposer as prompt_proposer

    monkeypatch.setattr(prompt_proposer, "_names_a_provider_fact", lambda record: False)

    proposals = _propose(THREE_PROVIDER_FACTS)
    assert proposals, (
        "nothing was proposed even with the filter blinded, so the drop above is not what "
        "stopped it and this attack proves nothing"
    )
    proposed = proposals[0].proposed  # type: ignore[attr-defined]
    attack_log.append(proposed)
    assert "persona_in_user_turn" in proposed, attack_log
    assert "declares no system channel" in proposed, attack_log
