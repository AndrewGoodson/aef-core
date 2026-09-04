"""The coding-agent harness as a `ModelProvider` (ADR 0112).

An agentic repo — one whose agents are Claude Code / Codex sessions and
`.md` personas — holds no API key. Its credential is the harness login.
Until this module existed every model path in the runtime went through an
SDK adapter, so in exactly the repos this scaffold is built for, no node
could reach a model and `CLAUDE.md` said the runtime "has nothing to attach
to". This is the attachment: a node's model call becomes one headless run
of the harness CLI under its own auth.

No vendor SDK is imported. The only dependency is the CLI on `PATH`, and the
subprocess is injectable so the adapters are tested without spawning one.

Both adapters are single-turn and tool-less by construction: a graph node
calling a model wants a completion, not an agent that edits the working
tree. Multi-message requests are rendered into one transcript because the
CLIs take one prompt — good enough for the reflection and consolidation
nodes this runtime ships, and stated here so nobody mistakes it for a chat
API.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ModelProviderError,
)


@dataclass(frozen=True)
class HarnessRun:
    """What one CLI invocation produced. The slice of `CompletedProcess`
    the adapters read, so tests can hand one in without a real process."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], HarnessRun]
"""Executes argv with a timeout in seconds and returns the run. Stdin is
closed: Codex reads a prompt from a non-tty stdin and would otherwise hang."""


def subprocess_runner(argv: Sequence[str], timeout_s: float) -> HarnessRun:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ModelProviderError(f"harness executable not found: {argv[0]!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelProviderError(f"harness run exceeded {timeout_s:.0f}s: {argv[0]!r}") from exc
    return HarnessRun(
        returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
    )


def _split_request(request: CompletionRequest) -> tuple[str | None, str]:
    """System text and the single prompt the CLI receives.

    The Messages API has no "tool" role and neither CLI can carry a
    `tool_result`; refuse it by name, as the Anthropic adapter does, before
    any process is spawned."""
    if any(m.role == "tool" for m in request.messages):
        raise ModelProviderError(
            "harness adapters cannot send role 'tool': a headless CLI run takes one "
            "prompt and ProviderMessage's string content cannot express a tool result"
        )
    system = "\n".join(m.content for m in request.messages if m.role == "system") or None
    turns = [m for m in request.messages if m.role != "system"]
    if len(turns) == 1 and turns[0].role == "user":
        return system, turns[0].content
    # Several turns: render a transcript. The CLI is single-turn, and hiding
    # that behind a fake chat would be the dishonest option.
    rendered = "\n\n".join(f"{m.role.capitalize()}: {m.content}" for m in turns)
    return system, rendered


class ClaudeCodeProvider(ModelProvider):
    """`claude -p` under the session's own login. Reproduced 2026-09-03
    inside a running Claude Code session: `--tools ""` and `--max-turns 1`
    give a tool-less single completion; `--output-format json` returns
    `result`, `stop_reason`, `is_error`, `usage` and `modelUsage`.

    `--bare` is deliberately NOT passed: it skips the keychain read and
    answers "Not logged in" — the one flag that would defeat the whole point.

    **The session is isolated, because it used to be inherited** (ADR 0126).
    As first shipped this argv ran inside whatever session the operator had
    configured: an adversarial round measured **211,470 input tokens per
    judge call** ($0.18 at cache-read rates, $2.22 uncached) against 4,684
    for the same prompt with the MCP configuration suppressed — the operator's
    MCP tool schemas and their `~/.claude/CLAUDE.md` were being re-sent on
    every critic and judge call, and the judge answered in the operator's
    personal register. Three flags fix it:

    - `--strict-mcp-config` with `--mcp-config {}` — "only use MCP servers
      from `--mcp-config`", and that config declares none. This is the pair
      the 4,684-token measurement used.
    - `--safe-mode` — "all customizations (CLAUDE.md, skills, plugins, hooks,
      MCP servers, custom commands and agents ...) disabled ... Auth, model
      selection, built-in tools, and permissions work normally". It is the
      only documented flag that drops CLAUDE.md discovery *without* dropping
      the keychain login the way `--bare` does. `--restricted` and
      `--setting-sources` reach settings files only, not memory files.

    `--safe-mode` is taken from `claude --help` (CLI 2.1.260) and is **not
    re-measured live** — the authoring session's model quota was exhausted.
    The CLI tolerates unknown options silently (verified: an invented flag
    changes nothing), so the worst case if a future CLI drops it is that the
    cost stays where it was, not a broken call.

    **`CompletionRequest.max_tokens` is dropped.** The CLI has no
    output-length flag and never had one; a caller that sets `max_tokens=400`
    (`LLMJudge` does) gets whatever the model writes. Stated here because a
    silently ignored parameter reads as a control that exists. The length
    controls that do work are prompt-side.
    """

    name = "claude_code"

    @property
    def default_model(self) -> str | None:
        return self._default_model

    def __init__(
        self,
        *,
        default_model: str | None = None,
        executable: str = "claude",
        timeout_s: float = 600.0,
        runner: Runner = subprocess_runner,
    ) -> None:
        self._default_model = default_model
        self._executable = executable
        self._timeout_s = timeout_s
        self._runner = runner

    def argv(self, request: CompletionRequest) -> list[str]:
        system, prompt = _split_request(request)
        model = request.model or self._default_model
        argv = [
            self._executable,
            "-p",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--tools",
            "",
            # Isolation from the operator's own session — see the class
            # docstring for the 211,470 -> 4,684 input-token measurement.
            "--strict-mcp-config",
            "--mcp-config",
            "{}",
            "--safe-mode",
        ]
        if model:
            argv += ["--model", model]
        if system is not None:
            argv += ["--system-prompt", system]
        argv.append(prompt)
        return argv

    def complete(self, request: CompletionRequest) -> CompletionResult:
        argv = self.argv(request)
        run = self._runner(argv, self._timeout_s)
        if run.returncode != 0:
            raise ModelProviderError(
                f"claude exited {run.returncode}: {run.stderr.strip()[-500:] or run.stdout[-500:]}"
            )
        try:
            payload = json.loads(run.stdout)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                f"claude returned non-JSON output: {run.stdout[:200]!r}"
            ) from exc
        if payload.get("is_error"):
            # The CLI reports auth and API failures with exit 0 and
            # `is_error: true` — the smoke run under `--bare` returned
            # "Not logged in · Please run /login" exactly this way.
            raise ModelProviderError(f"claude error: {payload.get('result', '')}")
        stop_reason = payload.get("stop_reason")
        if stop_reason == "refusal":
            raise ModelProviderError("claude refusal: no content returned")
        usage = payload.get("usage") or {}
        # `modelUsage` is keyed by the model that actually answered — the
        # authoritative name when the request used an alias.
        model_usage = payload.get("modelUsage") or {}
        answered_by = next(iter(model_usage), None) or request.model or self._default_model or ""
        return CompletionResult(
            content=str(payload.get("result", "")),
            model=answered_by,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            stop_reason=stop_reason,
        )


class CodexProvider(ModelProvider):
    """`codex exec` under the Codex login. Built from the CLI's documented
    flags and NOT reproduced: the Codex on the authoring box fails before
    reading a prompt (it cannot parse the server's model catalog). Treat the
    output parsing as a hypothesis until a run confirms it (ADR 0112).

    `codex exec` has no system-prompt flag; system text is prepended to the
    prompt. The last assistant message is read from `--output-last-message`
    rather than parsed out of the event stream, because that file is the
    documented contract and the JSONL is not."""

    name = "codex"

    @property
    def default_model(self) -> str | None:
        return self._default_model

    def __init__(
        self,
        *,
        default_model: str | None = None,
        executable: str = "codex",
        timeout_s: float = 600.0,
        runner: Runner = subprocess_runner,
        scratch_dir: Path | None = None,
    ) -> None:
        self._default_model = default_model
        self._executable = executable
        self._timeout_s = timeout_s
        self._runner = runner
        self._scratch_dir = scratch_dir

    def argv(self, request: CompletionRequest, last_message_file: Path) -> list[str]:
        system, prompt = _split_request(request)
        model = request.model or self._default_model
        argv = [
            self._executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--output-last-message",
            str(last_message_file),
        ]
        if model:
            argv += ["--model", model]
        argv.append(f"{system}\n\n{prompt}" if system else prompt)
        return argv

    def complete(self, request: CompletionRequest) -> CompletionResult:
        with tempfile.TemporaryDirectory(dir=self._scratch_dir) as tmp:
            last = Path(tmp) / "last_message.txt"
            argv = self.argv(request, last)
            run = self._runner(argv, self._timeout_s)
            if run.returncode != 0:
                raise ModelProviderError(
                    f"codex exited {run.returncode}: {run.stderr.strip()[-500:]}"
                )
            if not last.exists():
                raise ModelProviderError("codex produced no last message file")
            content = last.read_text(encoding="utf-8")
        input_tokens = output_tokens = 0
        for line in run.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = event.get("usage") if isinstance(event, dict) else None
            if isinstance(usage, dict):
                input_tokens = int(usage.get("input_tokens", input_tokens))
                output_tokens = int(usage.get("output_tokens", output_tokens))
        return CompletionResult(
            content=content,
            model=request.model or self._default_model or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason="end_turn",
        )
