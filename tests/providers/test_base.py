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
