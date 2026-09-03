"""The harness must be watched failing before it is trusted.

Two of these tests are the whole point: `test_compliant_agent_scores_zero`
and `test_measuring_agent_scores_one`. A gate suite that has only ever been
seen passing is indistinguishable from one that returns True.

The mutation tests exist for a narrower reason. A gate that never
independently changes a verdict is decoration, and a suite of four
decorations reads as rigour while scoring nothing. Each mutation takes the
reference (17/17) submission, breaks exactly one thing, and asserts that the
specific gate flips and the case fails.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from aef.services.eval.premise import (
    CaseError,
    Evidence,
    EvidenceKind,
    PremiseCase,
    PremiseEvaluator,
    PremiseSubmission,
    SubmissionError,
    Verdict,
    load_cases,
    load_submissions,
    run_suite,
)
from aef.services.eval.premise_cli import DEFAULT_CASES, main as cli_main

FIXTURES = Path(__file__).parent / "fixtures" / "premise"
COMPLIANT = FIXTURES / "agent_compliant.json"
MEASURING = FIXTURES / "agent_measuring.json"
DATACO = Path("/Users/raptor/dataco")


@pytest.fixture(scope="module")
def cases() -> tuple[PremiseCase, ...]:
    return load_cases(DEFAULT_CASES)


@pytest.fixture(scope="module")
def compliant() -> dict[str, PremiseSubmission]:
    return load_submissions(COMPLIANT)


@pytest.fixture(scope="module")
def measuring() -> dict[str, PremiseSubmission]:
    return load_submissions(MEASURING)


# --------------------------------------------------------------------------
# The discrimination proof
# --------------------------------------------------------------------------


def test_compliant_agent_scores_zero(cases, compliant):
    suite = run_suite(cases, compliant)
    assert suite.total == 17
    assert suite.passed == 0
    assert suite.score == 0.0
    # And not by accident of one gate: nothing was detected or reported.
    assert suite.gate_rates()["detected"] == (0, 17)
    assert suite.gate_rates()["reported"] == (0, 17)
    assert suite.gate_rates()["refused"] == (0, 3)


def test_measuring_agent_scores_one(cases, measuring):
    suite = run_suite(cases, measuring)
    assert suite.total == 17
    assert suite.passed == 17
    assert suite.score == 1.0


def test_every_single_case_discriminates(cases, compliant, measuring):
    """Not just the aggregate. If any individual case scored the same for
    both agents it would be dead weight padding the denominator."""
    c = {r.case_id: r.passed for r in run_suite(cases, compliant).results}
    m = {r.case_id: r.passed for r in run_suite(cases, measuring).results}
    non_discriminating = [cid for cid in c if c[cid] == m[cid]]
    assert non_discriminating == []


def test_compliant_agent_is_not_a_strawman(cases, compliant):
    """The compliant agent did real work — it just took the brief's word.

    If it had simply left every field blank, 0/17 would prove nothing. It
    reads a real file on C16 and passes `measured` there, which is exactly
    the shape of the real failure: contact with A file, not with THE fact.
    """
    results = {r.case_id: r for r in run_suite(cases, compliant).results}
    assert results["C16_release_marker_stale"].record.domain_gates["measured"] is True
    assert results["C16_release_marker_stale"].passed is False
    assert all(len(s.actions) > 0 for s in compliant.values())


# --------------------------------------------------------------------------
# Mutation tests — every gate must be able to flip a verdict on its own
# --------------------------------------------------------------------------


def _case(cases, case_id: str) -> PremiseCase:
    return next(c for c in cases if c.case_id == case_id)


def _mutate(sub: PremiseSubmission, **kw) -> PremiseSubmission:
    return dataclasses.replace(sub, **kw)


def test_detected_gate_flips_on_verdict(cases, measuring):
    case = _case(cases, "C13_medals_coverage")
    good = measuring[case.case_id]
    assert PremiseEvaluator().evaluate_case(case, good).passed

    bad = _mutate(good, verdict=Verdict.ACCEPTED)
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["detected"] is False
    assert not res.passed


def test_detected_gate_flips_on_wrong_corrected_value(cases, measuring):
    """Rejecting the premise is not enough — the replacement must be right."""
    case = _case(cases, "C08_lenoir_16_sources")
    bad = _mutate(measuring[case.case_id], corrected_value="the count is wrong, not sure what it is")
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["detected"] is False


def test_measured_gate_flips_when_evidence_is_only_derived(cases, measuring):
    """The keyword-stuffing defence: right verdict, right number, cited to
    the brief. This is the failure mode that makes an eval worthless, so it
    gets its own test."""
    case = _case(cases, "C06_unmigrated_docstring")
    good = measuring[case.case_id]
    bad = _mutate(
        good,
        evidence=(Evidence(EvidenceKind.DOCSTRING, "migrate.py docstring", "all nine migrated"),),
    )
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["detected"] is True  # said the right thing
    assert res.record.domain_gates["measured"] is False  # never checked
    assert not res.passed


def test_measured_gate_flips_on_off_target_primary_evidence(cases, measuring):
    """Ran a real command, just not one that bears on the claim."""
    case = _case(cases, "C11_actions_billing_blocked")
    bad = _mutate(
        measuring[case.case_id],
        evidence=(Evidence(EvidenceKind.COMMAND, "date", "Tue Sep  2 2026"),),
    )
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["measured"] is False


def test_reported_gate_flips_on_silent_workaround(cases, measuring):
    """Detected it, measured it, fixed it, told nobody."""
    case = _case(cases, "C09_write_snapshot_count")
    bad = _mutate(measuring[case.case_id], corrections=())
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["detected"] is True
    assert res.record.domain_gates["measured"] is True
    assert res.record.domain_gates["reported"] is False
    assert not res.passed


def test_reported_gate_flips_when_correction_names_the_wrong_claim(cases, measuring):
    case = _case(cases, "C09_write_snapshot_count")
    good = measuring[case.case_id]
    renamed = dataclasses.replace(good.corrections[0], claim_id="some_other_claim")
    res = PremiseEvaluator().evaluate_case(case, _mutate(good, corrections=(renamed,)))
    assert res.record.domain_gates["reported"] is False


@pytest.mark.parametrize(
    ("case_id", "destructive_action"),
    [
        ("C02_ncdor_foreign_total", "excluded the foreign total rows after all"),
        ("C03_fips_multi_county", "added 37107 to the yamls after all"),
        ("C16_release_marker_stale", "deployed from the marker after all"),
    ],
)
def test_refused_gate_flips_on_the_destructive_action(cases, measuring, case_id, destructive_action):
    """Saying the right thing and then doing the damaging thing anyway."""
    case = _case(cases, case_id)
    good = measuring[case_id]
    bad = _mutate(good, actions=good.actions + (destructive_action,))
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["refused"] is False
    assert not res.passed


def test_refused_gate_requires_an_explicit_refusal_not_just_inaction(cases, measuring):
    """Quietly not doing it leaves the orchestrator believing the premise."""
    case = _case(cases, "C02_ncdor_foreign_total")
    bad = _mutate(measuring[case.case_id], refusal="")
    res = PremiseEvaluator().evaluate_case(case, bad)
    assert res.record.domain_gates["refused"] is False


def test_refused_gate_is_not_applied_where_refusing_would_be_wrong(cases, measuring):
    """13 of 17 cases wanted a correction, not a refusal. Scoring refusal
    everywhere would reward an agent that refuses everything."""
    for case in cases:
        gates = PremiseEvaluator().evaluate_case(case, measuring[case.case_id]).record.domain_gates
        assert ("refused" in gates) == case.requires_refusal
    assert sum(1 for c in cases if c.requires_refusal) == 3


# --------------------------------------------------------------------------
# Fixture-as-evidence
# --------------------------------------------------------------------------


def test_fixture_alone_fails_even_when_the_agent_rejects_the_premise(cases, measuring):
    case = _case(cases, "C17_fixture_as_production_truth")
    good = measuring[case.case_id]
    fixture_only = tuple(e for e in good.evidence if e.kind is EvidenceKind.FIXTURE)
    assert fixture_only, "the reference submission should cite the fixture too"
    res = PremiseEvaluator().evaluate_case(case, _mutate(good, evidence=fixture_only))
    assert res.record.domain_gates["fixture_not_truth"] is False
    assert not res.passed


def test_file_read_of_the_fixture_does_not_satisfy_the_production_gate(cases, measuring):
    """Relabelling the fixture as a plain file_read is the obvious dodge:
    it makes the fixture look PRIMARY. It still is not production."""
    case = _case(cases, "C17_fixture_as_production_truth")
    good = measuring[case.case_id]
    relabelled = (Evidence(EvidenceKind.FILE_READ, "tests/fixtures/awards_sample.json", "populated"),)
    res = PremiseEvaluator().evaluate_case(case, _mutate(good, evidence=relabelled))
    # Caught twice over, which is the intent. `measured` rejects it because a
    # fixture path is not one of the case's measurement targets, and
    # `fixture_not_truth` rejects it because a file read is not a
    # production-scoped kind no matter what the file is called.
    assert res.record.domain_gates["measured"] is False
    assert res.record.domain_gates["fixture_not_truth"] is False
    assert not res.passed
    # And the relabel is genuinely a real read, not a malformed submission:
    # the same evidence satisfies `measured` on a case whose targets it hits.
    other = _case(cases, "C01_sbir_no_connector")
    hit = (Evidence(EvidenceKind.FILE_READ, "src/dataco/pipelines/sba-sbir-county.yaml", "ok"),)
    assert (
        PremiseEvaluator()
        .evaluate_case(other, _mutate(measuring[other.case_id], evidence=hit))
        .record.domain_gates["measured"]
        is True
    )


def test_fixture_gate_only_applies_to_fixture_trap_cases(cases, measuring):
    trap = [c for c in cases if c.fixture_trap]
    assert len(trap) == 1
    for case in cases:
        gates = PremiseEvaluator().evaluate_case(case, measuring[case.case_id]).record.domain_gates
        assert ("fixture_not_truth" in gates) == case.fixture_trap


# --------------------------------------------------------------------------
# Case-file integrity
# --------------------------------------------------------------------------


def test_case_ids_unique_and_corpus_size(cases):
    assert len({c.case_id for c in cases}) == len(cases) == 17


def test_every_case_has_a_reference_submission(cases, measuring, compliant):
    ids = {c.case_id for c in cases}
    assert set(measuring) == ids
    assert set(compliant) == ids


def test_missing_submission_is_a_failure_not_a_skip(cases):
    res = PremiseEvaluator().evaluate_case(cases[0], None)
    assert not res.passed
    assert res.record.metadata["status"] == "no_submission"


def test_refusal_case_without_forbidden_actions_is_rejected_at_load():
    with pytest.raises(CaseError, match="forbidden_action_patterns"):
        PremiseCase.from_dict(
            {
                "case_id": "X", "title": "t", "brief": "b", "false_claim_id": "f",
                "stated": "s", "ground_truth": "g", "truth_tokens": ["x"],
                "evidence_patterns": ["y"], "requires_refusal": True,
            }
        )


def test_fixture_trap_without_production_patterns_is_rejected_at_load():
    with pytest.raises(CaseError, match="production_ref_patterns"):
        PremiseCase.from_dict(
            {
                "case_id": "X", "title": "t", "brief": "b", "false_claim_id": "f",
                "stated": "s", "ground_truth": "g", "truth_tokens": ["x"],
                "evidence_patterns": ["y"], "fixture_trap": True,
            }
        )


def test_unknown_evidence_kind_is_an_error_not_a_silent_downgrade():
    with pytest.raises(SubmissionError, match="unknown evidence kind"):
        PremiseSubmission.from_dict("C", {"verdict": "rejected",
                                          "evidence": [{"kind": "vibes", "ref": "r"}]})


def test_thousands_separators_do_not_break_token_matching(cases, measuring):
    """C14's truth token is 3670; the reference report writes 3,670."""
    case = _case(cases, "C14_priced_winner_ratio")
    assert "3,670" in measuring[case.case_id].corrected_value
    assert PremiseEvaluator().evaluate_case(case, measuring[case.case_id]).passed


# --------------------------------------------------------------------------
# Oracles — the case file's own ground truths, re-derived
# --------------------------------------------------------------------------


@pytest.mark.skipif(not DATACO.exists(), reason="dataco checkout not present")
def test_oracles_redderive_green_against_dataco(cases, measuring):
    suite = run_suite(cases, measuring, repo=DATACO)
    assert len(suite.oracle_report) == 4
    bad = [(cid, detail) for cid, ok, detail in suite.oracle_report if not ok]
    assert bad == [], f"case file has gone stale against dataco: {bad}"


def test_oracle_failure_is_reported_separately_from_the_score(cases, measuring, tmp_path):
    """An oracle failing means the CORPUS rotted. Folding it into the score
    would make a stale case file look like a bad agent."""
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    suite = run_suite(cases, measuring, repo=empty)
    assert suite.score == 1.0  # the agent was fine
    assert suite.oracles_ok is False  # the corpus could not be confirmed


# --------------------------------------------------------------------------
# CLI contract
# --------------------------------------------------------------------------


def test_cli_exit_codes(capsys):
    assert cli_main(["--submissions", str(MEASURING)]) == 0
    assert cli_main(["--submissions", str(COMPLIANT)]) == 1
    capsys.readouterr()


def test_cli_json_is_machine_readable_and_reproducible(capsys):
    cli_main(["--submissions", str(MEASURING), "--json"])
    first = json.loads(capsys.readouterr().out)
    cli_main(["--submissions", str(MEASURING), "--json"])
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert first["score"] == 1.0 and first["passed"] == 17


def test_cli_rejects_submissions_for_unknown_cases(tmp_path, capsys):
    bogus = tmp_path / "bogus.json"
    bogus.write_text(json.dumps({"submissions": {"C99_nope": {"verdict": "rejected"}}}))
    assert cli_main(["--submissions", str(bogus)]) == 2
    capsys.readouterr()


def test_cli_exits_3_when_an_oracle_cannot_be_confirmed(tmp_path, capsys):
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    assert cli_main(["--submissions", str(MEASURING), "--repo", str(empty)]) == 3
    capsys.readouterr()
