"""The corpus must keep MORE THAN ONE recurring failure family (ADR 0201).

`tests/harness/test_corpus_negatives.py` asserts the corpus still has
negatives at all — the property ADR 0159 found had been widened away. This
file asserts the property one level up, and it is a different one: that the
negatives fall into **more than one recurring family**.

Why that is worth a test rather than a sentence. `RuleBasedConsolidator` keys
a check-derived failure on the joined `check:<path>:<op>` of every check that
failed and promotes a signature to knowledge once it has recurred in **two
distinct runs** (ADR 0110). For four ADRs every recorded failure in this
corpus carried one key, `check:working_memory.summary:max_words`, so the store
held exactly one entry — and ADR 0193 had to close by saying so:

    This corpus cannot produce a second knowledge entry, and three ADRs have
    now measured the knowledge layer on a store holding exactly one.
    Everything about ranking BETWEEN entries — the boost's real risk — is
    unmeasurable here.

ADR 0201 fixed that with fourteen recordings carrying one new owner rule, and
measured what could not be measured before. **A corpus that drifts back to one
family silently un-measures it**, and the drift needs no bad intent: deleting
a scenario, widening the new rule until it always passes, or re-recording the
summary agent onto a model that happens to carry attributions would each do
it, and each looks like tidying in a diff.

These assertions read the RECORDED answers and the owner's own checks. They
execute no graph and call no model, so they are as cheap as the corpus files
and cannot go stale against a cassette.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from aef.harness.check_memory import check_key
from aef.harness.checks import evaluate_checks
from aef.harness.corpus import Scenario, Split, load_corpus
from aef.services.knowledge.consolidate import DEFAULT_MIN_OCCURRENCES
from aef.state import AEFState

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_GRAPH_ID = "summary_agent"

# The one family that existed before ADR 0201, spelled out so a test that
# passes because everything collapsed back onto it cannot look like a pass.
WORD_CAP = "check:working_memory.summary:max_words"


def _final_state(scenario: Scenario) -> AEFState:
    last = scenario.trace[-1]
    return last.delta.apply(last.input_state)


def _signatures(split: Split) -> dict[str, list[str]]:
    """signature -> the scenario ids whose recorded answer produced it.

    The signature is built the way `consolidate.default_signature` builds it
    from a `check_memory` record: the failed checks' keys, de-duplicated,
    joined with ">" in the owner's declared order. It is derived here rather
    than imported so that a change to either side is a visible disagreement.
    """
    corpus = load_corpus(REPO_ROOT / "corpus")
    out: dict[str, list[str]] = defaultdict(list)
    for scenario in corpus.scenarios:
        if scenario.graph_id != SUMMARY_GRAPH_ID or not scenario.checks:
            continue
        if scenario.split is not split:
            continue
        report = evaluate_checks(scenario.checks, _final_state(scenario))
        keys: list[str] = []
        for check in report.failed:
            key = check_key(check)
            if key not in keys:
                keys.append(key)
        if keys:
            out[">".join(keys)].append(scenario.id)
    return dict(out)


def _recurring(split: Split) -> dict[str, list[str]]:
    """The signatures that clear ADR 0110's two-distinct-runs threshold."""
    return {
        signature: ids
        for signature, ids in _signatures(split).items()
        if len(set(ids)) >= DEFAULT_MIN_OCCURRENCES
    }


def test_the_train_split_consolidates_more_than_one_lesson() -> None:
    recurring = _recurring(Split.TRAIN)
    assert len(recurring) >= 2, (
        f"the train split produces {len(recurring)} recurring failure signature(s): "
        f"{ {k: sorted(v) for k, v in recurring.items()} }. With one, the knowledge "
        f"store holds one entry and nothing about ranking BETWEEN lessons can be "
        f"measured — the state ADR 0193 was stuck in and ADR 0201 got out of."
    )


def test_more_than_one_of_them_is_not_the_word_cap() -> None:
    """Two signatures that are both the word cap under different spellings
    would satisfy the count above and none of its purpose."""
    recurring = _recurring(Split.TRAIN)
    assert WORD_CAP in recurring, (
        f"the word-cap family is gone from train: {sorted(recurring)}. It is the "
        f"family every knowledge measurement before ADR 0201 was made on."
    )
    others = {s for s in recurring if s != WORD_CAP}
    assert others, "the word cap is once again the only recurring failure family"
    assert any(WORD_CAP not in s for s in others), (
        f"every other recurring signature still contains the word cap: {sorted(others)}. "
        f"A second family that is the first family plus something is not a second "
        f"family for the purpose of ADR 0201's measurement."
    )


def test_the_scored_split_carries_a_negative_that_is_not_a_word_cap_overrun() -> None:
    """A second lesson with nothing in the scored split to act on is a lesson
    whose usefulness cannot be measured. ADR 0201's arms are scored on
    validation, and two of its ten negatives are of the new family."""
    failures = _signatures(Split.VALIDATION)
    non_cap = {signature: ids for signature, ids in failures.items() if WORD_CAP not in signature}
    assert non_cap, (
        f"every validation negative is a word-cap overrun again: {sorted(failures)}. "
        f"ADR 0201's arms measure whether a second lesson helps; on this split they "
        f"would measure nothing."
    )
