import subprocess
import sys

import pytest
from pydantic import ValidationError

from aef.config import UnsupportedProviderImplError, build_model_provider
from aef.config.schema import ModelProviderConfig
from aef.providers.base import CompletionRequest, FallbackProvider, ProviderMessage


def test_importing_aef_config_does_not_require_anthropic() -> None:
    """aef-core's `anthropic` extra is optional; importing aef.config (used
    by `aef doctor`/`aef init`, which have nothing to do with model
    providers) must not force it to be installed. Only actually building an
    anthropic-backed provider should import the SDK. Run in a fresh
    subprocess — this process has likely already imported `anthropic` via
    other test modules, which would make an in-process check meaningless."""
    result = subprocess.run(
        [sys.executable, "-c", "import aef.config, sys; print('anthropic' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_build_anthropic_provider() -> None:
    from aef.providers.anthropic_provider import AnthropicProvider

    provider = build_model_provider(ModelProviderConfig(impl="anthropic", model="claude-x"))
    assert isinstance(provider, AnthropicProvider)


def test_unsupported_impl_raises_clearly() -> None:
    with pytest.raises(UnsupportedProviderImplError, match="openai"):
        build_model_provider(ModelProviderConfig(impl="openai", model="gpt-x"))


def test_fallback_wraps_in_fallback_provider_when_all_supported() -> None:
    config = ModelProviderConfig(impl="anthropic", model="claude-x", fallback=["anthropic"])
    provider = build_model_provider(config)
    assert isinstance(provider, FallbackProvider)


def test_fallback_with_unsupported_impl_raises_not_silently_dropped() -> None:
    config = ModelProviderConfig(impl="anthropic", model="claude-x", fallback=["local-llama"])
    with pytest.raises(UnsupportedProviderImplError, match="local-llama"):
        build_model_provider(config)


def test_no_fallback_returns_bare_provider_not_wrapped() -> None:
    from aef.providers.anthropic_provider import AnthropicProvider

    provider = build_model_provider(ModelProviderConfig(impl="anthropic", model="claude-x"))
    assert type(provider) is AnthropicProvider


def test_build_claude_code_provider_carries_the_config_model_as_default() -> None:
    """ADR 0112: the harness login is the credential in an agentic repo, and
    `model_provider.model` — which validated but was never read — is the
    provider's default."""
    from aef.providers.harness_provider import ClaudeCodeProvider

    provider = build_model_provider(
        ModelProviderConfig(impl="claude_code", model="claude-fable-5-1")
    )
    assert type(provider) is ClaudeCodeProvider
    assert provider.default_model == "claude-fable-5-1"


def test_build_codex_provider() -> None:
    from aef.providers.harness_provider import CodexProvider

    provider = build_model_provider(ModelProviderConfig(impl="codex", model="gpt-5.5"))
    assert type(provider) is CodexProvider
    assert provider.default_model == "gpt-5.5"


def test_unsupported_impl_message_names_the_harness_impls() -> None:
    with pytest.raises(UnsupportedProviderImplError, match="claude_code"):
        build_model_provider(ModelProviderConfig(impl="openai", model="gpt-x"))


# ---------------------------------------------------------------------------
# Grok and the generic command harness (ADR 0154)
# ---------------------------------------------------------------------------
_GROK_COMMAND: dict[str, object] = {
    "argv": ["grok", "--output-format", "json", "{model}", "{system}", "-p", "{prompt}"],
    "model_argv": ["-m", "{model}"],
    "system_argv": ["--system-prompt-override", "{system}"],
    "output": "json_pointer",
    "output_pointer": "/text",
    "usage_pointer": "/usage/input_tokens",
}


def test_build_grok_provider() -> None:
    from aef.providers.harness_provider import GrokProvider

    provider = build_model_provider(ModelProviderConfig(impl="grok", model="grok-4.6"))
    assert type(provider) is GrokProvider
    assert provider.default_model == "grok-4.6"


def test_build_command_provider_from_a_template_alone() -> None:
    """The whole claim of `impl: command`: a harness this repo has never
    seen becomes an owner's config, not a class someone here guesses at."""
    from aef.providers.command_provider import CommandProvider

    config = ModelProviderConfig(impl="command", model="grok-4.6", command=_GROK_COMMAND)
    provider = build_model_provider(config)
    assert type(provider) is CommandProvider
    assert provider.default_model == "grok-4.6"
    argv, _ = provider.build(
        CompletionRequest(messages=(ProviderMessage(role="user", content="hi"),), model="")
    )
    # `model_provider.model` reaches the CLI as the default (ADR 0112's rule
    # for a field that validated for months while nothing read it).
    assert argv[argv.index("-m") + 1] == "grok-4.6"


def test_impl_command_without_a_command_block_is_refused_at_load() -> None:
    with pytest.raises(ValidationError, match="no `command:` block"):
        ModelProviderConfig(impl="command", model="x")


def test_a_command_block_under_another_impl_is_refused_rather_than_ignored() -> None:
    """ADR 0100's rule. A block that validates while nothing reads it lets an
    owner believe a harness is configured."""
    with pytest.raises(ValidationError, match="never reads it"):
        ModelProviderConfig(impl="claude_code", model="x", command=_GROK_COMMAND)


def test_command_cannot_appear_in_fallback_because_it_has_one_template() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ModelProviderConfig(impl="claude_code", model="x", fallback=["command"])


def test_a_bad_template_fails_at_config_load_not_at_the_first_model_call() -> None:
    """Same validator as `CommandProvider.__init__`, called from the schema —
    so an `aef.yaml` typo fails when the config loads rather than halfway
    through a graph run, after the checkpoint."""
    with pytest.raises(ValidationError, match="exactly once"):
        ModelProviderConfig(impl="command", model="x", command={"argv": ["echo"]})


def test_the_unsupported_impl_message_names_grok_and_command() -> None:
    with pytest.raises(UnsupportedProviderImplError, match="grok"):
        build_model_provider(ModelProviderConfig(impl="openai", model="gpt-x"))
    with pytest.raises(UnsupportedProviderImplError, match="command"):
        build_model_provider(ModelProviderConfig(impl="openai", model="gpt-x"))


def test_the_command_isolation_assertion_is_validated_at_config_load() -> None:
    """One rule, two doors (ADR 0091): the same function `CommandProvider`
    calls, so a typo in `aef.yaml` fails at load rather than at first use.
    The claim itself is never verified against the binary — it cannot be, and
    ADR 0169 says so in the field's own docstring."""
    block: dict[str, object] = {
        "argv": ["cli", "-p", "{prompt}"],
        "isolation": ["no_tools", "single_turn"],
    }
    config = ModelProviderConfig(impl="command", model="m", command=block)  # type: ignore[arg-type]
    assert config.command is not None
    assert config.command.isolation == ["no_tools", "single_turn"]

    with pytest.raises(ValidationError, match="unknown isolation"):
        ModelProviderConfig(
            impl="command",
            model="m",
            command={**block, "isolation": ["no_toolz"]},  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="not the owner's to assert"):
        ModelProviderConfig(
            impl="command",
            model="m",
            command={**block, "isolation": ["system_role"]},  # type: ignore[arg-type]
        )


def test_the_owners_isolation_assertion_reaches_the_built_provider() -> None:
    """A block that validates and is never read is the ADR 0100 shape — and
    the whole point of ADR 0169 is that this assertion ends up in the trace."""
    from aef.providers.command_provider import CommandProvider

    provider = build_model_provider(
        ModelProviderConfig(
            impl="command",
            model="m",
            command={"argv": ["cli", "-p", "{prompt}"], "isolation": ["no_tools"]},  # type: ignore[arg-type]
        )
    )
    assert isinstance(provider, CommandProvider)
    assert provider.asserted_isolation == frozenset({"no_tools"})
    # And the half the owner does not get to assert is derived: no `{system}`
    # slot, so the persona would go out in the user turn.
    assert provider.isolation == frozenset({"no_tools", "user_turn_persona"})


def test_effort_reaches_the_providers_that_have_a_knob_for_it() -> None:
    from aef.providers.anthropic_provider import AnthropicProvider
    from aef.providers.harness_provider import ClaudeCodeProvider

    anth = build_model_provider(ModelProviderConfig(impl="anthropic", model="m", effort="low"))
    assert isinstance(anth, AnthropicProvider)
    assert anth._effort == "low"
    cc = build_model_provider(ModelProviderConfig(impl="claude_code", model="m", effort="max"))
    assert isinstance(cc, ClaudeCodeProvider)
    assert "--effort" in cc.argv(
        CompletionRequest(messages=(ProviderMessage(role="user", content="x"),), model="")
    )


def test_effort_is_refused_for_an_impl_that_would_ignore_it() -> None:
    """Present-but-ignored is refused, as `command:` is: an owner who sets
    effort on codex would believe it applied."""
    with pytest.raises(ValidationError, match="effort"):
        ModelProviderConfig(impl="codex", model="m", effort="high")
    with pytest.raises(ValidationError, match="effort"):
        ModelProviderConfig(impl="anthropic", model="m", effort="high", fallback=["grok"])


def test_effort_rejects_a_level_that_does_not_exist() -> None:
    with pytest.raises(ValidationError):
        ModelProviderConfig(impl="anthropic", model="m", effort="extreme")  # type: ignore[arg-type]
