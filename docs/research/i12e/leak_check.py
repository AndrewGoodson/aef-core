"""P2 — ADR 0180's excerpt property, asked of the LIVE prompts of every arm.

`docs/research/i12d/leak_check.py` (ADR 0193) with one character changed: the
glob reads arms a, b and d rather than a, b and c, because arm (c) sends arm
(b)'s prompts byte for byte and has no JSON of its own.

The property: no 12-character window of any run's own summary may appear in a
LATER run's rendered lesson block. It scans the lesson block only — the first
version scanned whole prompts and fired 28 times on the arm that has no
retrieve node at all, because the passage is in the prompt too (corrected in
ADR 0184). The lesson block is the only path an earlier output can travel.

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

# The HARNESS's own fixed vocabulary - `RuleBasedCritic`'s template and
# `check_memory._OP_PROSE` - spelled out for the same reason. A window that
# occurs inside one of these is text the producer wrote, not text a run wrote,
# and a scanner that counts it is measuring English rather than provenance.
#
# This is not a loosened control; it is a false positive found by running it.
# On this corpus the raw scan reported four hits, all of the SAME window,
# "er than the " - which is inside "is longer than the owner's maximum",
# present in every word-cap lesson bullet - against a summary that happened to
# contain "rather than the". The discriminator is reproducible offline: the
# same window is in arm (d) repeat 0's lesson blocks, where that repeat's
# `sum-39` summary does not contain it at all. Both counts are printed, so a
# reader can apply either.
TEMPLATE_PHRASES = (
    "error(s) recorded",
    "tool call(s) failed",
    "no failure signals",
    "check failed: working_memory.summary",
    "does not contain a required substring the owner declared",
    "does not equal the value the owner declared",
    "does not match the pattern the owner declared",
    "was never recorded",
    "is longer than the owner's maximum",
    "is shorter than the owner's minimum",
    "observed",
    "words,",
    "chars",
)


def windows(text: str, width: int = WINDOW) -> set[str]:
    if len(text) < width:
        return set()
    return {text[i : i + width] for i in range(len(text) - width + 1)}


def template_windows() -> set[str]:
    """Every 12-character window of the harness's own fixed phrasing."""
    out: set[str] = set()
    for phrase in TEMPLATE_PHRASES:
        out |= windows(phrase)
    return out


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
    template = template_windows()
    print(
        "| arm | repeat | later prompts carrying a lesson block | raw hits | "
        "hits from a RUN's own output |"
    )
    print("|---|---|---|---|---|")
    total = 0
    total_raw = 0
    for path in sorted(root.glob("[abd]_r*.json")):
        d = json.loads(path.read_text())
        order = d["order"]
        with_block = sum(1 for i in order if lesson_block(d["draft_prompts"].get(i, "")))
        leaked = 0
        raw = 0
        for i, earlier in enumerate(order):
            summary = d["summaries"].get(earlier, "")
            if not summary:
                continue
            for later in order[i + 1 :]:
                block = lesson_block(d["draft_prompts"].get(later, ""))
                if not block:
                    continue
                hits = windows(summary) & windows(block)
                raw += len(hits)
                real = hits - template
                if real:
                    leaked += len(real)
                    print(
                        f"    LEAK {d['arm']}r{d['repeat']} {earlier} -> {later}: "
                        f"{len(real)} e.g. {sorted(real)[0]!r}"
                    )
                elif hits:
                    print(
                        f"    (template collision, not a leak) {d['arm']}r{d['repeat']} "
                        f"{earlier} -> {later}: {sorted(hits)[0]!r}"
                    )
        total += leaked
        total_raw += raw
        print(
            f"| ({d['arm']}) | {d['repeat']} | {with_block}/{len(order)} | {raw} | **{leaked}** |"
        )
    print(f"\nraw window hits: {total_raw}   hits from a run's own output: {total}")


if __name__ == "__main__":
    main()
