"""The proposer, and the control cohort it also supplies.

M8's acceptance properties:
  1. an ungrounded proposal is never emitted
  2. grounding may cite the train split only — the anti-leak rule
  3. a deliberately-bad proposal is caught by the appropriate gate
  4. the control cohort G3 requires is reproducible
"""

import pytest

from aef.harness.corpus import Split
from aef.harness.proposer import (
    Citation,
    ControlCohortGenerator,
    Proposal,
    ProposalError,
    RuleBasedProposer,
    TrainOnlyEvidence,
    UngroundedProposalError,
    find_constants,
    rewrite_constant,
)

SOURCE = "RETRY_LIMIT = 3\nTIMEOUT_S = 2.5\n\n\ndef run():\n    return RETRY_LIMIT\n"
TRAIN = (Citation(source="s1", split=Split.TRAIN, detail="timed out twice"),)


def _propose(**overrides: object) -> tuple[Proposal, ...]:
    kwargs: dict[str, object] = {
        "proposal_id": "p1",
        "path": "agents/planner.py",
        "source": SOURCE,
        "citations": TRAIN,
        "rationale": "two recorded timeouts",
    }
    kwargs.update(overrides)
    return RuleBasedProposer().propose(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Finding and rewriting constants
# --------------------------------------------------------------------------


def test_module_level_numeric_constants_are_found() -> None:
    names = [c.name for c in find_constants(SOURCE)]
    assert names == ["RETRY_LIMIT", "TIMEOUT_S"]


def test_int_and_float_constants_are_distinguished() -> None:
    constants = {c.name: c for c in find_constants(SOURCE)}
    assert constants["RETRY_LIMIT"].is_int
    assert not constants["TIMEOUT_S"].is_int


def test_a_constant_inside_a_function_is_not_found() -> None:
    # Found by AST rather than regex alone, so a match in a nested scope
    # cannot be rewritten.
    assert find_constants("def f():\n    LOCAL_LIMIT = 3\n    return LOCAL_LIMIT\n") == ()


def test_a_number_inside_a_string_is_not_found() -> None:
    assert find_constants('DOC = "LIMIT = 3"\n') == ()


def test_a_lowercase_name_is_not_treated_as_a_constant() -> None:
    assert find_constants("retry_limit = 3\n") == ()


def test_unparseable_source_yields_no_constants() -> None:
    assert find_constants("def broken(\n") == ()


def test_rewriting_preserves_the_rest_of_the_file() -> None:
    constant = next(c for c in find_constants(SOURCE) if c.name == "RETRY_LIMIT")
    rewritten = rewrite_constant(SOURCE, constant, 5)
    assert "RETRY_LIMIT = 5\n" in rewritten
    assert "def run():" in rewritten
    assert "TIMEOUT_S = 2.5" in rewritten


def test_an_int_constant_stays_an_int() -> None:
    constant = next(c for c in find_constants(SOURCE) if c.name == "RETRY_LIMIT")
    assert "RETRY_LIMIT = 4\n" in rewrite_constant(SOURCE, constant, 4.0)


# --------------------------------------------------------------------------
# M8 ACCEPTANCE 1 — an ungrounded proposal is never emitted
# --------------------------------------------------------------------------


def test_a_proposal_with_no_citations_cannot_be_constructed() -> None:
    """Not emitted-and-rejected: never constructed. A proposer that can emit
    'I thought this might help' will fill the queue with it."""
    with pytest.raises(UngroundedProposalError, match="cites no evidence"):
        Proposal(
            id="p1",
            path="agents/a.py",
            original="A = 1\n",
            proposed="A = 2\n",
            rationale="hunch",
        )


def test_the_proposer_refuses_to_speculate() -> None:
    with pytest.raises(UngroundedProposalError, match="does not speculate"):
        _propose(citations=())


def test_a_proposal_with_no_rationale_is_refused() -> None:
    with pytest.raises(ProposalError, match="no rationale"):
        Proposal(
            id="p1",
            path="agents/a.py",
            original="A = 1\n",
            proposed="A = 2\n",
            rationale="   ",
            grounded_in=TRAIN,
        )


def test_a_noop_proposal_is_refused() -> None:
    # A no-op consumes a gate run and a rate-budget slot to prove the system
    # still works.
    with pytest.raises(ProposalError, match="changes nothing"):
        Proposal(
            id="p1",
            path="agents/a.py",
            original="A = 1\n",
            proposed="A = 1\n",
            rationale="r",
            grounded_in=TRAIN,
        )


def test_every_emitted_proposal_carries_its_citations() -> None:
    for proposal in _propose():
        assert proposal.grounded_in == TRAIN
        assert proposal.rationale


def test_the_rationale_names_what_changed() -> None:
    proposal = next(p for p in _propose() if "RETRY_LIMIT" in p.rationale)
    assert "3 to 4" in proposal.rationale


# --------------------------------------------------------------------------
# M8 ACCEPTANCE 2 — train-only grounding
# --------------------------------------------------------------------------


@pytest.mark.parametrize("split", [Split.VALIDATION, Split.HOLDOUT])
def test_citing_a_split_the_proposer_may_not_see_is_refused(split: Split) -> None:
    """Citing validation lets the proposer optimise against the set that
    gates it; citing the holdout destroys the owner's only independent read."""
    with pytest.raises(ProposalError, match="train split only"):
        _propose(citations=(Citation(source="s9", split=split),))


def test_the_evidence_view_refuses_a_scenario_outside_train() -> None:
    evidence = TrainOnlyEvidence(scenario_ids=frozenset({"s1", "s2"}))
    with pytest.raises(ProposalError, match="may only cite evidence it is permitted to see"):
        evidence.cite("holdout-scenario")


def test_the_evidence_view_issues_train_citations() -> None:
    evidence = TrainOnlyEvidence(scenario_ids=frozenset({"s1"}))
    citation = evidence.cite("s1", "failed on retry")
    assert citation.split is Split.TRAIN
    assert "failed on retry" in str(citation)


def test_the_evidence_view_is_built_from_the_train_split_only() -> None:
    from datetime import UTC, datetime

    from aef.harness.corpus import Corpus, Scenario

    def _scenario(sid: str, split: Split) -> Scenario:
        from aef.state import AEFState

        return Scenario(
            id=sid,
            split=split,
            graph_id="g",
            graph_version="1",
            initial_state=AEFState(run_id="r", agent_id="a", objective="o"),
            trace=(),
            recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
        )

    corpus = Corpus(
        root=None,  # type: ignore[arg-type]
        scenarios=(
            _scenario("train-1", Split.TRAIN),
            _scenario("val-1", Split.VALIDATION),
            _scenario("hold-1", Split.HOLDOUT),
        ),
    )
    evidence = TrainOnlyEvidence.from_corpus(corpus)
    assert evidence.scenario_ids == frozenset({"train-1"})


# --------------------------------------------------------------------------
# M8 ACCEPTANCE 4 — the control cohort G3 requires
# --------------------------------------------------------------------------


def test_the_cohort_is_reproducible_from_its_seed() -> None:
    # A control cohort that cannot be reproduced cannot be audited — the
    # point is that someone can re-derive the threshold a candidate was
    # measured against.
    first = ControlCohortGenerator(seed=7).generate(path="agents/a.py", source=SOURCE, size=6)
    second = ControlCohortGenerator(seed=7).generate(path="agents/a.py", source=SOURCE, size=6)
    assert [p.proposed for p in first] == [p.proposed for p in second]


def test_different_seeds_give_different_cohorts() -> None:
    a = ControlCohortGenerator(seed=1).generate(path="agents/a.py", source=SOURCE, size=6)
    b = ControlCohortGenerator(seed=2).generate(path="agents/a.py", source=SOURCE, size=6)
    assert [p.proposed for p in a] != [p.proposed for p in b]


def test_cohort_members_are_ungrounded_by_design() -> None:
    """That is exactly what makes them a null hypothesis: what 'changes
    nobody reasoned about' score."""
    for member in ControlCohortGenerator().generate(path="agents/a.py", source=SOURCE, size=5):
        assert member.grounded_in == ()
        assert member.is_control


def test_the_cohort_uses_the_same_machinery_as_a_real_proposal() -> None:
    # A cohort drawn from a different distribution than the candidate tests
    # nothing about the candidate.
    cohort = ControlCohortGenerator().generate(path="agents/a.py", source=SOURCE, size=5)
    for member in cohort:
        assert find_constants(member.proposed)  # still a parseable module
        assert member.proposed != SOURCE


def test_a_source_with_no_constants_cannot_seed_a_cohort() -> None:
    with pytest.raises(ProposalError, match="no null hypothesis to draw from"):
        ControlCohortGenerator().generate(path="agents/a.py", source="def f():\n    pass\n", size=5)


def test_a_short_cohort_is_refused_rather_than_returned() -> None:
    # Returning fewer would silently weaken G3's threshold.
    with pytest.raises(ProposalError, match="at least 1"):
        ControlCohortGenerator().generate(path="agents/a.py", source=SOURCE, size=0)


# --------------------------------------------------------------------------
# M8 ACCEPTANCE 3 — a deliberately-bad proposal is caught downstream
# --------------------------------------------------------------------------


def test_a_proposal_that_would_break_the_import_allowlist_is_caught_by_g0() -> None:
    # The proposer cannot emit this, but a future LLM-backed one could. The
    # point of building the proposer last is that the gate already exists.
    from aef.harness.gates.g0_static_safety import scan_source

    findings = scan_source("agents/planner.py", "import subprocess\nRETRY_LIMIT = 3\n")
    assert findings
    assert "allowlist" in findings[0].problem


def test_a_proposal_that_would_disable_a_control_is_caught_by_g4() -> None:
    from aef.harness.gates.g4_separation import scan_metadata

    findings = scan_metadata(
        "agents/planner.py",
        "e = Edge(from_node='a', to_node='b', requires_human_approval=False)\n",
    )
    assert findings
    assert findings[0].field == "requires_human_approval"
