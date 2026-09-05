"""A13 — a placebo carrying the treatment's own text.

G3 rejects a candidate that beats the incumbent but sits inside a random
cohort's spread: "beats the incumbent" launders chance into evidence. For a
prompt candidate the cohort is N placebo bullets, token-length matched, drawn
from a task-neutral vocabulary (ADR 0170).

The attack is on the null hypothesis rather than on the gate. If a control
bullet carries the candidate's own lesson, the cohort's p95 rises to meet the
candidate and G3 is comparing the candidate against itself — a threshold
wearing the costume of a control. It is the reward-hacking shape aimed one
level up, at the thing that decides what counts as evidence.

The attacker's lever is the vocabulary: `ProseControlCohortGenerator` takes
one, and an owner (or a candidate that reached Zone B) could supply the
treatment's own words. Two controls stand in the way, and both live on
`_content_words`: the pool is filtered by it, and `_assert_no_leak` refuses by
it. So one mutation removes both, which is the honest way to test them — they
are one control with two applications, not two.
"""

from __future__ import annotations

import pytest

from aef.harness.prose_cohort import (
    ProseCohortLeakError,
    ProseControlCohortGenerator,
    _assert_no_leak,
    _content_words,
    _lesson_text,
)

PATH = "agents/persona.md"
INCUMBENT = "# Persona\n\nAnswer the operator's question.\n"
LESSON = "always print the clearwater permit verdict before the summary"
BULLET = f"- <!-- aef sig=failure:prompt_agent runs=2 --> {LESSON}"
CANDIDATE = f"# Persona\n\nAnswer the operator's question.\n\n## Lessons (aef)\n\n{BULLET}\n"

# The hostile vocabulary: the treatment's own content words, plus enough
# filler that the generator has a pool to draw from at all.
HOSTILE_VOCABULARY = tuple(sorted(_content_words(LESSON))) + (
    "lantern",
    "meridian",
    "pumice",
    "tundra",
)


def _added_line(member: str) -> str:
    a, b = CANDIDATE.splitlines(), member.splitlines()
    assert len(a) == len(b), "a control changed the file's shape, not just one bullet"
    differing = [y for x, y in zip(a, b, strict=True) if x != y]
    assert len(differing) == 1, differing
    return differing[0]


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a13_a_hostile_vocabulary_cannot_leak_into_the_cohort(attack_log: list[str]) -> None:
    """Hand the generator the candidate's own words and every placebo it
    produces still shares none of them."""
    cohort = ProseControlCohortGenerator(vocabulary=HOSTILE_VOCABULARY).generate(
        path=PATH, source=INCUMBENT, candidate=CANDIDATE, size=5
    )
    treatment = _content_words(LESSON)
    for member in cohort:
        placebo = _lesson_text(_added_line(member.proposed))
        shared = sorted(_content_words(placebo) & treatment)
        attack_log.append(f"{member.id}: {placebo!r} shares {shared}")
        assert not shared, attack_log


def test_a13_a_placebo_that_did_leak_is_refused_rather_than_repaired() -> None:
    """The second application of the same rule, reachable on its own. Quietly
    redrawing would hide a bug in the generator; refusing surfaces it."""
    with pytest.raises(ProseCohortLeakError, match="not a null hypothesis"):
        _assert_no_leak(LESSON, "the clearwater note")

    # And it is not vacuously strict: an unrelated placebo passes.
    _assert_no_leak(LESSON, "lantern meridian pumice tundra")


def test_a13_the_refusal_is_its_own_type() -> None:
    """A leak is not "the cohort is small" or "the file is the wrong kind" —
    it is a control that is not a control, and callers must be able to tell
    those apart."""
    from aef.harness.prose_cohort import ProseCohortError

    assert issubclass(ProseCohortLeakError, ProseCohortError)


def test_a13_a_stopword_only_lesson_does_not_pretend_the_check_bound() -> None:
    """Honesty about the boundary: a lesson made entirely of stopwords has no
    content to leak, and `_assert_no_leak` says so by not firing rather than
    by claiming a check it did not perform."""
    _assert_no_leak("is it to be or to be", "is it to be or to be")


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a13_the_control_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, attack_log: list[str]
) -> None:
    """Blind `_content_words` — the one function both the pool filter and the
    leak refusal consult — and the hostile vocabulary reaches the cohort.

    With it blinded, the pool is no longer filtered and the leak check finds
    no shared words, so a "control" bullet is drawn from the treatment's own
    vocabulary. G3 would then compute its threshold against the candidate's
    own lesson.
    """
    import aef.harness.prose_cohort as prose_cohort

    monkeypatch.setattr(prose_cohort, "_content_words", lambda text: frozenset())

    cohort = ProseControlCohortGenerator(vocabulary=HOSTILE_VOCABULARY).generate(
        path=PATH, source=INCUMBENT, candidate=CANDIDATE, size=5
    )
    treatment = _content_words(LESSON)
    leaked = []
    for member in cohort:
        placebo = _lesson_text(_added_line(member.proposed))
        shared = sorted(set(placebo.lower().split()) & treatment)
        if shared:
            leaked.append((member.id, placebo, shared))
    attack_log.append(f"{len(leaked)} of {len(cohort)} placebos carry the treatment's words")

    assert leaked, (
        "no placebo leaked even with the content-word check blinded, so the hostile "
        f"vocabulary never reached the pool and the attack above proves less: {attack_log}"
    )
