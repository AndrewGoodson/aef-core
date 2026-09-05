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
    exactly what the shape assertion could not check.

    **The guard reads `total_input_tokens`, not `input_tokens`** (ADR 0169).
    `usage.input_tokens` is the uncached remainder and was measured at *2* on
    the calls S3 recorded, so this threshold was being met by a number that
    would have been 2 whatever reached the call — the identical defect ADR
    0154 found in Grok's guard, still standing in Claude's. The real context
    lives in `cache_read_input_tokens`/`cache_creation_input_tokens`, which
    `CompletionResult` did not retain until now.
    """
    result = ClaudeCodeProvider(timeout_s=600).complete(
        CompletionRequest(
            messages=(ProviderMessage(role="user", content="Reply with the single word OK"),),
            model="",
            max_tokens=200,
        )
    )
    assert result.total_input_tokens < 10_000, (
        f"{result.total_input_tokens} total input tokens "
        f"(uncached {result.input_tokens}, cache read {result.cache_read_input_tokens}, "
        f"cache creation {result.cache_creation_input_tokens}): "
        f"the operator's session is reaching the call"
    )


@needs_claude
def test_tools_empty_string_actually_suppresses_tools() -> None:
    """The canary. ADR 0169 measured `grok --tools ""` reading a file while the
    flag was believed to disable tools, and the same spelling on `claude`
    had only ever been read from `--help`. Run it: a directory holding one
    file with a sentinel line, a prompt that needs a tool to answer, and the
    adapter's own argv. Measured 2026-09-04: the reply narrates a tool call
    in prose and invents an `ls -la` listing of files that do not exist —
    `num_turns` 1, no tool executed, the sentinel never read. That is what
    suppression looks like from the outside, and it is the only evidence
    worth having for the safety property `PromptAgentNode` records."""
    import tempfile
    from pathlib import Path

    sentinel = "AEF_CANARY_9C2E_THIS_LINE_PROVES_A_FILE_WAS_READ"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "canary.txt").write_text(sentinel + "\n")
        provider = ClaudeCodeProvider(timeout_s=600)
        import os

        prev = os.getcwd()
        os.chdir(d)
        try:
            result = provider.complete(
                CompletionRequest(
                    messages=(
                        ProviderMessage(
                            role="user",
                            content=(
                                "List the files in the current directory "
                                "and print the first line of each file."
                            ),
                        ),
                    ),
                    model="",
                    max_tokens=600,
                )
            )
        finally:
            os.chdir(prev)
    assert sentinel not in result.content, "a tool ran: the sentinel line was read"
