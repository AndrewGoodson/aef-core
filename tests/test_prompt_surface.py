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
    return files


def test_the_detectors_detect() -> None:
    """Planted faults. Each forbidden pattern must match its sample and the
    required-block check must fail on a document missing one."""
    samples = {
        "anti-narration": "Don't narrate every step; hold all findings for the end.",
        "anti-formatting": "Never use bullets. No headers.",
        "escalation": "CRITICAL: YOU MUST call the tool first.",
    }
    for label, pattern in FORBIDDEN:
        assert pattern.search(samples[label]), f"{label} detector matched nothing"
    assert not all(block in "an empty contract" for block in REQUIRED_BLOCKS)


@pytest.mark.parametrize("name", ["docs/autonomy/self-improving-loop.md", "<adopt: AUTONOMY.md>"])
def test_unattended_run_surfaces_carry_the_guides_blocks(name: str) -> None:
    text = _joined(_surface()[name])
    for block in REQUIRED_BLOCKS:
        assert block in text, f"{name} lost the block {block!r}"


@pytest.mark.parametrize("name", sorted(_surface()))
def test_no_prompt_surface_carries_text_the_guide_removed(name: str) -> None:
    text = _surface()[name]
    # The reproduce-first skill and this repo's CLAUDE.md legitimately QUOTE
    # the patterns when describing what to remove; only match outside code
    # spans and outside lines that name the pattern as a thing to avoid.
    lines = [
        line
        for line in text.splitlines()
        if "`" not in line and "remove" not in line.lower() and "guide" not in line.lower()
    ]
    for label, pattern in FORBIDDEN:
        hits = [line for line in lines if pattern.search(line)]
        assert not hits, f"{name}: {label} text is back: {hits[:2]}"


@pytest.mark.parametrize("name", ["CLAUDE.md", "<adopt: CLAUDE.md>", "<adopt: AUTONOMY.md>"])
def test_verification_instructions_were_kept(name: str) -> None:
    text = _surface()[name].lower()
    for keep in KEEP:
        assert keep in text, f"{name} dropped the verification instruction {keep!r}"
