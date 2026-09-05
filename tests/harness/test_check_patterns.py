"""The word cap that hung the scorer, and the ops that replace it (ADR 0166).

The reproduce-first case is the first test, and it is a **timing** test
because that is the only shape the defect has: every summary scenario in
`corpus/` declared its word cap as `^(?:\\s*\\S+){1,N}\\s*$`, which matches in
0.05 ms and, on a string one word over the cap, backtracks over every
partition of the input and does not return. Every recorded cassette sits at or
under its cap, so no green test in this repo ever reached the failing branch
and every live gate pass could (ADR 0156 §D2).

The regression tests are therefore in three layers: the pattern is refused
before it can run, `max_words` says the same thing without a regex, and the
corpus is asserted to carry no pattern the detector rejects.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import re
import time
from pathlib import Path

import pytest

from aef.harness.checks import (
    OPS,
    CatastrophicPatternError,
    CheckError,
    TaskCheck,
    _holds,
    evaluate_checks,
    refuse_catastrophic_regex,
)
from aef.harness.corpus import CorpusError, load_corpus, load_scenario
from aef.state import AEFState

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "corpus"

# The exact pattern every summary scenario carried, and the exact input that
# hangs it: one word over the cap.
PATHOLOGICAL = r"^(?:\s*\S+){1,35}\s*$"
LINEAR = r"^\s*\S+(?:\s+\S+){0,34}\s*$"
AT_CAP = " ".join(f"word{i:02d}" for i in range(35))
OVER_CAP = " ".join(f"word{i:02d}" for i in range(36))


def _search(pattern: str, text: str, q) -> None:  # type: ignore[no-untyped-def]
    q.put(re.search(pattern, text) is not None)


def _terminates(pattern: str, text: str, wall: float) -> bool:
    """Run `re.search` in a CHILD process under a wall clock. The parent
    cannot time this in-process: `re` has no timeout, releases nothing, and
    the whole point is that the call never comes back."""
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_search, args=(pattern, text, q))
    proc.start()
    proc.join(wall)
    if proc.is_alive():
        proc.kill()
        proc.join()
        return False
    return True


# ---------------------------------------------------------------------------
# The defect, reproduced
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_the_corpus_word_cap_does_not_terminate_on_a_non_match() -> None:
    """One word over the cap is the difference between 0.05 ms and never — and
    it is the only input the check exists to catch."""
    started = time.perf_counter()
    assert _terminates(PATHOLOGICAL, AT_CAP, wall=3.0), "a MATCH is fast; that is the trap"
    assert (time.perf_counter() - started) < 3.0
    assert not _terminates(PATHOLOGICAL, OVER_CAP, wall=3.0)


def test_the_linear_rewrite_decides_the_same_input_immediately() -> None:
    assert _terminates(LINEAR, AT_CAP, wall=5.0)
    assert _terminates(LINEAR, OVER_CAP, wall=5.0)
    assert re.search(LINEAR, AT_CAP) is not None
    assert re.search(LINEAR, OVER_CAP) is None


# ---------------------------------------------------------------------------
# The detector, verified against a planted fault before it is trusted
# ---------------------------------------------------------------------------

MUST_REFUSE = [
    PATHOLOGICAL,
    r"^(?:\s*\S+){1,30}\s*$",
    r"^(?:\s*\S+){1,40}\s*$",
    r"(a+)+",
    r"(a*)*",
    r"(a+)*",
    r"^(\S+)+$",
    r"(?:x?y){2,}",
    r"((?:ab)+)+",
    r"(?:a|b*){2,}",
]

MUST_PASS = [
    r"^\S+$",
    r"(?:foo|bar){1,3}",
    r"\bword\b",
    LINEAR,
    r"^\s*\S+(?:\s+\S+){0,29}\s*$",
    r"^\s*\S+(?:\s+\S+){0,39}\s*$",
    r"lesson",
    r"[()]+",  # a class containing parens, not a group
    r"\(\d+\)",  # escaped parens
    r"(?:\d{2,4})",  # a group carrying no repetition
    r"^a{2,3}$",
]


@pytest.mark.parametrize("pattern", MUST_REFUSE)
def test_the_detector_refuses_every_exponential_pattern(pattern: str) -> None:
    with pytest.raises(CatastrophicPatternError):
        refuse_catastrophic_regex(pattern)


@pytest.mark.parametrize("pattern", MUST_PASS)
def test_the_detector_passes_every_innocent_pattern(pattern: str) -> None:
    """The control. A scanner that refuses everything is not a scanner, and
    the linear rewrite the error message offers must itself be accepted or the
    advice is a dead end."""
    refuse_catastrophic_regex(pattern)


def test_the_refusal_names_the_op_that_replaces_it() -> None:
    with pytest.raises(CatastrophicPatternError) as excinfo:
        TaskCheck(path="working_memory.summary", op="regex", value=PATHOLOGICAL)
    message = str(excinfo.value)
    assert "max_words" in message
    assert r"^\s*\S+(?:\s+\S+){0,N-1}\s*$" in message


def test_the_pattern_is_refused_at_load_not_at_score_time() -> None:
    """A corpus with this check must fail before any scenario runs — scoring
    everything 0 because one file hangs is not a report."""
    with pytest.raises(CheckError):
        TaskCheck.from_payload(
            {"path": "working_memory.summary", "op": "regex", "value": PATHOLOGICAL}
        )


def _holds_in_child(pattern: str, text: str, q) -> None:  # type: ignore[no-untyped-def]
    check = TaskCheck(path="working_memory.summary", op="regex", value=LINEAR)
    object.__setattr__(check, "value", pattern)  # a validated check, then edited
    try:
        q.put(("held", _holds(check, text)))
    except CatastrophicPatternError:
        q.put(("refused", None))


def _holds_outcome(pattern: str, text: str, wall: float) -> tuple[str, object]:
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_holds_in_child, args=(pattern, text, q))
    proc.start()
    proc.join(wall)
    if proc.is_alive():
        proc.kill()
        proc.join()
        return ("hung", None)
    outcome: tuple[str, object] = q.get()
    return outcome


def test_holds_refuses_it_too_even_when_validation_was_bypassed() -> None:
    """Defence in depth. `__post_init__` is the gate, but `_holds` is where a
    pattern actually meets an input, and a frozen dataclass can still be edited
    around it.

    Asserted in a CHILD process under a wall clock, and that is not
    ceremony: deleting the refusal from `_holds` does not make this test go
    red, it makes it HANG — which is the defect itself, and a hanging test is
    not a failing test. Verified by mutation (ADR 0166).
    """
    assert _holds_outcome(PATHOLOGICAL, OVER_CAP, wall=5.0) == ("refused", None)
    # The control: the linear pattern reaches `re.search` and answers.
    assert _holds_outcome(LINEAR, OVER_CAP, wall=5.0) == ("held", False)


def test_a_very_long_input_is_refused_rather_than_truncated() -> None:
    """Truncating would change the predicate — "at most 35 words" asked of the
    first 10,000 characters is a different question — so the backstop refuses
    and says so.

    **This test used to assert the refusal for `LINEAR`, and that assertion was
    wrong** (ADR 0177). `(?:\\s+\\S+){0,34}` is a BOUNDED repetition: it enters
    its body at most 34 times whatever the input length, so it cannot backtrack
    catastrophically and the length of the input says nothing new about it. The
    backstop now keys on an UNBOUNDED quantifier, which is the only shape whose
    iteration count grows with the input — so the pattern here is `+`, not
    `{0,34}`. The control that `LINEAR` at this length RUNS is the next test.
    """
    unbounded = TaskCheck(path="working_memory.summary", op="regex", value=r"^(?:\s+\S+)+$")
    assert _holds(unbounded, " one two three") is True
    with pytest.raises(CatastrophicPatternError) as excinfo:
        _holds(unbounded, " x" * 6000)
    assert "10000" in str(excinfo.value) or "10,000" in str(excinfo.value)
    assert "unbounded" in str(excinfo.value)


def test_a_long_input_against_a_pattern_with_no_repeated_group_is_fine() -> None:
    """The control for the backstop: length alone is not the hazard."""
    check = TaskCheck(path="working_memory.summary", op="contains", value="x")
    assert _holds(check, "x " * 6000) is True
    plain = TaskCheck(path="working_memory.summary", op="regex", value=r"\bxyzzy\b")
    assert _holds(plain, "x " * 6000) is False


# ---------------------------------------------------------------------------
# ADR 0177 R5(a) — the backstop counts UNBOUNDED repetition only
# ---------------------------------------------------------------------------

# ADR 0171's content patterns, copied from `corpus/train/` — the two shipped
# checks that carry a repeated group, and the only two in the whole corpus.
# Both are `( … )?`: bounded, linear, and refused by the old backstop.
S3B_SHIPPED = [
    r"(?i)(not (have been )?overloaded|no overloading|"
    r"overloading (was )?(rejected|ruled out|discounted|dismissed))",
    r"(?i)(not (yet )?(re)?open|no confirmed date|still closed|has not returned|"
    r"remains closed|delayed indefinitely|still awaiting)",
]

# The family every one of ADR 0171's seven negatives belongs to: a model that
# rambles past the word cap. 12,000 characters, over the 10,000 backstop.
RAMBLE = ("It also observes that the licensed capacity was one hundred and twenty. " * 200)[:12000]

# Bounded repetitions the backstop must NOT fire on, at any length.
BOUNDED_REPEATS = [
    *S3B_SHIPPED,
    LINEAR,
    r"^\s*\S+(?:\s+\S+){0,29}\s*$",
    r"^\s*\S+(?:\s+\S+){0,39}\s*$",
    r"(?:foo|bar){1,3}",
    r"(x )?y",
    r"(ab){2}",
]

# Unbounded repetitions the backstop must still refuse over a long input.
UNBOUNDED_REPEATS = [
    r"^(?:\s+\S+)+$",
    r"(?:ab)*c",
    r"(?:\s+\S+){2,}",
]


@pytest.mark.parametrize("pattern", BOUNDED_REPEATS)
def test_a_bounded_repetition_runs_on_a_long_input_and_runs_fast(pattern: str) -> None:
    """The reproduction, inverted (ADR 0177 R5).

    `aef loop score` on a corpus whose summary is 12,000 characters printed

        error: refusing to run regex check '(?i)(not (have been )?overloaded|...
        the pattern repeats a group and the input is over 10000 characters

    and exited 1 — EXIT_REJECTED — on a pattern that decides that same input in
    under half a millisecond. A bounded quantifier enters its body a fixed
    number of times whatever the input length; there is nothing for the length
    of the input to make worse.
    """
    check = TaskCheck(path="working_memory.summary", op="regex", value=pattern)
    started = time.perf_counter()
    held = _holds(check, RAMBLE)  # must not raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert isinstance(held, bool)
    assert elapsed_ms < 250, f"{pattern!r} took {elapsed_ms:.1f} ms on {len(RAMBLE)} chars"


@pytest.mark.parametrize("pattern", UNBOUNDED_REPEATS)
def test_an_unbounded_repetition_is_still_refused_over_a_long_input(pattern: str) -> None:
    """The control. Narrowing the backstop must not switch it off: an
    unbounded quantifier is the shape whose iteration count grows with the
    input, which is the precondition the backstop exists for."""
    check = TaskCheck(path="working_memory.summary", op="regex", value=pattern)
    with pytest.raises(CatastrophicPatternError):
        _holds(check, RAMBLE)


def test_the_shipped_content_patterns_find_what_they_were_written_to_find() -> None:
    """Not just "does not raise" — the patterns must still DECIDE, both ways,
    on the rambling summary that provoked the refusal. A backstop that lets a
    pattern through and a pattern that answers wrongly are different bugs and
    this rules out the second."""
    hit = "The inquiry found the vessel was not overloaded. " + RAMBLE
    for pattern in S3B_SHIPPED[:1]:
        check = TaskCheck(path="working_memory.summary", op="regex", value=pattern)
        assert _holds(check, hit[:12000]) is True
        assert _holds(check, RAMBLE) is False


def test_the_original_redos_pattern_is_still_refused_at_every_length() -> None:
    """The pattern this whole defence was built for (ADR 0166). It is refused
    by the static detector before the length backstop is even consulted, so
    narrowing the backstop cannot reach it."""
    with pytest.raises(CatastrophicPatternError):
        refuse_catastrophic_regex(PATHOLOGICAL)
    assert _holds_outcome(PATHOLOGICAL, OVER_CAP, wall=5.0) == ("refused", None)
    assert _holds_outcome(PATHOLOGICAL, RAMBLE, wall=5.0) == ("refused", None)


def test_every_regex_the_corpus_ships_runs_on_a_twelve_thousand_character_answer() -> None:
    """The producer→consumer property, over the REAL corpus rather than an
    example. A model that rambles is the ordinary failure these checks exist to
    catch; not one of them may abort instead of deciding."""
    patterns = set()
    for path in sorted(CORPUS_ROOT.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        payload = json.loads(path.read_text())
        for check in payload.get("checks", ()):
            if check.get("op") == "regex":
                patterns.add(check["value"])
    assert patterns, "no regex checks found — this test would pass vacuously"
    for pattern in sorted(patterns):
        check = TaskCheck(path="working_memory.summary", op="regex", value=pattern)
        assert isinstance(_holds(check, RAMBLE), bool), pattern


# ---------------------------------------------------------------------------
# `max_words` / `min_words` — the cap with no regex in it
# ---------------------------------------------------------------------------


def test_max_words_and_min_words_are_ops() -> None:
    assert {"max_words", "min_words"} <= OPS


@pytest.mark.parametrize(
    ("summary", "cap", "expected"),
    [(AT_CAP, 35, True), (OVER_CAP, 35, False), ("one two", 2, True), ("", 35, True)],
)
def test_max_words_counts_whitespace_separated_tokens(
    summary: str, cap: int, expected: bool
) -> None:
    check = TaskCheck(path="working_memory.summary", op="max_words", value=cap)
    assert _holds(check, summary) is expected


@pytest.mark.parametrize(
    ("summary", "floor", "expected"),
    [("", 1, False), ("   ", 1, False), ("one", 1, True), ("one two", 3, False)],
)
def test_min_words_is_what_makes_an_empty_answer_fail(
    summary: str, floor: int, expected: bool
) -> None:
    """The corpus regex said `{1,N}`, so it rejected an empty summary. A bare
    `max_words` accepts one — which is exactly the live failure mode ADR 0156
    saw — so the pair, not the cap alone, is the equivalent predicate."""
    check = TaskCheck(path="working_memory.summary", op="min_words", value=floor)
    assert _holds(check, summary) is expected


def test_max_words_agrees_with_the_corpus_pattern_wherever_that_pattern_returns() -> None:
    """4,000 generated strings per cap, restricted to the region where the
    original terminates. `max_words` plus `min_words: 1` is the same
    predicate; `max_words` alone differs on exactly the empty string."""
    import random

    rng = random.Random(20260904)
    seps = [" ", "  ", "\t", "\n", " \n "]
    for cap in (30, 35, 40):
        original = re.compile(r"^(?:\s*\S+){1," + str(cap) + r"}\s*$")
        for _ in range(4000):
            count = rng.randint(1, cap)
            tokens = [
                "".join(rng.choice("abcXY.,-") for _ in range(rng.randint(1, 6)))
                for _ in range(count)
            ]
            body = tokens[0]
            for token in tokens[1:]:
                body += rng.choice(seps) + token
            text = rng.choice(["", " ", "\n"]) + body + rng.choice(["", " ", "  \n"])
            want = original.search(text) is not None
            words = len(text.split())
            assert (1 <= words <= cap) is want


def test_a_word_count_check_needs_an_integer() -> None:
    for bad in ("35", 35.0, True, None, -1):
        with pytest.raises(CheckError):
            TaskCheck(path="working_memory.summary", op="max_words", value=bad)


def test_a_word_count_check_on_a_non_string_fails_rather_than_stringifying() -> None:
    """`len(str([1, 2]).split())` is 2. A check that silently PASSES on the
    wrong kind of value is worse than one that fails loudly on it."""
    check = TaskCheck(path="working_memory.answer", op="max_words", value=35)
    state = AEFState(run_id="s", agent_id="a", objective="o", working_memory={"answer": [1, 2]})
    report = evaluate_checks((check,), state)
    assert (report.passed, report.total) == (0, 1)


def test_a_word_count_check_round_trips_through_its_payload() -> None:
    check = TaskCheck(path="working_memory.summary", op="max_words", value=35)
    assert check.to_payload() == {"path": "working_memory.summary", "op": "max_words", "value": 35}
    assert TaskCheck.from_payload(check.to_payload()) == check


# ---------------------------------------------------------------------------
# The corpus itself
# ---------------------------------------------------------------------------


def test_no_scenario_in_the_corpus_carries_an_exponential_pattern() -> None:
    """The property, asserted over the real corpus rather than over an
    example: every `regex` check on disk survives the detector. It fails today
    only if someone reintroduces the word cap."""
    corpus = load_corpus(CORPUS_ROOT)
    patterns = [c.value for s in corpus.scenarios for c in s.checks if c.op == "regex"]
    assert patterns, "the corpus is expected to still exercise the regex op"
    for pattern in patterns:
        refuse_catastrophic_regex(pattern)


def test_every_summary_word_cap_decides_an_over_cap_answer_immediately() -> None:
    corpus = load_corpus(CORPUS_ROOT)
    caps = [c.value for s in corpus.scenarios for c in s.checks if c.op == "regex"]
    for pattern in caps:
        assert _terminates(pattern, OVER_CAP, wall=5.0), pattern


def test_a_planted_exponential_pattern_is_refused_when_the_scenario_loads(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Verify the detector against a planted fault before trusting "nothing
    found": a scanner that cannot detect is not a scanner."""
    source = CORPUS_ROOT / "validation" / "sum-13-cider-press.json"
    payload = json.loads(source.read_text())
    payload["checks"] = [c for c in payload["checks"] if c["op"] != "regex"] + [
        {"path": "working_memory.summary", "op": "regex", "value": PATHOLOGICAL}
    ]
    planted = tmp_path / "validation"
    planted.mkdir()
    target = planted / f"{payload['id']}.json"
    target.write_text(json.dumps(payload))

    with pytest.raises(CorpusError) as excinfo:
        load_scenario(target)
    message = str(excinfo.value)
    assert str(target) in message, "a refusal has to name the file it refused"
    assert "unusable check" in message
    assert "max_words" in message
