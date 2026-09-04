"""The prompt surface as a regression check (ADR 0120, I8).

`/new-model-check` audits prompts once per model release and applies the
guide's edits. Nothing then stops the next commit from putting back what it
removed, or trimming what it added. This pins the state the last check left,
the same way `tests/test_model_ids.py` pins model IDs: not a model table, a
shape.

Every detector here is proved against a planted fault before it is trusted
(`test_the_detectors_detect`) — a regex that quietly matches nothing would
pass the other tests forever.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aef.cli.adopt import render_autonomy_md, render_claude_md
from aef.cli.adopt_loop import render_first_day_md

REPO = Path(__file__).resolve().parents[1]

# Files a coding agent reads as instructions in THIS repo, plus the renderers
# that ship instructions into adopted repos.
PROMPT_SURFACE = (
    "CLAUDE.md",
    "AGENT_INTEGRATION.md",
    "docs/autonomy/self-improving-loop.md",
    ".claude/agents/seam-hunter.md",
    ".claude/skills/reproduce-first/SKILL.md",
)

# Text the current model guide says an unattended loop should carry, verbatim.
REQUIRED_BLOCKS = (
    "You are operating autonomously.",
    "the scope is the deliverable",
    "surgically edit a file rather than rewrite the entire thing",
)

# Text the current model guide says to REMOVE: the model over-obeys it.
# Case-insensitive: the first draft of the anti-formatting pattern was not,
# and the planted "Never use bullets" sailed past it — caught by
# `test_the_detectors_detect`, which is why that test exists.
FORBIDDEN = (
    (
        "anti-narration",
        re.compile(r"don.?t narrate|do not narrate|hold (all )?(findings|results)", re.I),
    ),
    (
        "anti-formatting",
        re.compile(r"never use (bullets|headers|bold)|no (bullet|header)s?\b", re.I),
    ),
    ("escalation", re.compile(r"CRITICAL:\s*YOU MUST|YOU MUST ALWAYS")),
)

# Verification instructions the guide says to KEEP.
KEEP = ("reproduce", "green bar")


def _joined(text: str) -> str:
    """Markdown joins `>` continuation lines; compare the joined quote."""
    return " ".join(line[2:] if line.startswith("> ") else line for line in text.splitlines())


def _surface() -> dict[str, str]:
    files = {name: (REPO / name).read_text() for name in PROMPT_SURFACE}
    files["<adopt: CLAUDE.md>"] = render_claude_md("none", "repo")
    files["<adopt: AUTONOMY.md>"] = render_autonomy_md("repo")
    # FIRST_DAY.md (ADR 0148) exists only in adopted repos, so it enters the
    # surface as its renderer rather than as a path — the same way the two
    # above do. It is a prompt surface and not merely a document: an adopting
    # coding agent is handed it as the task, so text the model guide says to
    # remove is as costly here as in CLAUDE.md.
    files["<adopt: FIRST_DAY.md>"] = render_first_day_md("repo")
    return files


# An inline code span. The prompt surfaces legitimately QUOTE the patterns
# when describing what a model check strips out, and a quoted pattern is not
# an instruction — but only inside backticks. Anything else is prose the
# model reads as an instruction, whatever the sentence around it claims.
_CODE_SPAN = re.compile(r"`[^`]*`")


def _prose(text: str) -> list[str]:
    """The surface with code spans blanked out — what a model reads as
    instruction. Nothing else is filtered. The first version of this also
    dropped every line containing "guide" or "remove", which hid a planted
    "Do not narrate your steps; the model guide says so." from its own
    detector: three of the four planted faults became invisible (ADR 0126)."""
    return [_CODE_SPAN.sub(" ", line) for line in text.splitlines()]


def test_the_detectors_detect() -> None:
    """Planted faults, pushed THROUGH the filter the real test uses.

    Asserting only that the regexes match is what let the defect in: the
    regexes were fine and the line filter threw their input away before they
    ever saw it. Every sample here therefore goes through `_prose` exactly as
    a real surface line would.
    """
    samples = {
        "anti-narration": "Don't narrate every step; hold all findings for the end.",
        "anti-formatting": "Never use bullets. No headers.",
        "escalation": "CRITICAL: YOU MUST call the tool first.",
    }
    # The same faults dressed in the words the old filter dropped on sight.
    # Each of these was invisible to the surface test (ADR 0126).
    disguised = {
        "anti-narration": "Do not narrate your steps; the model guide says so.",
        "anti-formatting": "Never use bullets in the final report (see the style guide).",
        "escalation": "CRITICAL: YOU MUST verify before you remove anything.",
    }
    for label, pattern in FORBIDDEN:
        assert pattern.search(samples[label]), f"{label} detector matched nothing"
        for planted in (samples[label], disguised[label]):
            assert any(pattern.search(line) for line in _prose(planted)), (
                f"{label}: the filter hid a planted fault from its own detector: {planted!r}"
            )
    assert not all(block in "an empty contract" for block in REQUIRED_BLOCKS)


def test_the_filter_still_exempts_a_quoted_pattern() -> None:
    """The exemption that survives: a pattern inside backticks is a quotation,
    not an instruction — this is how the reproduce-first skill and CLAUDE.md
    describe what a model check strips out without tripping the check."""
    quoted = "The check strips `Never use bullets` and `CRITICAL: YOU MUST` from prompts."
    for _label, pattern in FORBIDDEN:
        assert not any(pattern.search(line) for line in _prose(quoted))
    # ... and the exemption is the code span, not the surrounding sentence,
    # and not the whole line either: an instruction standing beside a quoted
    # command is still an instruction. Dropping the line wholesale — the rule
    # this test replaced — hides it.
    unquoted = "The check strips Never use bullets from prompts."
    mixed = "Run `aef loop score` after each edit. Never use bullets in the report."
    for planted in (unquoted, mixed):
        assert any(
            pattern.search(line) for _label, pattern in FORBIDDEN for line in _prose(planted)
        ), f"the filter hid a planted fault beside a code span: {planted!r}"


@pytest.mark.parametrize("name", ["docs/autonomy/self-improving-loop.md", "<adopt: AUTONOMY.md>"])
def test_unattended_run_surfaces_carry_the_guides_blocks(name: str) -> None:
    text = _joined(_surface()[name])
    for block in REQUIRED_BLOCKS:
        assert block in text, f"{name} lost the block {block!r}"


@pytest.mark.parametrize("name", sorted(_surface()))
def test_no_prompt_surface_carries_text_the_guide_removed(name: str) -> None:
    lines = _prose(_surface()[name])
    for label, pattern in FORBIDDEN:
        hits = [line for line in lines if pattern.search(line)]
        assert not hits, f"{name}: {label} text is back: {hits[:2]}"


@pytest.mark.parametrize(
    "name",
    ["CLAUDE.md", "<adopt: CLAUDE.md>", "<adopt: AUTONOMY.md>", "<adopt: FIRST_DAY.md>"],
)
def test_verification_instructions_were_kept(name: str) -> None:
    text = _surface()[name].lower()
    for keep in KEEP:
        assert keep in text, f"{name} dropped the verification instruction {keep!r}"
