"""The Codex path, measured rather than assumed (ADR 0131).

ADR 0112 shipped `CodexProvider` with its output parsing written from
`codex exec --help` and said so in as many words: *"its parsing is a
hypothesis until a run confirms it."* The CLI on the authoring box could
not parse its own server's model catalogue, so no run could confirm it, and
"works with any coding agent" rested on one verified backend and one guess.

This is the run. It is opt-in twice over — the CLI must be installed AND
`AEF_LIVE_HARNESS` set — because it spends the operator's Codex quota and
takes ~20 s, and a network call inside a routine `pytest -q` is a flaky
test waiting to happen. The command that runs it is in ADR 0131.
"""

from __future__ import annotations

import os
import shutil

import pytest

from aef.providers.base import CompletionRequest, ProviderMessage
from aef.providers.harness_provider import CodexProvider

needs_codex = pytest.mark.skipif(
    not shutil.which("codex") or not os.environ.get("AEF_LIVE_HARNESS"),
    reason="needs the codex CLI and AEF_LIVE_HARNESS=1 (spends quota, ~20s)",
)


@needs_codex
def test_codex_answers_through_the_provider() -> None:
    """Every field the adapter derives, against a real run: the reply comes
    from `--output-last-message`, the usage from the `turn.completed` event's
    `usage` object, and nothing raises on the way."""
    result = CodexProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(
                ProviderMessage(role="system", content="Answer with exactly one word."),
                ProviderMessage(role="user", content="Reply with the single word OK"),
            ),
            model="gpt-5.5",
            max_tokens=200,
        )
    )
    assert result.content.strip() == "OK"
    assert result.model == "gpt-5.5"
    assert result.stop_reason == "end_turn"
    # Parsed from the event stream, not defaulted: a zero here would mean the
    # scan found no `usage` object and quietly reported free.
    assert result.input_tokens > 0
    assert result.output_tokens > 0
