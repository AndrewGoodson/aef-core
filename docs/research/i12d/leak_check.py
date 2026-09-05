"""ADR 0180's excerpt property, checked end to end on the LIVE arms.

`seed.py::assert_no_excerpt` proves the property where it is defined — inside
a record's content. This asks the question one layer out, on the arms that
actually ran: **did any run's own summary reach a later run's prompt?**

That is the shape ADR 0162 measured the harm of. A lesson bullet carrying a
38-word example summary made two at-cap runs LONGER (23 -> 28 words against a
cap of 25; 38 -> 41 against 38) and broke the very check the lesson describes.
S1b's arm (c) put such a bullet in ten of seventeen prompts. If the fix holds,
the count here is zero for every arm.

Windows are 12 characters, the width the shipped regression test uses. Every
summary is checked against every LATER prompt in the same arm, not just the one
whose record produced the lesson, because a leak through consolidation would
surface anywhere downstream.

**Only the rendered LESSON BLOCK of the later prompt is scanned, and the first
version of this script scanned the whole prompt — which was wrong and said so
loudly.** Whole-prompt scanning reported 28 leaked windows in arm (a), the arm
with no retrieve node at all: the hits were ordinary English shared between a
summary and the next scenario's PASSAGE (`' for the first time '`, nine
overlapping windows of one idiom). A detector that fires on an arm with no
channel is measuring the language, not the channel. The lesson block is the
only path by which a prior run's output can reach a later prompt, so it is the
only thing scanned.

Usage:
  <venv>/bin/python leak_check.py [results-dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WINDOW = 12

# `aef.reasoning.nodes.LESSON_HEADER`, spelled out so this script reads the
# committed JSON without importing the package it is measuring.
HEADER = "Lessons from this agent's earlier runs (most relevant first):"


def windows(text: str, width: int = WINDOW) -> set[str]:
    if len(text) < width:
        return set()
    return {text[i : i + width] for i in range(len(text) - width + 1)}


def lesson_block(prompt: str) -> str:
    """The bullets `render_retrieved_context` put in this prompt, or "".

    `agents/summary/graph.py::draft_prompt` places the block after the
    instructions and before a blank line, `"Passage:"`, and the text — so the
    block ends at the first blank line after the header.
    """
    if HEADER not in prompt:
        return ""
    body = prompt.split(HEADER, 1)[1]
    return body.split("\n\n", 1)[0]


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results"
    print("| arm | repeat | later prompts carrying a lesson block | leaked windows |")
    print("|---|---|---|---|")
    total = 0
    for path in sorted(root.glob("[abc]_r*.json")):
        d = json.loads(path.read_text())
        order = d["order"]
        with_block = sum(1 for i in order if lesson_block(d["draft_prompts"].get(i, "")))
        leaked = 0
        for i, earlier in enumerate(order):
            summary = d["summaries"].get(earlier, "")
            if not summary:
                continue
            for later in order[i + 1 :]:
                block = lesson_block(d["draft_prompts"].get(later, ""))
                if not block:
                    continue
                hits = windows(summary) & windows(block)
                if hits:
                    leaked += len(hits)
                    print(
                        f"    LEAK {d['arm']}r{d['repeat']} {earlier} -> {later}: "
                        f"{len(hits)} e.g. {sorted(hits)[0]!r}"
                    )
        total += leaked
        print(f"| ({d['arm']}) | {d['repeat']} | {with_block}/{len(order)} | **{leaked}** |")
    print(f"\ntotal leaked windows across every arm and repeat: {total}")


if __name__ == "__main__":
    main()
