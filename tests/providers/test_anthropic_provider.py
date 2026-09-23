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


class _FalseyFakeClient(_FakeClient):
    def __bool__(self) -> bool:
        return False


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


def test_explicit_falsey_client_dependency_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    injected_response = _FakeResponse(
        model="injected", content=[_FakeTextBlock(text="injected")], usage=_FakeUsage(1, 1)
    )
    constructed_response = _FakeResponse(
        model="constructed", content=[_FakeTextBlock(text="constructed")], usage=_FakeUsage(1, 1)
    )
    injected = _FalseyFakeClient(response=injected_response)
    constructed = _FakeClient(response=constructed_response)
    constructor_calls = 0

    def _construct_anthropic(*args: Any, **kwargs: Any) -> _FakeClient:
        nonlocal constructor_calls
        constructor_calls += 1
        return constructed

    monkeypatch.setattr(anthropic, "Anthropic", _construct_anthropic)

    result = AnthropicProvider(client=injected).complete(_request())

    assert result.content == "injected"
    assert constructor_calls == 0


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


def test_complete_wraps_non_apierror_anthropic_exceptions() -> None:
    """Reproduces a real leak (docs/adr/0037): the SDK has AnthropicError
    subclasses that are NOT APIError (e.g. WorkloadIdentityError from the
    auth/credentials path, RetryableError on retry exhaustion). Catching only
    APIError let those propagate raw past the adapter, violating the base.py
    contract and — worse — defeating FallbackProvider, which only catches
    ModelProviderError. The adapter must wrap the true base, AnthropicError."""
    error = anthropic.WorkloadIdentityError("token fetch failed")
    provider = AnthropicProvider(client=_FakeClient(error=error))

    with pytest.raises(ModelProviderError, match="token fetch failed"):
        provider.complete(_request())


def test_fallbackprovider_recovers_when_primary_raises_a_non_apierror() -> None:
    from aef.providers.base import CompletionResult, FallbackProvider, ModelProvider

    class _Good(ModelProvider):
        name = "good"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(content="recovered", model="m", input_tokens=1, output_tokens=1)

    primary = AnthropicProvider(
        client=_FakeClient(error=anthropic.WorkloadIdentityError("auth down"))
    )
    result = FallbackProvider([primary, _Good()]).complete(_request())
    assert result.content == "recovered"  # fell through instead of aborting on a raw vendor exc


def test_complete_passes_through_user_id_metadata() -> None:
    response = _FakeResponse(
        model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
    )
    client = _FakeClient(response=response)
    provider = AnthropicProvider(client=client)

    provider.complete(_request(metadata={"user_id": "user-123"}))

    call = client.messages.calls[0]
    assert call["metadata"] == {"user_id": "user-123"}


def test_complete_omits_metadata_when_no_user_id() -> None:
    response = _FakeResponse(
        model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
    )
    client = _FakeClient(response=response)
    provider = AnthropicProvider(client=client)

    provider.complete(_request())

    call = client.messages.calls[0]
    assert call["metadata"] is None


def test_complete_ignores_non_user_id_metadata_keys() -> None:
    """Anthropic's API only accepts `user_id` under metadata — other keys
    are vendor-neutral fields another provider might use, and are
    correctly not something this specific adapter can do anything with."""
    response = _FakeResponse(
        model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
    )
    client = _FakeClient(response=response)
    provider = AnthropicProvider(client=client)

    provider.complete(_request(metadata={"session_id": "s-1", "user_id": "user-123"}))

    call = client.messages.calls[0]
    assert call["metadata"] == {"user_id": "user-123"}


# ---------------------------------------------------------------------------
# Model-check 2026-09-03 (docs/model-checks/2026-09-03-claude-fable-5-1.md).
# Each of these reproduces a request shape the current Anthropic models reject
# or a response the adapter silently mishandled. All three are documented
# rejections, not live-reproduced: this box holds no credential.
# ---------------------------------------------------------------------------
def test_complete_sends_no_sampling_parameters() -> None:
    """`temperature`/`top_p`/`top_k` return 400 on every current Anthropic
    model (Fable 5/5.1, Opus 5/4.8/4.7, Sonnet 5). The adapter used to send
    `temperature` on every call, so it could not talk to any of them."""
    client = _FakeClient(
        response=_FakeResponse(
            model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
        )
    )
    AnthropicProvider(client=client).complete(_request(temperature=0.0))

    call = client.messages.calls[0]
    assert "temperature" not in call
    assert "top_p" not in call
    assert "top_k" not in call


def test_complete_refuses_tool_role_before_calling_the_vendor() -> None:
    """`ProviderMessage.role` admits "tool", but the Messages API has no such
    role — tool results travel inside a `user` message as `tool_result`
    blocks, and `ProviderMessage.content` is a plain string that cannot carry
    one. Forwarding the role verbatim produced a vendor 400 naming a field the
    caller never wrote. Refuse it here, by name, before any network call."""
    client = _FakeClient(
        response=_FakeResponse(
            model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
        )
    )
    request = _request(
        messages=(
            ProviderMessage(role="user", content="hello"),
            ProviderMessage(role="tool", content="{}"),
        )
    )
    with pytest.raises(ModelProviderError, match="role 'tool'"):
        AnthropicProvider(client=client).complete(request)
    assert client.messages.calls == []


def test_refusal_stop_reason_raises_instead_of_returning_empty_content() -> None:
    """Current models can return HTTP 200 with `stop_reason == "refusal"` and
    no text. The adapter used to hand that back as `content == ""` with no
    error, so a caller could not tell a refusal from an empty answer.
    Raising `ModelProviderError` is the repo's own fallback mechanism: the
    guide's advice is to fall back on refusal, and `FallbackProvider` does
    exactly that on this exception."""
    client = _FakeClient(
        response=_FakeResponse(
            model="claude-x", content=[], usage=_FakeUsage(1, 0), stop_reason="refusal"
        )
    )
    with pytest.raises(ModelProviderError, match="refusal"):
        AnthropicProvider(client=client).complete(_request())


def test_fallbackprovider_falls_through_on_refusal() -> None:
    from aef.providers.base import CompletionResult, FallbackProvider, ModelProvider

    class _Good(ModelProvider):
        name = "good"

        def complete(self, request: CompletionRequest) -> CompletionResult:
            return CompletionResult(content="answered", model="m", input_tokens=1, output_tokens=1)

    refusing = AnthropicProvider(
        client=_FakeClient(
            response=_FakeResponse(
                model="claude-x", content=[], usage=_FakeUsage(1, 0), stop_reason="refusal"
            )
        )
    )
    assert FallbackProvider([refusing, _Good()]).complete(_request()).content == "answered"


# ---------------------------------------------------------------------------
# Model-check 2026-09-23 (docs/model-checks/2026-09-23-claude-opus-5-5.md).
# Claude Opus 5.5 rejects `thinking: {type: "disabled"}` and `budget_tokens`
# at every effort level, and forced `tool_choice` `any`/`tool`, with a 400.
# The adapter sends none of them today; this pins that. Its default effort
# also dropped from `high` to `medium`, so an owner who wants the old depth
# has to say so — `effort` is that knob, and it is sent only when set.
# ---------------------------------------------------------------------------
def _ok_client() -> _FakeClient:
    return _FakeClient(
        response=_FakeResponse(
            model="claude-x", content=[_FakeTextBlock(text="ok")], usage=_FakeUsage(1, 1)
        )
    )


def test_complete_sends_no_parameter_opus_5_5_rejects() -> None:
    client = _ok_client()
    AnthropicProvider(client=client).complete(_request())

    call = client.messages.calls[0]
    assert "thinking" not in call
    assert "tool_choice" not in call
    assert "tools" not in call  # `no_tools` isolation depends on this too


def test_effort_is_omitted_unless_the_owner_sets_it() -> None:
    client = _ok_client()
    AnthropicProvider(client=client).complete(_request())
    assert "output_config" not in client.messages.calls[0]


def test_effort_is_forwarded_inside_output_config() -> None:
    client = _ok_client()
    AnthropicProvider(client=client, effort="high").complete(_request())
    assert client.messages.calls[0]["output_config"] == {"effort": "high"}
