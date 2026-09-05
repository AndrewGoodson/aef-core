"""Which model answered, per scenario — asserted, not assumed.

ADR 0162 found the defect this file exists to make impossible: twenty of the
corpus's summary scenarios were recorded on `claude-fable-5-1` and **nothing
anywhere said so**. `corpus/README.md` did not name a model, ADR 0123 did not
name one, and ADR 0171's "model, everywhere in this document:
`claude-opus-5[1m]`" was true of its own nineteen recordings and read, in a
document about that corpus, as though it were true of all of them. S6's
`load_pairs` refused the mixed pairs; nothing else could tell.

A mixed-model corpus is not wrong in itself. It is wrong *silently*: every
measurement that treats a split as one model's output — a self-preference
control, a judge A/B, any writer-vs-judge comparison — is off by however many
scenarios came from the other model, and the number is invisible at the call
site. ADR 0186 re-recorded the eighteen train/validation Fable scenarios on
`claude-opus-5[1m]` and left the two holdout ones alone, because writing to
the holdout is the owner's act (`--i-am-spending-the-holdout`) and not a
worker's.

So: one family across the corpus, with the exceptions named here in full. A
recording on a third model, or a silent re-recording of the holdout, turns
this red — which is the entire point. The exception list is data an owner
edits deliberately, never a wildcard.
"""

from __future__ import annotations

import re
from pathlib import Path

from aef.harness.corpus import Split, load_corpus

REPO_ROOT = Path(__file__).resolve().parents[2]

# The model every re-recordable summary scenario was recorded on (ADR 0171 for
# sum-21..sum-39, ADR 0186 for sum-01..sum-18). Compared as a FAMILY, because
# the harness reports two spellings of one model — `claude-opus-5[1m]` and
# `claude-opus-5` (ADR 0169) — and a provenance guard defeated by a
# context-window suffix is not a guard (ADR 0162's M3 makes the same point
# about `PairwiseRanker`).
CORPUS_MODEL_FAMILY = "claude-opus-5"

# The scenarios NOT on that model, each with the reason it stayed. ADR 0186
# re-recorded every other Fable recording; these two are in the holdout, whose
# whole purpose is to be the owner's one independent read, and `record_run`
# refuses to write there without `allow_holdout=True`. Spending it is an owner
# decision, so they are declared rather than quietly converted.
KNOWN_OTHER_MODEL = {
    "sum-19-tram-depot": "claude-fable-5-1",
    "sum-20-seed-bank": "claude-fable-5-1",
}

SUMMARY_GRAPH_ID = "summary_agent"


def _family(model: str) -> str:
    """`claude-opus-5[1m]` and `claude-opus-5` are one model (ADR 0169)."""
    return re.sub(r"\[[^\]]*\]$", "", model)


def _answering_models() -> dict[str, set[str]]:
    """Scenario id -> the models its cassette says answered it."""
    corpus = load_corpus(REPO_ROOT / "corpus")
    return {
        s.id: {call.result.model for call in s.model_calls}
        for s in corpus.scenarios
        if s.model_calls
    }


def test_every_recording_names_one_model_family_or_is_a_declared_exception() -> None:
    off_family = {
        sid: sorted(models)
        for sid, models in _answering_models().items()
        if any(_family(m) != CORPUS_MODEL_FAMILY for m in models)
    }
    assert set(off_family) == set(KNOWN_OTHER_MODEL), (
        f"the corpus's answering models changed. Off-family now: {off_family}; "
        f"declared: {KNOWN_OTHER_MODEL}. A corpus that silently mixes models makes "
        f"every writer-vs-judge measurement wrong by an invisible fraction (ADR "
        f"0162's defect 1, ADR 0186's fix). If this is deliberate, say so here."
    )
    for sid, expected in KNOWN_OTHER_MODEL.items():
        assert off_family[sid] == [expected], f"{sid}: expected {expected}, got {off_family[sid]}"


def test_the_declared_exceptions_are_holdout_only() -> None:
    """The reason the two exceptions exist is that they are the holdout, and
    the recorder refuses to write there without explicit consent. If one ever
    turns up in train or validation, the reason has evaporated and the
    exception must go rather than be inherited."""
    corpus = load_corpus(REPO_ROOT / "corpus")
    by_id = {s.id: s for s in corpus.scenarios}
    for sid in KNOWN_OTHER_MODEL:
        assert by_id[sid].split is Split.HOLDOUT, (
            f"{sid} is {by_id[sid].split.value}, not holdout — it is re-recordable, so "
            f"it should have been re-recorded rather than excepted (ADR 0186)."
        )


def test_every_gated_summary_scenario_is_on_the_corpus_model() -> None:
    """The splits a gate or a judge actually reads carry NO exceptions.

    Stated separately from the test above because it is the property that
    matters at a measurement call site: whoever selects train or validation
    and treats it as one model's output is right, without having to consult a
    list of exceptions.
    """
    corpus = load_corpus(REPO_ROOT / "corpus")
    wrong = {
        s.id: sorted({c.result.model for c in s.model_calls})
        for s in corpus.scenarios
        if s.graph_id == SUMMARY_GRAPH_ID
        and s.model_calls
        and s.split in (Split.TRAIN, Split.VALIDATION)
        and any(_family(c.result.model) != CORPUS_MODEL_FAMILY for c in s.model_calls)
    }
    assert not wrong, (
        f"train/validation scenarios recorded on another model: {wrong}. S6's rig A had "
        f"to drop 6 of 17 validation states for exactly this (ADR 0162, amendment 1)."
    )


def test_the_re_recorded_scenarios_kept_the_owner_checks_they_had() -> None:
    """ADR 0186 re-recorded the ANSWER and nothing else.

    The Fable recordings are kept whole under `docs/research/i14/fable-recordings/`,
    so the claim is checkable rather than asserted: every owner field — the
    checks, the initial state, the split, the `expected` label — must still
    match the recording it replaced, and so must the cassette KEY, which is a
    hash of the request. A moved key would mean the prompt changed, and then
    the before/after in ADR 0186 would be comparing two different questions.
    """
    archive = REPO_ROOT / "docs/research/i14/fable-recordings"
    assert archive.is_dir(), "the historical Fable recordings are missing"
    corpus = load_corpus(REPO_ROOT / "corpus")
    by_id = {s.id: s for s in corpus.scenarios}
    # `load_scenario` refuses a file whose parent directory does not name its
    # split — the guard against a holdout scenario being moved into train — so
    # the archive, which is deliberately outside `corpus/`, is read through the
    # payload codec instead. Same decode, no directory claim.
    from aef.harness.corpus import Scenario
    from aef.harness.trace_codec import loads

    seen = 0
    for path in sorted(archive.glob("*.json")):
        old = Scenario.from_payload(loads(path.read_text()))
        new = by_id[old.id]
        assert new.checks == old.checks, f"{old.id}: owner checks moved"
        assert new.initial_state == old.initial_state, f"{old.id}: initial state moved"
        assert new.split is old.split, f"{old.id}: split moved"
        assert new.expected is old.expected, f"{old.id}: expected label moved"
        assert new.budget_ms == old.budget_ms, f"{old.id}: budget moved"
        assert [c.key for c in new.model_calls] == [c.key for c in old.model_calls], (
            f"{old.id}: the cassette key moved, so the prompt changed — the "
            f"before/after would not be the same question"
        )
        seen += 1
    assert seen == 18, f"expected 18 archived Fable recordings, found {seen}"
