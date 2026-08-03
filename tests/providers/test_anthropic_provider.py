from dataclasses import dataclass
from typing import Any

import anthropic
import httpx
import pytest

from aef.providers.anthropic_provider import AnthropicProvider
from aef.providers.base import CompletionRequest, ModelProviderError, ProviderMessage


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResponse:
    model: str
    content: list[_FakeTextBlock]
    usage: _FakeUsage
    stop_reason: str = "end_turn"


class _FakeMessages:
    def __init__(
        self, response: _FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class _FakeClient:
    def __init__(
        self, response: _FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self.messages = _FakeMessages(response=response, error=error)


def _request(**overrides: Any) -> CompletionRequest:
    defaults: dict[str, Any] = {
        "messages": (
            ProviderMessage(role="system", content="be terse"),
            ProviderMessage(role="user", content="hello"),
        ),
        "model": "claude-x",
    }
    defaults.update(overrides)
    return CompletionRequest(**defaults)


def test_complete_extracts_text_and_usage() -> None:
    response = _FakeResponse(
        model="claude-x",
        content=[_FakeTextBlock(text="hi there")],
        usage=_FakeUsage(input_tokens=10, output_tokens=5),
    )
    client = _FakeClient(response=response)
    provider = AnthropicProvider(client=client)

    result = provider.complete(_request())

    assert result.content == "hi there"
    assert result.model == "claude-x"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.stop_reason == "end_turn"


def test_complete_separates_system_from_messages() -> None:
    response = _FakeResponse(
        model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
    )
    client = _FakeClient(response=response)
    provider = AnthropicProvider(client=client)

    provider.complete(_request())

    call = client.messages.calls[0]
    assert call["system"] == "be terse"
    assert call["messages"] == [{"role": "user", "content": "hello"}]


def test_complete_wraps_anthropic_api_error() -> None:
    request_obj = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIError("boom", request_obj, body=None)
    client = _FakeClient(error=error)
    provider = AnthropicProvider(client=client)

    with pytest.raises(ModelProviderError, match="boom"):
        provider.complete(_request())
