"""The coding-agent harness as a ModelProvider (ADR 0112). Every test
injects a runner; no process is spawned. The Claude Code JSON shapes below
are copied from two real runs on 2026-09-03 (one logged in, one under
`--bare`); the Grok shapes are from five real runs on 2026-09-04 (ADR 0154);
the Codex shapes are from its documented flags only."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from aef.providers import command_provider, harness_provider
from aef.providers.base import (
    CompletionRequest,
    FallbackProvider,
    ModelProviderError,
    ProviderMessage,
)
from aef.providers.harness_provider import (
    ClaudeCodeProvider,
    CodexProvider,
    GrokProvider,
    HarnessRun,
)

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


# ---------------------------------------------------------------------------
# Grok — reproduced shape (ADR 0154)
# ---------------------------------------------------------------------------
# Verbatim from `grok -p ... --output-format json` on grok 1.0.5, 2026-09-04.
# The field names are NOT Claude's: `text` not `result`, `stopReason` not
# `stop_reason`, and no `is_error`.
_GROK_OK = {
    "text": "OK",
    "stopReason": "end_turn",
    "sessionId": "01a06f43-4b63-7233-b0e1-6e8de16e7d73",
    "requestId": "e2355477-9b9e-4b95-a14a-48180d492743",
    "thought": "The user wants me to reply with a single word: OK.\n",
    "usage": {
        "input_tokens": 24001,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 141,
        "reasoning_tokens": 136,
        "total_tokens": 24142,
    },
    "num_turns": 1,
    "total_cost_usd": 0.00830416,
    "modelUsage": {
        "grok-4.6-build": {
            "inputTokens": 24001,
            "outputTokens": 141,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
            "modelCalls": 1,
            "costUSD": 0.00830416,
        }
    },
}
# Verbatim from the same CLI given a model id that does not exist: exit 1,
# this object on stdout, the same sentence on stderr.
_GROK_ERROR = {
    "type": "error",
    "message": (
        "Couldn't set model 'not-a-real-model': Invalid params: \"unknown model id\". "
        "Run 'grok models' to see available models."
    ),
}


def _grok_argv(runner: _Recorder, **overrides: object) -> list[str]:
    GrokProvider(runner=runner).complete(_request(**overrides))
    return runner.calls[0]


def test_grok_argv_is_the_headless_single_turn_door() -> None:
    """`grok` with no flags opens a TUI. `-p/--single` is the headless door,
    and unlike `claude -p` the prompt is that flag's VALUE, not a trailing
    positional — pinned because guessing it wrong yields an interactive
    session that hangs, not an error."""
    argv = _grok_argv(_Recorder(_ok(_GROK_OK)))
    assert argv[0] == "grok"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[-2:] == ["-p", "hello"]
    assert argv[argv.index("-m") + 1] == "claude-fable-5-1"
    assert argv[argv.index("--system-prompt-override") + 1] == "be terse"


def test_grok_argv_is_toolless_and_asks_for_no_web_no_subagent_no_plan() -> None:
    argv = _grok_argv(_Recorder(_ok(_GROK_OK)))
    assert argv[argv.index("--tools") + 1] == ""  # a completion, not an agent
    for flag in ("--disable-web-search", "--no-subagents", "--no-plan", "--verbatim"):
        assert flag in argv


def test_grok_runs_in_an_empty_directory_because_it_has_no_safe_mode() -> None:
    """ADR 0154's measurement: `--cwd <empty dir>` took the call from 24,001
    to 18,581 input tokens by dropping this repo's `CLAUDE.md`/`AGENTS.md`,
    and `grok --help` offers no `--safe-mode`. The directory IS the flag, so
    it must exist and be empty at the moment the CLI runs."""
    seen: list[Path] = []

    class _CwdRecorder(_Recorder):
        def __call__(self, argv: Sequence[str], timeout_s: float) -> HarnessRun:
            cwd = Path(argv[argv.index("--cwd") + 1])
            assert cwd.is_dir(), "--cwd names a directory that does not exist at call time"
            assert list(cwd.iterdir()) == [], "the isolation directory is not empty"
            seen.append(cwd)
            return super().__call__(argv, timeout_s)

    GrokProvider(runner=_CwdRecorder(_ok(_GROK_OK))).complete(_request())
    assert len(seen) == 1
    assert not seen[0].exists(), "the temporary isolation directory outlived the call"


def test_grok_isolation_can_be_turned_off_and_then_passes_no_cwd() -> None:
    runner = _Recorder(_ok(_GROK_OK))
    GrokProvider(runner=runner, isolate_project_context=False).complete(_request())
    assert "--cwd" not in runner.calls[0]


def test_grok_drops_max_tokens_and_says_so() -> None:
    argv = _grok_argv(_Recorder(_ok(_GROK_OK)), max_tokens=400)
    assert not any("400" in a or "max-tokens" in a or "max_tokens" in a for a in argv)
    assert "max_tokens" in (GrokProvider.__doc__ or "")


def test_grok_result_reads_text_stopreason_and_usage_not_claudes_names() -> None:
    """The whole point of running the CLI once: `result`/`stop_reason` are
    Claude's spellings and would each have silently produced an empty
    completion here."""
    result = GrokProvider(runner=_Recorder(_ok(_GROK_OK))).complete(_request())
    assert result.content == "OK"
    assert result.stop_reason == "end_turn"
    assert (result.input_tokens, result.output_tokens) == (24001, 141)


def test_grok_input_tokens_counts_the_cached_context_too() -> None:
    """Grok's `usage.input_tokens` is the UNCACHED remainder. Reporting it
    raw let a de-isolated provider pass the live isolation guard, because the
    leaked instructions were cached that run (ADR 0154). This payload is the
    same 24,001-token context with 5,248 of it served from cache: the number
    a caller sees must not move because of that."""
    cached = {
        **_GROK_OK,
        "usage": {
            **_GROK_OK["usage"],  # type: ignore[dict-item]
            "input_tokens": 18753,
            "cache_read_input_tokens": 5248,
        },
    }
    result = GrokProvider(runner=_Recorder(_ok(cached))).complete(_request())
    assert result.input_tokens == 24001
    # From modelUsage. NOT an id `-m` accepts — `grok models` lists
    # `grok-4.6`, and `-m grok-4.6-build` exits 1 (ADR 0154).
    assert result.model == "grok-4.6-build"


def test_grok_error_object_is_a_provider_error() -> None:
    runner = _Recorder(HarnessRun(returncode=1, stdout=json.dumps(_GROK_ERROR), stderr=""))
    with pytest.raises(ModelProviderError, match="unknown model id"):
        GrokProvider(runner=runner).complete(_request())


def test_grok_error_object_at_exit_zero_is_still_a_provider_error() -> None:
    """Not observed on 1.0.5, and handled anyway: `claude` reports auth
    failures with exit 0 and an error payload (ADR 0150), and a zero exit
    carrying `{"type": "error"}` would otherwise be returned as an empty,
    successful completion."""
    with pytest.raises(ModelProviderError, match="grok error"):
        GrokProvider(runner=_Recorder(_ok(_GROK_ERROR))).complete(_request())


def test_grok_non_json_output_is_a_provider_error() -> None:
    runner = _Recorder(HarnessRun(returncode=0, stdout="Welcome to Grok", stderr=""))
    with pytest.raises(ModelProviderError, match="non-JSON"):
        GrokProvider(runner=runner).complete(_request())


def test_grok_refusal_raises_and_fallback_falls_through() -> None:
    refusing = GrokProvider(
        runner=_Recorder(_ok({**_GROK_OK, "text": "", "stopReason": "refusal"}))
    )
    good = GrokProvider(runner=_Recorder(_ok({**_GROK_OK, "text": "answered"})))
    with pytest.raises(ModelProviderError, match="refusal"):
        refusing.complete(_request())
    assert FallbackProvider([refusing, good]).complete(_request()).content == "answered"


def test_grok_tool_role_is_refused_before_any_process_is_spawned() -> None:
    runner = _Recorder(_ok(_GROK_OK))
    request = _request(messages=(ProviderMessage(role="tool", content="{}"),))
    with pytest.raises(ModelProviderError, match="role 'tool'"):
        GrokProvider(runner=runner).complete(request)
    assert runner.calls == []


# ---------------------------------------------------------------------------
# Which model actually answered (ADR 0154, defect found by M1 on the real CLI)
# ---------------------------------------------------------------------------
# Verbatim shape from a `--model claude-opus-5` run: the CLI bills a helper
# model alongside the requested one, and the helper is FIRST in the map.
_CLAUDE_TWO_MODELS = {
    **_CLAUDE_OK,
    "modelUsage": {
        "claude-haiku-4-5-20251001": {"inputTokens": 301, "outputTokens": 7},
        "claude-opus-5": {"inputTokens": 2, "outputTokens": 4},
    },
}


def test_the_helper_model_is_not_reported_as_the_one_that_answered() -> None:
    """The defect, as a test. `next(iter(modelUsage))` returned
    `claude-haiku-4-5-20251001` for a run made with `--model claude-opus-5`,
    and `CompletionResult.model` is what every provenance record and every
    recorded corpus scenario carries — so an ADR naming the model a
    measurement was taken on would have named the wrong one."""
    result = ClaudeCodeProvider(runner=_Recorder(_ok(_CLAUDE_TWO_MODELS))).complete(
        _request(model="claude-opus-5")
    )
    assert result.model == "claude-opus-5"


def test_an_alias_resolved_to_a_dated_id_is_still_recognised() -> None:
    """Rule 2, and the reason `modelUsage` is read at all rather than echoing
    the request: the dated id is more informative than the alias."""
    payload = {
        **_CLAUDE_OK,
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"outputTokens": 7},
            "claude-opus-5-20260101": {"outputTokens": 4},
        },
    }
    result = ClaudeCodeProvider(runner=_Recorder(_ok(payload))).complete(
        _request(model="claude-opus-5")
    )
    assert result.model == "claude-opus-5-20260101"


def test_an_unrecognised_map_falls_back_to_whichever_model_wrote_the_answer() -> None:
    """Rule 3. The helper writes a handful of tokens; the model that answered
    writes the answer."""
    payload = {
        **_CLAUDE_OK,
        "modelUsage": {
            "some-helper": {"outputTokens": 7},
            "the-one-that-answered": {"outputTokens": 4000},
        },
    }
    result = ClaudeCodeProvider(runner=_Recorder(_ok(payload))).complete(
        _request(model="not-in-the-map")
    )
    assert result.model == "the-one-that-answered"


def test_a_map_with_no_token_counts_still_names_something() -> None:
    """Rule 4. The shipped fixture `{"claude-fable-5-1": {}}` has no counts at
    all, and one entry is one entry."""
    result = ClaudeCodeProvider(runner=_Recorder(_ok(_CLAUDE_OK))).complete(_request())
    assert result.model == "claude-fable-5-1"


def test_an_empty_map_falls_back_to_what_was_requested_not_to_empty_string() -> None:
    payload = {**_CLAUDE_OK, "modelUsage": {}}
    result = ClaudeCodeProvider(runner=_Recorder(_ok(payload))).complete(
        _request(model="claude-opus-5")
    )
    assert result.model == "claude-opus-5"


def test_grok_uses_the_same_rule_so_the_two_adapters_cannot_drift() -> None:
    """One function, both call sites. Grok has only ever been observed with a
    single-key map, which is exactly the state Claude Code was believed to be
    in until someone ran it with a helper model in play."""
    payload = {
        **_GROK_OK,
        "modelUsage": {
            "grok-helper": {"outputTokens": 3},
            "grok-4.6-build": {"outputTokens": 141},
        },
    }
    result = GrokProvider(runner=_Recorder(_ok(payload))).complete(_request(model="grok-4.6"))
    # Rule 2: `grok-4.6` extends to `grok-4.6-build`, which is what the server
    # calls the model that answered.
    assert result.model == "grok-4.6-build"


def test_codex_and_command_report_the_requested_model_and_have_no_such_map() -> None:
    """The other half of the audit. `codex exec --json` emits no `modelUsage`
    and `CommandProvider` has no field for one, so neither can pick the wrong
    key — recorded here so the next reader does not have to re-derive it."""
    src = Path(harness_provider.__file__).read_text()
    codex_body = src[src.index("class CodexProvider") : src.index("class GrokProvider")]
    assert "CodexProvider" in codex_body and "GrokProvider" not in codex_body
    assert "modelUsage" not in codex_body
    assert "modelUsage" not in Path(command_provider.__file__).read_text()
