import pytest

from aef.providers.base import (
    CompletionRequest,
    CompletionResult,
    FallbackProvider,
    ModelProvider,
    ModelProviderError,
    ProviderMessage,
)


class _FailingProvider(ModelProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ModelProviderError(f"{self.name} is down")


class _WorkingProvider(ModelProvider):
    def __init__(self, name: str = "working") -> None:
        self.name = name

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="ok", model=request.model, input_tokens=1, output_tokens=1)


def _request() -> CompletionRequest:
    return CompletionRequest(messages=(ProviderMessage(role="user", content="hi"),), model="m")


def test_fallback_uses_first_working_provider() -> None:
    provider = FallbackProvider([_FailingProvider("primary"), _WorkingProvider("secondary")])
    result = provider.complete(_request())
    assert result.content == "ok"


def test_fallback_raises_when_all_providers_fail() -> None:
    provider = FallbackProvider([_FailingProvider("primary"), _FailingProvider("secondary")])
    with pytest.raises(ModelProviderError, match="primary is down"):
        provider.complete(_request())


def test_fallback_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError):
        FallbackProvider([])


def test_fallback_does_not_call_later_providers_once_one_succeeds() -> None:
    calls: list[str] = []

    class _CountingProvider(ModelProvider):
        def __init__(self, name: str) -> None:
            self.name = name

        def complete(self, request: CompletionRequest) -> CompletionResult:
            calls.append(self.name)
            return CompletionResult(
                content=self.name, model=request.model, input_tokens=0, output_tokens=0
            )

    provider = FallbackProvider([_CountingProvider("first"), _CountingProvider("second")])
    result = provider.complete(_request())
    assert result.content == "first"
    assert calls == ["first"]


def test_fallback_tries_a_third_provider_after_two_failures() -> None:
    provider = FallbackProvider(
        [_FailingProvider("primary"), _FailingProvider("secondary"), _WorkingProvider("tertiary")]
    )
    result = provider.complete(_request())
    assert result.content == "ok"


def test_fallback_all_fail_error_names_every_provider_not_just_the_first() -> None:
    provider = FallbackProvider([_FailingProvider("primary"), _FailingProvider("secondary")])
    with pytest.raises(ModelProviderError) as exc_info:
        provider.complete(_request())
    message = str(exc_info.value)
    assert "primary" in message and "primary is down" in message
    assert "secondary" in message and "secondary is down" in message


def test_fallback_does_not_catch_non_model_provider_errors() -> None:
    """A bug in an adapter (a raw exception leaking past the vendor
    boundary, contradicting ModelProvider's own contract) must surface
    immediately, not be silently retried against the next provider as if
    it were an ordinary vendor failure."""

    class _BuggyProvider(ModelProvider):
        name = "buggy"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            raise TypeError("adapter bug: forgot to wrap this in ModelProviderError")

    provider = FallbackProvider([_BuggyProvider(), _WorkingProvider("never_reached")])
    with pytest.raises(TypeError, match="adapter bug"):
        provider.complete(_request())
