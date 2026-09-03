import subprocess
import sys

import pytest

from aef.config import UnsupportedProviderImplError, build_model_provider
from aef.config.schema import ModelProviderConfig
from aef.providers.base import FallbackProvider


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
