"""The I14b hard set's fairness properties, as a tripwire (ADR 0202).

ADR 0171 took a rubric point on an AUC of 1.000 whose negatives were all word-
cap overruns — a failure family `len(summary.split()) > cap` detects without a
judge. ADR 0202's hard set exists to remove that shortcut, and the properties
that make it a fair test are exactly the ones a later edit could quietly undo:

* every case within its own cap, so a word counter scores chance;
* the pass/fail split balanced, so "answer pass to everything" scores chance;
* the positives byte-identical to the agent's own recorded summaries, so a
  positive cannot be quietly rewritten into something easier;
* each negative differing from its positive by exactly ONE declared span, so
  "one minimal edit" stays true;
* the committed `hardset.json` equal to what the builder produces from the
  corpus, so the file cannot drift away from the scenarios it was derived from.

These assert the SET, not the judge's scores. The scores are in
`docs/research/i14b/grades.jsonl` and are re-derived by
`docs/research/measure.py` (`make measure-ci`), which is where a claim about
the judge belongs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "docs" / "research" / "i14b" / "run_i14b.py"
HARDSET = REPO_ROOT / "docs" / "research" / "i14b" / "hardset.json"


def _runner():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("aef_i14b", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["aef_i14b"] = module
    spec.loader.exec_module(module)
    return module


i14b = _runner()
CASES = json.loads(HARDSET.read_text())


def test_the_committed_hard_set_is_what_the_builder_derives_from_the_corpus() -> None:
    """The file and the corpus cannot drift apart.

    `build()` reads the scenarios and applies the declared edits; the committed
    JSON is its output. If a cassette is re-recorded, or an edit's span is
    changed, this goes red before any number computed from the old file is
    quoted again.
    """
    assert i14b.build() == CASES


def test_every_case_is_within_its_word_cap() -> None:
    """The control that makes it a fair test.

    If one case went over its cap, a word counter would separate the classes
    and the set would be ADR 0171's again — a judge could score well by
    counting.
    """
    over = [c["case_id"] for c in CASES if c["words"] > c["cap"]]
    assert over == [], f"{over} exceed their cap; a word counter would discriminate"


def test_the_trivial_baselines_all_score_exactly_chance() -> None:
    n = len(CASES)
    pass_all = sum(1 for c in CASES if c["owner_pass"])
    word_count = sum(1 for c in CASES if (c["words"] <= c["cap"]) == bool(c["owner_pass"]))
    assert pass_all * 2 == n, "the set is not balanced; 'pass everything' would beat chance"
    assert word_count * 2 == n, "a word-count-only judge does better than chance on this set"


def test_each_pair_is_one_minimal_edit_of_the_agents_own_recorded_summary() -> None:
    by_scenario: dict[str, dict[str, dict[str, object]]] = {}
    for case in CASES:
        by_scenario.setdefault(str(case["scenario_id"]), {})[str(case["variant"])] = case
    assert len(by_scenario) == len(i14b.EDITS)
    for edit in i14b.EDITS:
        pair = by_scenario[edit.scenario_id]
        correct = str(pair["correct"]["summary"])
        corrupt = str(pair["corrupt"]["summary"])
        # The positive is the cassette's own text, untouched.
        scenario = i14b.load_scenario(i14b._scenario_path(edit.scenario_id))
        recorded = str(i14b._reflect_state(scenario).working_memory["summary"])
        assert correct == recorded, f"{edit.scenario_id}: the positive is not the recorded summary"
        # The negative differs by exactly the declared span, once.
        assert correct.count(edit.old) == 1
        assert correct.replace(edit.old, edit.new) == corrupt
        assert correct != corrupt


def test_every_label_carries_a_disputable_sentence() -> None:
    """A label with no stated reason is an opinion nobody can argue with."""
    for case in CASES:
        reason = str(case["owner_reason"])
        assert len(reason.split()) >= 12, case["case_id"]
        assert reason.strip().endswith("."), case["case_id"]


def test_the_six_families_are_distinct_and_none_is_a_word_cap_overrun() -> None:
    families = [e.family for e in i14b.EDITS]
    assert len(set(families)) == len(families) == 6
    assert not any("word" in f or "cap" in f or "length" in f for f in families)


@pytest.mark.parametrize("case", CASES, ids=[str(c["case_id"]) for c in CASES])
def test_the_inherited_check_verdict_is_recomputed_not_remembered(
    case: dict[str, object],
) -> None:
    """The check baseline in the report is evaluated, not asserted.

    It is the baseline the judge is compared against, and on this set it is the
    strongest of the non-model ones — so it has to be recomputed from the
    corpus's own `TaskCheck`s rather than copied forward.
    """
    scenario = i14b.load_scenario(i14b._scenario_path(str(case["scenario_id"])))
    state = i14b._with_summary(i14b._final_state(scenario), str(case["summary"]))
    report = i14b.evaluate_checks(scenario.checks, state)
    assert report.passed == case["inherited_checks_passed"]
    assert report.total == case["inherited_checks_total"]
    assert (report.passed == report.total) == case["inherited_pass"]
