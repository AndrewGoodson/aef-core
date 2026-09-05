"""The corpus must keep true content negatives, and must not re-acquire fake ones.

ADR 0159 measured that the summary corpus's only three negatives were
check-authoring defects — a required term capitalised at the start of a
sentence meeting a case-sensitive `contains` — and that correcting them left
the corpus **18/18 pass with no negatives at all**, which is a corpus that
cannot grade a judge, a proposer, or anything else. ADR 0171 corrected the
three defects and then recorded scenarios whose answers genuinely fail an
owner check.

Both halves need a tripwire, because both can be undone by an edit that looks
like tidying:

1. **The negatives can vanish.** Widening a check until everything passes is
   indistinguishable, in a diff, from fixing a check that was too narrow — and
   ADR 0171 did the second thing three times, deliberately. What separates them
   is the count afterwards, so the count is asserted here.
2. **The fake negatives can come back.** A `contains` check whose value is a
   term the model must mention will fail the moment the model starts the
   sentence with it. That is a defect the corpus has already had once.

Neither assertion is about how well the agent does. They are about whether the
corpus can still tell the difference between an agent that does well and one
that does not.
"""

from __future__ import annotations

from pathlib import Path

from aef.harness.checks import evaluate_checks
from aef.harness.corpus import Scenario, Split, load_corpus
from aef.state import AEFState

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_GRAPH_ID = "summary_agent"

# The floor, not the count. ADR 0171 recorded 7 (3 train, 4 validation); a
# later increment may add more, and only a DROP is a regression.
MIN_NEGATIVES = 6
MIN_VALIDATION_NEGATIVES = 2


def _final_state(scenario: Scenario) -> AEFState:
    last = scenario.trace[-1]
    return last.delta.apply(last.input_state)


def _negatives(split: Split | None = None) -> list[str]:
    """Scenario ids whose RECORDED answer fails at least one owner check."""
    corpus = load_corpus(REPO_ROOT / "corpus")
    out: list[str] = []
    for scenario in corpus.scenarios:
        if scenario.graph_id != SUMMARY_GRAPH_ID or not scenario.checks:
            continue
        if split is not None and scenario.split is not split:
            continue
        report = evaluate_checks(scenario.checks, _final_state(scenario))
        if report.passed < report.total:
            out.append(scenario.id)
    return sorted(out)


def test_the_corpus_has_scenarios_whose_recorded_answer_fails_an_owner_check() -> None:
    negatives = _negatives()
    assert len(negatives) >= MIN_NEGATIVES, (
        f"only {len(negatives)} summary scenario(s) fail an owner check: {negatives}. "
        f"A corpus with no negatives scores a constant judge exactly as well as a good "
        f"one (ADR 0159's finding, ADR 0171's fix) — do not widen checks until the "
        f"failures go away."
    )


def test_the_negatives_are_not_all_in_the_split_nobody_gates_on() -> None:
    # The judge A/B and every live claim in ADR 0171 are measured on validation.
    # Negatives that live only in train would leave that measurement with one
    # class, and an AUC needs two.
    negatives = _negatives(Split.VALIDATION)
    assert len(negatives) >= MIN_VALIDATION_NEGATIVES, (
        f"only {len(negatives)} validation scenario(s) fail an owner check: {negatives}"
    )


def test_no_summary_check_is_a_case_sensitive_contains_on_the_summary() -> None:
    """The defect ADR 0159 found, asserted away rather than remembered.

    `contains` is case-sensitive, so `contains 'swimming'` fails on a summary
    that opens "Swimming will be permitted…" — a check defect that reads as a
    content failure and cost this programme two ADRs to identify. On
    `working_memory.summary`, the term checks must be case-insensitive, which
    with this op set means `regex` with an inline `(?i)`.
    """
    corpus = load_corpus(REPO_ROOT / "corpus")
    offenders = [
        (s.id, c.value)
        for s in corpus.scenarios
        if s.graph_id == SUMMARY_GRAPH_ID
        for c in s.checks
        if c.op == "contains" and c.path == "working_memory.summary"
    ]
    assert not offenders, (
        f"case-sensitive `contains` on a summary: {offenders}. Use "
        f'{{"op": "regex", "value": "(?i)<term>"}} — see ADR 0159/0171.'
    )


def test_every_summary_scenario_states_its_word_cap_as_max_words() -> None:
    """ADR 0166's migration, pinned in both directions.

    A word cap written as a regex is how the scorer came to hang (`{1,N}` with a
    nullable separator); `max_words` alone accepts an empty summary, which is
    the signal ADR 0156 used to tell a failed provider call from a wrong answer.
    So every summary scenario carries BOTH ops, and its cap agrees with the cap
    the run was actually given.
    """
    corpus = load_corpus(REPO_ROOT / "corpus")
    for scenario in corpus.scenarios:
        if scenario.graph_id != SUMMARY_GRAPH_ID:
            continue
        ops = {c.op: c for c in scenario.checks if c.path == "working_memory.summary"}
        assert "max_words" in ops, f"{scenario.id} declares no max_words check"
        assert "min_words" in ops, f"{scenario.id} declares no min_words check"
        assert ops["min_words"].value == 1, scenario.id
        assert ops["max_words"].value == scenario.initial_state.working_memory["max_words"], (
            f"{scenario.id}: the max_words check disagrees with the cap the run was given"
        )
