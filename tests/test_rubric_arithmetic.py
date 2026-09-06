"""The rubric's own total is under test (ADR 0127).

`docs/research/self-learning-rubric.md` opens with the rule that a score
moves only on a cited artifact. Its headline total was not one of those: it
was carried forward by hand as `previous + delta` at each increment, and
nothing ever recomputed it from the rows. The baseline's rows summed to 51
against a stated 50, and every total after it inherited the point — for
nine increments, across two nights of work, in the document whose first
paragraph says a self-graded number is exactly the failure the trust case
warns about.

The table is append-only history: each increment prepends a row for the
dimension it moved, so the FIRST row for a dimension is its current score,
and a dimension that has never moved has no row in "Current" at all and
carries its baseline value. That shape is what this file encodes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RUBRIC = Path(__file__).resolve().parents[1] / "docs" / "research" / "self-learning-rubric.md"

_HEADING = re.compile(r"^## (?P<kind>Current|Baseline)[^\n]*?\*\*(?P<total>\d+) / 100\*\*", re.M)
# "| 1 | 19/20 | …" and the disambiguated "| 1 (I10) | 18/20 | …"
_ROW = re.compile(r"^\| (?P<dim>\d+)(?: \(I\d+\))? \| (?P<score>\d+)/(?P<weight>\d+) \|", re.M)
# The weights table at the top: "| 1 | Closed measurement loop | 20 | …"
_WEIGHT = re.compile(r"^\| (?P<dim>\d+) \| [^|]+ \| (?P<weight>\d+) \|", re.M)


def _text() -> str:
    return RUBRIC.read_text()


def _sections(text: str) -> list[tuple[str, int, str]]:
    """(kind, stated total, body) for each scored section, in file order."""
    out = []
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group("kind"), int(m.group("total")), text[m.end() : end]))
    return out


def _latest_per_dim(body: str) -> dict[str, tuple[int, int]]:
    """First row wins: the table is prepend-ordered, newest first."""
    seen: dict[str, tuple[int, int]] = {}
    for m in _ROW.finditer(body):
        seen.setdefault(m.group("dim"), (int(m.group("score")), int(m.group("weight"))))
    return seen


def _weights(text: str) -> dict[str, int]:
    head = text[: text.index("## ")]
    return {m.group("dim"): int(m.group("weight")) for m in _WEIGHT.finditer(head)}


def _current_scores() -> dict[str, tuple[int, int]]:
    """Every dimension's live score: its newest row anywhere, Current first,
    falling back to Baseline for a dimension that has never moved."""
    text = _text()
    sections = _sections(text)
    assert sections and sections[0][0] == "Current", "the newest section must be 'Current'"
    scores: dict[str, tuple[int, int]] = {}
    for _, _, body in sections:
        for dim, value in _latest_per_dim(body).items():
            scores.setdefault(dim, value)
    return scores


def test_the_stated_total_is_the_sum_of_the_rows() -> None:
    stated = _sections(_text())[0][1]
    scores = _current_scores()
    computed = sum(score for score, _ in scores.values())
    assert computed == stated, (
        f"rubric heading says {stated}, its rows sum to {computed}: "
        + ", ".join(
            f"dim {d}={s}" for d, (s, _) in sorted(scores.items(), key=lambda kv: int(kv[0]))
        )
    )


def test_every_weighted_dimension_has_a_score() -> None:
    """A dimension in the weights table with no row anywhere is a dimension
    silently counted as zero — or silently not counted at all."""
    weights, scores = _weights(_text()), _current_scores()
    assert weights, "no weights table parsed; the rubric's shape changed"
    assert set(weights) == set(scores), f"weighted {sorted(weights)} vs scored {sorted(scores)}"


def test_no_dimension_scores_above_its_weight() -> None:
    weights = _weights(_text())
    for dim, (score, row_weight) in _current_scores().items():
        assert row_weight == weights[dim], (
            f"dim {dim} row says /{row_weight}, table says /{weights[dim]}"
        )
        assert score <= weights[dim], f"dim {dim} scores {score} of {weights[dim]}"


def test_the_weights_still_sum_to_one_hundred() -> None:
    assert sum(_weights(_text()).values()) == 100


@pytest.mark.parametrize("kind", ["Current", "Baseline"])
def test_every_scored_section_is_self_consistent(kind: str) -> None:
    """The baseline is history and must stay correct too — it is the number
    every later delta was taken from, which is how the error propagated."""
    text = _text()
    section = next(s for s in _sections(text) if s[0] == kind)
    _, stated, body = section
    rows = _latest_per_dim(body)
    if kind == "Baseline":
        assert set(rows) == set(_weights(text)), "the baseline must score every dimension"
        assert sum(s for s, _ in rows.values()) == stated
    else:
        # Current omits dimensions that have never moved; they carry.
        carried = {d: v for d, v in _current_scores().items() if d not in rows}
        assert sum(s for s, _ in rows.values()) + sum(s for s, _ in carried.values()) == stated


def test_the_file_carries_exactly_one_current_heading() -> None:
    """A merge left two `## Current` headings with different totals (83 and a
    stale 74). `_sections` reads the first, so the arithmetic stayed green
    while a reader scrolling one line further saw a different number — the
    scoreboard defect this file exists to prevent, in the file itself."""
    assert _text().count("## Current") == 1, "two headings mean two answers"
