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

All three adapters (`claude`, `codex`, `grok`) are single-turn and tool-less
by construction: a graph node calling a model wants a completion, not an
agent that edits the working tree. Multi-message requests are rendered into
one transcript because the CLIs take one prompt — good enough for the
reflection and consolidation nodes this runtime ships, and stated here so
nobody mistakes it for a chat API.

A harness this repo has never seen is **configuration, not code**: see
`aef.providers.command_provider.CommandProvider` (`impl: command`), which
takes an argv template and an output extractor from `aef.yaml`. The three
adapters here exist because each one carries measured, non-obvious isolation
knowledge that no owner should have to rediscover — not because a fourth
harness needs a fourth class.
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

# The smallest VALID MCP config: an explicit, empty server set. Paired with
# `--strict-mcp-config` this is what stops the operator's own MCP servers
# reaching a node's model call. A bare `{}` fails the CLI's schema.
_EMPTY_MCP_CONFIG = '{"mcpServers":{}}'


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


def split_request(request: CompletionRequest) -> tuple[str | None, str]:
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


def answering_model(model_usage: dict[str, object], requested: str | None) -> str | None:
    """Which model in a CLI's `modelUsage` map actually answered.

    **`next(iter(model_usage))` — the first key — is wrong, and was wrong on
    `main`.** These CLIs bill a *helper* model alongside the one asked for
    (Claude Code runs a small model for its own housekeeping), and the helper
    is not last in the map. Running `--model claude-opus-5` produced a
    `modelUsage` whose first key was `claude-haiku-4-5-20251001`, so
    `CompletionResult.model` said Haiku, and every provenance record and
    recorded corpus scenario downstream inherited it:

        "provenance": [{"node_id": "prompt_agent",
                        "model": "claude-haiku-4-5-20251001", ...}]

    That is worse than an unhelpful label. Provenance is the field a reader
    trusts when an ADR says which model a measurement was taken on, and this
    one named a model that wrote none of the answer.

    Four rules, in order:

    1. the requested name, if the map has it;
    2. a key that *extends* the requested name (`claude-opus-5` ->
       `claude-opus-5-20260101`) — an alias resolves to a dated id, which is
       exactly the case that made reading `modelUsage` worth doing at all;
    3. the key that produced the most output tokens — the helper writes a
       handful, the answering model writes the answer;
    4. the first key, which is where we came in: with one entry it is right,
       and with none there is nothing better to say.
    """
    if not model_usage:
        return None
    if requested:
        if requested in model_usage:
            return requested
        extended = [k for k in model_usage if k.startswith(f"{requested}-")]
        if len(extended) == 1:
            return extended[0]

    def _output_tokens(key: str) -> int:
        entry = model_usage[key]
        if not isinstance(entry, dict):
            return 0
        value = entry.get("outputTokens", entry.get("output_tokens", 0))
        return int(value) if isinstance(value, (int, float)) else 0

    keys = list(model_usage)
    best = max(keys, key=_output_tokens)
    return best if _output_tokens(best) else keys[0]


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

    - `--strict-mcp-config` with `--mcp-config '{"mcpServers":{}}'` — "only use
      MCP servers from `--mcp-config`", and that config declares none. The
      value must be a valid MCP config document: a bare `{}` is refused by the
      CLI's own schema (ADR 0150). This is the pair
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
        system, prompt = split_request(request)
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
            # `{}` is REJECTED — the CLI validates this against a schema whose
            # `mcpServers` key is required, and every call died with
            # `Error: Invalid MCP configuration: mcpServers: Invalid input`
            # from the moment ADR 0126 added the flag until ADR 0150 fixed it.
            # It shipped because the quota was exhausted that day, so the tests
            # could only assert the SHAPE of argv, and argv was well-formed.
            _EMPTY_MCP_CONFIG,
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
        requested = request.model or self._default_model
        # NOT the first key of the map — see `answering_model`.
        answered_by = answering_model(model_usage, requested) or requested or ""
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
        system, prompt = split_request(request)
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


class GrokProvider(ModelProvider):
    """`grok -p` under the Grok login (ADR 0154). **Reproduced live** on
    `grok 1.0.5 (5115b46bc909) [stable]`, 2026-09-04, five real runs.

    `grok` with no flags opens an interactive TUI. The headless door is
    `-p, --single <PROMPT>` — "Single-turn prompt. Prints the response to
    stdout and exits" — which is a *flag taking the prompt as its value*,
    not a positional argument like `claude -p <prompt>`. Paired with
    `--output-format json` a run prints one JSON object:

        {"text": "OK", "stopReason": "end_turn",
         "sessionId": "...", "requestId": "...", "thought": "...",
         "usage": {"input_tokens": 24001, "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0, "output_tokens": 141,
                   "reasoning_tokens": 136, "total_tokens": 24142},
         "num_turns": 1, "total_cost_usd": 0.00830416,
         "modelUsage": {"grok-4.6-build": {"inputTokens": 24001, ...}}}

    The field names are **not** Claude's: the reply is `text` (Claude says
    `result`), the stop reason is `stopReason` (Claude says `stop_reason`),
    and there is no `is_error`. A failure exits non-zero and prints
    `{"type": "error", "message": "..."}` on stdout with the same text on
    stderr — measured by asking for a model that does not exist.

    **`CompletionResult.input_tokens` is the SUM**: `usage.input_tokens` plus
    `cache_read_input_tokens` plus `cache_creation_input_tokens`, which is
    what `total_tokens` minus the output comes to. Grok's own
    `usage.input_tokens` is only the *uncached remainder*, and it swings by
    thousands between two identical calls depending on cache state. Reporting
    it raw cost this adapter a real defect: the live isolation guard below,
    written against the raw field, **passed on a deliberately de-isolated
    provider** because the leaked instructions happened to be cached that run
    (ADR 0154). A number that moves for reasons unrelated to what was sent
    cannot guard what was sent.

    **Isolation, measured (ADR 0150's rule) rather than assumed.** Grok
    discovers project instructions the way Claude Code does — `grok inspect`
    in this repo listed `Claude.md` (~3,369 tokens), `Agents.md` (~1,784)
    and the operator's global `~/.claude/Claude.md` (~142), plus 78 skills.
    Four arms, same prompt, same box:

        arm                                   uncached  cache_read  TOTAL IN
        baseline (repo cwd, no flags)           24,001           0    24,001
        tool flags only (repo cwd)              18,272       5,248    23,520
        --cwd <empty dir> only                  12,821       5,760    18,581
        both                                    12,688       5,248    17,936

    Read the last column: it is the only one that separates the isolated arms
    from the unisolated ones, and it is what this adapter reports.

    **`--cwd <empty dir>` is the load-bearing lever**, and it is a directory
    rather than a flag because Grok has no `--safe-mode`: nothing in
    `grok --help` disables customization discovery, so the only way to stop
    a repo's `CLAUDE.md`/`AGENTS.md`/skills reaching a node's model call is
    to run the CLI somewhere that has none. This adapter therefore runs each
    call in a fresh empty temporary directory (`isolate_project_context`,
    default on). The tool flags — `--tools ""` (allow no built-in tool),
    `--disable-web-search`, `--no-subagents`, `--no-plan`, `--max-turns 1`,
    `--verbatim` — buy 481 tokens on their own and 645 on top of `--cwd`,
    which is inside run-to-run variation. They are kept because tool-less is
    the *safety* property this adapter promises, not because they are cheap.

    **The isolation is incomplete and there is no flag that completes it.**
    Even fully isolated the call carried ~17.9k tokens of input, and the
    reply's own `thought` field quoted a rule that exists only in the
    operator's global `~/.claude/Claude.md`. Claude Code's `--safe-mode` has
    no Grok equivalent in 1.0.5. Stated here rather than in a footnote
    because an owner comparing per-call cost across backends will otherwise
    read the `--cwd` win as the whole story.

    **`CompletionResult.model` is not a `-m` argument.** `modelUsage` is keyed
    `grok-4.6-build`; `grok models` lists `grok-4.6` and `grok-4.5`, and
    `-m grok-4.6-build` exits 1 with `Invalid params: "unknown model id"` —
    measured. This adapter reports the answering name because that is what
    `CompletionResult.model` means and what `ClaudeCodeProvider` does, but
    round-tripping it into the next `CompletionRequest.model` fails. Nothing
    in this runtime does that today; this is the note for the first caller
    that tries.

    **`CompletionRequest.max_tokens` is dropped**, for the same reason it is
    on `ClaudeCodeProvider`: `grok --help` has `--max-turns` but no
    output-length flag. A caller setting `max_tokens=400` gets whatever the
    model writes. Said out loud because a silently ignored parameter reads
    as a control that exists.
    """

    name = "grok"

    @property
    def default_model(self) -> str | None:
        return self._default_model

    def __init__(
        self,
        *,
        default_model: str | None = None,
        executable: str = "grok",
        timeout_s: float = 600.0,
        runner: Runner = subprocess_runner,
        scratch_dir: Path | None = None,
        isolate_project_context: bool = True,
    ) -> None:
        self._default_model = default_model
        self._executable = executable
        self._timeout_s = timeout_s
        self._runner = runner
        self._scratch_dir = scratch_dir
        self._isolate_project_context = isolate_project_context

    def argv(self, request: CompletionRequest, isolation_cwd: Path | None) -> list[str]:
        system, prompt = split_request(request)
        model = request.model or self._default_model
        argv = [
            self._executable,
            "--output-format",
            "json",
            "--max-turns",
            "1",
            # A completion, not an agent: no built-in tool, no web fetch, no
            # subagent, no plan mode, and the prompt sent as written.
            "--tools",
            "",
            "--disable-web-search",
            "--no-subagents",
            "--no-plan",
            "--verbatim",
        ]
        if isolation_cwd is not None:
            # The only lever that drops project instructions — see the class
            # docstring's four-arm measurement. There is no `--safe-mode`.
            argv += ["--cwd", str(isolation_cwd)]
        if model:
            argv += ["-m", model]
        if system is not None:
            # `--system-prompt-override` is the documented spelling;
            # `--system-prompt` is a compat alias for it.
            argv += ["--system-prompt-override", system]
        # `-p` TAKES the prompt: unlike `claude -p`, the prompt is this
        # flag's value and not a trailing positional.
        argv += ["-p", prompt]
        return argv

    def _complete_in(self, request: CompletionRequest, isolation_cwd: Path | None) -> HarnessRun:
        return self._runner(self.argv(request, isolation_cwd), self._timeout_s)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        if self._isolate_project_context:
            with tempfile.TemporaryDirectory(dir=self._scratch_dir) as tmp:
                run = self._complete_in(request, Path(tmp))
        else:
            run = self._complete_in(request, None)
        if run.returncode != 0:
            raise ModelProviderError(
                f"grok exited {run.returncode}: {run.stderr.strip()[-500:] or run.stdout[-500:]}"
            )
        try:
            payload = json.loads(run.stdout)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                f"grok returned non-JSON output: {run.stdout[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise ModelProviderError(f"grok returned non-object JSON: {run.stdout[:200]!r}")
        if payload.get("type") == "error":
            # Observed with exit 1; handled at exit 0 too because that is
            # exactly the shape `claude` uses for auth failures (ADR 0150),
            # and a zero exit carrying an error would otherwise be returned
            # as an empty completion.
            raise ModelProviderError(f"grok error: {payload.get('message', '')}")
        stop_reason = payload.get("stopReason")
        if stop_reason == "refusal":
            raise ModelProviderError("grok refusal: no content returned")
        usage = payload.get("usage") or {}
        model_usage = payload.get("modelUsage") or {}
        requested = request.model or self._default_model
        # NOT the first key of the map — see `answering_model`.
        answered_by = answering_model(model_usage, requested) or requested or ""
        return CompletionResult(
            content=str(payload.get("text", "")),
            model=answered_by,
            # The WHOLE context, cached parts included — see the class
            # docstring. `usage.input_tokens` alone is the uncached remainder
            # and swings by thousands between identical calls.
            input_tokens=(
                int(usage.get("input_tokens", 0))
                + int(usage.get("cache_read_input_tokens", 0))
                + int(usage.get("cache_creation_input_tokens", 0))
            ),
            output_tokens=int(usage.get("output_tokens", 0)),
            stop_reason=stop_reason,
        )
