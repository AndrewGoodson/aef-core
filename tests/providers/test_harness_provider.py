"""The coding-agent harness as a ModelProvider (ADR 0112). Every test
injects a runner; no process is spawned. The Claude Code JSON shapes below
are copied from two real runs on 2026-09-03 (one logged in, one under
`--bare`); the Codex shapes are from its documented flags only."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from aef.providers.base import (
    CompletionRequest,
    FallbackProvider,
    ModelProviderError,
    ProviderMessage,
)
from aef.providers.harness_provider import ClaudeCodeProvider, CodexProvider, HarnessRun

# Verbatim fields from `claude -p --output-format json` on a logged-in box.
_CLAUDE_OK = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "OK",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 2, "output_tokens": 4},
    "modelUsage": {"claude-fable-5-1": {}},
}
# Verbatim from the same CLI under `--bare` (keychain skipped): exit 0,
# `is_error: true`, the failure carried in `result`.
_CLAUDE_NOT_LOGGED_IN = {
    "type": "result",
    "subtype": "success",
    "is_error": True,
    "result": "Not logged in · Please run /login",
    "stop_reason": "stop_sequence",
    "usage": {"input_tokens": 0, "output_tokens": 0},
    "modelUsage": {},
}


class _Recorder:
    def __init__(self, run: HarnessRun) -> None:
        self.run = run
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], timeout_s: float) -> HarnessRun:
        self.calls.append(list(argv))
        return self.run


def _request(**overrides: object) -> CompletionRequest:
    defaults: dict[str, object] = {
        "messages": (
            ProviderMessage(role="system", content="be terse"),
            ProviderMessage(role="user", content="hello"),
        ),
        "model": "claude-fable-5-1",
    }
    defaults.update(overrides)
    return CompletionRequest(**defaults)  # type: ignore[arg-type]


def _ok(payload: dict[str, object]) -> HarnessRun:
    return HarnessRun(returncode=0, stdout=json.dumps(payload), stderr="")


# ---------------------------------------------------------------------------
# Claude Code — reproduced shape
# ---------------------------------------------------------------------------
def test_claude_argv_is_a_toolless_single_turn_under_the_session_login() -> None:
    runner = _Recorder(_ok(_CLAUDE_OK))
    ClaudeCodeProvider(runner=runner).complete(_request())
    argv = runner.calls[0]
    assert argv[:2] == ["claude", "-p"]
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--tools") + 1] == ""  # a completion, not an agent
    assert argv[argv.index("--model") + 1] == "claude-fable-5-1"
    assert argv[argv.index("--system-prompt") + 1] == "be terse"
    assert argv[-1] == "hello"
    # `--bare` skips the keychain and answers "Not logged in".
    assert "--bare" not in argv


def test_claude_argv_does_not_inherit_the_operators_session() -> None:
    """The operator's MCP schemas and `~/.claude/CLAUDE.md` were reaching every
    judge call: 211,470 input tokens per call as issued, 4,684 with the MCP
    configuration suppressed (ADR 0126). These three flags are that fix, and
    `--bare` — which would also drop the keychain login — stays absent."""
    runner = _Recorder(_ok(_CLAUDE_OK))
    ClaudeCodeProvider(runner=runner).complete(_request())
    argv = runner.calls[0]
    assert "--strict-mcp-config" in argv
    # A VALID empty MCP config, not a bare `{}` — the CLI's schema requires
    # `mcpServers`, and asserting the shape of argv is exactly what let a
    # malformed value ship (ADR 0150). `test_claude_answers_through_the_provider`
    # in test_harness_live.py is the guard that runs the real CLI.
    payload = json.loads(argv[argv.index("--mcp-config") + 1])
    assert payload == {"mcpServers": {}}, payload
    assert "--safe-mode" in argv  # no CLAUDE.md, no skills, keychain intact
    assert "--bare" not in argv
    # Isolation flags precede the prompt, which stays last and positional.
    assert argv[-1] == "hello"


def test_claude_drops_max_tokens_and_says_so() -> None:
    """The CLI has no output-length flag. A caller that sets `max_tokens`
    (`LLMJudge` sets 400) gets no cap — pinned so the omission stays a
    documented fact rather than a silently missing control."""
    runner = _Recorder(_ok(_CLAUDE_OK))
    ClaudeCodeProvider(runner=runner).complete(_request(max_tokens=400))
    argv = runner.calls[0]
    assert not any("400" in a or "max-tokens" in a or "max_tokens" in a for a in argv)
    assert "max_tokens" in (ClaudeCodeProvider.__doc__ or "")


def test_claude_result_maps_text_usage_and_the_answering_model() -> None:
    result = ClaudeCodeProvider(runner=_Recorder(_ok(_CLAUDE_OK))).complete(_request())
    assert result.content == "OK"
    assert result.model == "claude-fable-5-1"  # from modelUsage, not the request
    assert (result.input_tokens, result.output_tokens) == (2, 4)
    assert result.stop_reason == "end_turn"


def test_claude_is_error_with_exit_zero_is_a_provider_error() -> None:
    provider = ClaudeCodeProvider(runner=_Recorder(_ok(_CLAUDE_NOT_LOGGED_IN)))
    with pytest.raises(ModelProviderError, match="Not logged in"):
        provider.complete(_request())


def test_claude_nonzero_exit_is_a_provider_error_carrying_stderr() -> None:
    runner = _Recorder(HarnessRun(returncode=2, stdout="", stderr="usage: claude ..."))
    with pytest.raises(ModelProviderError, match="exited 2.*usage: claude"):
        ClaudeCodeProvider(runner=runner).complete(_request())


def test_claude_non_json_output_is_a_provider_error() -> None:
    runner = _Recorder(HarnessRun(returncode=0, stdout="<html>", stderr=""))
    with pytest.raises(ModelProviderError, match="non-JSON"):
        ClaudeCodeProvider(runner=runner).complete(_request())


def test_claude_refusal_raises_and_fallback_falls_through() -> None:
    refusing = ClaudeCodeProvider(
        runner=_Recorder(_ok({**_CLAUDE_OK, "result": "", "stop_reason": "refusal"}))
    )
    good = ClaudeCodeProvider(runner=_Recorder(_ok({**_CLAUDE_OK, "result": "answered"})))
    with pytest.raises(ModelProviderError, match="refusal"):
        refusing.complete(_request())
    assert FallbackProvider([refusing, good]).complete(_request()).content == "answered"


def test_default_model_fills_an_empty_request_model() -> None:
    runner = _Recorder(_ok(_CLAUDE_OK))
    ClaudeCodeProvider(default_model="claude-opus-5", runner=runner).complete(_request(model=""))
    argv = runner.calls[0]
    assert argv[argv.index("--model") + 1] == "claude-opus-5"


def test_multi_turn_request_is_rendered_as_one_transcript() -> None:
    runner = _Recorder(_ok(_CLAUDE_OK))
    ClaudeCodeProvider(runner=runner).complete(
        _request(
            messages=(
                ProviderMessage(role="user", content="first"),
                ProviderMessage(role="assistant", content="reply"),
                ProviderMessage(role="user", content="second"),
            )
        )
    )
    assert runner.calls[0][-1] == "User: first\n\nAssistant: reply\n\nUser: second"


def test_tool_role_is_refused_before_any_process_is_spawned() -> None:
    runner = _Recorder(_ok(_CLAUDE_OK))
    request = _request(messages=(ProviderMessage(role="tool", content="{}"),))
    with pytest.raises(ModelProviderError, match="role 'tool'"):
        ClaudeCodeProvider(runner=runner).complete(request)
    assert runner.calls == []


# ---------------------------------------------------------------------------
# Codex — documented shape, not reproduced
# ---------------------------------------------------------------------------
class _CodexRecorder(_Recorder):
    """Writes the last-message file the way `--output-last-message` does."""

    def __init__(self, run: HarnessRun, last_message: str | None) -> None:
        super().__init__(run)
        self._last_message = last_message

    def __call__(self, argv: Sequence[str], timeout_s: float) -> HarnessRun:
        self.calls.append(list(argv))
        if self._last_message is not None:
            Path(argv[argv.index("--output-last-message") + 1]).write_text(self._last_message)
        return self.run


def test_codex_argv_is_ephemeral_read_only_and_json(tmp_path: Path) -> None:
    runner = _CodexRecorder(HarnessRun(0, "", ""), "OK")
    CodexProvider(runner=runner, scratch_dir=tmp_path).complete(_request(model="gpt-5.5"))
    argv = runner.calls[0]
    assert argv[:2] == ["codex", "exec"]
    for flag in ("--ephemeral", "--skip-git-repo-check", "--json"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--model") + 1] == "gpt-5.5"
    # no system flag on codex exec: system text is prepended to the prompt
    assert argv[-1] == "be terse\n\nhello"


def test_codex_reads_the_last_message_file_and_usage_events(tmp_path: Path) -> None:
    events = "\n".join(
        [
            json.dumps({"type": "thread.started"}),
            "not json",
            json.dumps(
                {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}}
            ),
        ]
    )
    runner = _CodexRecorder(HarnessRun(0, events, ""), "answer text")
    result = CodexProvider(runner=runner, scratch_dir=tmp_path).complete(_request(model="gpt-5.5"))
    assert result.content == "answer text"
    assert (result.input_tokens, result.output_tokens) == (7, 3)
    assert result.model == "gpt-5.5"


def test_codex_nonzero_exit_is_a_provider_error(tmp_path: Path) -> None:
    runner = _CodexRecorder(HarnessRun(1, "", "ERROR failed to load models cache"), None)
    with pytest.raises(ModelProviderError, match="exited 1.*models cache"):
        CodexProvider(runner=runner, scratch_dir=tmp_path).complete(_request(model="gpt-5.5"))


def test_codex_missing_last_message_is_a_provider_error(tmp_path: Path) -> None:
    runner = _CodexRecorder(HarnessRun(0, "", ""), None)
    with pytest.raises(ModelProviderError, match="no last message"):
        CodexProvider(runner=runner, scratch_dir=tmp_path).complete(_request(model="gpt-5.5"))
