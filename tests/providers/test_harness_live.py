"""The Claude Code path, run against the real CLI (ADR 0150).

`ClaudeCodeProvider` was completely broken for hours: ADR 0126 added
`--mcp-config {}` to stop the operator's MCP servers reaching a node's model
call, and the CLI validates that value against a schema whose `mcpServers`
key is required. Every call exited 1 with `Invalid MCP configuration`. It
shipped because the model quota was exhausted that day, so the tests could
only assert the SHAPE of argv — and argv was perfectly well formed.

A shape assertion cannot tell a valid flag value from an invalid one. This
runs the real binary. Opt-in twice — the CLI must exist AND
`AEF_LIVE_HARNESS` must be set — because it spends the operator's quota;
the same contract as `test_codex_live.py`.

    AEF_LIVE_HARNESS=1 pytest -q tests/providers/test_harness_live.py
"""

from __future__ import annotations

import os
import shutil

import pytest

from aef.providers.base import CompletionRequest, ProviderMessage
from aef.providers.harness_provider import ClaudeCodeProvider

needs_claude = pytest.mark.skipif(
    not shutil.which("claude") or not os.environ.get("AEF_LIVE_HARNESS"),
    reason="needs the claude CLI and AEF_LIVE_HARNESS=1 (spends quota)",
)


@needs_claude
def test_claude_answers_through_the_provider() -> None:
    """Every flag the adapter passes, judged by the binary rather than by a
    string comparison: a malformed one exits 1 and this fails."""
    result = ClaudeCodeProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(
                ProviderMessage(role="system", content="Answer with exactly one word."),
                ProviderMessage(role="user", content="Reply with the single word OK"),
            ),
            model="",  # the session's own default; the point is the flags, not the model
            max_tokens=200,
        )
    )
    assert result.content.strip() == "OK"
    assert result.stop_reason == "end_turn"


@needs_claude
def test_the_operators_session_does_not_reach_the_call() -> None:
    """ADR 0126's measurement, re-run: unisolated this call carried 211,470
    input tokens of MCP schemas and the operator's own CLAUDE.md. The
    isolation flags are only worth having if they are ACCEPTED, which is
    exactly what the shape assertion could not check."""
    result = ClaudeCodeProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content="Reply with the single word OK"),),
            model="",
            max_tokens=200,
        )
    )
    assert result.input_tokens < 10_000, (
        f"{result.input_tokens} input tokens: the operator's session is reaching the call"
    )
